import copy
import json
import subprocess

import pytest

from rain_pipeline import registry_stage, vendor


@pytest.fixture
def spec():
    return json.loads((vendor.PROJECT_ROOT / "specs" / "cardiorespiratory.json").read_text(encoding="utf-8"))


@pytest.fixture
def registry(tmp_path):
    return registry_stage.open_registry(tmp_path / "experiments")


@pytest.fixture
def refusal():
    return registry_stage.experiment_error()


def _submission(definition, measurements):
    return {
        "schema_version": "rain-experiment-submission/v1",
        "experiment_id": definition["experiment_id"],
        "experiment_version": definition["experiment_version"],
        "evidence_class": definition["evidence_class"],
        "started_at": "2026-10-04T10:00:00.000Z",
        "finished_at": "2026-10-04T10:01:00.000Z",
        "seed": definition["seed"],
        "parameters": definition["parameters"],
        "inputs": {},
        "measurements": measurements,
        "series": {"coupling_adjusted_p": [0.005, 0.01]},
        "observations": [],
        "limitations": [],
        "artifacts": [],
        "models": [],
        "provenance": {"producer": "test", "repository": "example/repo", "commit": "abcdef1"},
    }


GOOD = {
    "records_analyzed": 20, "coupling_detection_rate": 0.9, "mismatched_detection_rate": 0.05,
    "detection_rate_gap": 0.85, "positive_control_detection_rate": 1.0, "synthetic_null_false_positive_rate": 0.05,
    "reverse_detection_rate": 0.8, "median_coupling_lag_s": 1.0, "spectral_peak_agreement_rate": 0.7,
    "median_respiratory_frequency_hz": 0.25, "median_heart_rate_bpm": 70.0,
}


def test_registration_is_write_once(registry, spec, refusal):
    assert registry_stage.find(registry, spec) is None
    first = registry_stage.register(registry, spec)
    assert first["runner"]["kind"] == "external"
    assert registry_stage.find(registry, spec)["experiment_id"] == first["experiment_id"]
    with pytest.raises(refusal, match="already registered"):
        registry_stage.register(registry, spec)

    moved_goalposts = copy.deepcopy(spec)
    moved_goalposts["preregistration"]["criteria"]["success"][0]["value"] = 0.5
    with pytest.raises(refusal, match="write-once"):
        registry_stage.find(registry, moved_goalposts)
    assert registry_stage.drift(first, moved_goalposts) == ["criteria"]
    assert "V3D-EXP-0001" in registry.results_path.read_text(encoding="utf-8")  # planned experiments are published


def test_framing_is_bound_into_the_registration_but_not_compared_with_the_spec(registry, spec, refusal):
    spec["lineage"] = {"follows": "V3D-EXP-0001/RUN-0001", "observation": "two slow breathers were missed"}
    binding = {"anna_record_sha256": "a" * 64, "panel_corpus_sha256": "b" * 64}
    definition = registry_stage.register(registry, spec, binding)
    assert definition["parameters"]["framing"] == binding
    assert definition["parameters"]["lineage"] == spec["lineage"]
    assert registry_stage.find(registry, spec)["experiment_id"] == definition["experiment_id"]
    del spec["lineage"]
    with pytest.raises(refusal, match="write-once"):
        registry_stage.find(registry, spec)


def test_preflight_runs_rains_validation_without_registering(registry, spec):
    assert registry_stage.preflight(spec) == []
    spec["preregistration"]["criteria"]["success"][0]["metric"] = "undeclared"
    assert any("criteria/success/S1" in p for p in registry_stage.preflight(spec))
    assert registry.experiment_ids() == []


def test_rain_assigns_the_status_from_measurements(registry, spec):
    definition = registry_stage.register(registry, spec)
    record = registry_stage.submit(registry, definition, _submission(definition, GOOD))
    assert (record["status"], record["hypothesis_verdict"]) == ("passed", "supported")
    assert registry_stage.definition_sha256(definition) == record["definition_sha256"]
    assert registry_stage.record_divergence(record, _submission(definition, GOOD)) == []

    confounded = {**GOOD, "mismatched_detection_rate": 0.6}  # shared rhythm alone "detects" -> guard G4
    record = registry_stage.submit(registry, definition, _submission(definition, confounded))
    assert (record["status"], record["hypothesis_verdict"]) == ("inconclusive", "insufficient_evidence")

    weak = {**GOOD, "coupling_detection_rate": 0.3}
    record = registry_stage.submit(registry, definition, _submission(definition, weak))
    assert (record["status"], record["hypothesis_verdict"]) == ("failed", "not_supported")

    unmeasured = {**GOOD, "coupling_detection_rate": None}  # a missing measurement can support nothing
    record = registry_stage.submit(registry, definition, _submission(definition, unmeasured))
    assert record["status"] == "inconclusive" and "Not evaluable" in record["evaluation"]["summary"]

    results = registry.results_path.read_text(encoding="utf-8")
    assert "Do not edit by hand" in results and definition["experiment_id"] in results
    assert registry_stage.verify(registry, definition["experiment_id"])["valid"]


def test_a_status_in_the_submission_is_refused(registry, spec, refusal):
    definition = registry_stage.register(registry, spec)
    with pytest.raises(refusal, match="status"):
        registry_stage.submit(registry, definition, {**_submission(definition, GOOD), "status": "passed"})


def test_a_crashed_run_is_recorded_as_error_not_as_failure(registry, spec):
    definition = registry_stage.register(registry, spec)
    submission = _submission(definition, {name: None for name in GOOD})
    submission["error"] = {"stage": "data", "type": "ConnectionError", "message": "physionet.org unreachable"}
    record = registry_stage.submit(registry, definition, submission)
    assert (record["status"], record["hypothesis_verdict"], record["evaluation"]) == ("error", "not_evaluated", None)


def test_only_registered_metrics_are_submitted_and_none_may_be_missing(registry, spec):
    definition = registry_stage.register(registry, spec)
    selected = registry_stage.select_measurements(definition, {**GOOD, "something_descriptive": 1.0})
    assert list(selected) == [m["name"] for m in definition["metrics"]]
    incomplete = {k: v for k, v in GOOD.items() if k != "coupling_detection_rate"}
    with pytest.raises(ValueError, match="coupling_detection_rate"):
        registry_stage.select_measurements(definition, incomplete)
    assert registry_stage.evaluated_metrics(definition) == ["records_analyzed", "coupling_detection_rate",
                                                            "mismatched_detection_rate",
                                                            "positive_control_detection_rate",
                                                            "synthetic_null_false_positive_rate"]


def test_an_uncommitted_registration_has_no_anchor(registry, spec):
    definition = registry_stage.register(registry, spec)  # tmp_path is not a git repository
    with pytest.raises(registry_stage.NotAnchored):
        registry_stage.anchor(registry, definition["experiment_id"])


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_the_anchor_is_the_first_commit_and_history_must_not_change(tmp_path, spec):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    registry = registry_stage.open_registry(tmp_path / "experiments")
    definition = registry_stage.register(registry, spec)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "register")
    first = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "notes.md").write_text("later work\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "later")
    anchor = registry_stage.anchor(registry, definition["experiment_id"])
    assert anchor["commit"] == first and anchor["pushed_to"] == []  # the first commit, not the latest

    path = registry.experiment_dir(definition["experiment_id"]) / "experiment.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"value": 0.8', '"value": 0.5'), encoding="utf-8")
    with pytest.raises(registry_stage.NotAnchored, match="not committed"):  # edited in the working tree
        registry_stage.anchor(registry, definition["experiment_id"])
    _git(tmp_path, "commit", "-q", "-am", "move the goalposts")
    with pytest.raises(registry_stage.NotAnchored, match="changed after its first commit"):
        registry_stage.anchor(registry, definition["experiment_id"])


def test_the_anchor_cutoff_counts_the_commit_second_against_the_claim():
    assert registry_stage.anchor_cutoff("2026-10-04T13:41:53-04:00") == "2026-10-04T17:41:54.000Z"
    assert registry_stage.anchor_cutoff("2026-10-04T17:41:53Z") == "2026-10-04T17:41:54.000Z"


def test_the_published_page_names_commands_that_exist_here(registry, spec):
    """Every phrase localize() replaces must still be in R.A.I.N.'s output, or a dead command would slip through."""
    _, results, *_ = registry_stage._rain()
    registry_stage.register(registry, spec)                     # planned: names the next step
    planned = results.render_results(registry)
    definition = registry.load_definition("V3D-EXP-0001")
    registry_stage.submit(registry, definition, _submission(definition, GOOD))
    measured = results.render_results(registry)                 # measured: names how to reproduce
    for pattern, _ in registry_stage._LOCAL_COMMANDS:
        assert pattern.search(planned) or pattern.search(measured), pattern.pattern
    for page in (registry_stage.localize(planned), registry_stage.localize(measured)):
        assert "rain_lab.py" not in page and "EXPERIMENTS.md" not in page and "experiment record" not in page
    assert "`python -m rain_pipeline replay V3D-EXP-0001`" in registry_stage.localize(measured)
