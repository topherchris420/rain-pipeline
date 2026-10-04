"""The two ledger rules: exploration never touches unseen data; a holdout must be unseen.

These tests call the 0.2 keyword API (registry_root=..., data_root=...) on
purpose: it must keep working for existing callers.
"""

import json
from pathlib import Path

import pytest

from rain_pipeline import ledger, physio, pipeline, vendor
from rain_pipeline.errors import SpecError

URL = "https://example.org/rec.dat"


def _plans(monkeypatch, byte_range):
    plan = physio.SegmentPlan("rec", None, "0" * 64, URL, byte_range, 0.0, 600.0, Path("unused"))
    monkeypatch.setattr(pipeline, "plan_data", lambda data, cache_dir: [plan])


def _spec(tmp_path, name, **data):
    spec = json.loads((vendor.PROJECT_ROOT / "specs" / "slow-breathers-6s-window.json").read_text(encoding="utf-8"))
    spec["data"].update(data)
    if not spec["data"]["holdout"]:
        del spec["data"]["holdout"]
    spec.pop("lineage")
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_explore_refuses_bytes_the_ledger_has_not_seen(tmp_path, monkeypatch):
    _plans(monkeypatch, (0, 999))
    ledger.record(tmp_path / "data" / "ledger.json", url=URL, byte_range=(0, 499), sha256="a" * 64,
                  read_at="2026-01-01T00:00:00.000Z", read_by="V3D-EXP-0001")
    with pytest.raises(pipeline.HoldoutViolation, match="500 bytes of this spec are unseen"):
        pipeline.explore(_spec(tmp_path, "explore", holdout=False), explorations_root=tmp_path / "explorations",
                         data_root=tmp_path / "data", log=lambda _: None)
    assert not (tmp_path / "explorations").exists()


def test_explore_refuses_a_spec_that_declares_a_holdout(tmp_path, monkeypatch):
    _plans(monkeypatch, (0, 999))
    with pytest.raises(SpecError, match="cannot declare a holdout"):
        pipeline.explore(_spec(tmp_path, "explore", holdout=True), explorations_root=tmp_path / "explorations",
                         data_root=tmp_path / "data", log=lambda _: None)
    assert not (tmp_path / "explorations").exists()


def test_register_refuses_a_holdout_that_was_already_read(tmp_path, monkeypatch):
    _plans(monkeypatch, (0, 999))
    ledger.record(tmp_path / "data" / "ledger.json", url=URL, byte_range=(900, 1999), sha256="a" * 64,
                  read_at="2026-01-01T00:00:00.000Z", read_by="exploration")
    with pytest.raises(pipeline.HoldoutViolation, match="100 bytes of the declared holdout"):
        pipeline.register(_spec(tmp_path, "confirm", holdout=True), registry_root=tmp_path / "experiments",
                          framing_root=tmp_path / "framing", data_root=tmp_path / "data", log=lambda _: None)
    assert not (tmp_path / "framing").exists()          # refused before any literature work
    assert not (tmp_path / "experiments").exists()      # and before the registry was touched


def test_run_refuses_a_spec_that_was_never_registered(tmp_path):
    with pytest.raises(RuntimeError, match="not registered"):
        pipeline.run(_spec(tmp_path, "unregistered", holdout=True), registry_root=tmp_path / "experiments",
                     runs_root=tmp_path / "runs", framing_root=tmp_path / "framing", data_root=tmp_path / "data",
                     log=lambda _: None)
    assert not (tmp_path / "runs").exists()


def test_a_misspelt_keyword_root_is_an_error_not_a_silent_default(tmp_path):
    from rain_pipeline.layout import resolve

    with pytest.raises(TypeError, match="registry_rot"):
        resolve(None, {"registry_rot": tmp_path})
