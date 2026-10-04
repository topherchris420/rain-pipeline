"""Content identity: hashes, deterministic serialization, and mapping recorded code back to git history."""

import json
import math
import subprocess

import pytest

from rain_pipeline import provenance, registry_stage, vendor
from rain_pipeline.layout import Layout


def test_canonical_hash_is_the_digest_rain_records():
    vendor.ensure_importable()
    from james_library.experiments.schema import sha256_json

    sample = {"b": [1, 2.5, None, "é"], "a": {"z": True, "y": 0.1}}
    assert provenance.canonical_sha256(sample) == sha256_json(sample)
    assert provenance.canonical_sha256({"a": 1, "b": 2}) == provenance.canonical_sha256({"b": 2, "a": 1})


def test_serialization_is_deterministic_and_strict(tmp_path):
    payload = {"z": 1, "a": [0.1, 2], "text": "café"}
    ref = provenance.write_json(tmp_path / "a.json", payload)
    again = provenance.write_json(tmp_path / "b.json", json.loads((tmp_path / "a.json").read_text(encoding="utf-8")))
    assert ref["sha256"] == again["sha256"] and ref["bytes"] == (tmp_path / "a.json").stat().st_size
    assert (tmp_path / "a.json").read_bytes().endswith(b"\n") and "café".encode() in (tmp_path / "a.json").read_bytes()
    with pytest.raises(ValueError):
        provenance.write_json(tmp_path / "nan.json", {"x": math.nan})  # strict JSON has no NaN
    assert not (tmp_path / "nan.json").exists() and not list(tmp_path.glob(".*.tmp"))  # atomic: nothing half-written


def test_non_finite_values_become_null_and_are_counted():
    clean, count = provenance.finite({"a": [1.0, math.nan, {"b": math.inf}], "c": "x", "d": None})
    assert clean == {"a": [1.0, None, {"b": None}], "c": "x", "d": None} and count == 2


def test_fresh_names_never_overwrite_a_record(tmp_path):
    assert provenance.fresh_dir(tmp_path, "20260101T000000Z").name == "20260101T000000Z"
    assert provenance.fresh_dir(tmp_path, "20260101T000000Z").name == "20260101T000000Z-2"
    assert provenance.fresh_file(tmp_path, "RUN-0001", ".json").name == "RUN-0001.json"
    assert provenance.fresh_file(tmp_path, "RUN-0001", ".json").name == "RUN-0001-2.json"


def test_the_source_digest_ignores_line_endings_and_is_per_file():
    unix = {"a.py": b"x = 1\ny = 2\n", "b.py": b"z = 3\n"}
    windows = {"b.py": b"z = 3\r\n", "a.py": b"x = 1\r\ny = 2\r\n"}
    assert provenance.source_sha256_of(unix) == provenance.source_sha256_of(windows)
    assert provenance.source_sha256_of(unix) != provenance.source_sha256_of({**unix, "b.py": b"z = 4\n"})
    identity = provenance.code_identity()
    assert identity["source_sha256"] == provenance.source_sha256() and "pipeline.py" in identity["files"]


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_recorded_code_resolves_to_the_commit_that_holds_it(tmp_path):
    root = tmp_path / "repo"
    (root / "rain_pipeline").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "rain_pipeline" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one")
    first = _git(root, "rev-parse", "HEAD")
    digest_one = provenance.source_sha256(root / "rain_pipeline")
    (root / "rain_pipeline" / "a.py").write_text("x = 2\n", encoding="utf-8")
    uncommitted = provenance.source_sha256(root / "rain_pipeline")
    history = provenance.History(root)
    assert provenance.resolve_source_commit(history, digest_one) == first
    assert provenance.resolve_source_commit(history, uncommitted) is None
    assert history.is_ancestor(first) and history.exists(first) and not history.exists("0" * 40)
    assert provenance.resolve_source_commit(provenance.History(tmp_path / "not-a-repo"), digest_one) is None


def test_the_historical_runs_resolve_to_their_commits():
    """Every committed run names the exact pipeline commit that produced it, recoverable from history alone."""
    history = provenance.History(vendor.PROJECT_ROOT)
    if not history.available or history.shallow:
        pytest.skip("needs full git history")
    expected = {"V3D-EXP-0001": "19de682", "V3D-EXP-0002": "9718470", "V3D-EXP-0003": "9718470"}
    registry = registry_stage.open_registry(Layout.default().experiments)
    for experiment_id, commit in expected.items():
        (record,) = registry.runs(experiment_id)
        resolved = provenance.resolve_source_commit(history, record["inputs"]["code"]["pipeline"]["source_sha256"])
        assert resolved and resolved.startswith(commit), experiment_id


def test_layout_maps_the_legacy_keyword_roots(tmp_path):
    layout = Layout.at(tmp_path).with_roots(registry_root=tmp_path / "reg", data_root=tmp_path / "d")
    assert layout.experiments == tmp_path / "reg" and layout.results == tmp_path / "RESULTS.md"
    assert layout.ledger == tmp_path / "d" / "ledger.json" and layout.cache == tmp_path / "d" / "cache" / "fantasia"
    assert layout.relative(tmp_path / "runs" / "x") == "runs/x" and layout.resolve("runs/x") == tmp_path / "runs" / "x"
