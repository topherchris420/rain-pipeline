"""Rehearsal: what a registration's criteria can decide on data like its exploration, before the holdout is read.

Preregistration proves the criteria came first. A rehearsal shows whether they
could have come out otherwise: contrasts whose arms never disagree, verdicts
that recur in every resample, rivals the criteria cannot tell apart. It is
description, bound by hash at registration and derived again by verify.
"""

import json
from pathlib import Path

import pytest
from conftest import ANALYSIS, base_spec, metric, quiet

from rain_pipeline import drr_stage, evidence, pipeline, provenance, rehearsal
from rain_pipeline.__main__ import EXIT_OK, EXIT_REFUSED, main
from rain_pipeline.errors import DossierMismatch
from rain_pipeline.layout import CODE_ROOT, Layout

ARMS = {"short": {"max_lag_s": 3.0}, "long": {"max_lag_s": 6.0}, "minimal": {"max_lag_s": 0.25}}
NORMAL_HZ, SLOW_HZ = 0.25, 0.12


def adjusted(p: float) -> dict:
    return {"forward_adjusted_p": p, "forward_lag_samples": 2}


def window(record: str, hz: float, real: dict, mismatched: dict | None = None) -> dict:
    return {"record": record, "respiratory_frequency_hz": hz, "arms": {k: adjusted(v) for k, v in real.items()},
            "mismatched": None if mismatched is None else {"heart_rate_of": "other",
                                                           "arms": {k: adjusted(v) for k, v in mismatched.items()}}}


def report(windows: list[dict], *, null_p: float = 0.5) -> dict:
    """An exploration report as the lag_window study writes it, built by hand: every test's adjusted p."""
    synthetic = {arm: {"positive": [adjusted(0.01)] * 4, "null": [adjusted(null_p)] * 4, "long_lag": [adjusted(0.01)] * 4}
                 for arm in ARMS}
    return {"status": evidence.EXPLORATORY, "study": "lag_window", "windows": windows, "synthetic": synthetic,
            "settings": {**ANALYSIS, "arms": ARMS, "contrasts": {}, "grid_hz": 4.0}}


def registration(*, success=(), failure=(), guards=(), arms=("short", "long"), holdout=True) -> dict:
    contrasts = {"normal_change_long_vs_short": {"metric": "normal_detection_rate", "arm": "long", "minus": "short"},
                 "mismatched_long_vs_short": {"metric": "mismatched_detection_rate", "arm": "long", "minus": "short"}}
    analysis = {**ANALYSIS, "arms": {name: ARMS[name] for name in arms}, "contrasts": contrasts}
    names = {"windows_analyzed": "count", "holdout_bytes_read_before_anchor": "bytes"}
    names.update({c["metric"]: "ratio" for c in (*success, *failure, *guards) if c["metric"] not in names})
    return {"analysis": analysis, "holdout": holdout, "metrics": [metric(n, unit) for n, unit in names.items()],
            "criteria": {"guards": list(guards), "success": list(success), "failure": list(failure)}}


def criterion(id_: str, metric_: str, op: str, value: float) -> dict:
    return {"id": id_, "metric": metric_, "op": op, "value": value}


def rehearse(registration_: dict, report_: dict, resamples: int = 200) -> dict:
    return rehearsal.rehearse(registration_, report_, exploration="explorations/x/report.json",
                              exploration_sha256="0" * 64, resamples=resamples)


# Six people, two windows each. short and long decide every real window alike (all detected but one
# person's); on mismatched pairs long fires twice where short does not. minimal copies long exactly.
AGREEING = [window(f"p{i}", NORMAL_HZ, {"short": p, "long": p, "minimal": p},
                   {"short": 0.4, "long": 0.03 if i < 2 else 0.4, "minimal": 0.03 if i < 2 else 0.4})
            for i in range(6) for p in ((0.005, 0.005) if i else (0.3, 0.3))]


# --------------------------------------------------------------------------- #
# What a rehearsal finds
# --------------------------------------------------------------------------- #
def test_a_contrast_whose_arms_never_disagree_is_blind_and_its_verdict_settled():
    gain = registration(success=[criterion("S1", "normal_change_long_vs_short", ">=", 0.1)],
                        failure=[criterion("F1", "normal_change_long_vs_short", "<=", 0)])
    doc = rehearse(gain, report(AGREEING))

    assert doc["rehearsed"] and doc["observed"]["status"] == "failed"
    assert doc["resampled"]["statuses"] == {"passed": 0, "failed": 200, "inconclusive": 0}
    assert doc["resampled"]["settled"] is True
    blind, mismatched = doc["contrasts"]
    assert (blind["contrast"], blind["tests"], blind["arm_only"], blind["minus_only"], blind["value"]) == (
        "normal_change_long_vs_short", 12, 0, 0, 0.0)
    assert (mismatched["tests"], mismatched["arm_only"], mismatched["minus_only"]) == (12, 4, 0)
    assert any("normal_change_long_vs_short is blind" in f and "every resample" in f for f in doc["findings"])
    assert rehearsal.summary(doc)["blind_contrasts"] == ["normal_change_long_vs_short"]


def test_a_rival_that_earns_the_same_verdict_cannot_be_told_apart_from_the_arm_it_replaces():
    calibrated = registration(success=[criterion("S1", "normal_detection_rate_long", ">=", 0.8),
                                       criterion("S2", "mismatched_detection_rate_long", "<=", 0.5)])
    rivals = {(r["arm"], r["status"], r["same_as_observed"]): r["criteria_changed"]
              for r in rehearse(calibrated, report(AGREEING))["rivals"]}
    assert rivals == {("short", "passed", True): [], ("long", "passed", True): []}

    strict = registration(success=[criterion("S1", "mismatched_detection_rate_long", "<=", 0.0)],
                          failure=[criterion("F1", "mismatched_detection_rate_long", ">", 0.1)])
    doc = rehearse(strict, report(AGREEING))  # long fires on mismatched pairs; minimal in short's place changes nothing
    assert doc["observed"]["status"] == "failed"
    by_arm = {r["arm"]: r for r in doc["rivals"]}
    assert by_arm["short"]["same_as_observed"] and not by_arm["short"]["criteria_changed"]
    minimal_quiet = [window(w["record"], NORMAL_HZ, {k: v["forward_adjusted_p"] for k, v in w["arms"].items()},
                            {"short": 0.4, "long": w["mismatched"]["arms"]["long"]["forward_adjusted_p"],
                             "minimal": 0.4}) for w in AGREEING]
    doc = rehearse(strict, report(minimal_quiet))
    long = {r["arm"]: r for r in doc["rivals"]}["long"]
    assert (long["status"], long["same_as_observed"], long["criteria_changed"]) == ("passed", False, ["S1", "F1"])
    assert any("they tell long from minimal by S1, F1" in f for f in doc["findings"])


def test_size_and_holdout_guards_are_set_aside_but_quality_guards_are_applied():
    guarded = registration(
        guards=[criterion("G1", "windows_analyzed", ">=", 1000), criterion("G2", "holdout_bytes_read_before_anchor",
                                                                           "<=", 0),
                criterion("G3", "synthetic_null_false_positive_rate_short", "<=", 0.15)],
        success=[criterion("S1", "normal_detection_rate_short", ">=", 0.5)])
    doc = rehearse(guarded, report(AGREEING))
    assert [(c["id"], c["reason"].split(":")[0]) for c in doc["set_aside"]] == [("G1", "size"), ("G2", "holdout")]
    assert doc["observed"]["status"] == "passed"  # 12 windows cannot meet G1, and G2 has nothing to say here

    miscalibrated = rehearse(guarded, report(AGREEING, null_p=0.01))  # the synthetic null fires: G3 still applies
    assert miscalibrated["observed"]["status"] == "inconclusive"
    assert "G3" in miscalibrated["observed"]["evaluation"]["summary"]


def test_resampling_draws_whole_people_and_is_deterministic():
    split = [window("detected", NORMAL_HZ, {"short": 0.005, "long": 0.005, "minimal": 0.005}),
             window("detected", NORMAL_HZ, {"short": 0.005, "long": 0.005, "minimal": 0.005}),
             window("missed", NORMAL_HZ, {"short": 0.5, "long": 0.5, "minimal": 0.5}),
             window("missed", NORMAL_HZ, {"short": 0.5, "long": 0.5, "minimal": 0.5})]
    half = registration(success=[criterion("S1", "normal_detection_rate_short", ">=", 0.5)])
    first, again = rehearse(half, report(split)), rehearse(half, report(split))
    assert first == again
    statuses = first["resampled"]["statuses"]
    assert statuses["passed"] and statuses["inconclusive"] and not statuses["failed"]
    assert not first["resampled"]["settled"]  # two people: the verdict turns on which one is drawn

    drawn = rehearsal._resampled(report(split), ["missed", "missed"])
    assert [w["record"] for w in drawn["windows"]] == ["missed#0", "missed#0", "missed#1", "missed#1"]
    assert drr_stage.measure(drawn, half["analysis"])["normal_subjects"] == 2  # two draws, two people


def test_only_an_exploration_of_the_same_tests_can_rehearse():
    criteria = {"success": [criterion("S1", "normal_detection_rate_short", ">=", 0.5)]}
    other_surrogates = registration(**criteria)
    other_surrogates["analysis"] = {**other_surrogates["analysis"], "n_surrogates": 999}
    assert "n_surrogates" in rehearse(other_surrogates, report(AGREEING))["reason"]

    redefined = registration(**criteria)
    redefined["analysis"] = {**redefined["analysis"], "arms": {"short": {"max_lag_s": 2.0}}}
    doc = rehearse(redefined, report(AGREEING))
    assert not doc["rehearsed"] and "arm 'short' was explored as" in doc["reason"]
    assert doc["findings"] == [f"Not rehearsed: {doc['reason']}."]

    other_study = registration(**criteria)
    other_study["analysis"] = {**base_spec()["analysis"], "study": "rsa_coupling"}
    assert "rsa_coupling" in rehearse(other_study, report(AGREEING))["reason"]

    finer_grid = {**registration(**criteria), "grid_hz": 8}  # a 3 s window is 24 samples here, 12 where explored
    doc = rehearse(finer_grid, report(AGREEING))
    assert not doc["rehearsed"] and "data.grid_hz: registered 8, explored 4.0" in doc["reason"]
    assert rehearse({**registration(**criteria), "grid_hz": 4}, report(AGREEING))["rehearsed"]


def test_an_exploration_in_which_nothing_passed_qc_cannot_rehearse():
    doc = rehearse(registration(success=[criterion("S1", "normal_detection_rate_short", ">=", 0.5)]), report([]))
    assert not doc["rehearsed"] and "no window of the exploration passed QC" in doc["reason"]
    assert doc["findings"] == [f"Not rehearsed: {doc['reason']}."]  # never "settled" on zero tests


# --------------------------------------------------------------------------- #
# This repository's records
# --------------------------------------------------------------------------- #
def test_measurements_are_recomputed_exactly_from_every_committed_study_report():
    reports = sorted(CODE_ROOT.glob("explorations/*/report.json")) + sorted(CODE_ROOT.glob("runs/*/drr_report.json"))
    assert len(reports) >= 6
    for path in reports:
        recorded = provenance.read_json(path)
        recomputed = drr_stage.measure(recorded)
        assert list(recomputed.items()) == list(recorded["measurements"].items()), path


def test_the_lag_window_experiments_were_settled_by_their_own_exploration():
    """The record behind the README: on the data their registrations bound, the arms never disagreed."""
    layout = Layout.default()
    six_s = rehearsal.rehearse_spec(CODE_ROOT / "specs" / "slow-breathers-6s-window.json", layout=layout)
    derived = rehearsal.rehearse_spec(CODE_ROOT / "specs" / "resonance-derived-window.json", layout=layout)

    assert (six_s["observed"]["status"], six_s["resampled"]["statuses"]["failed"]) == ("failed", 1000)
    assert rehearsal.summary(six_s)["blind_contrasts"] == ["slow_gain_long_vs_short", "normal_change_long_vs_short"]
    assert (derived["observed"]["status"], derived["resampled"]["statuses"]["passed"]) == ("passed", 911)
    assert rehearsal.summary(derived)["blind_contrasts"] == ["slow_resonant_vs_long", "normal_resonant_vs_short"]
    recorded = {c["experiment_id"]: c["status"] for c in evidence.verify(layout).claims}
    assert (recorded["V3D-EXP-0002"], recorded["V3D-EXP-0003"]) == ("failed", "passed")  # what the holdout then said


# --------------------------------------------------------------------------- #
# The protocol: bound at registration, carried by the run, derived again by verify
# --------------------------------------------------------------------------- #
def rehearsed_spec(ws) -> Path:
    exploration = ws.layout.relative(sorted(ws.layout.explorations.glob("*/report.json"))[0])
    prereg = {**base_spec()["preregistration"], "title": "Synthetic coupling is detected (rehearsed)"}
    return ws.spec("rehearsed", lineage={"exploration": exploration}, preregistration=prereg)


def test_register_binds_the_rehearsal_and_the_run_reports_it(completed, physionet, anna):
    spec = rehearsed_spec(completed)
    lines = []
    pipeline.register(spec, layout=completed.layout, log=lines.append)
    completed.commit("register V3D-EXP-0002")

    dossier = completed.layout.framing / "rehearsed"
    doc = provenance.read_json(dossier / "rehearsal.json")
    assert doc["schema"] == rehearsal.SCHEMA and doc["rehearsed"] and doc["epistemic_role"] == "design (not evidence)"
    definition = json.loads((completed.layout.experiments / "V3D-EXP-0002" / "experiment.json").read_text())
    assert definition["parameters"]["framing"]["rehearsal_sha256"] == provenance.sha256_file(dossier / "rehearsal.json")
    assert any(line.strip() == doc["findings"][0] for line in lines)

    pipeline.run(spec, layout=completed.layout, log=quiet)
    completed.commit("run V3D-EXP-0002")
    report = evidence.verify(completed.layout)
    assert report.ok, [c for c in report.checks if not c.ok]
    checks = {(c.name, c.subject): c for c in report.checks}
    assert checks[("framing.rehearsal", "V3D-EXP-0002")].status == evidence.OK
    claim = next(c for c in report.claims if c["experiment_id"] == "V3D-EXP-0002")
    assert claim["rehearsal"]["observed"] == doc["observed"]["status"]
    assert next(c for c in report.claims if c["experiment_id"] == "V3D-EXP-0001")["rehearsal"] is None

    run_dir = next(p.parent for p in completed.layout.runs.glob("*/REPORT.md") if "rehearsed" in p.read_text())
    report_md = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "## Rehearsal at registration (description, not evidence)" in report_md
    assert doc["findings"][0] in report_md
    graph = evidence.graph(completed.layout)
    assert any(e["relation"] == "rehearses_on" for e in graph["edges"])
    assert "rehearsed    on explorations/" in evidence.describe(report, graph)


def test_a_tampered_rehearsal_breaks_the_chain_and_stops_the_run(completed, physionet, anna):
    spec = rehearsed_spec(completed)
    pipeline.register(spec, layout=completed.layout, log=quiet)
    completed.commit("register V3D-EXP-0002")
    path = completed.layout.framing / "rehearsed" / "rehearsal.json"
    doc = provenance.read_json(path)
    doc["observed"]["status"] = "passed" if doc["observed"]["status"] != "passed" else "failed"
    provenance.write_json(path, doc)

    checks = {(c.name, c.subject): c for c in evidence.verify(completed.layout).checks}
    assert checks[("framing.rehearsal", "V3D-EXP-0002")].status == evidence.FAIL
    with pytest.raises(DossierMismatch, match="framing.rehearsal"):
        pipeline.run(spec, layout=completed.layout, log=quiet)


def test_a_rehearsal_whose_exploration_vanished_is_refused_cleanly(completed, physionet, anna):
    spec = rehearsed_spec(completed)
    pipeline.register(spec, layout=completed.layout, log=quiet)
    completed.commit("register V3D-EXP-0002")
    for path in completed.layout.explorations.glob("*/report.json"):
        path.unlink()

    checks = {(c.name, c.subject): c for c in evidence.verify(completed.layout).checks}
    assert checks[("lineage.exploration", "V3D-EXP-0002")].status == evidence.FAIL
    assert checks[("framing.rehearsal", "V3D-EXP-0002")].status == evidence.WARN
    with pytest.raises(DossierMismatch, match="lineage.exploration"):
        pipeline.run(spec, layout=completed.layout, log=quiet)


def test_rehearse_on_the_command_line(completed, capsys):
    spec = rehearsed_spec(completed)
    assert main(["--root", str(completed.root), "rehearse", str(spec), "--resamples", "50"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Rehearsal of ") and "not evidence" in out and "recurs in" in out

    bare = completed.spec("bare", preregistration={**base_spec()["preregistration"], "title": "No exploration"})
    assert main(["--root", str(completed.root), "rehearse", str(bare)]) == EXIT_REFUSED
    assert "names no exploration" in capsys.readouterr().err
    assert main(["--root", str(completed.root), "rehearse", str(bare), "--on", "specs"]) == EXIT_REFUSED
    assert "not an exploration report" in capsys.readouterr().err


def test_an_exploration_that_cannot_rehearse_is_recorded_as_such(completed, physionet, anna):
    spec = rehearsed_spec(completed)
    other = json.loads(spec.read_text(encoding="utf-8"))
    other["analysis"] = {**other["analysis"], "n_surrogates": 39}  # not the tests the exploration ran
    spec.write_text(json.dumps(other), encoding="utf-8")
    pipeline.register(spec, layout=completed.layout, log=quiet)

    doc = provenance.read_json(completed.layout.framing / "rehearsed" / "rehearsal.json")
    assert not doc["rehearsed"] and "n_surrogates" in doc["reason"]
    checks = {(c.name, c.subject): c for c in evidence.verify(completed.layout).checks}
    assert checks[("framing.rehearsal", "V3D-EXP-0002")].status == evidence.OK
