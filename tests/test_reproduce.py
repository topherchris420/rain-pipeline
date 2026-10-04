"""Replay V3D-EXP-0001 from the cached bytes and compare with the committed run.

Skipped when the PhysioNet cache is absent (a fresh clone): run the pipeline once to fill it.
"""

import json

import pytest

from rain_pipeline import drr_stage, ledger, pipeline, vendor

ROOT = vendor.PROJECT_ROOT
RUN = ROOT / "runs" / "20261004T150406Z"


def test_exp0001_measurements_reproduce_exactly(tmp_path):
    spec = pipeline.load_spec(ROOT / "specs" / "cardiorespiratory.json")
    cache_dir, _ = pipeline._paths(None)
    plans = pipeline.plan_data(spec["data"], cache_dir) if (cache_dir / "f1y01.hea").exists() else []
    if not plans or not all(plan.cache_path.exists() for plan in plans):
        pytest.skip("PhysioNet cache not present")

    scratch_ledger = tmp_path / "ledger.json"   # a replay must not write to the real ledger
    windows, excluded, files = pipeline.read_windows(spec["data"], plans, scratch_ledger, "replay", lambda _: None)
    study = drr_stage.run(windows, excluded, spec["analysis"])

    committed = json.loads((RUN / "summary.json").read_text(encoding="utf-8"))
    assert study.measurements == committed["measurements"]
    recorded = {f["record"]: f["sha256"] for f in
                json.loads((RUN / "drr_report.json").read_text(encoding="utf-8"))["dataset_files"]}
    assert {f["record"]: f["sha256"] for f in files} == recorded
    real = ledger.load(ROOT / "data" / "ledger.json")
    assert ledger.bytes_unseen(real, [(plan.url, plan.byte_range) for plan in plans]) == 0
