"""Offline doubles for the two network boundaries, and a throwaway evidence repository.

- ``physionet``: an in-memory PhysioNet serving synthetic WFDB records (RESP
  and ECG, format 16) through the real header, byte-range, cache and decode
  code. Breathing drives heart rate in every record, so the coupling is real.
- ``anna``: Anna's literature step replaced by a sealed, verifiable record
  over fixed documents (the R.A.I.N. panel still runs for real over them).
- ``workspace``: a git repository with its own layout, where the protocol
  can register, commit, run and verify without touching this repository.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from rain_pipeline import anna_stage, physio, provenance, vendor
from rain_pipeline.layout import Layout

FS = 250
RECORDS = {"syn01": 0.25, "syn02": 0.22, "syn03": 0.12, "syn04": 0.28}  # breathing frequency, Hz
SECONDS = 320


def quiet(_: str) -> None:
    pass


def _recording(name: str, breath_hz: float) -> bytes:
    """RESP and an ECG spike train whose rate follows breathing (respiratory sinus arrhythmia)."""
    rng = np.random.default_rng(sum(map(ord, name)))
    t = np.arange(FS * SECONDS) / FS
    resp = np.sin(2 * np.pi * breath_hz * t + rng.uniform(0, 6)) + 0.05 * rng.standard_normal(len(t))
    beats, now = [], 0.5
    while now < SECONDS - 0.5:
        beats.append(now)
        now += 60.0 / (65 + 6 * np.sin(2 * np.pi * breath_hz * (now - 0.6)) + rng.normal(0, 0.4))
    ecg = 0.02 * rng.standard_normal(len(t))
    for beat in beats:
        i = int(beat * FS)
        ecg[i - 2:i + 3] += [0.2, 0.6, 1.0, 0.6, 0.2]
    digital = np.column_stack([resp, ecg]) * 200.0
    return np.round(digital).astype("<i2").tobytes()


class FakePhysioNet:
    def __init__(self) -> None:
        self.files = {}
        for name, hz in RECORDS.items():
            self.files[f"{name}.dat"] = _recording(name, hz)
            frames = len(self.files[f"{name}.dat"]) // 4
            self.files[f"{name}.hea"] = (f"{name} 2 {FS} {frames}\n{name}.dat 16 200 16 0 0 0 0 RESP\n"
                                         f"{name}.dat 16 200 16 0 0 0 0 ECG\n").encode("ascii")
        self.requests: list[tuple[str, str | None]] = []
        self.fail: str | None = None

    def get(self, url: str, **headers: str):
        name = url.rsplit("/", 1)[-1]
        self.requests.append((name, headers.get("Range")))
        if self.fail:
            raise ConnectionError(self.fail)

        class Response:
            status_code = 200
            content = b""

        response = Response()
        body = self.files[name]
        if "Range" in headers:
            first, last = (int(b) for b in headers["Range"].removeprefix("bytes=").split("-"))
            response.status_code, response.content = 206, body[first:last + 1]
        else:
            response.content = body
        return response

    def range_requests(self) -> list[tuple[str, str]]:
        return [(name, span) for name, span in self.requests if span]


@pytest.fixture
def physionet(monkeypatch):
    server = FakePhysioNet()
    monkeypatch.setattr(physio, "_get", server.get)
    return server


@dataclass
class Doc:
    id: str
    title: str
    url: str
    published: str
    authors: list[str]
    abstract: str


DOCUMENTS = [
    Doc("arxiv:2001.00001", "Respiratory sinus arrhythmia couples breathing and heart rate",
        "https://arxiv.org/abs/2001.00001", "2020-01-01", ["A. Author"],
        "Respiratory sinus arrhythmia is the rhythmic increase of heart rate during inspiration and its decrease "
        "during expiration in healthy resting adults. Breathing drives heart rate through vagal modulation."),
    Doc("arxiv:2002.00002", "Lag windows for cardiorespiratory coupling detection",
        "https://arxiv.org/abs/2002.00002", "2020-02-02", ["B. Author"],
        "Surrogate tests detect cardiorespiratory coupling when the lag window covers the breathing period. "
        "Slow breathing shifts the peak of the cross-correlation to longer lags."),
    Doc("arxiv:2003.00003", "Heart rate variability at rest",
        "https://arxiv.org/abs/2003.00003", "2020-03-03", ["C. Author"],
        "Heart rate variability at rest reflects respiration and autonomic tone in healthy young adults."),
]


def sealed_packet(query: str) -> dict[str, Any]:
    vendor.ensure_importable()
    from engine import records

    hits = [{"score": 1.0 / (rank + 1), "explanation": None, "highlights": [],
             "document": {"id": d.id, "title": d.title, "source": "arxiv", "url": d.url, "pdf_url": "",
                          "authors": d.authors, "published": d.published, "version": "", "abstract": d.abstract}}
            for rank, d in enumerate(DOCUMENTS)]
    record = {"schema": records.RECORD_SCHEMA, "provider": "live",
              "request": {"q": query, "mode": "hybrid", "page": 1, "per_page": len(hits), "filters": {}},
              "retrieval": {"embedding": "hashing", "fusion": "rrf"}, "result_count": len(hits),
              "scope": "current-page", "hits": hits, "summary": None}
    return {"captured_at": "2026-10-04T00:00:00.000Z", "content_sha256": records.fingerprint(record), "record": record}


@pytest.fixture
def anna(monkeypatch):
    calls = []

    def run(spec, *, pgdata, offline):
        calls.append(spec["literature"]["search"])
        return anna_stage.AnnaResult(packet=sealed_packet(spec["literature"]["search"]),
                                     verification={"ok": True, "counts": {"verified": 0}}, ingestion=[],
                                     documents=list(DOCUMENTS))

    monkeypatch.setattr(anna_stage, "run", run)
    return calls


@pytest.fixture
def clean_code(monkeypatch):
    """Pretend this package's source is committed, so holdout runs are allowed while it is being edited."""
    identity = provenance.code_identity()
    identity["git"] = {"commit": "c" * 40, "branch": "main", "dirty": False}
    monkeypatch.setattr(provenance, "code_identity", lambda: copy.deepcopy(identity))
    return identity


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class Workspace:
    """A git repository with a bare 'origin' beside it, so anchors can be pushed as on GitHub."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True)
        self.layout = Layout.at(root)
        remote = root.parent / f"{root.name}-origin.git"
        git(root.parent, "init", "-q", "--bare", "-b", "main", str(remote))
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "test@example.invalid")
        git(root, "config", "user.name", "test")
        git(root, "config", "commit.gpgsign", "false")
        git(root, "remote", "add", "origin", str(remote))
        (root / "README.md").write_text("evidence workspace\n", encoding="utf-8")
        self.commit("start")

    def commit(self, message: str = "record", push: bool = True) -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", message)
        if push:
            git(self.root, "push", "-q", "origin", "main")
        return git(self.root, "rev-parse", "HEAD")

    def spec(self, name: str, **changes: Any) -> Path:
        """A small spec over the synthetic records; each of ``changes`` updates one section (top-level keys only)."""
        spec = base_spec()
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(spec.get(key), dict):
                spec[key] = {**spec[key], **value}
            else:
                spec[key] = value
        path = self.layout.specs / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return path

    def copy(self, destination: Path) -> "Workspace":
        shutil.copytree(self.root, destination)
        clone = Workspace.__new__(Workspace)
        clone.root, clone.layout = destination, Layout.at(destination)
        return clone


@pytest.fixture
def workspace(tmp_path) -> Workspace:
    return Workspace(tmp_path / "evidence")


ANALYSIS = {
    "study": "lag_window", "method": "lagged_correlation", "surrogate_method": "circular_shift",
    "correction": "max_statistic", "n_surrogates": 19, "alpha": 0.05, "seed": 7,
    "arms": {"short": {"max_lag_s": 3.0}, "long": {"max_lag_s": 6.0}},
    "strata": {"slow": {"min_hz": 0.0833, "below_hz": 0.1667}, "normal": {"min_hz": 0.1667}},
    "contrasts": {"normal_change_long_vs_short": {"metric": "normal_detection_rate", "arm": "long", "minus": "short"}},
    "controls": {"synthetic_trials": 2, "positive_coupling": 0.3, "positive_lag_samples": 4,
                 "long_lag_samples": 18, "ar_coefficient": 0.5},
}


def metric(name: str, unit: str = "ratio") -> dict[str, Any]:
    return {"name": name, "unit": unit, "description": name.replace("_", " "), "deterministic": True}


def base_spec() -> dict[str, Any]:
    return copy.deepcopy({
        "question": "Does breathing drive heart rate in synthetic recordings?",
        "literature": {"arxiv_queries": ["abs:\"respiratory sinus arrhythmia\""], "limit_per_query": 5,
                       "search": "respiratory sinus arrhythmia", "max_sources": 3},
        "data": {"source": "physionet-fantasia", "records": list(RECORDS),
                 "segments": {"first_start_s": 0, "duration_s": 150, "count": 2},
                 "grid_hz": 4, "highpass_hz": 0.05, "qc": {"min_valid_rr_fraction": 0.9}},
        "analysis": ANALYSIS,
        "preregistration": {
            "title": "Synthetic coupling is detected",
            "question": "Is coupling detected in synthetic recordings with built-in sinus arrhythmia?",
            "hypothesis": "Normal-breathing windows are detected at a subject-balanced rate of at least 0.5.",
            "rationale": "A test fixture.",
            "evidence_class": "measured",
            "procedure": ["Run the registered study on the synthetic records."],
            "variables": {"independent": ["lag window"], "dependent": ["adjusted p"], "controls": ["synthetic"]},
            "metrics": [metric("windows_analyzed", "count"), metric("normal_detection_rate_short"),
                        metric("normal_change_long_vs_short"), metric("synthetic_null_false_positive_rate_short")],
            "criteria": {
                "guards": [{"id": "G1", "metric": "windows_analyzed", "op": ">=", "value": 4}],
                "success": [{"id": "S1", "metric": "normal_detection_rate_short", "op": ">=", "value": 0.5}],
                "failure": [{"id": "F1", "metric": "normal_detection_rate_short", "op": "<", "value": 0.2}],
            },
            "dependencies": ["drr-framework"],
            "data_policy": {"classification": "public", "store_artifacts": False},
            "limitations": ["Synthetic data."],
            "created_by": "rain-pipeline-tests",
        },
    })


HOLDOUT_METRICS = [metric("holdout_bytes_read_before_registration", "bytes"),
                   metric("holdout_bytes_read_before_anchor", "bytes")]
HOLDOUT_GUARDS = [{"id": "G2", "metric": "holdout_bytes_read_before_anchor", "op": "<=", "value": 0},
                  {"id": "G3", "metric": "holdout_bytes_read_before_registration", "op": "<=", "value": 0}]


def holdout_changes(**data: Any) -> dict[str, Any]:
    spec = base_spec()
    prereg = spec["preregistration"]
    prereg["metrics"] = prereg["metrics"] + HOLDOUT_METRICS
    prereg["criteria"]["guards"] = prereg["criteria"]["guards"] + HOLDOUT_GUARDS
    return {"data": {**spec["data"], "holdout": True, **data}, "preregistration": prereg}


def _fake_anna_run(spec, *, pgdata, offline):
    return anna_stage.AnnaResult(packet=sealed_packet(spec["literature"]["search"]),
                                 verification={"ok": True, "counts": {"verified": 0}}, ingestion=[],
                                 documents=list(DOCUMENTS))


def build_completed(root: Path) -> Workspace:
    """A finished evidence repository: holdout registered, anchored, run, explored afterwards, replayed."""
    from rain_pipeline import pipeline, replay

    with pytest.MonkeyPatch.context() as patch:
        server = FakePhysioNet()
        patch.setattr(physio, "_get", server.get)
        patch.setattr(anna_stage, "run", _fake_anna_run)
        identity = provenance.code_identity()
        identity["git"] = {"commit": "c" * 40, "branch": "main", "dirty": False}
        patch.setattr(provenance, "code_identity", lambda: copy.deepcopy(identity))
        ws = Workspace(root)
        spec = ws.spec("coupling", **holdout_changes())
        pipeline.register(spec, layout=ws.layout, log=quiet)
        ws.commit("register V3D-EXP-0001")
        pipeline.run(spec, layout=ws.layout, log=quiet)
        ws.commit("run V3D-EXP-0001")
        seen = {"question": "After the run: what does the 6 s window see on the same, now seen, windows?",
                "data": base_spec()["data"], "analysis": ANALYSIS}
        path = ws.layout.specs / "explore-seen.json"
        path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
        pipeline.explore(path, layout=ws.layout, log=quiet)
        replay.replay("V3D-EXP-0001", layout=ws.layout, log=quiet)
        ws.commit("explore seen data; replay V3D-EXP-0001")
    return ws


@pytest.fixture(scope="session")
def completed_template(tmp_path_factory) -> Workspace:
    return build_completed(tmp_path_factory.mktemp("completed") / "evidence")


@pytest.fixture
def completed(completed_template, tmp_path) -> Workspace:
    """A private copy of the finished repository, free to tamper with."""
    return completed_template.copy(tmp_path / "evidence")
