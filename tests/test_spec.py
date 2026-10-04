"""Malformed specs are refused before any work, with every problem named at once."""

import copy
import json

import pytest
from conftest import base_spec, holdout_changes

from rain_pipeline import spec as specs
from rain_pipeline import vendor
from rain_pipeline.errors import SpecError


def _with(change):
    spec = base_spec()
    change(spec)
    return spec


def _set(path, value):
    def change(spec):
        *parents, last = path.split(".")
        target = spec
        for key in parents:
            target = target[key]
        target[last] = value
    return change


MALFORMED = [
    (lambda s: s.pop("data"), "register", "'data': missing"),
    (lambda s: s.pop("preregistration"), "run", "'preregistration': missing"),
    (lambda s: s.update(lineagee={}), "explore", "'lineagee': not a spec section"),
    (_set("question", "  "), "explore", "question: must be a non-empty string"),
    (_set("data.source", "somewhere"), "explore", "data.source: one of physionet-fantasia"),
    (_set("data.records", ["syn01", "syn01"]), "explore", "listed more than once: syn01"),
    (_set("data.records", []), "explore", "data.records: a non-empty list"),
    (_set("data.start_s", 60), "explore", "either segments or start_s/duration_s"),
    (_set("data.segments", {"first_start_s": 0, "duration_s": 0, "count": 2}), "explore", "duration_s: seconds > 0"),
    (_set("data.qc", {"min_valid_rr_fraction": 1.5}), "explore", "data.qc"),
    (_set("data.highpass_hz", 3.0), "explore", "below half of grid_hz"),
    (_set("data.holdout", "yes"), "explore", "data.holdout: true or false"),
    (_set("data.holdout_shared_with", ["V3D-EXP-0001"]), "explore", "only meaningful with data.holdout"),
    (_set("data.window", 5), "explore", "data.window: not a data setting"),
    (_set("analysis.study", "telepathy"), "explore", "'telepathy' is not a study"),
    (_set("analysis.max_lag", 3), "explore", "analysis.max_lag: not a setting of this study"),
    (_set("analysis.n_surrogates", 0), "explore", "analysis.n_surrogates"),
    (_set("analysis.alpha", 1.5), "explore", "analysis.alpha"),
    (_set("analysis.seed", -1), "explore", "analysis.seed"),
    (_set("analysis.arms", {"Long": {"max_lag_s": 6.0}}), "explore", "lowercase identifiers"),
    (_set("analysis.arms", {"long": {"max_lag_s": -6.0}}), "explore", "a fixed arm is"),
    (_set("analysis.arms", {"derived": {"rule": "half_period", "min_lag_s": 5, "max_lag_s": 1}}), "explore",
     "needs 0 < min_lag_s <= max_lag_s"),
    (_set("analysis.strata", {"slow": {"min_hz": 0.3, "below_hz": 0.1}}), "explore", "min_hz must be below"),
    (_set("analysis.contrasts", {"gain": {"metric": "normal_detection_rate", "arm": "huge", "minus": "short"}}),
     "explore", "'huge' is not an arm"),
    (_set("analysis.contrasts", {"windows_analyzed": {"metric": "normal_detection_rate", "arm": "long",
                                                      "minus": "short"}}),
     "explore", "no other measurement uses"),
    (_set("analysis.controls", {"synthetic_trials": 2}), "explore", "positive_coupling: required"),
    (_set("lineage", {"follows": "V3D-EXP-0001"}), "explore", "V3D-EXP-NNNN/RUN-NNNN"),
    (_set("lineage", {"exploration": "../outside.json"}), "explore", "relative to the repository root"),
    (_set("preregistration.experiment_id", "V3D-EXP-0009"), "run", "assigned by R.A.I.N."),
    (_set("preregistration.seed", 4), "run", "parameters and seed come from"),
    (_set("literature.arxiv_queries", []), "register", "literature.arxiv_queries"),
]


@pytest.mark.parametrize("change, purpose, message", MALFORMED, ids=[m for _, _, m in MALFORMED])
def test_malformed_specs_are_refused(change, purpose, message):
    found = specs.problems(_with(change), purpose)
    assert any(message in problem for problem in found), found


def test_every_problem_is_reported_at_once(tmp_path):
    spec = base_spec()
    spec["data"]["source"] = "elsewhere"
    spec["analysis"]["alpha"] = 2
    spec["unexpected"] = True
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(SpecError) as refused:
        specs.load(path, "register")
    assert all(text in str(refused.value) for text in ("data.source", "analysis.alpha", "'unexpected'"))


def test_unreadable_specs_are_refused(tmp_path):
    with pytest.raises(SpecError, match="no such spec file"):
        specs.load(tmp_path / "absent.json")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(SpecError, match="not valid JSON"):
        specs.load(tmp_path / "bad.json")


def test_registration_problems_catch_unproducible_metrics_and_unguarded_holdouts():
    spec = base_spec()
    assert specs.registration_problems(spec) == []
    spec["preregistration"]["metrics"].append({"name": "detection_rate_short", "unit": "ratio",
                                               "description": "typo", "deterministic": True})
    assert any("'detection_rate_short' is not produced" in p for p in specs.registration_problems(spec))

    held = {**base_spec(), **holdout_changes()}
    assert specs.registration_problems(held) == []
    held["preregistration"]["criteria"]["guards"] = [g for g in held["preregistration"]["criteria"]["guards"]
                                                     if not g["metric"].startswith("holdout_")]
    assert any("a holdout needs a guard" in p for p in specs.registration_problems(held))
    lenient = copy.deepcopy(held)
    lenient["preregistration"]["criteria"]["guards"].append(
        {"id": "G9", "metric": "holdout_bytes_read_before_anchor", "op": "<=", "value": 1000})
    assert any("a holdout needs a guard" in p for p in specs.registration_problems(lenient))  # 1000 bytes is not zero
    strict = copy.deepcopy(held)
    strict["preregistration"]["criteria"]["guards"].append(
        {"id": "G9", "metric": "holdout_bytes_read_before_anchor", "op": "<", "value": 1})
    assert specs.registration_problems(strict) == []


def test_the_committed_specs_are_valid_for_what_they_were_used_for():
    for path in sorted((vendor.PROJECT_ROOT / "specs").glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        purposes = ["explore", "register", "run"] if "preregistration" in spec else ["explore"]
        for purpose in purposes:
            assert specs.problems(spec, purpose) == [], (path.name, purpose)
        if "preregistration" in spec:
            assert specs.registration_problems(spec) == [], path.name


def test_segments_of_both_layouts():
    assert specs.segments_of({"start_s": 60, "duration_s": 600}) == (60, 600, 1)
    assert specs.segments_of({"segments": {"first_start_s": 660, "duration_s": 600, "count": 10}}) == (660, 600, 10)
