import json

import numpy as np

from rain_pipeline import drr_stage, vendor
from rain_pipeline.physio import PairedSeries

ANALYSIS = {
    "method": "lagged_correlation", "surrogate_method": "circular_shift", "correction": "max_statistic",
    "max_lag_s": 3.0, "n_surrogates": 39, "alpha": 0.05, "peak_agreement_hz": 0.03, "seed": 11,
    "controls": {"synthetic_trials": 4, "positive_coupling": 0.3, "positive_lag_samples": 4, "ar_coefficient": 0.5},
}


def _pair(name: str, rng: np.random.Generator, coupled: bool, n: int = 1200) -> PairedSeries:
    source = rng.standard_normal(n)
    target = 0.7 * np.roll(source, 3) + 0.7 * rng.standard_normal(n) if coupled else rng.standard_normal(n)
    z = lambda x: (x - x.mean()) / x.std()  # noqa: E731
    return PairedSeries(name, z(source), z(target), 4.0, {"mean_heart_rate_bpm": 70.0, "valid_rr_fraction": 1.0})


def test_detects_coupled_pairs_and_not_mismatched_ones():
    rng = np.random.default_rng(5)
    pairs = [_pair(f"r{i}", rng, coupled=True) for i in range(5)]
    result = drr_stage.run(pairs, [], ANALYSIS)
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


def test_measurements_match_the_preregistered_metrics_exactly():
    spec = json.loads((vendor.PROJECT_ROOT / "specs" / "cardiorespiratory.json").read_text(encoding="utf-8"))
    declared = {m["name"] for m in spec["preregistration"]["metrics"]}
    rng = np.random.default_rng(7)
    result = drr_stage.run([_pair(f"r{i}", rng, coupled=True) for i in range(3)], [], ANALYSIS)
    assert set(result.measurements) == declared
