"""Replay the committed V3D-EXP-0001 run from the public PhysioNet bytes and compare every value.

Skipped when the cache is absent (a fresh clone); `python -m rain_pipeline replay V3D-EXP-0001`
fetches it, checks every byte against the ledger, and writes a receipt. CI replays it weekly.
"""

import pytest

from rain_pipeline import pipeline, replay
from rain_pipeline.layout import Layout


def test_exp0001_registered_measurements_reproduce_exactly():
    layout = Layout.default()
    registry = replay.registry_stage.open_registry(layout.experiments, layout.results)
    data = registry.load_definition("V3D-EXP-0001")["parameters"]["data"]
    plans = pipeline.plan_data(data, layout.cache) if (layout.cache / "f1y01.hea").exists() else []
    if not plans or not all(plan.cache_path.exists() for plan in plans):
        pytest.skip("PhysioNet cache not present")
    receipt = replay.replay("V3D-EXP-0001", layout=layout, write=False, log=lambda _: None)
    comparison = receipt["comparison"]
    assert comparison["data_identical"]                                  # the same public bytes, hash for hash
    assert all(m["identical"] for m in comparison["measurements"].values()), comparison["measurements"]
    assert comparison["status"] == {"recorded": "passed", "replayed": "passed"}
    assert receipt["outcome"] in ("reproduced", "measurements-reproduced")
    largest = max([s.get("max_abs_difference", 0.0) for s in comparison["series"].values()]
                  + [comparison["report"]["max_abs_difference"] or 0.0])
    assert largest < 1e-9  # any descriptive difference is floating-point noise across platforms, nothing more
