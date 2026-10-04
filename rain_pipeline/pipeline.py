"""Explore -> register -> run -> verify: the protocol that keeps the evidence honest.

explore    Try an analysis on data the ledger has already seen. Never evidence.
register   Anna retrieves and cites the literature, the R.A.I.N. panel argues
           over it, and the experiment is registered write-once. The
           registration binds the literature record, the panel corpus, the
           parent result, the exploration and the holdout proof by hash.
           -> commit and push: that commit is the registration's timestamp.
run        Refuses an uncommitted registration, a framing dossier that no
           longer matches it, and (for a holdout) uncommitted or unpinned code.
           Reads the pre-registered data (logging every byte range in the
           ledger), runs the DRR study, and submits measurements with no
           status. R.A.I.N. alone evaluates the pre-registered criteria.
verify     Re-derives every stored result and re-checks every link of the
           evidence chain (see ``evidence``).

Refusals happen before anything is read and leave no record. Once a run has
started, every outcome is recorded: a crash anywhere after registration (in
the data, the analysis, the artifacts, even a submission R.A.I.N. rejects, or
an interrupt) is filed by R.A.I.N. as an ``error`` run, which is distinct from
a failed hypothesis and cannot be mistaken for one.
"""

from __future__ import annotations

import json
import math
import shutil
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import (__version__, anna_stage, drr_stage, evidence, figures, ledger, panel_stage, physio, provenance,
               registry_stage, vendor)
from . import spec as specs
from .errors import HoldoutViolation, NotRegistered, ProtocolRefusal, SpecError, UnpinnedCode
from .evidence import EXPLORATORY
from .layout import Layout
from .layout import resolve as resolve_layout

Log = Callable[[str], None]
segments_of = specs.segments_of

__all__ = ["HoldoutViolation", "explore", "register", "run", "verify", "plan_data", "read_windows", "load_spec"]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_spec(path: Path, sections: tuple[str, ...] = ("question", "literature", "data", "analysis",
                                                       "preregistration")) -> dict[str, Any]:
    """0.2 API: read a spec and require ``sections``. New code uses ``spec.load(path, purpose)``."""
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    for section in sections:
        if section not in loaded:
            raise SpecError(f"{path}: missing '{section}'")
    return loaded


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def plan_data(data: dict[str, Any], cache_dir: Path) -> list[physio.SegmentPlan]:
    """One contiguous byte range per record. Reads headers only."""
    if data["source"] != "physionet-fantasia":
        raise SpecError(f"unsupported data source {data['source']!r}")
    start, duration, count = segments_of(data)
    return [physio.plan_segment(record, start, duration * count, cache_dir) for record in data["records"]]


def _ranges(plans: list[physio.SegmentPlan]) -> list[ledger.Range]:
    return [(plan.url, plan.byte_range) for plan in plans]


def recorder(ledger_path: Path, read_by: str) -> Callable[[dict[str, Any]], None]:
    """What a registered run does with each read: log it in the ledger (first reads only)."""
    def on_read(provenance_: dict[str, Any]) -> None:
        ledger.record(ledger_path, url=provenance_["url"], byte_range=provenance_["byte_range"],
                      sha256=provenance_["sha256"], read_at=ledger.utc_now(), read_by=read_by)
    return on_read


def checker(ledger_path: Path) -> Callable[[dict[str, Any]], None]:
    """What an exploration or a replay does with each read: prove it was seen before, never log it."""
    book = ledger.load(ledger_path)

    def on_read(provenance_: dict[str, Any]) -> None:
        ledger.require_seen(book, url=provenance_["url"], byte_range=provenance_["byte_range"],
                            sha256=provenance_["sha256"])
    return on_read


def read_windows(data: dict[str, Any], plans: list[physio.SegmentPlan], ledger_path: Path | None = None,
                 read_by: str | None = None, log: Log = print, *, on_read: Callable[[dict[str, Any]], None] | None = None
                 ) -> tuple[list[physio.PairedSeries], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read every planned range and cut it into QC-passed windows.

    ``on_read`` sees each read's provenance before its bytes are used (the 0.2
    form, ``ledger_path`` and ``read_by``, logs each read in that ledger).
    """
    if on_read is None:
        if ledger_path is None or read_by is None:
            raise TypeError("read_windows needs on_read, or ledger_path and read_by")
        on_read = recorder(ledger_path, read_by)
    start, duration, count = segments_of(data)
    threshold = data["qc"]["min_valid_rr_fraction"]
    windows, excluded, files = [], [], []
    for plan in plans:
        span, provenance_ = physio.read_segment(plan)
        on_read(provenance_)
        files.append(provenance_)
        kept = 0
        for k, chunk in enumerate(physio.split_windows(span, count)):
            where = {"record": plan.record, "segment": k, "start_s": start + k * duration}
            try:
                pair = physio.paired_series(plan.header, chunk, grid_fs=data["grid_hz"], highpass_hz=data["highpass_hz"])
            except physio.QualityError as exc:
                excluded.append({**where, "reason": str(exc)})
                continue
            if pair.qc["valid_rr_fraction"] < threshold:
                excluded.append({**where, "reason": f"valid RR fraction {pair.qc['valid_rr_fraction']:.3f} < {threshold}",
                                 "qc": pair.qc})
                continue
            windows.append(replace(pair, segment=k, start_s=where["start_s"]))
            kept += 1
        log(f"    {plan.record}: {kept}/{count} windows pass QC" + ("  (downloaded)" if provenance_["downloaded"] else ""))
    return windows, excluded, files


def _show(value: Any) -> Any:
    return value if value is None or isinstance(value, int) else round(value, 4)


# --------------------------------------------------------------------------- #
# explore
# --------------------------------------------------------------------------- #
def explore(spec_path: Path, *, layout: Layout | None = None, log: Log = print,
            explorations_root: Path | None = None, data_root: Path | None = None) -> dict[str, Any]:
    """An analysis on data the ledger has already seen. Its report is labelled: never evidence."""
    layout = resolve_layout(layout, {"explorations_root": explorations_root, "data_root": data_root})
    spec = specs.load(spec_path, "explore")
    if spec["data"].get("holdout"):
        raise SpecError(f"{spec_path}: an exploration cannot declare a holdout; exploring is for seen data only")
    plans = plan_data(spec["data"], layout.cache)
    book = ledger.load(layout.ledger)
    unseen = ledger.bytes_unseen(book, _ranges(plans))
    if unseen:
        raise HoldoutViolation(
            f"explore only reads data the ledger has already seen, and {unseen:,} bytes of this spec are unseen. "
            "Unseen data is for registered experiments."
        )
    out_dir = provenance.fresh_dir(layout.explorations, f"{_stamp()}-{Path(spec_path).stem}")
    log(f"Exploration: {layout.relative(out_dir)}  (seen data only; not evidence)")
    windows, excluded, files = read_windows(spec["data"], plans, log=log, on_read=checker(layout.ledger))
    study = drr_stage.run(windows, excluded, spec["analysis"])
    report, _ = provenance.finite({
        "status": EXPLORATORY, "epistemic_role": "observation",
        "spec": layout.relative(Path(spec_path)), "question": spec["question"],
        "code": {"pipeline": provenance.code_identity(), "vendored": vendor.vendored_state()},
        "ledger_sha256": ledger.sha256_file(layout.ledger),
        "dataset_files": files, **study.report})
    provenance.write_json(out_dir / "report.json", report)
    try:
        figures.render(study.report, out_dir / "figure.png", note="Exploratory: seen data, not evidence")
    except Exception as exc:  # a figure is presentation; the report above is the record
        log(f"    figure not rendered ({type(exc).__name__}: {exc})")
    for name, value in study.measurements.items():
        log(f"    {name} = {_show(value)}")
    return {"dir": out_dir, "measurements": study.measurements}


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #
def register(spec_path: Path, *, offline: bool = False, layout: Layout | None = None, log: Log = print,
             registry_root: Path | None = None, framing_root: Path | None = None,
             data_root: Path | None = None) -> dict[str, Any]:
    layout = resolve_layout(layout, {"registry_root": registry_root, "framing_root": framing_root,
                                     "data_root": data_root})
    spec_path = Path(spec_path)
    spec = specs.load(spec_path, "register")
    registry = registry_stage.open_registry(layout.experiments, layout.results)
    existing = registry_stage.find(registry, spec)
    if existing is not None:
        log(f"{existing['experiment_id']} is already registered (created {existing['created_at']}). Nothing to do.")
        return {"experiment_id": existing["experiment_id"], "created": False}

    # Cheap refusals first: nothing below may cost a literature search, let alone a byte of data.
    problems = registry_stage.preflight(spec) + specs.registration_problems(spec)
    if problems:
        raise SpecError(f"{spec_path} cannot be registered:\n  " + "\n  ".join(problems))
    try:
        drr_stage.dry_run(spec["analysis"])
    except Exception as exc:
        raise SpecError(f"{spec_path}: the analysis does not run ({type(exc).__name__}: {exc})") from exc
    framing_dir = layout.framing / spec_path.stem
    held = (provenance.read_json(framing_dir / "framing.json") or {}).get("experiment_id")
    if held:
        raise ProtocolRefusal(
            f"{layout.relative(framing_dir)} already holds the framing of {held}, which stays on the record. "
            "A new experiment needs a spec file of its own: copy the spec to a new name, then register that."
        )

    log(f"Question: {spec['question']}")
    binding: dict[str, Any] = {}
    lineage = spec.get("lineage", {})
    if "follows" in lineage:
        experiment_id, run_id = lineage["follows"].split("/")
        parent = registry.root / experiment_id / "runs" / run_id / "result.json"
        if not parent.is_file():
            raise SpecError(f"lineage.follows: {lineage['follows']} is not a recorded run")
        binding["parent_result_sha256"] = provenance.sha256_file(parent)
    if "exploration" in lineage:
        report = layout.resolve(lineage["exploration"])
        if not report.is_file() or (provenance.read_json(report) or {}).get("status") != EXPLORATORY:
            raise SpecError(f"lineage.exploration: {lineage['exploration']} is not an exploration report")
        binding["exploration_report_sha256"] = provenance.sha256_file(report)
    holdout_ranges: list[ledger.Range] = []
    if spec["data"].get("holdout"):
        holdout_ranges = _ranges(plan_data(spec["data"], layout.cache))
        total = sum(b - a + 1 for _, (a, b) in holdout_ranges)
        seen = total - ledger.bytes_unseen(ledger.load(layout.ledger), holdout_ranges)
        if seen:
            raise HoldoutViolation(f"{seen:,} bytes of the declared holdout have already been read. "
                                   "This data cannot confirm anything; choose data the ledger has never seen.")
        _require_acknowledged_siblings(layout, spec, holdout_ranges)
        binding["holdout"] = {"byte_ranges": len(holdout_ranges), "bytes": total,
                              "ledger_sha256": ledger.sha256_file(layout.ledger)}

    if framing_dir.exists():  # no framing.json: a dossier left over from a registration that never completed
        shutil.rmtree(framing_dir)
    framing_dir.mkdir(parents=True)
    files = []

    log("\n[1/3] Anna: literature retrieval")
    anna = anna_stage.run(spec, pgdata=layout.root / ".pgdata", offline=offline)
    for item in anna.ingestion:
        if "query" in item:
            log(f"    ingest {item['query']}: indexed={item.get('indexed', 0)}"
                + (f"  ({item['error']})" if item.get("error") else ""))
    files.append(provenance.write_json(framing_dir / "anna_record.json", anna.packet))
    files.append(provenance.write_json(framing_dir / "anna_verification.json", anna.verification))
    citations = (anna.packet["record"]["summary"] or {}).get("citations", [])
    log(f"    {len(anna.documents)} sources, {len(citations)} cited; record sha256 {anna.fingerprint[:16]}...")
    log(f"    excerpt verification: {'OK' if anna.verification['ok'] else 'FAILED'} {anna.verification['counts']}")
    if not anna.verification["ok"]:
        raise RuntimeError("Anna could not re-verify its own citations; refusing to build on them")

    log("\n[2/3] R.A.I.N. research panel (offline, over Anna's sources)")
    panel = panel_stage.run(spec["question"], anna.documents, framing_dir / "corpus", relative_to=layout.root)
    files.append(provenance.write_text(framing_dir / "panel_meeting.md", panel.markdown))
    files.append(provenance.write_json(framing_dir / "panel_summary.json", panel.summary))
    audit = panel.summary["citation_audit"]
    log(f"    grounding: {panel.summary['grounding']}; quotes verified {audit['verified']}/{audit['checked']}")
    log(f"    agreed:    {panel.summary['verdict']['agreed']}")
    log(f"    contested: {panel.summary['verdict']['contested']}")

    log("\n[3/3] R.A.I.N. registration (write-once)")
    binding = {"anna_record_sha256": anna.fingerprint, "panel_corpus_sha256": audit["corpus_sha256"], **binding}
    definition = registry_stage.register(registry, spec, binding)
    experiment_id = definition["experiment_id"]
    provenance.write_json(framing_dir / "framing.json", {
        "schema": "rain-pipeline-framing/v1",
        "experiment_id": experiment_id,
        "spec": layout.relative(spec_path),
        "registered_at": definition["created_at"],
        "definition_sha256": registry_stage.definition_sha256(definition),
        "binding": binding,
        "holdout_ranges": [[url, list(byte_range)] for url, byte_range in holdout_ranges],
        "files": files,
    })
    log(f"    {experiment_id} v{definition['experiment_version']} registered at {definition['created_at']}")
    _log_criteria(definition, log)
    if "holdout" in binding:
        log(f"    holdout: {binding['holdout']['bytes']:,} bytes in {binding['holdout']['byte_ranges']} ranges, "
            "none ever read")
    log("\nNext: commit and push experiments/, framing/, data/ledger.json and RESULTS.md, then `run`. "
        "The commit is the proof that these criteria came before the data.")
    return {"experiment_id": experiment_id, "created": True}


def _require_acknowledged_siblings(layout: Layout, spec: dict[str, Any], ranges: list[ledger.Range]) -> None:
    """Two experiments judged on the same held-out bytes form a family; the second must say so in its data section.

    The acknowledgement becomes part of the registration, so the multiplicity
    is on the record before anything is measured instead of being discovered later.
    """
    acknowledged = set(spec["data"].get("holdout_shared_with", []))
    unacknowledged = []
    for manifest_path in sorted(layout.framing.glob("*/framing.json")):
        manifest = provenance.read_json(manifest_path) or {}
        theirs = [(url, tuple(span)) for url, span in manifest.get("holdout_ranges", [])]
        if theirs and ledger.overlap(ranges, theirs) and manifest.get("experiment_id") not in acknowledged:
            unacknowledged.append(manifest["experiment_id"])
    if unacknowledged:
        raise SpecError(
            f"the holdout overlaps the holdout already reserved by {', '.join(unacknowledged)}. Experiments judged "
            "on the same data form a family with no correction across it; acknowledge it with "
            f"data.holdout_shared_with: {json.dumps(sorted(acknowledged | set(unacknowledged)))} "
            "(and say so in the limitations), or choose other data."
        )


def _log_criteria(definition: dict[str, Any], log: Log) -> None:
    for group in ("guards", "success", "failure"):
        for c in definition["criteria"][group]:
            log(f"      {c['id']}: {c['metric']} {c['op']} {c['value']}")


def load_framing(framing_dir: Path, definition: dict[str, Any], *, layout: Layout | None = None
                 ) -> tuple[dict, dict, dict]:
    """The dossier this experiment was framed with, checked against everything the registration bound."""
    layout = layout or Layout.default()
    registry = registry_stage.open_registry(layout.experiments, layout.results)
    return evidence.load_dossier(layout, registry, framing_dir, definition)


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
@dataclass
class _Measured:
    """Everything a run produced before submission, whatever stage it reached."""

    measurements: dict[str, Any]
    series: dict[str, list[float]] = field(default_factory=dict)
    report: dict[str, Any] | None = None
    windows: list[physio.PairedSeries] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    holdout: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None
    interrupted: BaseException | None = None


def run(spec_path: Path, *, layout: Layout | None = None, allow_uncommitted: bool = False, log: Log = print,
        registry_root: Path | None = None, runs_root: Path | None = None, framing_root: Path | None = None,
        data_root: Path | None = None) -> dict[str, Any]:
    layout = resolve_layout(layout, {"registry_root": registry_root, "runs_root": runs_root,
                                     "framing_root": framing_root, "data_root": data_root})
    spec_path = Path(spec_path)
    spec = specs.load(spec_path, "run")
    registry = registry_stage.open_registry(layout.experiments, layout.results)
    definition = registry_stage.find(registry, spec)
    if definition is None:
        raise NotRegistered(f"{spec_path.name} is not registered. Run `register` first, then commit and push.")
    experiment_id = definition["experiment_id"]
    holdout = bool(spec["data"].get("holdout"))
    if holdout and allow_uncommitted:
        raise HoldoutViolation(
            f"{experiment_id} declares a holdout, which can be read only once, by a run whose registration is "
            "anchored in git. --allow-uncommitted would spend it without that proof: commit and push, then run.")
    dossier = evidence.dossier_dir(layout, experiment_id)
    manifest, packet, panel = evidence.load_dossier(layout, registry, dossier, definition)
    anchor = None if allow_uncommitted else registry_stage.anchor(registry, experiment_id)
    code, vendored = provenance.code_identity(), vendor.vendored_state()
    if holdout:
        unpinned = vendor.unpinned(vendored)
        if code["git"]["dirty"] is not False:
            unpinned.insert(0, "rain_pipeline: uncommitted changes, or not a git checkout")
        if unpinned:
            raise UnpinnedCode(f"{experiment_id} declares a holdout, so it must run committed, pinned code "
                               "(the exact code then stays in history):\n  " + "\n  ".join(unpinned))
    try:
        drr_stage.dry_run(spec["analysis"])
    except Exception as exc:
        raise ProtocolRefusal(f"the registered analysis does not run here ({type(exc).__name__}: {exc}); "
                              "nothing was read") from exc
    if holdout:
        _wait_for_anchor(anchor)

    run_dir = provenance.fresh_dir(layout.runs, _stamp())
    log(f"Run directory: {layout.relative(run_dir)}")
    log(f"{experiment_id}: {definition['title']}")
    log(f"    registered {definition['created_at']}; "
        + (f"anchored in commit {anchor['commit'][:7]} ({', '.join(anchor['pushed_to']) or 'not pushed'})" if anchor
           else "NOT anchored in git (--allow-uncommitted)"))
    _log_criteria(definition, log)

    started_at = ledger.utc_now()
    measured = _measure(spec, definition, anchor, layout, run_dir, log)
    finished_at = ledger.utc_now()
    if measured.report is None and measured.error is None:
        raise AssertionError("a run must end with a report or an error")
    kinds = {"anna_record.json": "anna-research-record/v1", "anna_verification.json": "anna-verification",
             "panel_meeting.md": "rain-offline-meeting", "panel_summary.json": "rain-panel-summary"}
    for ref in manifest["files"]:
        measured.artifacts.append({**{k: ref[k] for k in ("name", "sha256", "bytes")},
                                   "kind": kinds.get(ref["name"], "framing"),
                                   "uri": f"{layout.relative(dossier)}/{ref['name']}"})

    log("\n[3/3] R.A.I.N. evaluation")
    try:
        submission = _submission(definition, spec, measured, packet, panel, anchor, code, vendored, started_at,
                                 finished_at)
    except Exception as exc:  # assembling the record must never lose a run that has read data
        provenance.write_text(run_dir / "error.txt", traceback.format_exc())
        submission = _fallback_submission(definition, measured, started_at, finished_at, _error("submission", exc))
    record = _submit(registry, definition, submission, run_dir, log)
    verification = registry_stage.verify(registry, experiment_id)
    summary = {
        "run_dir": layout.relative(run_dir),
        "experiment_id": experiment_id,
        "run_id": record["run_id"],
        "status": record["status"],
        "verdict": record["hypothesis_verdict"],
        "evaluation": record["evaluation"],
        "measurements": record["measurements"],
        "rain_verify": verification,
        "anna_record_sha256": packet["content_sha256"],
    }
    provenance.write_json(run_dir / "summary.json", summary)
    provenance.write_text(run_dir / "REPORT.md", _report(spec, definition, record, packet, panel, measured,
                                                         verification, anchor, layout.relative(dossier),
                                                         has_figure=(run_dir / "figure.png").exists()))
    log(f"    {record['run_id']}: {record['status'].upper()} ({record['hypothesis_verdict'].replace('_', ' ')})")
    if record["evaluation"]:
        log(f"    {record['evaluation']['summary']}")
    log(f"    R.A.I.N. verify: {_verify_line(verification)}")
    log(f"\nReport: {layout.relative(run_dir / 'REPORT.md')}   Results: {layout.relative(layout.results)}")
    if measured.interrupted is not None:
        raise measured.interrupted
    return summary


def _wait_for_anchor(anchor: dict[str, Any]) -> None:
    """Read nothing until it is provably later than the anchor commit (whole seconds; see ``anchor_cutoff``)."""
    wait = (ledger.parse_time(registry_stage.anchor_cutoff(anchor["committed_at"]))
            - datetime.now(timezone.utc)).total_seconds()
    if wait > 2:
        raise ProtocolRefusal(f"the anchor commit is dated {anchor['committed_at']}, ahead of this machine's clock; "
                              "reads could not be ordered after it. Fix the clock, then run.")
    if wait > 0:
        time.sleep(wait)


def _measure(spec: dict[str, Any], definition: dict[str, Any], anchor: dict[str, Any] | None, layout: Layout,
             run_dir: Path, log: Log) -> _Measured:
    """Data -> analysis -> registered measurements -> artifacts. Any failure becomes the run's error."""
    experiment_id = definition["experiment_id"]
    measured = _Measured(measurements={m["name"]: None for m in definition["metrics"]},
                         holdout={"declared": bool(spec["data"].get("holdout"))})
    stage = "data"
    try:
        log("\n[1/3] Data: PhysioNet Fantasia")
        plans = plan_data(spec["data"], layout.cache)
        if measured.holdout["declared"]:
            ranges, book = _ranges(plans), ledger.load(layout.ledger)
            measured.holdout.update(
                byte_ranges=len(ranges), bytes=sum(b - a + 1 for _, (a, b) in ranges),
                bytes_read_before_registration=ledger.bytes_read_before(book, ranges, definition["created_at"]),
                bytes_read_before_anchor=ledger.bytes_read_before(
                    book, ranges, registry_stage.anchor_cutoff(anchor["committed_at"])) if anchor else None)
            log(f"    holdout: {measured.holdout['bytes_read_before_registration']:,} bytes read before registration"
                + (f", {measured.holdout['bytes_read_before_anchor']:,} before the anchor commit"
                   if anchor else ""))
        measured.windows, measured.excluded, measured.files = read_windows(
            spec["data"], plans, log=log, on_read=recorder(layout.ledger, experiment_id))
        if not measured.windows:
            raise RuntimeError("no window passed QC")

        stage = "analysis"
        log(f"\n[2/3] DRR: {drr_stage.study_name(spec['analysis'])} study on {len(measured.windows)} windows")
        study = drr_stage.run(measured.windows, measured.excluded, spec["analysis"])

        stage = "measurements"
        computed = dict(study.measurements)
        if measured.holdout["declared"]:
            computed["holdout_bytes_read_before_registration"] = measured.holdout["bytes_read_before_registration"]
            computed["holdout_bytes_read_before_anchor"] = measured.holdout["bytes_read_before_anchor"]
        measurements, unusable = _finite(registry_stage.select_measurements(definition, computed))
        series, dropped = _finite_series(study.series)
        if unusable:
            measured.notes.append("Not a finite number, so submitted as not measured (criteria on them cannot "
                                  f"hold): {', '.join(unusable)}.")
        if dropped:
            measured.notes.append(f"Series with non-finite values, left out of the submission: {', '.join(dropped)}.")
        for name, value in measurements.items():
            log(f"    {name} = {_show(value)}")

        stage = "artifacts"
        report, undefined = provenance.finite({"dataset_files": measured.files, **study.report})
        if undefined:
            measured.notes.append(f"drr_report.json holds {undefined} undefined (non-finite) value(s), written as null.")
        measured.artifacts.append({**provenance.write_json(run_dir / "drr_report.json", report), "kind": "drr-report",
                                   "uri": f"{layout.relative(run_dir)}/drr_report.json"})
        try:
            figure = figures.render(study.report, run_dir / "figure.png",
                                    note=f"{experiment_id}, held-out data" if measured.holdout["declared"]
                                    else experiment_id)
        except Exception as exc:  # a figure is presentation, never evidence: its failure must not void the run
            (run_dir / "figure.png").unlink(missing_ok=True)
            figure = None
            measured.notes.append(f"The figure could not be rendered ({type(exc).__name__}: {exc}).")
        if figure:
            measured.artifacts.append({**figure, "kind": "figure", "uri": f"{layout.relative(run_dir)}/figure.png"})
        measured.measurements, measured.series, measured.report = measurements, series, study.report
    except KeyboardInterrupt as exc:  # an interrupted run read data too: it is recorded, then the interrupt resumes
        measured.error, measured.interrupted = _error(stage, exc, "interrupted"), exc
    except Exception as exc:  # recorded as an R.A.I.N. 'error' run, never swallowed
        measured.error = _error(stage, exc)
        provenance.write_text(run_dir / "error.txt", traceback.format_exc())
    if measured.error is not None:
        measured.measurements = {m["name"]: None for m in definition["metrics"]}
        measured.series = {}
        log(f"    ERROR at {measured.error['stage']}: {measured.error['type']}: {measured.error['message']}")
    return measured


def _error(stage: str, exc: BaseException, message: str | None = None) -> dict[str, str]:
    return {"stage": stage, "type": type(exc).__name__, "message": (message or str(exc) or type(exc).__name__)[:2000]}


def _finite(measurements: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A value R.A.I.N. can evaluate, or None (not measured). Never a NaN in disguise."""
    clean, unusable = {}, []
    for name, value in measurements.items():
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if value is None or (number and math.isfinite(value)):
            clean[name] = value
        else:
            clean[name] = None
            unusable.append(name)
    return clean, unusable


def _finite_series(series: dict[str, list[Any]]) -> tuple[dict[str, list[float]], list[str]]:
    clean, dropped = {}, []
    for name, values in series.items():
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
            clean[name] = values
        else:
            dropped.append(name)
    return clean, dropped


def _submission(definition: dict[str, Any], spec: dict[str, Any], measured: _Measured, packet: dict[str, Any],
                panel: dict[str, Any], anchor: dict[str, Any] | None, code: dict[str, Any],
                vendored: dict[str, Any], started_at: str, finished_at: str) -> dict[str, Any]:
    drr_git = vendored["drr"]
    environment = provenance.environment()
    submission = {
        "schema_version": "rain-experiment-submission/v1",
        "experiment_id": definition["experiment_id"],
        "experiment_version": definition["experiment_version"],
        "evidence_class": definition["evidence_class"],
        "started_at": started_at,
        "finished_at": finished_at,
        "seed": definition["seed"],
        "parameters": definition["parameters"],
        "inputs": {
            "registration": {"definition_sha256": registry_stage.definition_sha256(definition),
                             "created_at": definition["created_at"], "git": anchor},
            "holdout": measured.holdout,
            "literature": {
                "engine": "Anna (in-process, embedded PostgreSQL)",
                "record_sha256": packet["content_sha256"],
                "search": packet["record"]["request"]["q"],
                "retrieval": packet["record"]["retrieval"],
                "sources": [{k: hit["document"][k] for k in ("id", "title", "url")} for hit in packet["record"]["hits"]],
            },
            "panel": {k: panel[k] for k in ("engine", "grounding", "citation_audit", "verdict")},
            "dataset": {"name": "PhysioNet Fantasia Database 1.0.0", "license": "ODC-By-1.0",
                        "files": measured.files, "windows_analyzed": len(measured.windows),
                        "excluded_windows": measured.excluded},
            "code": {"pipeline": code, "vendored": vendored},
            "evidence": {
                "evaluated_metrics": registry_stage.evaluated_metrics(definition),
                "described_metrics": [m["name"] for m in definition["metrics"]
                                      if m["name"] not in registry_stage.evaluated_metrics(definition)],
                "unregistered_outputs": [name for name in drr_stage.outputs(spec["analysis"])
                                         if name not in {m["name"] for m in definition["metrics"]}],
            },
        },
        "measurements": measured.measurements,
        "series": measured.series,
        "observations": _observations(packet, panel, measured, anchor, code),
        "limitations": [],
        "artifacts": [{k: a[k] for k in ("name", "sha256", "bytes", "kind", "uri")} for a in measured.artifacts],
        "models": [],
        "provenance": {
            "producer": f"rain-pipeline {__version__}",
            "repository": drr_git["repository"],
            "commit": drr_git["commit"],
            "branch": drr_git["branch"],
            "dirty": drr_git["dirty"],
            "environment": {"python": environment["python"], "platform": environment["platform"],
                            **environment["packages"]},
        },
    }
    if measured.error:
        submission["error"] = measured.error
    return submission


def _fallback_submission(definition: dict[str, Any], measured: _Measured, started_at: str, finished_at: str,
                         error: dict[str, str]) -> dict[str, Any]:
    """The least a run can file: what it read, and why it could not report more. R.A.I.N. records it as an error."""
    return {
        "schema_version": "rain-experiment-submission/v1", "experiment_id": definition["experiment_id"],
        "experiment_version": definition["experiment_version"], "evidence_class": definition["evidence_class"],
        "started_at": started_at, "finished_at": finished_at, "seed": definition["seed"],
        "parameters": definition["parameters"],
        "inputs": {"holdout": measured.holdout, "dataset": {"files": measured.files}},
        "measurements": {m["name"]: None for m in definition["metrics"]}, "series": {},
        "observations": [], "limitations": [], "artifacts": [], "models": [],
        "provenance": {"producer": f"rain-pipeline {__version__}", "repository": vendor.REPOSITORIES["drr"][0],
                       "commit": "0000000"},
        "error": error,
    }


def _submit(registry: Any, definition: dict[str, Any], submission: dict[str, Any], run_dir: Path, log: Log
            ) -> dict[str, Any]:
    """Hand the submission to R.A.I.N. If R.A.I.N. refuses it, record the attempt as an error run instead.

    Data was read either way, so a rejected submission must not leave the run
    without a record; the rejected document is kept beside the accepted one.
    """
    problems = registry_stage.submission_errors(submission)
    if problems:
        provenance.write_json(run_dir / "submission.rejected.json", submission)
        log(f"    R.A.I.N. rejects the submission ({len(problems)} problem(s)); recording an error run instead")
        submission = {**submission, "measurements": {m["name"]: None for m in definition["metrics"]}, "series": {},
                      "error": {"stage": "submission", "type": "InvalidSubmission",
                                "message": "; ".join(problems)[:2000]}}
    provenance.write_json(run_dir / "submission.json", submission)
    return registry_stage.submit(registry, definition, submission)


def _observations(packet: dict, panel: dict, measured: _Measured, anchor: dict | None, code: dict) -> list[str]:
    retrieval = packet["record"]["retrieval"] or {}
    audit = panel["citation_audit"]
    notes = [
        f"Literature: Anna record {packet['content_sha256']} ({len(packet['record']['hits'])} arXiv sources, "
        f"embedding={retrieval.get('embedding')}, fusion={retrieval.get('fusion')}).",
        f"Panel: grounding={panel['grounding']}; quotes verified {audit['verified']}/{audit['checked']}. "
        f"Agreed: {panel['verdict']['agreed']}"[:2000],
        f"Panel contested: {panel['verdict']['contested']}"[:2000],
        (f"Registration anchored in git commit {anchor['commit']} ({anchor['committed_at']}); "
         f"pushed to: {', '.join(anchor['pushed_to']) or 'nowhere yet'}.") if anchor
        else "Registration was NOT anchored in git for this run.",
        f"Code: rain-pipeline {code['version']}, source {code['source_sha256'][:16]}, "
        + (f"commit {code['git']['commit'][:10]}" + (" with uncommitted changes" if code["git"]["dirty"] else "")
           if code["git"]["commit"] else "not a git checkout") + ".",
    ]
    holdout = measured.holdout
    if holdout.get("declared") and "bytes" in holdout:
        notes.append(f"Holdout: {holdout['bytes']:,} bytes in {holdout['byte_ranges']} ranges; "
                     f"{holdout['bytes_read_before_registration']:,} first read before registration, "
                     + (f"{holdout['bytes_read_before_anchor']:,} before the anchor commit."
                        if holdout["bytes_read_before_anchor"] is not None else "no anchor commit."))
    if measured.excluded:
        notes.append(f"Excluded by pre-registered QC: {len(measured.excluded)} window(s) from "
                     + ", ".join(sorted({e['record'] for e in measured.excluded})))
    return [note[:2000] for note in notes + measured.notes][:100]


def _verify_line(verification: dict[str, Any]) -> str:
    if verification["valid"]:
        return f"OK ({verification['runs']} run(s) re-derived from stored data)"
    return f"{len(verification['problems'])} problem(s): {verification['problems'][:3]}"


def _report(spec, definition, record, packet, panel, measured: _Measured, verification, anchor, dossier: str,
            *, has_figure: bool) -> str:
    ev = record["evaluation"]
    lines = [
        f"# {record['run_id']}: {record['status'].upper()}",
        "",
        f"**{definition['title']}**",
        "",
        f"- Question: {spec['question']}",
        f"- Hypothesis: {definition['hypothesis']}",
        f"- Verdict (assigned by R.A.I.N. `{ev['rule'] if ev else 'n/a'}`): "
        f"{record['hypothesis_verdict'].replace('_', ' ')}",
        f"- {ev['summary'] if ev else 'Error at ' + record['error']['stage'] + ': ' + record['error']['message']}",
        f"- R.A.I.N. re-verification: {_verify_line(verification)}",
        "",
        "## Criteria (evidence)",
        "",
        "These measurements, and only these, decide the verdict.",
        "",
        "| Id | Metric | Needs | Observed | Holds |",
        "|---|---|---|---|---|",
    ]
    for group in ("guards", "success", "failure"):
        for c in (ev or {}).get(group, []):
            observed = "—" if c["observed"] is None else f"{c['observed']:.4g}"
            lines.append(f"| {c['id']} | `{c['metric']}` | {c['op']} {c['value']} | {observed} | {c['holds']} |")
    described = [m for m in definition["metrics"] if m["name"] not in registry_stage.evaluated_metrics(definition)]
    if described:
        lines += ["", "## Registered, not evaluated (description)", "",
                  "Registered and submitted, but no criterion reads them: they describe the run and decide nothing.",
                  "", "| Metric | Value |", "|---|---|"]
        for metric in described:
            value = record["measurements"].get(metric["name"])
            lines.append(f"| `{metric['name']}` | {'—' if value is None else f'{value:.4g}'} {metric.get('unit', '')} |")
    unregistered = [n for n in drr_stage.outputs(spec["analysis"]) if n not in {m["name"] for m in definition["metrics"]}]
    if unregistered:
        lines += ["", f"The study computed {len(unregistered)} further measurement(s) that were not registered. They "
                  "are in `drr_report.json` as description only and were never submitted."]
    if has_figure:
        lines += ["", "![Detection by breathing frequency and lag window](figure.png)"]

    lines += ["", "## Registration", "", f"- Registered: {definition['created_at']}"]
    if anchor:
        lines.append(f"- Anchored: git commit `{anchor['commit']}` ({anchor['committed_at']}); "
                     f"pushed to {', '.join(anchor['pushed_to']) or 'nowhere yet'}")
    else:
        lines.append("- Not anchored in git for this run")
    holdout = measured.holdout
    if holdout.get("declared") and "bytes" in holdout:
        lines.append(f"- Holdout: {holdout['bytes']:,} bytes; {holdout['bytes_read_before_registration']:,} had been "
                     "read before registration"
                     + (f", {holdout['bytes_read_before_anchor']:,} before the anchor commit"
                        if holdout["bytes_read_before_anchor"] is not None else ""))
    lineage = definition["parameters"].get("lineage")
    if lineage:
        lines.append(f"- Follows: {lineage.get('follows', '—')}. {lineage.get('observation', '')}".rstrip())
        if "exploration" in lineage:
            lines.append(f"- Exploration on seen data (not evidence): `{lineage['exploration']}`")
    lines.append(f"- Framing dossier: `{dossier}/`")

    lines += ["", "## Literature (Anna)", "", f"Record `{packet['content_sha256']}`", ""]
    for i, hit in enumerate(packet["record"]["hits"], start=1):
        lines.append(f"{i}. [{hit['document']['title']}]({hit['document']['url']})")
    answer = (packet["record"]["summary"] or {}).get("answer")
    if answer:
        lines += ["", "> " + answer.replace("\n", " ")]
    lines += ["", "## Research panel (R.A.I.N., offline)", "",
              f"- Grounding: {panel['grounding']}",
              f"- Agreed: {panel['verdict']['agreed']}",
              f"- Contested: {panel['verdict']['contested']}",
              f"- Next move: {panel['verdict']['next_move']}"]

    start, duration, count = segments_of(spec["data"])
    lines += ["", "## Data", "",
              f"PhysioNet Fantasia 1.0.0 (ODC-By 1.0): {len(spec['data']['records'])} records × {count} window(s) of "
              f"{duration} s from t={start} s. Analyzed {len(measured.windows)}; excluded by QC {len(measured.excluded)}.",
              "", "Cite: Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the "
              "fractal scaling of cardiac interbeat interval dynamics. Am J Physiol 1996;271:R1078-R1084. "
              "Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 2000;101(23):e215-e220.",
              "", "## Observations", ""]
    lines += [f"- {note}" for note in record["observations"]]
    lines += ["", "## Limitations (pre-registered)", ""]
    lines += [f"- {item}" for item in definition["limitations"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def verify(*, layout: Layout | None = None, registry_root: Path | None = None, runs_root: Path | None = None,
           framing_root: Path | None = None, data_root: Path | None = None) -> dict[str, Any]:
    """Re-derive every result and re-check every link of the evidence chain (see ``evidence.verify``)."""
    layout = resolve_layout(layout, {"registry_root": registry_root, "runs_root": runs_root,
                                     "framing_root": framing_root, "data_root": data_root})
    report = evidence.verify(layout)
    return {**report.as_dict(),
            "checks": [{"check": f"{c.subject}: {c.name}", "ok": c.ok, "status": c.status, "name": c.name,
                        "subject": c.subject, "detail": c.detail} for c in report.checks]}


def publish(*, layout: Layout | None = None) -> Path:
    """Regenerate RESULTS.md from the registry (after moving the R.A.I.N. pin, for example)."""
    layout = layout or Layout.default()
    registry_stage.publish(registry_stage.open_registry(layout.experiments, layout.results))
    return layout.results
