"""Rehearsal: the registered criteria, performed on data that cannot count.

Preregistration proves *when* criteria were written. It cannot show that the
data could have answered them. A contrast between two lag windows that never
disagree is 0 whatever the truth; a margin that a deliberately wrong window
also clears confirms nothing about the right one. Both are visible before a
holdout is spent, on an exploration of data the ledger has already seen.

``rehearse`` takes the criteria of a spec (or of a registration) and the
report of an exploration and answers four questions, without running a test or
reading a byte:

    observed     the verdict R.A.I.N.'s own evaluator gives the exploration's
                 tests, measured under the registration's settings
    resampled    how often that verdict recurs when the exploration's subjects
                 are resampled; a verdict that always recurs is settled, on
                 data like this, before the registered data is read
    contrasts    for each registered contrast, in how many windows its two arms
                 disagree; arms that never disagree make the contrast 0 by
                 construction, in every resample (a blind contrast)
    rivals       the verdict when a registered arm is replaced by an arm the
                 exploration ran and the registration did not, such as a
                 window the hypothesis says should fail; a rival that earns the
                 same verdict cannot be told apart by these criteria

Guards on the design's size (``count`` metrics) and every criterion on the
pipeline's holdout metrics are set aside: an exploration is smaller than the
experiment it rehearses, and is by definition not held out. Every other guard,
and every success and failure criterion, is applied as registered.

A rehearsal is description, never evidence: it changes no registration, run or
verdict, and it speaks only for data like the exploration's. A holdout can
still disagree, which is why it is read. ``register`` binds the rehearsal by
hash, so what the data could and could not decide is on the record before
anything is measured, and ``verify`` derives it again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import drr_stage, evidence, provenance, registry_stage
from . import spec as specs
from .errors import ProtocolRefusal
from .layout import Layout

Log = Callable[[str], None]

SCHEMA = "rain-pipeline-rehearsal/v1"
LABEL = ("REHEARSAL. Registered criteria applied by R.A.I.N.'s evaluator to an exploration of data the ledger had "
         "already seen. It describes what such data can and cannot decide; it is not evidence and decides nothing.")
RESAMPLES = 1000
SETTLED = 0.95  # a verdict that recurs in at least this share of resamples is settled on data like this
TEST_SETTINGS = ("method", "surrogate_method", "correction", "n_surrogates")  # change what a test computes
KEPT_AS_EXPLORED = ("seed", "controls")  # differences a rehearsal reports but cannot undo
SYNTHETIC = {"synthetic_positive_detection_rate": "positive", "synthetic_null_false_positive_rate": "null",
             "synthetic_long_lag_detection_rate": "long_lag"}


# --------------------------------------------------------------------------- #
# What is rehearsed
# --------------------------------------------------------------------------- #
def of_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """The criteria a spec would register, in the form ``rehearse`` reads."""
    preregistration = spec["preregistration"]
    return {"analysis": spec["analysis"], "holdout": bool(spec["data"].get("holdout")),
            "metrics": preregistration.get("metrics", []), "criteria": preregistration.get("criteria", {})}


def of_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """The criteria a registration holds, in the form ``rehearse`` reads."""
    parameters = definition["parameters"]
    return {"analysis": parameters["analysis"], "holdout": bool(parameters["data"].get("holdout")),
            "metrics": definition["metrics"], "criteria": definition["criteria"]}


def incompatibilities(analysis: dict[str, Any], explored: dict[str, Any]) -> list[str]:
    """Why an exploration's tests are not the tests this analysis would run (empty when they are)."""
    study, ran = drr_stage.study_name(analysis), drr_stage.study_name(explored)
    if study != ran:
        return [f"the exploration ran the {ran} study, the registration the {study} study"]
    found = [f"analysis.{key}: registered {analysis.get(key)!r}, explored {explored.get(key)!r}"
             for key in TEST_SETTINGS if analysis.get(key) != explored.get(key)]
    if study == "rsa_coupling":
        if analysis.get("max_lag_s") != explored.get("max_lag_s"):
            found.append(f"analysis.max_lag_s: registered {analysis.get('max_lag_s')!r}, "
                         f"explored {explored.get('max_lag_s')!r}")
        return found
    for name, arm in analysis["arms"].items():
        if name not in explored["arms"]:
            found.append(f"arm {name!r} was not explored")
        elif explored["arms"][name] != arm:
            found.append(f"arm {name!r} was explored as {explored['arms'][name]}, registered as {arm}")
    return found


def _set_aside(registration: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The criteria a rehearsal applies, and those it sets aside with the reason."""
    units = {m["name"]: m.get("unit") for m in registration["metrics"]}
    kept: dict[str, list[dict[str, Any]]] = {}
    aside = []
    for group in ("guards", "success", "failure"):
        kept[group] = []
        for criterion in registration["criteria"].get(group, []):
            if criterion["metric"] in specs.PIPELINE_METRICS:
                reason = "holdout: an exploration is not held out"
            elif group == "guards" and units.get(criterion["metric"]) == "count":
                reason = "size: an exploration is smaller than the experiment it rehearses"
            else:
                kept[group].append(criterion)
                continue
            aside.append({**{k: criterion[k] for k in ("id", "metric", "op", "value")}, "reason": reason})
    return {"criteria": kept}, aside


# --------------------------------------------------------------------------- #
# Variations on the exploration's tests (never new tests)
# --------------------------------------------------------------------------- #
def _subjects(report: dict[str, Any]) -> list[str]:
    rows = report["windows"] if "windows" in report else report["real_pairs"]
    return list(dict.fromkeys(row["record"] for row in rows))


def _resampled(report: dict[str, Any], picks: list[str]) -> dict[str, Any]:
    """The report with these subjects, each drawn copy counted as a person of its own."""
    if "windows" in report:
        mine: dict[str, list[dict[str, Any]]] = {}
        for row in report["windows"]:
            mine.setdefault(row["record"], []).append(row)
        return {**report, "windows": [{**row, "record": f"{record}#{k}"}
                                      for k, record in enumerate(picks) for row in mine[record]]}
    real = {pair["record"]: pair for pair in report["real_pairs"]}
    mismatched = {pair["respiration_of"]: pair for pair in report["mismatched_pairs"]}
    return {**report, "real_pairs": [{**real[record], "record": f"{record}#{k}"} for k, record in enumerate(picks)],
            "mismatched_pairs": [mismatched[record] for record in picks if record in mismatched]}


def _substituted(report: dict[str, Any], arm: str, rival: str) -> dict[str, Any]:
    """The report with every test of ``arm`` replaced by the same window's test under ``rival``."""
    def swap(arms: dict[str, Any]) -> dict[str, Any]:
        return {**arms, arm: arms[rival]}

    windows = [{**row, "arms": swap(row["arms"]),
                "mismatched": row["mismatched"] and {**row["mismatched"], "arms": swap(row["mismatched"]["arms"])}}
               for row in report["windows"]]
    return {**report, "windows": windows, "synthetic": swap(report["synthetic"])}


def _population(metric: str, strata: dict[str, Any]) -> tuple[str, str | None] | None:
    """Which tests a detection-rate metric counts: real or mismatched windows (of a stratum), or a synthetic kind."""
    if metric == "window_detection_rate":
        return "real", None
    if metric == "mismatched_detection_rate":
        return "mismatched", None
    if metric in SYNTHETIC:
        return "synthetic", SYNTHETIC[metric]
    for name in strata:
        if metric == f"{name}_detection_rate":
            return "real", name
        if metric == f"mismatched_{name}_detection_rate":
            return "mismatched", name
    return None  # not a detection rate (a median lag): arms cannot be compared test by test


def _contrasts(report: dict[str, Any], analysis: dict[str, Any], measured: dict[str, Any]) -> list[dict[str, Any]]:
    """Per registered contrast: the tests it compares, and in how many of them its two arms disagree."""
    if drr_stage.study_name(analysis) != "lag_window":
        return []
    alpha, strata = analysis["alpha"], analysis["strata"]
    found = []
    for name, contrast in analysis.get("contrasts", {}).items():
        entry = {"contrast": name, **contrast, "value": measured.get(name)}
        population = _population(contrast["metric"], strata)
        if population is None:
            found.append({**entry, "tests": None})
            continue
        source, which = population
        if source == "synthetic":
            pairs = list(zip(report["synthetic"][contrast["arm"]][which],
                             report["synthetic"][contrast["minus"]][which]))
        else:
            rows = [row for row in report["windows"]
                    if which is None or drr_stage.stratum_of(row["respiratory_frequency_hz"], strata) == which]
            arms = [row["arms"] if source == "real" else row["mismatched"]["arms"]
                    for row in rows if source == "real" or row["mismatched"]]
            pairs = [(tests[contrast["arm"]], tests[contrast["minus"]]) for tests in arms]
        decided = [(a["forward_adjusted_p"] <= alpha, b["forward_adjusted_p"] <= alpha) for a, b in pairs]
        found.append({**entry, "tests": len(decided), "population": " ".join(filter(None, (which, source))),
                      "arm_only": sum(a and not b for a, b in decided),
                      "minus_only": sum(b and not a for a, b in decided)})
    return found


# --------------------------------------------------------------------------- #
# The rehearsal
# --------------------------------------------------------------------------- #
def rehearse(registration: dict[str, Any], report: dict[str, Any], *, exploration: str, exploration_sha256: str,
             resamples: int = RESAMPLES) -> dict[str, Any]:
    """Apply ``registration``'s criteria to an exploration's tests. Deterministic: the same inputs, the same document."""
    analysis = registration["analysis"]
    head = {"schema": SCHEMA, "status": LABEL, "epistemic_role": "design (not evidence)",
            "exploration": {"report": exploration, "sha256": exploration_sha256}}
    problems = incompatibilities(analysis, report["settings"])
    if problems:
        doc = {**head, "rehearsed": False, "reason": "; ".join(problems)}
        return {**doc, "findings": findings(doc)}

    definition, aside = _set_aside(registration)
    registered = [m["name"] for m in registration["metrics"]]

    def judge(variant: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        computed = drr_stage.measure(variant, analysis)
        return (*registry_stage.evaluate(definition, {name: computed.get(name) for name in registered}), computed)

    status, verdict, evaluation, computed = judge(report)
    measured = {name: computed.get(name) for name in registered}
    holds = _holds(evaluation)
    subjects = _subjects(report)
    # The legacy generator: numpy guarantees its stream across versions, so verify derives the same rehearsal anywhere.
    rng = np.random.RandomState(analysis["seed"])
    tally = {"passed": 0, "failed": 0, "inconclusive": 0}
    for _ in range(resamples):
        picks = [subjects[i] for i in rng.randint(0, len(subjects), size=len(subjects))]
        tally[judge(_resampled(report, picks))[0]] += 1
    share = tally[status] / resamples if resamples else None

    rivals = []
    if drr_stage.study_name(analysis) == "lag_window":
        for rival in [name for name in report["settings"]["arms"] if name not in analysis["arms"]]:
            for arm in analysis["arms"]:
                rival_status, _, rival_evaluation, _ = judge(_substituted(report, arm, rival))
                flipped = [key for key, held in _holds(rival_evaluation).items() if held != holds[key]]
                rivals.append({"arm": arm, "rival": rival, "rival_arm": report["settings"]["arms"][rival],
                               "status": rival_status, "same_as_observed": rival_status == status,
                               "criteria_changed": flipped})

    rows = report["windows"] if "windows" in report else report["real_pairs"]
    explored = report["settings"]
    doc = {
        **head,
        "rehearsed": True,
        "exploration": {**head["exploration"], "tests": len(rows), "subjects": len(subjects)},
        "kept_as_explored": [f"analysis.{key}: registered {analysis.get(key)!r}, explored {explored.get(key)!r}"
                             for key in KEPT_AS_EXPLORED if analysis.get(key) != explored.get(key)],
        "set_aside": aside,
        "observed": {"status": status, "verdict": verdict, "evaluation": evaluation, "measurements": measured},
        "resampled": {"unit": "subject", "resamples": resamples, "seed": analysis["seed"], "statuses": tally,
                      "share_observed": share, "settled": share is not None and share >= SETTLED},
        "contrasts": _contrasts(report, analysis, computed),
        "rivals": rivals,
    }
    doc, _ = provenance.finite(doc)
    return {**doc, "findings": findings(doc)}


def _holds(evaluation: dict[str, Any]) -> dict[str, bool | None]:
    return {c["id"]: c["holds"] for group in ("guards", "success", "failure") for c in evaluation[group]}


def findings(doc: dict[str, Any]) -> list[str]:
    """What a rehearsal found, one plain sentence each."""
    if not doc["rehearsed"]:
        return [f"Not rehearsed: {doc['reason']}."]
    observed, resampled, explored = doc["observed"], doc["resampled"], doc["exploration"]
    out = [f"On {explored['tests']} windows from {explored['subjects']} people of seen data, R.A.I.N.'s evaluator "
           f"gives the registered criteria {observed['status'].upper()}. {observed['evaluation']['summary']}"]
    if resampled["resamples"]:
        out.append(f"{observed['status'].upper()} recurs in {resampled['statuses'][observed['status']]} of "
                   f"{resampled['resamples']} resamples of those people"
                   + (": on data like this, the verdict is settled before the registered data is read."
                      if resampled["settled"] else "."))
    for c in doc["contrasts"]:
        if c["tests"] is None:
            continue
        if c["tests"] and c["arm_only"] == c["minus_only"] == 0:
            out.append(f"{c['contrast']} is blind: {c['arm']} and {c['minus']} decide all {c['tests']} "
                       f"{c['population']} tests alike, so it is 0 here in every resample.")
        else:
            out.append(f"{c['contrast']}: {c['arm']} and {c['minus']} disagree on "
                       f"{c['arm_only'] + c['minus_only']} of {c['tests']} {c['population']} tests "
                       f"({c['arm_only']} {c['arm']} only, {c['minus_only']} {c['minus']} only).")
    for r in doc["rivals"]:
        out.append(f"With {r['rival']} in place of {r['arm']}, the criteria give {r['status'].upper()}"
                   + (f" as well: on this data they cannot tell {r['arm']} from {r['rival']}." if r["same_as_observed"]
                      else f", not {observed['status'].upper()}: they tell {r['arm']} from {r['rival']} by "
                           f"{', '.join(r['criteria_changed'])}."))
    if doc["set_aside"]:
        out.append("Set aside: " + "; ".join(f"{c['id']} ({c['reason'].split(':')[0]})" for c in doc["set_aside"])
                   + ".")
    out += [f"Kept as explored: {note}." for note in doc["kept_as_explored"]]
    return out


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    """The few facts a claim carries about its rehearsal."""
    if not doc.get("rehearsed"):
        return {"rehearsed": False, "exploration": doc["exploration"]["report"], "reason": doc.get("reason")}
    return {"rehearsed": True, "exploration": doc["exploration"]["report"], "observed": doc["observed"]["status"],
            "share_observed": doc["resampled"]["share_observed"], "settled": doc["resampled"]["settled"],
            "blind_contrasts": [c["contrast"] for c in doc["contrasts"]
                                if c["tests"] and c["arm_only"] == c["minus_only"] == 0],
            "indistinguishable_rivals": [f"{r['rival']} for {r['arm']}" for r in doc["rivals"]
                                         if r["same_as_observed"]]}


# --------------------------------------------------------------------------- #
# Command line and registration
# --------------------------------------------------------------------------- #
def load_exploration(layout: Layout, where: str | Path) -> tuple[Path, dict[str, Any]]:
    """An exploration report, by its directory or its report.json; refused unless it is labelled exploratory."""
    path = Path(where)
    if not path.is_absolute() and not path.exists():
        path = layout.resolve(str(where))
    if path.is_dir():
        path = path / "report.json"
    report = provenance.read_json(path) if path.is_file() else None
    if not isinstance(report, dict) or report.get("status") != evidence.EXPLORATORY:
        raise ProtocolRefusal(f"{where} is not an exploration report: a rehearsal runs only on data already seen")
    return path, report


def for_spec(spec: dict[str, Any], path: Path, report: dict[str, Any], layout: Layout,
             resamples: int = RESAMPLES) -> dict[str, Any]:
    return rehearse(of_spec(spec), report, exploration=layout.relative(path),
                    exploration_sha256=provenance.sha256_file(path), resamples=resamples)


def rehearse_spec(spec_path: Path, *, on: str | Path | None = None, layout: Layout | None = None,
                  resamples: int = RESAMPLES) -> dict[str, Any]:
    """``python -m rain_pipeline rehearse``: read-only; writes nothing and reads no data."""
    layout = layout or Layout.default()
    spec = specs.load(spec_path, "run")
    problems = registry_stage.preflight(spec)
    if problems:
        raise ProtocolRefusal(f"{spec_path}: these criteria cannot be registered, so there is nothing to rehearse:\n  "
                              + "\n  ".join(problems))
    on = on or spec.get("lineage", {}).get("exploration")
    if not on:
        raise ProtocolRefusal(f"{spec_path} names no exploration (lineage.exploration); give one with --on")
    path, report = load_exploration(layout, on)
    doc = for_spec(spec, path, report, layout, resamples)
    if not doc["rehearsed"]:
        raise ProtocolRefusal(f"{layout.relative(path)} cannot rehearse {spec_path}: {doc['reason']}")
    return doc


def render(doc: dict[str, Any], title: str = "") -> str:
    lines = [f"Rehearsal{' of ' + title if title else ''} on {doc['exploration']['report']} "
             "(seen data; description, not evidence)"]
    return "\n".join(lines + [f"  - {finding}" for finding in doc["findings"]]) + "\n"
