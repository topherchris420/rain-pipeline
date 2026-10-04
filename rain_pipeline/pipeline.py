"""Anna -> R.A.I.N. -> DRR, in the order that keeps the evidence honest.

1. Anna        literature: ingest, search, cite, seal, verify
2. R.A.I.N.    panel deliberates over Anna's sources (offline, no model)
3. R.A.I.N.    pre-register the experiment (write-once) BEFORE any data is read
4. data        fetch the pre-registered PhysioNet segments, hash every byte
5. DRR         lead-lag tests on real pairs + positive / null / mismatched controls
6. R.A.I.N.    admit the submission; R.A.I.N. alone evaluates the criteria
7. R.A.I.N.    re-verify the stored run; regenerate RESULTS.md

A crash after pre-registration is still recorded: the submission carries an
``error`` block and R.A.I.N. files the run as ``error``, which is distinct
from a failed hypothesis.
"""

from __future__ import annotations

import json
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__, anna_stage, drr_stage, panel_stage, physio, registry_stage, vendor

Log = Callable[[str], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    for section in ("question", "literature", "data", "analysis", "preregistration"):
        if section not in spec:
            raise ValueError(f"{path}: missing '{section}'")
    return spec


def fetch_pairs(data: dict[str, Any], cache_dir: Path, log: Log) -> tuple[list, list, list]:
    if data["source"] != "physionet-fantasia":
        raise ValueError(f"unsupported data source {data['source']!r}")
    pairs, excluded, files = [], [], []
    for record in data["records"]:
        header, signals, provenance = physio.fetch_segment(record, data["start_s"], data["duration_s"], cache_dir)
        files.append(provenance)
        pair = physio.paired_series(header, signals, grid_fs=data["grid_hz"], highpass_hz=data["highpass_hz"])
        threshold = data["qc"]["min_valid_rr_fraction"]
        if pair.qc["valid_rr_fraction"] < threshold:
            excluded.append({"record": record, "reason": f"valid RR fraction {pair.qc['valid_rr_fraction']:.3f} < {threshold}",
                             "qc": pair.qc})
            log(f"    {record}: excluded by QC ({pair.qc['valid_rr_fraction']:.3f} valid RR)")
        else:
            pairs.append(pair)
            log(f"    {record}: {pair.qc['beats']} beats, {pair.qc['mean_heart_rate_bpm']:.0f} bpm, "
                f"{pair.qc['valid_rr_fraction']:.3f} valid RR")
    return pairs, excluded, files


def run(spec_path: Path, *, offline: bool = False, registry_root: Path | None = None,
        runs_root: Path | None = None, log: Log = print) -> dict[str, Any]:
    root = vendor.PROJECT_ROOT
    spec = load_spec(spec_path)
    registry_root = registry_root or root / "experiments"
    run_dir = (runs_root or root / "runs") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    artifacts: list[dict[str, Any]] = []

    def keep(ref: dict[str, Any], kind: str) -> None:
        artifacts.append({**ref, "kind": kind, "uri": f"{run_dir.relative_to(root).as_posix()}/{ref['name']}"})

    log(f"Run directory: {run_dir.relative_to(root)}")
    log(f"Question: {spec['question']}")

    # 1. Anna --------------------------------------------------------------
    log("\n[1/6] Anna: literature retrieval")
    anna = anna_stage.run(spec, pgdata=root / ".pgdata", offline=offline)
    for item in anna.ingestion:
        if "query" in item:
            log(f"    ingest {item['query']}: indexed={item.get('indexed', 0)}"
                + (f"  ({item['error']})" if item.get("error") else ""))
    keep(vendor.write_json(run_dir / "anna_record.json", anna.packet), "anna-research-record/v1")
    keep(vendor.write_json(run_dir / "anna_verification.json", anna.verification), "anna-verification")
    citations = (anna.packet["record"]["summary"] or {}).get("citations", [])
    log(f"    {len(anna.documents)} sources, {len(citations)} cited; record sha256 {anna.fingerprint[:16]}...")
    log(f"    excerpt verification: {'OK' if anna.verification['ok'] else 'FAILED'} {anna.verification['counts']}")
    if not anna.verification["ok"]:
        raise RuntimeError("Anna could not re-verify its own citations; refusing to build on them")

    # 2. R.A.I.N. panel -----------------------------------------------------
    log("\n[2/6] R.A.I.N. research panel (offline, over Anna's sources)")
    panel = panel_stage.run(spec["question"], anna.documents, run_dir / "corpus")
    keep(vendor.write_text(run_dir / "panel_meeting.md", panel.markdown), "rain-offline-meeting")
    keep(vendor.write_json(run_dir / "panel_summary.json", panel.summary), "rain-panel-summary")
    audit = panel.summary["citation_audit"]
    log(f"    grounding: {panel.summary['grounding']}; quotes verified {audit['verified']}/{audit['checked']}")
    log(f"    agreed:    {panel.summary['verdict']['agreed']}")
    log(f"    contested: {panel.summary['verdict']['contested']}")

    # 3. Pre-registration -----------------------------------------------------
    log("\n[3/6] R.A.I.N. pre-registration")
    registry = registry_stage.open_registry(registry_root)
    definition, created = registry_stage.preregister(registry, spec)
    experiment_id = definition["experiment_id"]
    log(f"    {experiment_id} v{definition['experiment_version']} "
        f"{'registered now' if created else 'already registered'} at {definition['created_at']}")
    for group in ("guards", "success", "failure"):
        for c in definition["criteria"][group]:
            log(f"      {c['id']}: {c['metric']} {c['op']} {c['value']}")

    # 4-5. Data + DRR -----------------------------------------------------------
    started_at = _utc_now()
    error = None
    measurements: dict[str, Any] = {m["name"]: None for m in definition["metrics"]}
    series: dict[str, list[float]] = {}
    dataset_files: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    stage = "data"
    try:
        log("\n[4/6] Data: PhysioNet Fantasia segments")
        pairs, excluded, dataset_files = fetch_pairs(spec["data"], root / "data" / "cache" / "fantasia", log)
        if not pairs:
            raise RuntimeError("no record passed QC")
        log("\n[5/6] DRR: lead-lag analysis with controls")
        stage = "drr"
        drr = drr_stage.run(pairs, excluded, spec["analysis"])
        registry_stage.check_measurements(definition, drr.measurements)
        measurements, series = drr.measurements, drr.series
        keep(vendor.write_json(run_dir / "drr_report.json", {"dataset_files": dataset_files, **drr.report}),
             "drr-report")
        for name, value in measurements.items():
            log(f"    {name} = {value if value is None or isinstance(value, int) else round(value, 4)}")
    except Exception as exc:  # recorded as an R.A.I.N. 'error' run, never swallowed
        error = {"stage": stage, "type": type(exc).__name__, "message": str(exc)[:2000]}
        log(f"    ERROR {error['type']}: {error['message']}")
        (run_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finished_at = _utc_now()

    # 6. Submission -------------------------------------------------------------
    log("\n[6/6] R.A.I.N. evaluation")
    vendored = vendor.vendored_state()
    drr_git = vendored["drr"]
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
            "preregistration": {"definition_sha256": registry_stage.definition_sha256(definition),
                                "created_at": definition["created_at"]},
            "literature": {
                "engine": "Anna (in-process, embedded PostgreSQL)",
                "record_sha256": anna.fingerprint,
                "search": spec["literature"]["search"],
                "retrieval": anna.packet["record"]["retrieval"],
                "sources": [{"id": d.id, "title": d.title, "url": d.url} for d in anna.documents],
                "excerpt_verification": anna.verification["counts"],
            },
            "panel": {k: panel.summary[k] for k in ("engine", "grounding", "citation_audit", "verdict")},
            "dataset": {"name": "PhysioNet Fantasia Database 1.0.0", "license": "ODC-By-1.0",
                        "files": dataset_files, "excluded_records": excluded},
            "code": {"pipeline": {"version": __version__, "source_sha256": vendor.pipeline_source_sha256()},
                     "vendored": vendored},
        },
        "measurements": measurements,
        "series": series,
        "observations": _observations(anna, panel, excluded),
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
        "run_dir": str(run_dir),
        "experiment_id": experiment_id,
        "run_id": record["run_id"],
        "status": record["status"],
        "verdict": record["hypothesis_verdict"],
        "evaluation": record["evaluation"],
        "measurements": measurements,
        "rain_verify": verification,
        "anna_record_sha256": anna.fingerprint,
    }
    vendor.write_json(run_dir / "summary.json", summary)
    (run_dir / "REPORT.md").write_text(_report(spec, definition, record, anna, panel, excluded, verification),
                                       encoding="utf-8", newline="\n")

    log(f"    {experiment_id} {record['run_id']}: {record['status'].upper()} "
        f"({record['hypothesis_verdict'].replace('_', ' ')})")
    if record["evaluation"]:
        log(f"    {record['evaluation']['summary']}")
    log(f"    R.A.I.N. verify: {_verify_line(verification)}")
    log(f"\nReport: {(run_dir / 'REPORT.md').relative_to(root)}   Results: RESULTS.md")
    return summary


def _versions(*names: str) -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    found = {}
    for name in names:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            pass
    return found


def _observations(anna: anna_stage.AnnaResult, panel: panel_stage.PanelResult, excluded: list) -> list[str]:
    retrieval = anna.packet["record"]["retrieval"] or {}
    audit = panel.summary["citation_audit"]
    notes = [
        f"Literature: Anna record {anna.fingerprint} ({len(anna.documents)} arXiv sources, "
        f"embedding={retrieval.get('embedding')}, fusion={retrieval.get('fusion')}); "
        f"excerpt verification ok={anna.verification['ok']}.",
        f"Panel: grounding={panel.summary['grounding']}; quotes verified {audit['verified']}/{audit['checked']}. "
        f"Agreed: {panel.summary['verdict']['agreed']}"[:2000],
        f"Panel contested: {panel.summary['verdict']['contested']}"[:2000],
    ]
    if excluded:
        notes.append("Excluded by pre-registered QC: " + ", ".join(e["record"] for e in excluded))
    return notes


def _verify_line(verification: dict[str, Any]) -> str:
    if verification["valid"]:
        return f"OK ({verification['runs']} run(s) re-derived from stored data)"
    return f"{len(verification['problems'])} problem(s): {verification['problems'][:3]}"


def _report(spec, definition, record, anna, panel, excluded, verification) -> str:
    ev = record["evaluation"]
    lines = [
        f"# {definition['experiment_id']} {record['run_id']}: {record['status'].upper()}",
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
    lines += ["", "## Literature (Anna)", "",
              f"Record `{anna.fingerprint}`, excerpts re-verified: {anna.verification['counts']}", ""]
    for i, doc in enumerate(anna.documents, start=1):
        lines.append(f"{i}. [{doc.title}]({doc.url})")
    summary = (anna.packet["record"]["summary"] or {}).get("answer")
    if summary:
        lines += ["", "> " + summary.replace("\n", " ")]
    lines += ["", "## Research panel (R.A.I.N., offline)", "",
              f"- Grounding: {panel.summary['grounding']}",
              f"- Agreed: {panel.summary['verdict']['agreed']}",
              f"- Contested: {panel.summary['verdict']['contested']}",
              f"- Next move: {panel.summary['verdict']['next_move']}",
              "", "Full transcript: `panel_meeting.md`.", "",
              "## Data", "",
              f"PhysioNet Fantasia 1.0.0 (ODC-By 1.0): {len(spec['data']['records'])} records, "
              f"{spec['data']['duration_s']} s from t={spec['data']['start_s']} s. "
              f"Excluded by QC: {', '.join(e['record'] for e in excluded) or 'none'}.",
              "", "Cite: Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the "
              "fractal scaling of cardiac interbeat interval dynamics. Am J Physiol 1996;271:R1078-R1084. "
              "Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 2000;101(23):e215-e220.",
              "", "## Limitations (pre-registered)", ""]
    lines += [f"- {item}" for item in definition["limitations"]]
    return "\n".join(lines) + "\n"
