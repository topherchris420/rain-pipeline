"""Explore -> register -> run -> verify: the protocol that keeps the evidence honest.

explore    Try an analysis on data the ledger has already seen. Never evidence.
register   Anna retrieves and cites the literature, the R.A.I.N. panel argues
           over it, and the experiment is registered write-once. The
           registration binds the literature record, the panel corpus, the
           parent result and the holdout proof by hash.
           -> commit and push: that commit is the registration's timestamp.
run        Refuses an uncommitted registration. Reads the pre-registered data
           (logging every byte range in the ledger), runs the DRR study, and
           submits measurements with no status. R.A.I.N. alone evaluates the
           pre-registered criteria and assigns the verdict.
verify     Re-derives every stored result and re-checks every hash and holdout.

A crash after registration is still recorded: the submission carries an
``error`` block and R.A.I.N. files the run as ``error``, which is distinct
from a failed hypothesis.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import traceback
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from . import __version__, anna_stage, drr_stage, figures, ledger, panel_stage, physio, registry_stage, vendor

Log = Callable[[str], None]
EXPLORATORY = ("EXPLORATORY. Computed on data the ledger had already seen, to choose what to register. "
               "It is not evidence for any claim.")


class HoldoutViolation(RuntimeError):
    """A request would read unseen data in exploration, or seen data as a holdout."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(vendor.PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


@contextmanager
def _cwd(path: Path) -> Iterator[None]:
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def load_spec(path: Path, sections: tuple[str, ...] = ("question", "literature", "data", "analysis", "preregistration")
              ) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    for section in sections:
        if section not in spec:
            raise ValueError(f"{path}: missing '{section}'")
    return spec


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def segments_of(data: dict[str, Any]) -> tuple[float, float, int]:
    """``(first start, window length, window count)`` per record."""
    if "segments" in data:
        segments = data["segments"]
        return segments["first_start_s"], segments["duration_s"], segments["count"]
    return data["start_s"], data["duration_s"], 1  # V3D-EXP-0001: one window per record


def plan_data(data: dict[str, Any], cache_dir: Path) -> list[physio.SegmentPlan]:
    """One contiguous byte range per record. Reads headers only."""
    if data["source"] != "physionet-fantasia":
        raise ValueError(f"unsupported data source {data['source']!r}")
    start, duration, count = segments_of(data)
    return [physio.plan_segment(record, start, duration * count, cache_dir) for record in data["records"]]


def read_windows(data: dict[str, Any], plans: list[physio.SegmentPlan], ledger_path: Path, read_by: str, log: Log
                 ) -> tuple[list[physio.PairedSeries], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read every planned range (logging it in the ledger) and cut it into QC-passed windows."""
    start, duration, count = segments_of(data)
    threshold = data["qc"]["min_valid_rr_fraction"]
    windows, excluded, files = [], [], []
    for plan in plans:
        span, provenance = physio.read_segment(plan)
        ledger.record(ledger_path, url=provenance["url"], byte_range=provenance["byte_range"],
                      sha256=provenance["sha256"], read_at=ledger.utc_now(), read_by=read_by)
        files.append(provenance)
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
        log(f"    {plan.record}: {kept}/{count} windows pass QC" + ("  (downloaded)" if provenance["downloaded"] else ""))
    return windows, excluded, files


def _paths(data_root: Path | None) -> tuple[Path, Path]:
    data_root = data_root or vendor.PROJECT_ROOT / "data"
    return data_root / "cache" / "fantasia", data_root / "ledger.json"


def _ranges(plans: list[physio.SegmentPlan]) -> list[ledger.Range]:
    return [(plan.url, plan.byte_range) for plan in plans]


# --------------------------------------------------------------------------- #
# explore
# --------------------------------------------------------------------------- #
def explore(spec_path: Path, *, explorations_root: Path | None = None, data_root: Path | None = None,
            log: Log = print) -> dict[str, Any]:
    root = vendor.PROJECT_ROOT
    spec = load_spec(spec_path, sections=("question", "data", "analysis"))
    cache_dir, ledger_path = _paths(data_root)
    plans = plan_data(spec["data"], cache_dir)
    unseen = ledger.bytes_unseen(ledger.load(ledger_path), _ranges(plans))
    if unseen:
        raise HoldoutViolation(
            f"explore only reads data the ledger has already seen, and {unseen:,} bytes of this spec are unseen. "
            "Unseen data is for registered experiments."
        )
    out_dir = (explorations_root or root / "explorations") / f"{_stamp()}-{spec_path.stem}"
    out_dir.mkdir(parents=True, exist_ok=False)
    log(f"Exploration: {_relative(out_dir)}  (seen data only; not evidence)")
    windows, excluded, files = read_windows(spec["data"], plans, ledger_path, "exploration", log)
    study = drr_stage.run(windows, excluded, spec["analysis"])
    report = {"status": EXPLORATORY, "spec": _relative(spec_path), "question": spec["question"],
              "code": {"pipeline": {"version": __version__, "source_sha256": vendor.pipeline_source_sha256()},
                       "vendored": vendor.vendored_state()},
              "dataset_files": files, **study.report}
    vendor.write_json(out_dir / "report.json", report)
    figures.render(study.report, out_dir / "figure.png", note="Exploratory: seen data, not evidence")
    for name, value in study.measurements.items():
        log(f"    {name} = {_show(value)}")
    return {"dir": out_dir, "measurements": study.measurements}


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #
def register(spec_path: Path, *, offline: bool = False, registry_root: Path | None = None,
             framing_root: Path | None = None, data_root: Path | None = None, log: Log = print) -> dict[str, Any]:
    root = vendor.PROJECT_ROOT
    spec = load_spec(spec_path)
    registry = registry_stage.open_registry(registry_root or root / "experiments")
    framing_dir = (framing_root or root / "framing") / spec_path.stem
    existing = registry_stage.find(registry, spec)
    if existing is not None:
        log(f"{existing['experiment_id']} is already registered (created {existing['created_at']}). Nothing to do.")
        return {"experiment_id": existing["experiment_id"], "created": False}

    log(f"Question: {spec['question']}")
    binding: dict[str, Any] = {}
    cache_dir, ledger_path = _paths(data_root)

    # Cheap refusals first: lineage files must exist and a holdout must be untouched.
    lineage = spec.get("lineage", {})
    if "follows" in lineage:
        experiment_id, run_id = lineage["follows"].split("/")
        binding["parent_result_sha256"] = _sha256(registry.root / experiment_id / "runs" / run_id / "result.json")
    if "exploration" in lineage:
        binding["exploration_report_sha256"] = _sha256(root / lineage["exploration"])
    holdout_ranges: list[ledger.Range] = []
    if spec["data"].get("holdout"):
        holdout_ranges = _ranges(plan_data(spec["data"], cache_dir))
        total = sum(b - a + 1 for _, (a, b) in holdout_ranges)
        seen = total - ledger.bytes_unseen(ledger.load(ledger_path), holdout_ranges)
        if seen:
            raise HoldoutViolation(f"{seen:,} bytes of the declared holdout have already been read. "
                                   "This data cannot confirm anything; choose data the ledger has never seen.")
        binding["holdout"] = {"byte_ranges": len(holdout_ranges), "bytes": total,
                              "ledger_sha256": ledger.sha256_file(ledger_path)}

    if framing_dir.exists():  # a dossier with no registration is left over from a failed attempt
        shutil.rmtree(framing_dir)
    framing_dir.mkdir(parents=True)
    files = []

    log("\n[1/3] Anna: literature retrieval")
    anna = anna_stage.run(spec, pgdata=root / ".pgdata", offline=offline)
    for item in anna.ingestion:
        if "query" in item:
            log(f"    ingest {item['query']}: indexed={item.get('indexed', 0)}"
                + (f"  ({item['error']})" if item.get("error") else ""))
    files.append(vendor.write_json(framing_dir / "anna_record.json", anna.packet))
    files.append(vendor.write_json(framing_dir / "anna_verification.json", anna.verification))
    citations = (anna.packet["record"]["summary"] or {}).get("citations", [])
    log(f"    {len(anna.documents)} sources, {len(citations)} cited; record sha256 {anna.fingerprint[:16]}...")
    log(f"    excerpt verification: {'OK' if anna.verification['ok'] else 'FAILED'} {anna.verification['counts']}")
    if not anna.verification["ok"]:
        raise RuntimeError("Anna could not re-verify its own citations; refusing to build on them")

    log("\n[2/3] R.A.I.N. research panel (offline, over Anna's sources)")
    with _cwd(root):  # the transcript prints the corpus path relative to the working directory
        panel = panel_stage.run(spec["question"], anna.documents, framing_dir / "corpus")
    files.append(vendor.write_text(framing_dir / "panel_meeting.md", panel.markdown))
    files.append(vendor.write_json(framing_dir / "panel_summary.json", panel.summary))
    audit = panel.summary["citation_audit"]
    log(f"    grounding: {panel.summary['grounding']}; quotes verified {audit['verified']}/{audit['checked']}")
    log(f"    agreed:    {panel.summary['verdict']['agreed']}")
    log(f"    contested: {panel.summary['verdict']['contested']}")

    log("\n[3/3] R.A.I.N. registration (write-once)")
    binding = {"anna_record_sha256": anna.fingerprint, "panel_corpus_sha256": audit["corpus_sha256"], **binding}
    definition = registry_stage.register(registry, spec, binding)
    experiment_id = definition["experiment_id"]
    vendor.write_json(framing_dir / "framing.json", {
        "schema": "rain-pipeline-framing/v1",
        "experiment_id": experiment_id,
        "spec": _relative(spec_path),
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
    log("\nNext: commit and push experiments/, framing/ and RESULTS.md, then `run`. "
        "The commit is the proof that these criteria came before the data.")
    return {"experiment_id": experiment_id, "created": True}


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"lineage points at {path}, which does not exist")
    return vendor.sha256_bytes(path.read_bytes())


def _log_criteria(definition: dict[str, Any], log: Log) -> None:
    for group in ("guards", "success", "failure"):
        for c in definition["criteria"][group]:
            log(f"      {c['id']}: {c['metric']} {c['op']} {c['value']}")


def load_framing(framing_dir: Path, definition: dict[str, Any]) -> tuple[dict, dict, dict]:
    """The dossier this experiment was framed with, checked against what the registration bound."""
    manifest = json.loads((framing_dir / "framing.json").read_text(encoding="utf-8"))
    if manifest["experiment_id"] != definition["experiment_id"]:
        raise RuntimeError(f"{framing_dir} frames {manifest['experiment_id']}, not {definition['experiment_id']}")
    packet = json.loads((framing_dir / "anna_record.json").read_text(encoding="utf-8"))
    vendor.ensure_importable()
    from engine import records

    if records.verify_record(packet, None)["fingerprint"]["matches"] is not True:
        raise RuntimeError(f"{framing_dir}/anna_record.json no longer matches its fingerprint")
    bound = definition["parameters"].get("framing")
    if bound and bound["anna_record_sha256"] != packet["content_sha256"]:
        raise RuntimeError("the literature record is not the one this registration was bound to")
    panel = json.loads((framing_dir / "panel_summary.json").read_text(encoding="utf-8"))
    return manifest, packet, panel


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def run(spec_path: Path, *, registry_root: Path | None = None, runs_root: Path | None = None,
        framing_root: Path | None = None, data_root: Path | None = None, allow_uncommitted: bool = False,
        log: Log = print) -> dict[str, Any]:
    root = vendor.PROJECT_ROOT
    spec = load_spec(spec_path)
    registry = registry_stage.open_registry(registry_root or root / "experiments")
    definition = registry_stage.find(registry, spec)
    if definition is None:
        raise RuntimeError(f"{spec_path.name} is not registered. Run `register` first, then commit and push.")
    experiment_id = definition["experiment_id"]
    framing_dir = (framing_root or root / "framing") / spec_path.stem
    manifest, packet, panel = load_framing(framing_dir, definition)
    anchor = None if allow_uncommitted else registry_stage.anchor(registry, experiment_id)

    run_dir = (runs_root or root / "runs") / _stamp()
    run_dir.mkdir(parents=True, exist_ok=False)
    log(f"Run directory: {_relative(run_dir)}")
    log(f"{experiment_id}: {definition['title']}")
    log(f"    registered {definition['created_at']}; "
        + (f"commit {anchor['commit'][:7]} ({', '.join(anchor['pushed_to']) or 'not pushed'})" if anchor
           else "NOT anchored in git (--allow-uncommitted)"))
    _log_criteria(definition, log)

    cache_dir, ledger_path = _paths(data_root)
    holdout = bool(spec["data"].get("holdout"))
    started_at = ledger.utc_now()
    error = None
    measurements: dict[str, Any] = {m["name"]: None for m in definition["metrics"]}
    series: dict[str, list[float]] = {}
    dataset_files: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    windows: list[physio.PairedSeries] = []
    early_bytes = None
    report = None
    stage = "data"
    try:
        log("\n[1/3] Data: PhysioNet Fantasia")
        plans = plan_data(spec["data"], cache_dir)
        if holdout:
            early_bytes = ledger.bytes_read_before(ledger.load(ledger_path), _ranges(plans), definition["created_at"])
            log(f"    holdout: {early_bytes:,} bytes read before registration")
        windows, excluded, dataset_files = read_windows(spec["data"], plans, ledger_path, experiment_id, log)
        if not windows:
            raise RuntimeError("no window passed QC")
        log(f"\n[2/3] DRR: {drr_stage.study_name(spec['analysis'])} study on {len(windows)} windows")
        stage = "drr"
        study = drr_stage.run(windows, excluded, spec["analysis"])
        computed = dict(study.measurements)
        if holdout:
            computed["holdout_bytes_read_before_registration"] = early_bytes
        measurements, series, report = registry_stage.select_measurements(definition, computed), study.series, study.report
        for name, value in measurements.items():
            log(f"    {name} = {_show(value)}")
    except Exception as exc:  # recorded as an R.A.I.N. 'error' run, never swallowed
        error = {"stage": stage, "type": type(exc).__name__, "message": str(exc)[:2000]}
        log(f"    ERROR {error['type']}: {error['message']}")
        (run_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finished_at = ledger.utc_now()

    artifacts: list[dict[str, Any]] = []

    def keep(ref: dict[str, Any], kind: str, folder: Path) -> None:
        artifacts.append({**ref, "kind": kind, "uri": f"{_relative(folder)}/{ref['name']}"})

    if report is not None:
        keep(vendor.write_json(run_dir / "drr_report.json", {"dataset_files": dataset_files, **report}),
             "drr-report", run_dir)
        figure = figures.render(report, run_dir / "figure.png", note=f"{experiment_id}, held-out data"
                                if holdout else experiment_id)
        if figure:
            keep(figure, "figure", run_dir)
    kinds = {"anna_record.json": "anna-research-record/v1", "anna_verification.json": "anna-verification",
             "panel_meeting.md": "rain-offline-meeting", "panel_summary.json": "rain-panel-summary"}
    for ref in manifest["files"]:
        keep({k: ref[k] for k in ("name", "sha256", "bytes")}, kinds.get(ref["name"], "framing"), framing_dir)

    log("\n[3/3] R.A.I.N. evaluation")
    vendored = vendor.vendored_state()
    drr_git = vendored["drr"]
    record_hits = packet["record"]["hits"]
    submission = {
        "schema_version": "rain-experiment-submission/v1",
        "experiment_id": experiment_id,
        "experiment_version": definition["experiment_version"],
        "evidence_class": definition["evidence_class"],
        "started_at": started_at,
        "finished_at": finished_at,
        "seed": definition["seed"],
        "parameters": definition["parameters"],
        "inputs": {
            "registration": {"definition_sha256": registry_stage.definition_sha256(definition),
                             "created_at": definition["created_at"], "git": anchor},
            "holdout": {"declared": holdout, "bytes_read_before_registration": early_bytes},
            "literature": {
                "engine": "Anna (in-process, embedded PostgreSQL)",
                "record_sha256": packet["content_sha256"],
                "search": packet["record"]["request"]["q"],
                "retrieval": packet["record"]["retrieval"],
                "sources": [{k: hit["document"][k] for k in ("id", "title", "url")} for hit in record_hits],
            },
            "panel": {k: panel[k] for k in ("engine", "grounding", "citation_audit", "verdict")},
            "dataset": {"name": "PhysioNet Fantasia Database 1.0.0", "license": "ODC-By-1.0",
                        "files": dataset_files, "windows_analyzed": len(windows), "excluded_windows": excluded},
            "code": {"pipeline": {"version": __version__, "source_sha256": vendor.pipeline_source_sha256()},
                     "vendored": vendored},
        },
        "measurements": measurements,
        "series": series,
        "observations": _observations(packet, panel, excluded, anchor),
        "limitations": [],
        "artifacts": [{k: a[k] for k in ("name", "sha256", "bytes", "kind", "uri")} for a in artifacts],
        "models": [],
        "provenance": {
            "producer": f"rain-pipeline {__version__}",
            "repository": drr_git["repository"],
            "commit": drr_git["commit"],
            "branch": drr_git["branch"],
            "dirty": drr_git["dirty"],
            "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                            **_versions("numpy", "scipy", "drr-framework", "pgserver")},
        },
    }
    if error:
        submission["error"] = error
    vendor.write_json(run_dir / "submission.json", submission)

    record = registry_stage.submit(registry, definition, submission)
    verification = registry_stage.verify(registry, experiment_id)
    summary = {
        "run_dir": _relative(run_dir),
        "experiment_id": experiment_id,
        "run_id": record["run_id"],
        "status": record["status"],
        "verdict": record["hypothesis_verdict"],
        "evaluation": record["evaluation"],
        "measurements": measurements,
        "rain_verify": verification,
        "anna_record_sha256": packet["content_sha256"],
    }
    vendor.write_json(run_dir / "summary.json", summary)
    (run_dir / "REPORT.md").write_text(
        _report(spec, definition, record, packet, panel, windows, excluded, verification, anchor, early_bytes,
                has_figure=(run_dir / "figure.png").exists()),
        encoding="utf-8", newline="\n")

    log(f"    {record['run_id']}: {record['status'].upper()} ({record['hypothesis_verdict'].replace('_', ' ')})")
    if record["evaluation"]:
        log(f"    {record['evaluation']['summary']}")
    log(f"    R.A.I.N. verify: {_verify_line(verification)}")
    log(f"\nReport: {_relative(run_dir / 'REPORT.md')}   Results: RESULTS.md")
    return summary


def _show(value: Any) -> Any:
    return value if value is None or isinstance(value, int) else round(value, 4)


def _versions(*names: str) -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    found = {}
    for name in names:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            pass
    return found


def _observations(packet: dict, panel: dict, excluded: list, anchor: dict | None) -> list[str]:
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
    ]
    if excluded:
        notes.append(f"Excluded by pre-registered QC: {len(excluded)} window(s) from "
                     + ", ".join(sorted({e['record'] for e in excluded})))
    return notes


def _verify_line(verification: dict[str, Any]) -> str:
    if verification["valid"]:
        return f"OK ({verification['runs']} run(s) re-derived from stored data)"
    return f"{len(verification['problems'])} problem(s): {verification['problems'][:3]}"


def _report(spec, definition, record, packet, panel, windows, excluded, verification, anchor, early_bytes,
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
        f"- {ev['summary'] if ev else (record.get('error') or {}).get('message', '')}",
        f"- R.A.I.N. re-verification: {_verify_line(verification)}",
        "",
        "## Criteria",
        "",
        "| Id | Metric | Needs | Observed | Holds |",
        "|---|---|---|---|---|",
    ]
    for group in ("guards", "success", "failure"):
        for c in (ev or {}).get(group, []):
            observed = "—" if c["observed"] is None else f"{c['observed']:.4g}"
            lines.append(f"| {c['id']} | `{c['metric']}` | {c['op']} {c['value']} | {observed} | {c['holds']} |")
    if has_figure:
        lines += ["", "![Detection by breathing frequency and lag window](figure.png)"]

    lines += ["", "## Registration", "", f"- Registered: {definition['created_at']}"]
    if anchor:
        lines.append(f"- Git commit: `{anchor['commit']}` ({anchor['committed_at']}); "
                     f"pushed to {', '.join(anchor['pushed_to']) or 'nowhere yet'}")
    else:
        lines.append("- Not anchored in git for this run")
    if early_bytes is not None:
        lines.append(f"- Holdout: {early_bytes:,} bytes of this data had been read before registration")
    lineage = definition["parameters"].get("lineage")
    if lineage:
        lines.append(f"- Follows: {lineage.get('follows', '—')}. {lineage.get('observation', '')}".rstrip())
        if "exploration" in lineage:
            lines.append(f"- Exploration on seen data (not evidence): `{lineage['exploration']}`")

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
              f"{duration} s from t={start} s. Analyzed {len(windows)}; excluded by QC {len(excluded)}.",
              "", "Cite: Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the "
              "fractal scaling of cardiac interbeat interval dynamics. Am J Physiol 1996;271:R1078-R1084. "
              "Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 2000;101(23):e215-e220.",
              "", "## Limitations (pre-registered)", ""]
    lines += [f"- {item}" for item in definition["limitations"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def verify(*, registry_root: Path | None = None, runs_root: Path | None = None, framing_root: Path | None = None,
           data_root: Path | None = None) -> dict[str, Any]:
    """R.A.I.N. re-derives every result; every Anna fingerprint, framing binding and holdout is re-checked."""
    root = vendor.PROJECT_ROOT
    registry = registry_stage.open_registry(registry_root or root / "experiments")
    framing_root, runs_root = framing_root or root / "framing", runs_root or root / "runs"
    _, ledger_path = _paths(data_root)
    rain = registry_stage.verify(registry)
    from engine import records  # importable once the registry set up the vendored paths

    checks: list[dict[str, Any]] = []

    def check(what: str, ok: bool) -> None:
        checks.append({"check": what, "ok": bool(ok)})

    for path in sorted([*framing_root.glob("*/anna_record.json"), *runs_root.glob("*/anna_record.json")]):
        packet = json.loads(path.read_text(encoding="utf-8"))
        check(f"{_relative(path)}: Anna fingerprint", records.verify_record(packet, None)["fingerprint"]["matches"])
    book = ledger.load(ledger_path)
    for path in sorted(framing_root.glob("*/framing.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        definition = registry.load_definition(manifest["experiment_id"])
        label = f"{manifest['experiment_id']} ({path.parent.name})"
        check(f"{label}: registration unchanged since framing",
              registry_stage.definition_sha256(definition) == manifest["definition_sha256"])
        bound = definition["parameters"].get("framing", {})
        packet = json.loads((path.parent / "anna_record.json").read_text(encoding="utf-8"))
        if "anna_record_sha256" in bound:
            check(f"{label}: literature record is the one bound", bound["anna_record_sha256"] == packet["content_sha256"])
        lineage = definition["parameters"].get("lineage", {})
        if "parent_result_sha256" in bound:
            experiment_id, run_id = lineage["follows"].split("/")
            parent = registry.root / experiment_id / "runs" / run_id / "result.json"
            check(f"{label}: parent result is the one bound", _sha256(parent) == bound["parent_result_sha256"])
        if "exploration_report_sha256" in bound:
            check(f"{label}: exploration report is the one bound",
                  _sha256(root / lineage["exploration"]) == bound["exploration_report_sha256"])
        if manifest.get("holdout_ranges"):
            ranges = [(url, tuple(byte_range)) for url, byte_range in manifest["holdout_ranges"]]
            early = ledger.bytes_read_before(book, ranges, definition["created_at"])
            check(f"{label}: no holdout byte read before registration ({early:,} found)", early == 0)
    return {"rain": rain, "checks": checks, "ok": rain["valid"] and all(c["ok"] for c in checks)}
