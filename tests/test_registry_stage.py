import copy
import json

import pytest

from rain_pipeline import registry_stage, vendor


@pytest.fixture
def spec():
    return json.loads((vendor.PROJECT_ROOT / "specs" / "cardiorespiratory.json").read_text(encoding="utf-8"))


@pytest.fixture
def registry(tmp_path):
    return registry_stage.open_registry(tmp_path / "experiments")


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


def test_preregistration_is_reused_when_identical_and_refused_when_changed(registry, spec):
    first, created = registry_stage.preregister(registry, spec)
    assert created and first["runner"]["kind"] == "external"
    again, created = registry_stage.preregister(registry, spec)
    assert not created and again["experiment_id"] == first["experiment_id"]

    moved_goalposts = copy.deepcopy(spec)
    moved_goalposts["preregistration"]["criteria"]["success"][0]["value"] = 0.5
    with pytest.raises(Exception, match="write-once"):
        registry_stage.preregister(registry, moved_goalposts)


def test_rain_assigns_the_status_from_measurements(registry, spec):
    definition, _ = registry_stage.preregister(registry, spec)
    record = registry_stage.submit(registry, definition, _submission(definition, GOOD))
    assert (record["status"], record["hypothesis_verdict"]) == ("passed", "supported")
    assert registry_stage.definition_sha256(definition) == record["definition_sha256"]

    confounded = {**GOOD, "mismatched_detection_rate": 0.6}  # shared rhythm alone "detects" -> guard G4
    record = registry_stage.submit(registry, definition, _submission(definition, confounded))
    assert record["status"] == "inconclusive"

    weak = {**GOOD, "coupling_detection_rate": 0.3}
    record = registry_stage.submit(registry, definition, _submission(definition, weak))
    assert (record["status"], record["hypothesis_verdict"]) == ("failed", "not_supported")

    results = registry.results_path.read_text(encoding="utf-8")
    assert "Do not edit by hand" in results and definition["experiment_id"] in results
    assert registry_stage.verify(registry, definition["experiment_id"])["valid"]


def test_a_crashed_run_is_recorded_as_error_not_as_failure(registry, spec):
    definition, _ = registry_stage.preregister(registry, spec)
    submission = _submission(definition, {name: None for name in GOOD})
    submission["error"] = {"stage": "data", "type": "ConnectionError", "message": "physionet.org unreachable"}
    record = registry_stage.submit(registry, definition, submission)
    assert record["status"] == "error"


def test_undeclared_measurements_are_refused(spec, registry):
    definition, _ = registry_stage.preregister(registry, spec)
    with pytest.raises(ValueError, match="undeclared"):
        registry_stage.check_measurements(definition, {**GOOD, "extra_metric": 1.0})
