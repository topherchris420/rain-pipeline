"""Replay: re-execute a recorded run from its registration and compare everything.

A replay needs nothing but the repository. The registration holds the exact
data ranges, settings and seed (its ``parameters``); the ledger holds the hash
of every byte the run read; the run record holds what it measured. ``replay``
reads the same bytes (each must hash as the ledger says), runs the registered
study, recomputes the pipeline's holdout measurements from the ledger, has
R.A.I.N.'s evaluator judge the replayed measurements, and writes a receipt
that compares every registered measurement, every series and the full study
report with the record.

A replay never writes to the registry or the ledger, and refuses to read a
byte the ledger has not seen: it cannot become a back door to a holdout.

Outcomes follow from the comparison alone (``evidence.outcome_of``), graded by
the line the protocol draws everywhere, evidence above description:

    reproduced               measurements, series and study report bit-identical; same verdict
    measurements-reproduced  registered measurements identical, same verdict; some descriptive
                             value differs (the receipt gives the largest difference)
    verdict-reproduced       same verdict, but a registered measurement differs
    verdict-differs          R.A.I.N. reaches another status on the replayed measurements
    error                    the replay could not complete (the receipt says where and why)
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import drr_stage, evidence, ledger, pipeline, provenance, registry_stage, vendor
from . import spec as specs
from .errors import HoldoutViolation, ProtocolRefusal
from .layout import Layout

Log = Callable[[str], None]
COMPLETED = ("passed", "failed", "inconclusive")


def _pick_run(registry: Any, experiment_id: str, run: str | None) -> tuple[dict[str, Any], Path]:
    records = {r["run_id"]: r for r in registry.runs(experiment_id)}
    if run:
        run_id = run if run.startswith(experiment_id) else f"{experiment_id}-{run}"
        if run_id not in records:
            raise ProtocolRefusal(f"{run_id} is not recorded")
    else:
        completed = [r for r in records.values() if r["status"] in COMPLETED]
        if not completed:
            raise ProtocolRefusal(f"{experiment_id} has no completed run to replay")
        run_id = completed[-1]["run_id"]
    record = records[run_id]
    if record["status"] not in COMPLETED:
        raise ProtocolRefusal(f"{run_id} ended as {record['status']}: it measured nothing to compare")
    path, _ = registry.resolve_run(run_id)
    return record, path / "result.json"


def _compare_values(recorded: Any, replayed: Any) -> dict[str, Any]:
    entry = {"recorded": recorded, "replayed": replayed, "identical": recorded == replayed}
    if isinstance(recorded, (int, float)) and isinstance(replayed, (int, float)):
        entry["difference"] = replayed - recorded
    return entry


def _compare_series(recorded: list[float] | None, replayed: list[float] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"recorded_n": None if recorded is None else len(recorded),
                             "replayed_n": None if replayed is None else len(replayed),
                             "identical": recorded == replayed}
    if recorded is not None and replayed is not None and len(recorded) == len(replayed) and recorded:
        entry["max_abs_difference"] = max(abs(a - b) for a, b in zip(recorded, replayed, strict=True))
    return entry


def _differences(recorded: Any, replayed: Any, path: str = "") -> tuple[list[str], float]:
    """Paths where two JSON documents differ, and the largest numeric difference among them."""
    if isinstance(recorded, dict) and isinstance(replayed, dict):
        found, largest = [], 0.0
        for key in sorted(set(recorded) | set(replayed)):
            if key not in recorded or key not in replayed:
                found.append(f"{path}/{key}")
                continue
            more, size = _differences(recorded[key], replayed[key], f"{path}/{key}")
            found, largest = found + more, max(largest, size)
        return found, largest
    if isinstance(recorded, list) and isinstance(replayed, list) and len(recorded) == len(replayed):
        found, largest = [], 0.0
        for index, (a, b) in enumerate(zip(recorded, replayed, strict=True)):
            more, size = _differences(a, b, f"{path}/{index}")
            found, largest = found + more, max(largest, size)
        return found, largest
    if recorded == replayed:
        return [], 0.0
    numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (recorded, replayed))
    return [path or "/"], abs(replayed - recorded) if numbers else float("inf")


def _recorded_report(layout: Layout, record: dict[str, Any]) -> dict[str, Any] | None:
    for artifact in record["artifacts"]:
        if artifact["kind"] == "drr-report" and artifact.get("uri"):
            report = provenance.read_json(layout.resolve(artifact["uri"]))
            if isinstance(report, dict):
                report.pop("dataset_files", None)  # names the run's own downloads; not part of the analysis
                return report
    return None


def _report_comparison(recorded: dict[str, Any], replayed: dict[str, Any]) -> dict[str, Any]:
    paths, largest = _differences(recorded, replayed)
    return {"identical": not paths, "differing_values": len(paths), "first_differences": paths[:10],
            "max_abs_difference": None if largest == float("inf") else largest,
            "recorded_sha256": provenance.canonical_sha256(recorded),
            "replayed_sha256": provenance.canonical_sha256(replayed)}


def replay(experiment_id: str, *, run: str | None = None, layout: Layout | None = None, write: bool = True,
           log: Log = print) -> dict[str, Any]:
    """Replay a recorded run (the latest completed one by default) and return its receipt."""
    layout = layout or Layout.default()
    registry = registry_stage.open_registry(layout.experiments, layout.results)
    definition = registry.load_definition(experiment_id)
    record, result_path = _pick_run(registry, experiment_id, run)
    data, analysis = definition["parameters"]["data"], definition["parameters"]["analysis"]
    found = specs.data_problems(data) + drr_stage.problems(analysis)
    if found:
        raise ProtocolRefusal(f"{experiment_id}: the registered parameters cannot be replayed:\n  " + "\n  ".join(found))

    plans = pipeline.plan_data(data, layout.cache)
    ranges = pipeline._ranges(plans)
    book = ledger.load(layout.ledger)
    unseen = ledger.bytes_unseen(book, ranges)
    if unseen:
        raise HoldoutViolation(f"{unseen:,} bytes of {experiment_id}'s data were never read by a run; "
                               "a replay only re-reads data the ledger has seen")
    log(f"Replaying {record['run_id']} ({record['status'].upper()}) from its registration")

    receipt: dict[str, Any] = {
        "schema": evidence.RECEIPT_SCHEMA,
        "replayed_at": ledger.utc_now(),
        "replayed": {"experiment_id": experiment_id, "run_id": record["run_id"],
                     "result_sha256": provenance.sha256_file(result_path),
                     "definition_sha256": record["definition_sha256"],
                     "submission_sha256": record["provenance"]["submission_sha256"]},
        "environment": provenance.environment(),
        "code": {"pipeline": provenance.code_identity(), "vendored": vendor.vendored_state()},
        "recorded_code": (record.get("inputs") or {}).get("code"),
    }
    recorded_files = {(f["url"], tuple(f["byte_range"])): f["sha256"]
                      for f in ((record.get("inputs") or {}).get("dataset") or {}).get("files") or []}
    stage = "data"
    try:
        windows, excluded, files = pipeline.read_windows(data, plans, log=log, on_read=pipeline.checker(layout.ledger))
        receipt["data"] = [{"record": f["record"], "url": f["url"], "byte_range": f["byte_range"],
                            "sha256": f["sha256"],
                            "matches_ledger": (ledger.entry_for(book, f["url"], f["byte_range"]) or {}).get(
                                "sha256", f["sha256"]) == f["sha256"],
                            "matches_run": recorded_files.get((f["url"], tuple(f["byte_range"]))) == f["sha256"]}
                           for f in files]
        stage = "analysis"
        log(f"    {drr_stage.study_name(analysis)} study on {len(windows)} windows")
        study = drr_stage.run(windows, excluded, analysis)
        stage = "comparison"
        computed = dict(study.measurements)
        if data.get("holdout"):
            anchor = ((record.get("inputs") or {}).get("registration") or {}).get("git") or {}
            computed["holdout_bytes_read_before_registration"] = ledger.bytes_read_before(
                book, ranges, definition["created_at"])
            computed["holdout_bytes_read_before_anchor"] = ledger.bytes_read_before(
                book, ranges, anchor["committed_at"]) if anchor.get("committed_at") else None
        measurements, _ = pipeline._finite(registry_stage.select_measurements(definition, computed))
        series, _ = pipeline._finite_series(study.series)
        status, verdict, _ = registry_stage.evaluate(definition, measurements)
        replayed_report = json.loads(provenance.dumps(provenance.finite(study.report)[0]))
        recorded_report = _recorded_report(layout, record)
        receipt["comparison"] = {
            "measurements": {name: _compare_values(record["measurements"].get(name), value)
                             for name, value in measurements.items()},
            "series": {name: _compare_series(record["series"].get(name), series.get(name))
                       for name in sorted(set(record["series"]) | set(series))},
            "report": None if recorded_report is None else _report_comparison(recorded_report, replayed_report),
            "status": {"recorded": record["status"], "replayed": status},
            "verdict": {"recorded": record["hypothesis_verdict"], "replayed": verdict},
            "data_identical": all(item["matches_ledger"] and item["matches_run"] for item in receipt["data"]),
            "error": None,
        }
    except Exception as exc:  # the receipt records a failed replay as plainly as a successful one
        receipt.setdefault("data", [])
        receipt["comparison"] = {"measurements": {}, "series": {}, "report": None,
                                 "status": {"recorded": record["status"], "replayed": None},
                                 "verdict": {"recorded": record["hypothesis_verdict"], "replayed": None},
                                 "data_identical": None,
                                 "error": {"stage": stage, "type": type(exc).__name__, "message": str(exc)[:2000],
                                           "traceback": traceback.format_exc()[-4000:]}}
    receipt["outcome"] = evidence.outcome_of(receipt["comparison"])
    if write:
        number = record["run_id"].rsplit("-", 1)[1]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = provenance.fresh_file(layout.replays / experiment_id, f"RUN-{number}-{stamp}", ".json")
        provenance.write_json(out, receipt)
        receipt["path"] = layout.relative(out)
    comparison = receipt["comparison"]
    same = sum(m["identical"] for m in comparison["measurements"].values())
    log(f"    {receipt['outcome'].upper()}: {same}/{len(comparison['measurements'])} measurements identical; "
        f"recorded {comparison['status']['recorded']}, replayed {comparison['status']['replayed']}"
        + (f"; error at {comparison['error']['stage']}: {comparison['error']['message']}" if comparison["error"] else ""))
    return receipt
