"""DRR stage: lead–lag studies with controls, reduced to measurements.

Every test is DRR's ``RootingAnalyzer`` (lagged correlation, circular-shift
surrogates, max-statistic family-wise correction). Detection is read from the
adjusted p-value matrix directly, not from ``significant_edges``: that list is
gated by a mean+std heuristic which, with two channels, can hide an edge whose
reverse direction scores as high (see DRR's own limitations).

A *study* is a named function that turns windows of paired series into
measurements. The spec picks one with ``analysis.study``:

- ``rsa_coupling`` (default): one lag window; real pairs against synthetic
  positive/null controls and mismatched-subject pairs. This is V3D-EXP-0001.
- ``lag_window``: the same windows tested under several lag-window *arms*
  (fixed, or derived from the breathing resonance), split into strata by
  breathing frequency, with the same controls per arm.

Controls always run with exactly the settings of the real pairs. Studies only
measure; the registration chooses which measurements are evidence, and
R.A.I.N. evaluates them.
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .physio import PairedSeries

PARALLEL_MIN_TASKS = 64  # below this, starting worker processes costs more than it saves


@dataclass(frozen=True)
class DrrResult:
    measurements: dict[str, float | None]
    series: dict[str, list[float]]
    report: dict[str, Any]


def _rooting(pair: np.ndarray, analysis: dict[str, Any], max_lag: int, seed: int) -> dict[str, Any]:
    from drr_framework import RootingAnalyzer

    result = RootingAnalyzer().analyze(
        pair,
        max_lag=max_lag,
        n_surrogates=analysis["n_surrogates"],
        random_state=seed,
        alpha=analysis["alpha"],
        method=analysis["method"],
        surrogate_method=analysis["surrogate_method"],
        correction=analysis["correction"],
    )
    if result["method"] != analysis["method"]:
        raise RuntimeError(f"DRR fell back to {result['method']!r}; the pre-registered method did not run")
    return {
        "forward_score": float(result["score_matrix"][0, 1]),
        "forward_lag_samples": int(result["effective_lag"][0, 1]),
        "forward_p": float(result["p_values"][0, 1]),
        "forward_adjusted_p": float(result["adjusted_p_values"][0, 1]),
        "reverse_score": float(result["score_matrix"][1, 0]),
        "reverse_lag_samples": int(result["effective_lag"][1, 0]),
        "reverse_adjusted_p": float(result["adjusted_p_values"][1, 0]),
        "seed": seed,
    }


def _rooting_task(task: tuple) -> dict[str, Any]:
    return _rooting(*task)


def _map_rooting(tasks: list[tuple]) -> list[dict[str, Any]]:
    """Run independent rooting tests, across processes when there are enough to pay for it.

    Each test is seeded on its own, so the results are identical however they
    are scheduled. ``RAIN_PIPELINE_WORKERS=1`` forces a single process.
    """
    workers = int(os.environ.get("RAIN_PIPELINE_WORKERS", max(1, (os.cpu_count() or 2) - 1)))
    if workers <= 1 or len(tasks) < PARALLEL_MIN_TASKS:
        return [_rooting_task(task) for task in tasks]
    inherited = {name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")}
    os.environ.update({name: "1" for name in inherited})  # workers inherit this: one thread each, no oversubscription
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_rooting_task, tasks, chunksize=4))
    finally:
        for name, value in inherited.items():
            os.environ.pop(name, None) if value is None else os.environ.__setitem__(name, value)


def _dominant_hz(series: np.ndarray, fs: float) -> float | None:
    """The strongest spectral peak, from DRR's own resonance detector."""
    from drr_framework import ResonanceDetector

    peaks = ResonanceDetector().detect(series, method="welch", sampling_rate=fs)["dominant_freq"]
    return float(peaks[0]) if len(peaks) else None


def _rate(flags: list[bool]) -> float | None:
    return float(np.mean(flags)) if flags else None


def _median(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return float(np.median(present)) if present else None


# --------------------------------------------------------------------------- #
# Study: rsa_coupling (V3D-EXP-0001)
# --------------------------------------------------------------------------- #
def rsa_coupling(pairs: list[PairedSeries], excluded: list[dict[str, Any]], analysis: dict[str, Any]) -> DrrResult:
    alpha = analysis["alpha"]
    seed = analysis["seed"]
    fs = pairs[0].fs if pairs else 4.0
    max_lag = max(1, int(round(analysis["max_lag_s"] * fs)))

    # Real pairs: each subject's respiration (source) -> own heart rate (target).
    real = []
    for i, pair in enumerate(pairs):
        stats = _rooting(np.column_stack([pair.respiration, pair.heart_rate]), analysis, max_lag, seed + i)
        resp_hz, hr_hz = _dominant_hz(pair.respiration, fs), _dominant_hz(pair.heart_rate, fs)
        real.append({"record": pair.record, **stats, "respiration_peak_hz": resp_hz,
                     "heart_rate_peak_hz": hr_hz, "qc": pair.qc})

    # Real-data null: respiration of subject i against heart rate of subject i+1.
    mismatched = []
    for i, pair in enumerate(pairs if len(pairs) > 1 else []):
        other = pairs[(i + 1) % len(pairs)]
        n = min(len(pair.respiration), len(other.heart_rate))
        stats = _rooting(np.column_stack([pair.respiration[:n], other.heart_rate[:n]]), analysis, max_lag, seed + 1000 + i)
        mismatched.append({"respiration_of": pair.record, "heart_rate_of": other.record, **stats})

    # Synthetic controls with the same length, lag window, surrogates and correction.
    from drr_framework.calibration import simulate_ar1, simulate_directed_pair

    controls = analysis["controls"]
    n_samples = int(np.median([len(p.respiration) for p in pairs])) if pairs else 2400
    rng = np.random.default_rng(seed)
    positive, null = [], []
    for k in range(controls["synthetic_trials"]):
        data = simulate_directed_pair(n_samples, controls["positive_coupling"], controls["positive_lag_samples"],
                                      controls["ar_coefficient"], rng)
        positive.append(_rooting(data[:, :2], analysis, max_lag, seed + 2000 + k))
        data = simulate_ar1(n_samples, 2, controls["ar_coefficient"], rng)
        null.append(_rooting(data, analysis, max_lag, seed + 3000 + k))

    detected = [r["forward_adjusted_p"] <= alpha for r in real]
    mismatched_detected = [m["forward_adjusted_p"] <= alpha for m in mismatched]
    coupling_rate, mismatched_rate = _rate(detected), _rate(mismatched_detected)
    agreement = [
        r["respiration_peak_hz"] is not None and r["heart_rate_peak_hz"] is not None
        and abs(r["respiration_peak_hz"] - r["heart_rate_peak_hz"]) <= analysis["peak_agreement_hz"]
        for r in real
    ]
    detected_lags = [r["forward_lag_samples"] / fs for r in real if r["forward_adjusted_p"] <= alpha]

    measurements = {
        "records_analyzed": len(real),
        "coupling_detection_rate": coupling_rate,
        "mismatched_detection_rate": mismatched_rate,
        "detection_rate_gap": None if coupling_rate is None or mismatched_rate is None else coupling_rate - mismatched_rate,
        "positive_control_detection_rate": _rate([p["forward_adjusted_p"] <= alpha for p in positive]),
        "synthetic_null_false_positive_rate": _rate([n["forward_adjusted_p"] <= alpha for n in null]),
        "reverse_detection_rate": _rate([r["reverse_adjusted_p"] <= alpha for r in real]),
        "median_coupling_lag_s": float(np.median(detected_lags)) if detected_lags else None,
        "spectral_peak_agreement_rate": _rate(agreement),
        "median_respiratory_frequency_hz": _median([r["respiration_peak_hz"] for r in real]),
        "median_heart_rate_bpm": _median([r["qc"]["mean_heart_rate_bpm"] for r in real]),
    }
    series = {
        "coupling_adjusted_p": [r["forward_adjusted_p"] for r in real],
        "mismatched_adjusted_p": [m["forward_adjusted_p"] for m in mismatched],
        "coupling_lag_s": [r["forward_lag_samples"] / fs for r in real],
        "coupling_score": [r["forward_score"] for r in real],
        "mismatched_score": [m["forward_score"] for m in mismatched],
    }
    report = {
        "engine": "drr_framework.RootingAnalyzer",
        "settings": {**analysis, "max_lag_samples": max_lag, "grid_hz": fs,
                     "minimum_attainable_p": 1.0 / (analysis["n_surrogates"] + 1)},
        "real_pairs": real,
        "mismatched_pairs": mismatched,
        "excluded_records": excluded,
        "positive_controls": positive,
        "null_controls": null,
        "measurements": measurements,
    }
    return DrrResult(measurements=measurements, series=series, report=report)


# --------------------------------------------------------------------------- #
# Study: lag_window
# --------------------------------------------------------------------------- #
def arm_lag_samples(arm: dict[str, Any], frequency_hz: float | None, fs: float) -> int:
    """The lag window of one arm, in samples.

    A fixed arm is ``{"max_lag_s": 6}``. A resonance-derived arm is
    ``{"rule": "half_period", "min_lag_s": 1, "max_lag_s": 8}``: the absolute
    cross-correlation of two signals sharing a rhythm peaks once every half
    period, so lags 1..(half period + 1 sample) always contain a peak, and no
    shorter window can promise that.
    """
    if arm.get("rule") == "half_period":
        low, high = int(round(arm["min_lag_s"] * fs)), int(round(arm["max_lag_s"] * fs))
        if not frequency_hz:
            return high
        return min(high, max(low, math.ceil(fs / (2.0 * frequency_hz)) + 1))
    return max(1, int(round(arm["max_lag_s"] * fs)))


def stratum_of(frequency_hz: float | None, strata: dict[str, dict[str, float]]) -> str | None:
    """First stratum whose ``min_hz <= f < below_hz`` holds (either bound may be absent)."""
    if frequency_hz is None:
        return None
    for name, bounds in strata.items():
        if bounds.get("min_hz", 0.0) <= frequency_hz < bounds.get("below_hz", math.inf):
            return name
    return None


def lag_window(windows: list[PairedSeries], excluded: list[dict[str, Any]], analysis: dict[str, Any]) -> DrrResult:
    alpha, seed = analysis["alpha"], analysis["seed"]
    arms: dict[str, dict[str, Any]] = analysis["arms"]
    strata: dict[str, dict[str, float]] = analysis["strata"]
    fs = windows[0].fs if windows else 4.0

    # Every test is queued as (slot, task) and filled in afterwards, so the tests
    # can run in parallel. Each has its own seed, so the order cannot matter.
    jobs: list[tuple[dict[str, Any], tuple]] = []

    def queue(pair: np.ndarray, lag: int, test_seed: int) -> dict[str, Any]:
        slot = {"max_lag_samples": lag}
        jobs.append((slot, (pair, analysis, lag, test_seed)))
        return slot

    # Real windows: respiration (source) -> own heart rate (target), once per arm.
    # The stratum comes from respiration alone, so it cannot depend on the outcome.
    rows: list[dict[str, Any]] = []
    for i, window in enumerate(windows):
        frequency = _dominant_hz(window.respiration, fs)
        pair = np.column_stack([window.respiration, window.heart_rate])
        rows.append({"record": window.record, "segment": window.segment, "start_s": window.start_s,
                     "respiratory_frequency_hz": frequency, "stratum": stratum_of(frequency, strata),
                     "qc": window.qc, "mismatched": None,
                     "arms": {name: queue(pair, arm_lag_samples(arm, frequency, fs), seed + i)
                              for name, arm in arms.items()}})

    # Real-data null: this window's respiration against another person's heart
    # rate in the same segment, under the lag window the respiration earned.
    # The partner moves one person further along in each segment, so ten segments
    # test ten different pairings instead of the same one ten times.
    by_segment: dict[int, list[int]] = {}
    for i, window in enumerate(windows):
        by_segment.setdefault(window.segment, []).append(i)
    for segment, members in by_segment.items():
        if len(members) < 2:
            continue
        offset = 1 + segment % (len(members) - 1)
        for j, i in enumerate(members):
            other = windows[members[(j + offset) % len(members)]]
            n = min(len(windows[i].respiration), len(other.heart_rate))
            pair = np.column_stack([windows[i].respiration[:n], other.heart_rate[:n]])
            rows[i]["mismatched"] = {"heart_rate_of": other.record, "arms": {
                name: queue(pair, rows[i]["arms"][name]["max_lag_samples"], seed + 1_000_000 + i) for name in arms}}

    # Synthetic controls: a coupling every arm can reach, no coupling at all, and
    # a coupling whose lag lies beyond the shortest fixed window.
    from drr_framework.calibration import simulate_ar1, simulate_directed_pair

    controls = analysis["controls"]
    n_samples = int(np.median([len(w.respiration) for w in windows])) if windows else 2400
    rng = np.random.default_rng(seed)
    kinds = ("positive", "null", "long_lag")
    synthetic: dict[str, dict[str, list[dict[str, Any]]]] = {name: {kind: [] for kind in kinds} for name in arms}
    for k in range(controls["synthetic_trials"]):
        datasets = {
            "positive": simulate_directed_pair(n_samples, controls["positive_coupling"],
                                               controls["positive_lag_samples"], controls["ar_coefficient"], rng)[:, :2],
            "null": simulate_ar1(n_samples, 2, controls["ar_coefficient"], rng),
            "long_lag": simulate_directed_pair(n_samples, controls["positive_coupling"],
                                               controls["long_lag_samples"], controls["ar_coefficient"], rng)[:, :2],
        }
        for kind_index, kind in enumerate(kinds):
            data = datasets[kind]
            frequency = _dominant_hz(data[:, 0], fs)
            for name, arm in arms.items():
                synthetic[name][kind].append(queue(data, arm_lag_samples(arm, frequency, fs),
                                                   seed + 2_000_000 + 1000 * kind_index + k))

    for (slot, _), outcome in zip(jobs, _map_rooting([task for _, task in jobs])):
        slot.update(outcome)

    def detected(entry: dict[str, Any]) -> bool:
        return entry["forward_adjusted_p"] <= alpha

    def subject_balanced(members: list[dict[str, Any]], arm: str) -> float | None:
        """Each subject's share of detected windows, averaged with equal weight per subject."""
        per_subject: dict[str, list[bool]] = {}
        for row in members:
            per_subject.setdefault(row["record"], []).append(detected(row["arms"][arm]))
        return float(np.mean([np.mean(flags) for flags in per_subject.values()])) if per_subject else None

    in_stratum = {name: [row for row in rows if row["stratum"] == name] for name in strata}
    with_mismatch = [row for row in rows if row["mismatched"]]

    measurements: dict[str, float | None] = {"windows_analyzed": len(rows)}
    for stratum, members in in_stratum.items():
        measurements[f"{stratum}_windows"] = len(members)
        measurements[f"{stratum}_subjects"] = len({row["record"] for row in members})
    for name in arms:
        measurements[f"window_detection_rate_{name}"] = _rate([detected(row["arms"][name]) for row in rows])
        measurements[f"mismatched_detection_rate_{name}"] = _rate(
            [detected(row["mismatched"]["arms"][name]) for row in with_mismatch])
        for stratum, members in in_stratum.items():
            measurements[f"{stratum}_detection_rate_{name}"] = subject_balanced(members, name)
            measurements[f"mismatched_{stratum}_detection_rate_{name}"] = _rate(
                [detected(row["mismatched"]["arms"][name]) for row in with_mismatch if row["stratum"] == stratum])
            measurements[f"{stratum}_median_lag_s_{name}"] = _median(
                [row["arms"][name]["forward_lag_samples"] / fs for row in members if detected(row["arms"][name])])
        measurements[f"synthetic_positive_detection_rate_{name}"] = _rate([detected(s) for s in synthetic[name]["positive"]])
        measurements[f"synthetic_null_false_positive_rate_{name}"] = _rate([detected(s) for s in synthetic[name]["null"]])
        measurements[f"synthetic_long_lag_detection_rate_{name}"] = _rate([detected(s) for s in synthetic[name]["long_lag"]])
    for name, contrast in analysis.get("contrasts", {}).items():
        left = measurements.get(f"{contrast['metric']}_{contrast['arm']}")
        right = measurements.get(f"{contrast['metric']}_{contrast['minus']}")
        measurements[name] = None if left is None or right is None else left - right

    series: dict[str, list[float]] = {
        "respiratory_frequency_hz": [row["respiratory_frequency_hz"] or 0.0 for row in rows]}
    for name in arms:
        series[f"adjusted_p_{name}"] = [row["arms"][name]["forward_adjusted_p"] for row in rows]
        series[f"mismatched_adjusted_p_{name}"] = [row["mismatched"]["arms"][name]["forward_adjusted_p"]
                                                    for row in with_mismatch]
    report = {
        "engine": "drr_framework.RootingAnalyzer",
        "study": "lag_window",
        "settings": {**analysis, "grid_hz": fs, "minimum_attainable_p": 1.0 / (analysis["n_surrogates"] + 1)},
        "windows": rows,
        "excluded_windows": excluded,
        "synthetic": synthetic,
        "measurements": measurements,
    }
    return DrrResult(measurements=measurements, series=series, report=report)


STUDIES: dict[str, Callable[[list[PairedSeries], list[dict[str, Any]], dict[str, Any]], DrrResult]] = {
    "rsa_coupling": rsa_coupling,
    "lag_window": lag_window,
}


def study_name(analysis: dict[str, Any]) -> str:
    return analysis.get("study", "rsa_coupling")  # V3D-EXP-0001 was registered before studies had names


def run(windows: list[PairedSeries], excluded: list[dict[str, Any]], analysis: dict[str, Any]) -> DrrResult:
    return STUDIES[study_name(analysis)](windows, excluded, analysis)
