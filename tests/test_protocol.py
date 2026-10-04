"""The protocol end to end, offline: register -> commit -> run -> verify, every refusal and every outcome.

A refusal must leave no trace (no run, no ledger entry, no byte requested). Once
a run has started it must leave a R.A.I.N. record whatever happens, and the
record's status is R.A.I.N.'s alone.
"""

import json
import math

import pytest
from conftest import HOLDOUT_GUARDS, HOLDOUT_METRICS, base_spec, holdout_changes, metric, quiet

from rain_pipeline import drr_stage, evidence, figures, ledger, pipeline, provenance, registry_stage
from rain_pipeline.errors import DossierMismatch, HoldoutViolation, NotRegistered, ProtocolRefusal, SpecError, UnpinnedCode


def register(ws, name="coupling", commit=True, **changes):
    spec = ws.spec(name, **changes)
    pipeline.register(spec, layout=ws.layout, log=quiet)
    if commit:
        ws.commit(f"register {name}")
    return spec


def runs(ws):
    return sorted(ws.layout.runs.glob("*/submission.json"))


def records(ws, experiment_id="V3D-EXP-0001"):
    registry = registry_stage.open_registry(ws.layout.experiments, ws.layout.results)
    return registry.runs(experiment_id)


def nothing_happened(ws, physionet):
    return not ws.layout.runs.exists() and not ws.layout.ledger.exists() and not physionet.range_requests()


def with_criteria(**criteria):
    prereg = base_spec()["preregistration"]
    prereg["criteria"] = {**prereg["criteria"], **criteria}
    return prereg


# --------------------------------------------------------------------------- #
# The normal path
# --------------------------------------------------------------------------- #
def test_register_commit_run_verify(workspace, physionet, anna, clean_code):
    spec = register(workspace, **holdout_changes())
    summary = pipeline.run(spec, layout=workspace.layout, log=quiet)
    workspace.commit("run")

    assert (summary["status"], summary["verdict"]) == ("passed", "supported")
    submission = json.loads(runs(workspace)[0].read_text(encoding="utf-8"))
    assert not {"status", "verdict", "hypothesis_verdict"} & set(submission)  # the runner decides nothing
    definition = registry_stage.open_registry(workspace.layout.experiments).load_definition("V3D-EXP-0001")
    assert list(submission["measurements"]) == [m["name"] for m in definition["metrics"]]  # exactly the registered
    assert submission["measurements"]["holdout_bytes_read_before_anchor"] == 0
    assert submission["inputs"]["registration"]["git"]["commit"]
    assert submission["inputs"]["evidence"]["evaluated_metrics"] == [  # read by a criterion: they decide the verdict
        "windows_analyzed", "normal_detection_rate_short", "holdout_bytes_read_before_registration",
        "holdout_bytes_read_before_anchor"]
    assert submission["inputs"]["evidence"]["described_metrics"] == [  # registered, but decide nothing
        "normal_change_long_vs_short", "synthetic_null_false_positive_rate_short"]
    assert "synthetic_long_lag_detection_rate_long" in submission["inputs"]["evidence"]["unregistered_outputs"]

    book = ledger.load(workspace.layout.ledger)
    assert {e["first_read_by"] for e in book["entries"]} == {"V3D-EXP-0001"}
    assert len(book["entries"]) == len(physionet.range_requests()) == 4  # one range per record, read once

    report = evidence.verify(workspace.layout)
    assert report.ok, [c for c in report.checks if not c.ok]
    (claim,) = report.claims
    assert claim["evidence_level"] == "confirmatory"
    report_md = (runs(workspace)[0].parent / "REPORT.md").read_text(encoding="utf-8")
    assert report_md.startswith("# V3D-EXP-0001-RUN-0001: PASSED\n")
    assert "## Registered, not evaluated (description)" in report_md and "never submitted" in report_md


def test_failed_and_inconclusive_are_recorded_as_such(workspace, physionet, anna, clean_code):
    failing = with_criteria(failure=[{"id": "F1", "metric": "normal_detection_rate_short", "op": ">=", "value": 0.5}],
                            success=[{"id": "S1", "metric": "normal_detection_rate_short", "op": ">=", "value": 0.9}])
    spec = register(workspace, "fails", preregistration=failing)
    assert pipeline.run(spec, layout=workspace.layout, log=quiet)["status"] == "failed"

    starved = with_criteria(guards=[{"id": "G1", "metric": "windows_analyzed", "op": ">=", "value": 1000}])
    spec = register(workspace, "starved", preregistration={**starved, "title": "Needs more windows than exist"})
    summary = pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert (summary["status"], summary["verdict"]) == ("inconclusive", "insufficient_evidence")


# --------------------------------------------------------------------------- #
# Refusals before anything is read
# --------------------------------------------------------------------------- #
def test_run_refuses_a_spec_that_was_never_registered(workspace, physionet):
    with pytest.raises(NotRegistered):
        pipeline.run(workspace.spec("never"), layout=workspace.layout, log=quiet)
    assert nothing_happened(workspace, physionet)


def test_run_refuses_an_uncommitted_registration(workspace, physionet, anna):
    spec = register(workspace, commit=False)
    with pytest.raises(registry_stage.NotAnchored, match="not committed"):
        pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert nothing_happened(workspace, physionet)


def test_run_refuses_a_spec_whose_goalposts_moved(workspace, physionet, anna):
    spec = register(workspace)
    moved = json.loads(spec.read_text(encoding="utf-8"))
    moved["preregistration"]["criteria"]["success"][0]["value"] = 0.1
    spec.write_text(json.dumps(moved), encoding="utf-8")
    with pytest.raises(registry_stage.experiment_error(), match="write-once"):
        pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert nothing_happened(workspace, physionet)
    checks = {c.name: c for c in evidence.verify(workspace.layout).checks}
    assert checks["registration.spec"].status == evidence.FAIL


def test_run_refuses_a_registration_edited_in_history(workspace, physionet, anna):
    spec = register(workspace)
    path = workspace.layout.experiments / "V3D-EXP-0001" / "experiment.json"
    definition = json.loads(path.read_text(encoding="utf-8"))
    definition["criteria"]["success"][0]["value"] = 0.1          # move the goalposts in the record itself...
    path.write_text(json.dumps(definition, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    edited = json.loads(spec.read_text(encoding="utf-8"))        # ...and in the spec, and in the dossier,
    edited["preregistration"]["criteria"]["success"][0]["value"] = 0.1
    spec.write_text(json.dumps(edited), encoding="utf-8")
    framing = next(workspace.layout.framing.glob("*/framing.json"))
    manifest = json.loads(framing.read_text(encoding="utf-8"))
    manifest["definition_sha256"] = registry_stage.definition_sha256(definition)
    framing.write_text(json.dumps(manifest), encoding="utf-8")
    workspace.commit("quietly edit the registration")           # ...and commit it: history still remembers
    with pytest.raises(registry_stage.NotAnchored, match="changed after its first commit"):
        pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert nothing_happened(workspace, physionet)
    checks = {c.name: c for c in evidence.verify(workspace.layout).checks}
    assert checks["registration.history"].status == evidence.FAIL


def test_run_refuses_a_framing_dossier_that_changed(workspace, physionet, anna):
    spec = register(workspace)
    meeting = next(workspace.layout.framing.glob("*/panel_meeting.md"))
    meeting.write_text(meeting.read_text(encoding="utf-8") + "\nA convenient afterthought.\n", encoding="utf-8")
    workspace.commit("edit the transcript")
    with pytest.raises(DossierMismatch, match="framing.files"):
        pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert nothing_happened(workspace, physionet)


def test_a_holdout_is_never_read_without_an_anchor(workspace, physionet, anna, clean_code):
    spec = register(workspace, commit=False, **holdout_changes())
    with pytest.raises(HoldoutViolation, match="anchored in git"):
        pipeline.run(spec, layout=workspace.layout, allow_uncommitted=True, log=quiet)
    assert nothing_happened(workspace, physionet)


def test_a_holdout_runs_only_committed_pinned_code(workspace, physionet, anna, monkeypatch):
    spec = register(workspace, **holdout_changes())
    identity = provenance.code_identity()
    identity["git"]["dirty"] = True
    monkeypatch.setattr(provenance, "code_identity", lambda: identity)
    with pytest.raises(UnpinnedCode, match="rain_pipeline: uncommitted changes"):
        pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert nothing_happened(workspace, physionet)


def test_an_unanchored_run_is_allowed_without_a_holdout_but_rated_lower(workspace, physionet, anna):
    spec = register(workspace, commit=False)
    assert pipeline.run(spec, layout=workspace.layout, allow_uncommitted=True, log=quiet)["status"] == "passed"
    workspace.commit("unanchored run")
    report = evidence.verify(workspace.layout)
    assert report.ok
    (claim,) = report.claims
    assert claim["evidence_level"] == "registered"
    assert any("run.anchor" in link for link in claim["weaker_links"])


# --------------------------------------------------------------------------- #
# Registration refuses what would later waste or contaminate data
# --------------------------------------------------------------------------- #
def test_register_refuses_a_metric_the_study_never_produces(workspace, physionet, anna):
    prereg = base_spec()["preregistration"]
    prereg["metrics"].append(metric("normal_detection_rate_shortt"))  # a typo would end a holdout run as an error
    with pytest.raises(SpecError, match="normal_detection_rate_shortt"):
        pipeline.register(workspace.spec("typo", preregistration=prereg), layout=workspace.layout, log=quiet)
    assert anna == [] and not workspace.layout.experiments.exists() and not workspace.layout.framing.exists()


def test_register_refuses_a_definition_rain_would_reject(workspace, physionet, anna):
    prereg = with_criteria(success=[{"id": "S1", "metric": "not_declared", "op": ">=", "value": 1}])
    with pytest.raises(SpecError, match="R.A.I.N.: criteria/success/S1"):
        pipeline.register(workspace.spec("invalid", preregistration=prereg), layout=workspace.layout, log=quiet)
    assert anna == []


def test_register_refuses_an_unguarded_holdout(workspace, physionet, anna):
    changes = holdout_changes()
    changes["preregistration"]["criteria"]["guards"] = [{"id": "G1", "metric": "windows_analyzed", "op": ">=", "value": 4}]
    with pytest.raises(SpecError, match="a holdout needs a guard"):
        pipeline.register(workspace.spec("unguarded", **changes), layout=workspace.layout, log=quiet)
    assert anna == []


def test_a_shared_holdout_must_be_acknowledged(workspace, physionet, anna):
    register(workspace, "first", **holdout_changes())
    second = holdout_changes()
    second["preregistration"]["title"] = "A sibling on the same held-out data"
    with pytest.raises(SpecError, match="holdout_shared_with"):
        pipeline.register(workspace.spec("second", **second), layout=workspace.layout, log=quiet)
    acknowledged = holdout_changes(holdout_shared_with=["V3D-EXP-0001"])
    acknowledged["preregistration"]["title"] = second["preregistration"]["title"]
    assert pipeline.register(workspace.spec("second", **acknowledged), layout=workspace.layout,
                             log=quiet)["experiment_id"] == "V3D-EXP-0002"
    workspace.commit("siblings")
    assert evidence.holdout_families(evidence.snapshot(workspace.layout)) == [["V3D-EXP-0001", "V3D-EXP-0002"]]


def test_retitling_a_spec_never_destroys_the_registered_dossier(workspace, physionet, anna):
    spec = register(workspace)
    dossier = sorted(p.name for p in (workspace.layout.framing / "coupling").iterdir())
    renamed = json.loads(spec.read_text(encoding="utf-8"))
    renamed["preregistration"]["title"] = "A new idea in the old file"
    spec.write_text(json.dumps(renamed), encoding="utf-8")
    with pytest.raises(ProtocolRefusal, match="already holds the framing of V3D-EXP-0001"):
        pipeline.register(spec, layout=workspace.layout, log=quiet)
    assert sorted(p.name for p in (workspace.layout.framing / "coupling").iterdir()) == dossier


def test_register_refuses_a_holdout_that_was_already_read(workspace, physionet, anna):
    register(workspace, "seen", commit=True)
    pipeline.run(workspace.layout.specs / "seen.json", layout=workspace.layout, log=quiet)
    changes = holdout_changes()
    changes["preregistration"]["title"] = "Confirm on the same bytes"
    with pytest.raises(HoldoutViolation, match="already been read"):
        pipeline.register(workspace.spec("reuse", **changes), layout=workspace.layout, log=quiet)


# --------------------------------------------------------------------------- #
# Holdout timing: reads between registration and anchor are caught
# --------------------------------------------------------------------------- #
def test_a_read_between_registration_and_anchor_fails_the_guard(workspace, physionet, anna, clean_code):
    spec = register(workspace, commit=False, **holdout_changes())
    plan = pipeline.plan_data(json.loads(spec.read_text(encoding="utf-8"))["data"], workspace.layout.cache)[0]
    content = physionet.files["syn01.dat"][plan.byte_range[0]:plan.byte_range[1] + 1]
    ledger.record(workspace.layout.ledger, url=plan.url, byte_range=plan.byte_range,  # someone peeks
                  sha256=provenance.sha256_bytes(content), read_at=ledger.utc_now(), read_by="V3D-EXP-0001")
    workspace.commit("anchor after the peek")
    summary = pipeline.run(spec, layout=workspace.layout, log=quiet)
    assert summary["measurements"]["holdout_bytes_read_before_registration"] == 0  # the old check sees nothing
    assert summary["measurements"]["holdout_bytes_read_before_anchor"] == len(content)
    assert summary["status"] == "inconclusive"                                   # R.A.I.N.'s guard G2 does
    workspace.commit("run")
    checks = {(c.name, c.subject): c for c in evidence.verify(workspace.layout).checks}
    assert checks[("holdout.before_anchor", "V3D-EXP-0001")].status == evidence.FAIL


# --------------------------------------------------------------------------- #
# Once data is read, every failure is an R.A.I.N. error run, never a lost run
# --------------------------------------------------------------------------- #
def _crash_only_on_real_data(monkeypatch, error):
    real = drr_stage.run

    def run(windows, excluded, analysis):
        if windows and not windows[0].record.startswith("dry_"):  # let the pre-run dry run pass
            raise error
        return real(windows, excluded, analysis)

    monkeypatch.setattr(drr_stage, "run", run)


def test_a_crash_while_fetching_data_is_an_error_run(workspace, physionet, anna):
    spec = register(workspace)
    physionet.fail = "physionet.org unreachable"
    summary = pipeline.run(spec, layout=workspace.layout, log=quiet)
    (record,) = records(workspace)
    assert summary["status"] == record["status"] == "error"
    assert record["error"]["stage"] == "data" and record["hypothesis_verdict"] == "not_evaluated"
    assert all(value is None for value in record["measurements"].values())


def test_a_crash_in_the_analysis_is_an_error_run(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    _crash_only_on_real_data(monkeypatch, RuntimeError("DRR diverged"))
    assert pipeline.run(spec, layout=workspace.layout, log=quiet)["status"] == "error"
    (record,) = records(workspace)
    assert record["error"] == {"stage": "analysis", "type": "RuntimeError", "message": "DRR diverged"}
    assert ledger.load(workspace.layout.ledger)["entries"]  # the data was spent, and the record says so
    assert (runs(workspace)[0].parent / "error.txt").is_file()


def test_a_crash_writing_artifacts_is_an_error_run(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    real = provenance.write_json

    def write_json(path, payload):
        if path.name == "drr_report.json":
            raise OSError("disk full")
        return real(path, payload)

    monkeypatch.setattr(provenance, "write_json", write_json)
    pipeline.run(spec, layout=workspace.layout, log=quiet)
    (record,) = records(workspace)
    assert (record["status"], record["error"]["stage"]) == ("error", "artifacts")


def test_an_interrupted_run_is_recorded_before_the_interrupt_resumes(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    _crash_only_on_real_data(monkeypatch, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(spec, layout=workspace.layout, log=quiet)
    (record,) = records(workspace)
    assert (record["status"], record["error"]["type"], record["error"]["message"]) == \
        ("error", "KeyboardInterrupt", "interrupted")


def test_a_submission_rain_rejects_is_kept_and_recorded_as_error(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    real, calls = registry_stage.submission_errors, []

    def submission_errors(submission):
        calls.append(1)
        return ["measurements/x: not a number"] if len(calls) == 1 else real(submission)

    monkeypatch.setattr(registry_stage, "submission_errors", submission_errors)
    pipeline.run(spec, layout=workspace.layout, log=quiet)
    (record,) = records(workspace)
    assert (record["status"], record["error"]["stage"]) == ("error", "submission")
    assert (runs(workspace)[0].parent / "submission.rejected.json").is_file()


def test_a_crash_assembling_the_submission_is_still_recorded(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    monkeypatch.setattr(pipeline, "_observations", lambda *a: [][0])  # an IndexError deep in assembly
    pipeline.run(spec, layout=workspace.layout, log=quiet)
    (record,) = records(workspace)
    assert (record["status"], record["error"]["stage"], record["error"]["type"]) == ("error", "submission", "IndexError")
    assert record["inputs"]["dataset"]["files"]  # what was read is still on the record
    workspace.commit("record")
    checks = {c.name: c for c in evidence.verify(workspace.layout).checks if c.subject == record["run_id"]}
    assert checks["run.submission"].status == evidence.OK and checks["run.data"].status == evidence.OK


def test_a_figure_failure_does_not_void_a_measured_run(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    monkeypatch.setattr(figures, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no display")))
    assert pipeline.run(spec, layout=workspace.layout, log=quiet)["status"] == "passed"
    (record,) = records(workspace)
    assert any("figure could not be rendered" in note for note in record["observations"])
    assert "figure" not in {a["kind"] for a in record["artifacts"]}
    assert not (runs(workspace)[0].parent / "figure.png").exists()


def test_a_non_finite_measurement_is_submitted_as_not_measured(workspace, physionet, anna, monkeypatch):
    spec = register(workspace)
    real = drr_stage.run

    def run(windows, excluded, analysis):
        result = real(windows, excluded, analysis)
        if windows and not windows[0].record.startswith("dry_"):
            result.measurements["normal_detection_rate_short"] = math.nan
        return result

    monkeypatch.setattr(drr_stage, "run", run)
    summary = pipeline.run(spec, layout=workspace.layout, log=quiet)
    (record,) = records(workspace)
    assert record["measurements"]["normal_detection_rate_short"] is None
    assert summary["status"] == "inconclusive"  # a criterion on a missing measurement cannot hold
    assert any("normal_detection_rate_short" in note for note in record["observations"])
    report = json.loads((runs(workspace)[0].parent / "drr_report.json").read_text(encoding="utf-8"))
    assert report["measurements"]["normal_detection_rate_short"] is None  # strict JSON: null, never NaN
    assert any("drr_report.json" in note and "null" in note for note in record["observations"])


def test_holdout_guard_metrics_are_documented_pipeline_outputs():
    assert {m["name"] for m in HOLDOUT_METRICS} == set(pipeline.specs.PIPELINE_METRICS)
    assert all(guard["metric"] in pipeline.specs.PIPELINE_METRICS for guard in HOLDOUT_GUARDS)
