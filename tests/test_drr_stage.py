import json

import numpy as np

from rain_pipeline import drr_stage, vendor
from rain_pipeline.physio import PairedSeries

ANALYSIS = {
    "method": "lagged_correlation", "surrogate_method": "circular_shift", "correction": "max_statistic",
    "max_lag_s": 3.0, "n_surrogates": 39, "alpha": 0.05, "peak_agreement_hz": 0.03, "seed": 11,
    "controls": {"synthetic_trials": 4, "positive_coupling": 0.3, "positive_lag_samples": 4, "ar_coefficient": 0.5},
}
LAG_WINDOW = {
    "study": "lag_window",
    "method": "lagged_correlation", "surrogate_method": "circular_shift", "correction": "max_statistic",
    "n_surrogates": 39, "alpha": 0.05, "seed": 11,
    "arms": {"short": {"max_lag_s": 3.0}, "long": {"max_lag_s": 6.0},
             "resonant": {"rule": "half_period", "min_lag_s": 1.0, "max_lag_s": 8.0}},
    "strata": {"slow": {"min_hz": 0.0833, "below_hz": 0.1667}, "normal": {"min_hz": 0.1667}},
    "contrasts": {"slow_gain": {"metric": "slow_detection_rate", "arm": "long", "minus": "short"}},
    "controls": {"synthetic_trials": 4, "positive_coupling": 0.3, "positive_lag_samples": 4,
                 "long_lag_samples": 18, "ar_coefficient": 0.5},
}


def _z(x):
    return (x - x.mean()) / x.std()


def _pair(name: str, rng: np.random.Generator, coupled: bool, n: int = 1200) -> PairedSeries:
    source = rng.standard_normal(n)
    target = 0.7 * np.roll(source, 3) + 0.7 * rng.standard_normal(n) if coupled else rng.standard_normal(n)
    return PairedSeries(name, _z(source), _z(target), 4.0, {"mean_heart_rate_bpm": 70.0, "valid_rr_fraction": 1.0})


def _breather(name: str, segment: int, hz: float, rng: np.random.Generator, n: int = 1200) -> PairedSeries:
    """A wandering breathing rhythm at ``hz`` and a heart rate that follows it 3 samples later."""
    phase = 2 * np.pi * hz * np.arange(n) / 4.0 + np.cumsum(0.15 * rng.standard_normal(n))
    breath = np.sin(phase) + 0.3 * rng.standard_normal(n)
    heart = np.roll(breath, 3) + 0.5 * rng.standard_normal(n)
    return PairedSeries(name, _z(breath), _z(heart), 4.0, {"mean_heart_rate_bpm": 70.0}, segment=segment,
                        start_s=600.0 * segment)


def test_detects_coupled_pairs_and_not_mismatched_ones():
    rng = np.random.default_rng(5)
    pairs = [_pair(f"r{i}", rng, coupled=True) for i in range(5)]
    result = drr_stage.run(pairs, [], ANALYSIS)  # no "study" key: the V3D-EXP-0001 study
    m = result.measurements
    assert m["records_analyzed"] == 5
    assert m["coupling_detection_rate"] == 1.0
    assert m["mismatched_detection_rate"] <= 0.2
    assert m["median_coupling_lag_s"] == 0.75  # 3 samples at 4 Hz
    assert result.series["coupling_adjusted_p"] == [r["forward_adjusted_p"] for r in result.report["real_pairs"]]


def test_null_pairs_are_not_detected():
    rng = np.random.default_rng(6)
    result = drr_stage.run([_pair(f"n{i}", rng, coupled=False) for i in range(5)], [], ANALYSIS)
    assert result.measurements["coupling_detection_rate"] <= 0.2


def test_rsa_coupling_emits_every_metric_exp0001_registered():
    spec = json.loads((vendor.PROJECT_ROOT / "specs" / "cardiorespiratory.json").read_text(encoding="utf-8"))
    declared = {m["name"] for m in spec["preregistration"]["metrics"]}
    rng = np.random.default_rng(7)
    result = drr_stage.run([_pair(f"r{i}", rng, coupled=True) for i in range(3)], [], ANALYSIS)
    assert set(result.measurements) == declared


def test_arm_lag_and_strata_follow_the_half_period_rule():
    fixed, resonant = {"max_lag_s": 6.0}, {"rule": "half_period", "min_lag_s": 1.0, "max_lag_s": 8.0}
    assert drr_stage.arm_lag_samples(fixed, 0.3, 4.0) == 24
    assert drr_stage.arm_lag_samples(resonant, 0.125, 4.0) == 17   # half of an 8 s breath = 16 samples, plus one
    assert drr_stage.arm_lag_samples(resonant, 0.25, 4.0) == 9
    assert drr_stage.arm_lag_samples(resonant, 1.0, 4.0) == 4      # clamped to the 1 s floor
    assert drr_stage.arm_lag_samples(resonant, 0.01, 4.0) == 32    # clamped to the 8 s ceiling
    assert drr_stage.arm_lag_samples(resonant, None, 4.0) == 32
    strata = LAG_WINDOW["strata"]
    assert [drr_stage.stratum_of(f, strata) for f in (0.05, 0.0833, 0.16, 0.1667, 0.3, None)] == \
           [None, "slow", "slow", "normal", "normal", None]


def test_lag_window_study_strata_arms_and_controls():
    rng = np.random.default_rng(8)
    windows = [_breather("a", k, 0.125, rng) for k in range(3)]       # one person, three slow windows
    windows += [_breather("b", 0, 0.125, rng)]                         # another, one slow window
    windows += [_breather("c", k, 0.28, rng) for k in range(2)]        # a normal breather
    result = drr_stage.run(windows, [], LAG_WINDOW)
    m = result.measurements

    assert (m["windows_analyzed"], m["slow_windows"], m["slow_subjects"]) == (6, 4, 2)
    assert (m["normal_windows"], m["normal_subjects"]) == (2, 1)
    lags = {row["record"]: {arm: row["arms"][arm]["max_lag_samples"] for arm in LAG_WINDOW["arms"]}
            for row in result.report["windows"]}
    assert lags["a"] == {"short": 12, "long": 24, "resonant": 17}
    assert lags["c"]["resonant"] < 12                                  # faster breathing earns a shorter window
    assert m["slow_detection_rate_long"] == 1.0 and m["normal_detection_rate_resonant"] == 1.0
    assert m["slow_gain"] == m["slow_detection_rate_long"] - m["slow_detection_rate_short"]

    # A coupling 18 samples away is invisible to a 12-sample window and plain to a 24-sample one.
    assert m["synthetic_long_lag_detection_rate_long"] >= 0.75
    assert m["synthetic_long_lag_detection_rate_short"] <= 0.25
    assert m["synthetic_positive_detection_rate_short"] >= 0.75
    # Mismatched pairs exist only where a segment has two people (segment 0: a, b, c).
    assert len(result.series["mismatched_adjusted_p_long"]) == 5
    assert set(result.series) == {"respiratory_frequency_hz", *(f"{kind}adjusted_p_{arm}" for arm in LAG_WINDOW["arms"]
                                                                for kind in ("", "mismatched_"))}


def test_parallel_and_single_process_give_identical_results(monkeypatch):
    rng = np.random.default_rng(10)
    windows = [_breather("a", 0, 0.125, rng), _breather("b", 0, 0.28, rng)]
    monkeypatch.setenv("RAIN_PIPELINE_WORKERS", "1")
    single = drr_stage.run(windows, [], LAG_WINDOW)
    monkeypatch.setenv("RAIN_PIPELINE_WORKERS", "2")
    monkeypatch.setattr(drr_stage, "PARALLEL_MIN_TASKS", 1)
    parallel = drr_stage.run(windows, [], LAG_WINDOW)
    assert parallel.measurements == single.measurements
    assert parallel.series == single.series


def test_subject_balanced_rate_weights_people_not_windows():
    rng = np.random.default_rng(9)
    coupled = [_breather("a", k, 0.125, rng) for k in range(3)]
    silent = _breather("b", 0, 0.125, rng)
    silent = PairedSeries("b", silent.respiration, _z(rng.standard_normal(1200)), 4.0, silent.qc, segment=0)
    m = drr_stage.run([*coupled, silent], [], LAG_WINDOW).measurements
    # Person a: 3 of 3 detected. Person b: 0 of 1. Window-level would say 0.75.
    assert m["slow_detection_rate_long"] == 0.5
    assert m["window_detection_rate_long"] == 0.75
