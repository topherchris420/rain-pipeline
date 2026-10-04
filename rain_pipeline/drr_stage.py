"""Stage 3 — DRR: lead–lag analysis with controls, reduced to pre-registered metrics.

Every test is DRR's ``RootingAnalyzer`` (lagged correlation, circular-shift
surrogates, max-statistic family-wise correction). Detection is read from the
adjusted p-value matrix directly, not from ``significant_edges``: that list is
gated by a mean+std heuristic which, with two channels, can hide an edge whose
reverse direction scores as high (see DRR's own limitations).

Controls run with exactly the same settings as the real pairs:

- positive:  synthetic AR(1) pairs with a known directed coupling;
- null:      independent AR(1) pairs;
- real null: subject A's respiration against subject B's heart rate. Breathing
             and heart rate share a ~0.25 Hz rhythm, so this is what a
             periodicity artefact would look like on real data.

This module only measures. R.A.I.N. evaluates the criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .physio import PairedSeries


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


def _dominant_hz(series: np.ndarray, fs: float) -> float | None:
    from drr_framework import ResonanceDetector

    peaks = ResonanceDetector().detect(series, method="welch", sampling_rate=fs)["dominant_freq"]
    return float(peaks[0]) if len(peaks) else None


def _rate(flags: list[bool]) -> float | None:
    return float(np.mean(flags)) if flags else None


def run(pairs: list[PairedSeries], excluded: list[dict[str, Any]], analysis: dict[str, Any]) -> DrrResult:
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


def _median(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return float(np.median(present)) if present else None
