"""verify must notice every way the evidence could be quietly changed after the fact.

Each case takes a finished, verified repository, alters one record the way a
careless edit or a motivated one might, and requires the named check to fail.
"""

import json
from pathlib import Path

import pytest

from rain_pipeline import evidence, provenance


def _one(ws, pattern: str) -> Path:
    (path,) = sorted(ws.root.glob(pattern))
    return path


def _edit_json(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _ledger(ws, change) -> None:
    _edit_json(ws.layout.ledger, change)


def _set(key, value):
    def change(data):
        data[key] = value
    return change


TAMPERING = {
    "an artifact is edited": (
        lambda ws: _append(_one(ws, "runs/*/drr_report.json"), " "), {"run.artifacts"}),
    "the submission is edited": (
        lambda ws: _edit_json(_one(ws, "runs/*/submission.json"),
                              lambda s: s["measurements"].update(normal_detection_rate_short=0.0)), {"run.submission"}),
    "a descriptive measurement is edited in the R.A.I.N. record": (
        lambda ws: _edit_json(_one(ws, "experiments/*/runs/RUN-0001/result.json"),
                              lambda r: r["measurements"].update(normal_change_long_vs_short=0.5)),
        {"run.submission", "run.summary"}),
    "the recorded anchor is rewritten": (
        lambda ws: _edit_json(_one(ws, "experiments/*/runs/RUN-0001/result.json"),
                              lambda r: r["inputs"]["registration"]["git"].update(commit="0" * 40)),
        {"run.submission", "run.anchor"}),
    "the human summary claims another status": (
        lambda ws: _edit_json(_one(ws, "runs/*/summary.json"), _set("status", "failed")), {"run.summary"}),
    "the report claims another outcome": (
        lambda ws: _one(ws, "runs/*/REPORT.md").write_text(
            _one(ws, "runs/*/REPORT.md").read_text(encoding="utf-8").replace(": PASSED", ": FAILED", 1),
            encoding="utf-8"), {"run.report"}),
    "the panel transcript is edited": (
        lambda ws: _append(_one(ws, "framing/*/panel_meeting.md"), "\nOne more thing.\n"), {"framing.files"}),
    "a corpus abstract is edited": (
        lambda ws: _append(sorted(ws.root.glob("framing/*/corpus/*.md"))[0], "\nIt was obvious all along.\n"),
        {"framing.corpus"}),
    "the literature record is edited": (
        lambda ws: _edit_json(_one(ws, "framing/*/anna_record.json"),
                              lambda p: p["record"]["hits"][0]["document"].update(title="A better paper")),
        {"framing.anna", "framing.files"}),
    "the results page is edited by hand": (
        lambda ws: ws.layout.results.write_text(ws.layout.results.read_text(encoding="utf-8").replace(
            "PASSED", "PASSED (decisively)", 1), encoding="utf-8"), {"results.page"}),
    "the registration is edited in the working tree": (
        lambda ws: _edit_json(_one(ws, "experiments/V3D-EXP-0001/experiment.json"),
                              lambda d: d["criteria"]["success"][0].update(value=0.1)),
        {"registration.history", "framing.manifest", "rain.verify"}),
    "the registered spec is edited": (
        lambda ws: _edit_json(ws.layout.specs / "coupling.json",
                              lambda s: s["preregistration"]["criteria"]["success"][0].update(value=0.1)),
        {"registration.spec"}),
    "a ledger entry is removed": (
        lambda ws: _ledger(ws, lambda book: book["entries"].pop(0)), {"ledger.history", "run.data"}),
    "a first read is backdated before the registration": (
        lambda ws: _ledger(ws, lambda book: book["entries"][0].update(first_read_at="2001-01-01T00:00:00.000Z")),
        {"ledger.history", "holdout.before_registration", "holdout.before_anchor"}),
    "the ledger records a different content hash": (
        lambda ws: _ledger(ws, lambda book: book["entries"][0].update(sha256="f" * 64)), {"ledger.history", "run.data"}),
    "an exploration is recorded as a first reader": (
        lambda ws: _ledger(ws, lambda book: book["entries"].append(
            {"url": "https://example.org/x.dat", "byte_range": [0, 9], "sha256": "a" * 64,
             "first_read_at": "2030-01-01T00:00:00.000Z", "first_read_by": "exploration"})), {"ledger.accounted"}),
    "an exploration loses its label": (
        lambda ws: _edit_json(_one(ws, "explorations/*/report.json"), _set("status", "CONFIRMED")),
        {"exploration.label"}),
    "a replay receipt overstates its outcome": (
        lambda ws: _edit_json(_one(ws, "replays/*/*.json"), lambda r: r["comparison"]["measurements"][
            "windows_analyzed"].update(identical=False)), {"receipt.binding"}),
}


def test_the_finished_repository_verifies(completed):
    report = evidence.verify(completed.layout)
    assert report.ok, [c for c in report.checks if not c.ok]
    assert {c.status for c in report.checks} <= {evidence.OK, evidence.WARN}
    (claim,) = report.claims
    assert claim["evidence_level"] == "confirmatory"
    assert [r["outcome"] for r in claim["replays"]] == ["reproduced"]


@pytest.mark.parametrize("case", sorted(TAMPERING))
def test_tampering_is_detected(completed, case):
    tamper, expected = TAMPERING[case]
    tamper(completed)
    report = evidence.verify(completed.layout)
    failed = {c.name for c in report.checks if c.status == evidence.FAIL}
    assert expected <= failed, f"{case}: expected {expected} to fail, failed: {failed}"
    assert not report.ok


def test_a_tampered_claim_is_downgraded(completed):
    _append(_one(completed, "runs/*/drr_report.json"), " ")
    (claim,) = evidence.verify(completed.layout).claims
    assert claim["evidence_level"] == "unverified"
    assert any(link.startswith("run.artifacts") for link in claim["broken_links"])


def test_verify_never_crashes_on_a_corrupt_record(completed):
    _one(completed, "framing/*/framing.json").write_text("{not json", encoding="utf-8")
    report = evidence.verify(completed.layout)
    assert not report.ok and any(c.name == "framing.manifest" for c in report.checks if c.status == evidence.FAIL)


def test_an_unrecorded_attempt_stays_visible(completed):
    attempt = completed.layout.runs / "20000101T000000Z"
    attempt.mkdir()
    (attempt / "CRASHED.txt").write_text("Crashed before it could submit.\n", encoding="utf-8")
    checks = [c for c in evidence.verify(completed.layout).checks if c.name == "runs.unrecorded"]
    assert [(c.subject, c.status) for c in checks] == [("runs/20000101T000000Z", evidence.WARN)]
    assert "Crashed before it could submit." in checks[0].detail


def test_without_git_history_the_history_checks_skip_instead_of_passing(completed):
    import shutil

    shutil.rmtree(completed.root / ".git")
    report = evidence.verify(completed.layout)
    skipped = {c.name for c in report.checks if c.status == evidence.SKIP}
    assert {"registration.history", "ledger.history", "run.anchor", "holdout.before_anchor"} <= skipped
    assert report.ok  # nothing is broken; it just cannot be shown here (--strict turns this into a failure)


def test_the_graph_is_content_addressed_and_stable(completed):
    first, second = evidence.graph(completed.layout), evidence.graph(completed.layout)
    assert first == second and first["schema"] == evidence.GRAPH_SCHEMA
    nodes = {n["id"]: n for n in first["nodes"]}
    relations = {(e["from"].split(":")[0], e["relation"], e["to"].split(":")[0]) for e in first["edges"]}
    assert {("run", "tests", "registration"), ("verdict", "evaluates", "run"), ("run", "consumed", "data"),
            ("run", "produced", "file"), ("run", "anchored_by", "commit"), ("registration", "binds", "corpus"),
            ("registration", "reserves", "data"), ("receipt", "replays", "run"),
            ("exploration", "consumed", "data")} <= relations
    assert nodes["verdict:V3D-EXP-0001-RUN-0001"]["status"] == "passed"
    assert nodes["exploration:" + next(k.split(":", 1)[1] for k in nodes if k.startswith("exploration:"))]["role"] \
        == "observation (not evidence)"
    assert first["digest"] == provenance.canonical_sha256({"nodes": first["nodes"], "edges": first["edges"]})
    _append(_one(completed, "runs/*/drr_report.json"), " ")
    assert evidence.graph(completed.layout)["digest"] != first["digest"]  # any change to evidence changes the digest


def test_lineage_describes_the_chain(completed):
    text = evidence.describe(evidence.verify(completed.layout), evidence.graph(completed.layout))
    assert "confirmatory" in text and "anchored" in text and "replayed     reproduced" in text
    assert "Explorations (observations on seen data, never evidence)" in text
