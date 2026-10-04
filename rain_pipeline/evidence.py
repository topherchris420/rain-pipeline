"""The evidence graph: every link between the records, and whether it still holds.

A claim in this repository is the verdict of one run, and it stands on a chain:

    spec ── registration ── anchor commit       criteria written, then timestamped by git
                 │ binds by hash: literature record, panel corpus, parent result,
                 │ exploration report, holdout ranges and the ledger as it was
                 ▼
    data ranges (ledger) ──► run ──► artifacts   measured; every byte and file hash-bound
                              │
                              ▼
                      R.A.I.N. verdict           assigned by the registered criteria alone
                              ▲
                       replay receipts           re-executed from the registration, compared

``verify`` re-derives each link from the files on disk and the git history and
reports one ``Check`` per link:

    ok    the link holds
    fail  the link is broken: a hash, a binding, a time order or a record disagrees
    warn  the record is honest but weaker than the protocol's standard
          (for example a registration that was never anchored in git)
    skip  the link cannot be checked here (no git history, or a shallow clone)

``claims`` then gives each run an evidence level that follows mechanically from
those checks, and ``graph`` exports the chain itself, nodes and edges with
their hashes, as one machine-readable document whose digest identifies the
evidence state of the repository independently of its code and prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import ledger, panel_stage, provenance, registry_stage, vendor
from .errors import DossierMismatch
from .layout import Layout

OK, FAIL, WARN, SKIP = "ok", "fail", "warn", "skip"
GRAPH_SCHEMA = "rain-pipeline-evidence-graph/v1"
RECEIPT_SCHEMA = "rain-pipeline-replay-receipt/v1"
EXPLORATORY = ("EXPLORATORY. Computed on data the ledger had already seen, to choose what to register. "
               "It is not evidence for any claim.")

# Evidence levels, strongest first. Each follows mechanically from the checks.
LEVELS = {
    "confirmatory": "registered, anchored in git and pushed before the run, on a holdout no byte of which was read "
                    "before the anchor; every link verified",
    "preregistered": "registered and anchored in git before the run; every link verified (no holdout, or the anchor "
                     "was not pushed before the run)",
    "registered": "criteria recorded by R.A.I.N. before the run, but not anchored in git before it",
    "unverified": "a link in its chain failed verification; treat the verdict as unsupported",
}

_STAMP = re.compile(r"^(\d{8}T\d{6}Z)")


@dataclass(frozen=True)
class Check:
    name: str
    subject: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != FAIL


@dataclass
class Snapshot:
    """Everything ``verify`` reads, loaded once."""

    layout: Layout
    registry: Any
    history: provenance.History
    ledger: dict[str, Any] | None = None
    ledger_error: str | None = None
    definitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    result_paths: dict[str, Path] = field(default_factory=dict)
    dossiers: dict[str, list[Path]] = field(default_factory=dict)
    submissions: dict[str, Path] = field(default_factory=dict)
    explorations: list[Path] = field(default_factory=list)
    receipts: list[Path] = field(default_factory=list)


@dataclass
class Report:
    checks: list[Check]
    claims: list[dict[str, Any]]
    rain: dict[str, Any]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def counts(self) -> dict[str, int]:
        return {status: sum(c.status == status for c in self.checks) for status in (OK, FAIL, WARN, SKIP)}

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "counts": self.counts(), "rain": self.rain, "claims": self.claims,
                "checks": [asdict(c) for c in self.checks]}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
_json = provenance.read_json


def snapshot(layout: Layout) -> Snapshot:
    registry = registry_stage.open_registry(layout.experiments, layout.results)
    snap = Snapshot(layout=layout, registry=registry, history=provenance.History(layout.root))
    try:
        snap.ledger = ledger.load(layout.ledger)
    except ledger.LedgerError as exc:
        snap.ledger_error = str(exc)
    for experiment_id in registry.experiment_ids():
        try:
            snap.definitions[experiment_id] = registry.load_definition(experiment_id)
        except Exception:  # R.A.I.N.'s own verification reports why
            continue
        snap.runs[experiment_id] = []
        for run_dir in registry.run_dirs(experiment_id):
            record = _json(run_dir / "result.json")
            if isinstance(record, dict) and "run_id" in record:
                snap.runs[experiment_id].append(record)
                snap.result_paths[record["run_id"]] = run_dir / "result.json"
    for manifest_path in sorted(layout.framing.glob("*/framing.json")):
        manifest = _json(manifest_path)
        if isinstance(manifest, dict) and isinstance(manifest.get("experiment_id"), str):
            snap.dossiers.setdefault(manifest["experiment_id"], []).append(manifest_path.parent)
    for path in sorted(layout.runs.glob("*/submission.json")):
        submission = _json(path)
        if isinstance(submission, dict):
            try:
                snap.submissions[registry_stage.submission_sha256(submission)] = path
            except (TypeError, ValueError):
                continue
    snap.explorations = sorted(layout.explorations.glob("*/report.json"))
    snap.receipts = sorted(layout.replays.glob("**/*.json"))
    return snap


def dossier_dir(layout: Layout, experiment_id: str) -> Path:
    """The framing dossier of an experiment, found by the experiment it declares (not by spec name)."""
    found = [p.parent for p in sorted(layout.framing.glob("*/framing.json"))
             if isinstance(_json(p), dict) and _json(p).get("experiment_id") == experiment_id]
    if len(found) != 1:
        raise DossierMismatch(f"{experiment_id}: expected one framing dossier under {layout.relative(layout.framing)}/, "
                              f"found {len(found)}")
    return found[0]


# --------------------------------------------------------------------------- #
# The framing dossier
# --------------------------------------------------------------------------- #
def dossier_checks(layout: Layout, registry: Any, dossier: Path, definition: dict[str, Any]) -> list[Check]:
    """Is the dossier still exactly what the registration was framed with and bound to?"""
    eid = definition["experiment_id"]
    manifest = _json(dossier / "framing.json")
    if not isinstance(manifest, dict):
        return [Check("framing.manifest", eid, FAIL, f"{layout.relative(dossier)}/framing.json is unreadable")]
    checks = []
    same = (manifest.get("experiment_id") == eid
            and manifest.get("definition_sha256") == registry_stage.definition_sha256(definition))
    checks.append(Check("framing.manifest", eid, OK if same else FAIL,
                        "registration unchanged since framing" if same else
                        "framing.json names another registration, or the registration changed since framing"))

    changed = []
    for ref in manifest.get("files", []):
        path = dossier / ref["name"]
        if not path.is_file():
            changed.append(f"{ref['name']} missing")
        elif path.stat().st_size != ref["bytes"] or provenance.sha256_file(path) != ref["sha256"]:
            changed.append(f"{ref['name']} changed")
    checks.append(Check("framing.files", eid, FAIL if changed else OK,
                        "; ".join(changed) or f"{len(manifest.get('files', []))} files match their recorded SHA-256"))

    bound = definition["parameters"].get("framing", {})
    packet = _json(dossier / "anna_record.json")
    if not isinstance(packet, dict):
        checks.append(Check("framing.anna", eid, FAIL, "anna_record.json is unreadable"))
    else:
        vendor.ensure_importable()
        from engine import records

        sealed = records.verify_record(packet, None)["fingerprint"]["matches"] is True
        bound_ok = bound.get("anna_record_sha256", packet.get("content_sha256")) == packet.get("content_sha256")
        detail = ("Anna fingerprint verifies" + ("; it is the record the registration bound" if bound else
                                                 "; the registration predates framing bindings"))
        checks.append(Check("framing.anna", eid, OK if sealed and bound_ok else FAIL,
                            detail if sealed and bound_ok else
                            ("the record no longer matches its own fingerprint" if not sealed
                             else "the record is not the one the registration bound")))

    panel = _json(dossier / "panel_summary.json")
    audited = ((panel or {}).get("citation_audit") or {}).get("corpus_sha256")
    on_disk = panel_stage.corpus_fingerprint(dossier / "corpus")
    corpus_ok = audited == on_disk and bound.get("panel_corpus_sha256", audited) == audited
    checks.append(Check("framing.corpus", eid, OK if corpus_ok else FAIL,
                        "panel corpus matches the citation audit" + (" and the binding" if bound else "")
                        if corpus_ok else "the panel's corpus files changed since the citation audit or binding"))

    lineage = definition["parameters"].get("lineage", {})
    if "parent_result_sha256" in bound:
        parent_id, run = lineage["follows"].split("/")
        parent = registry.root / parent_id / "runs" / run / "result.json"
        same = parent.is_file() and provenance.sha256_file(parent) == bound["parent_result_sha256"]
        checks.append(Check("lineage.parent", eid, OK if same else FAIL,
                            f"follows {lineage['follows']}, bound by hash" if same else
                            f"{lineage['follows']} is missing or is not the result this registration bound"))
    if "exploration_report_sha256" in bound:
        report = layout.resolve(lineage["exploration"])
        same = report.is_file() and provenance.sha256_file(report) == bound["exploration_report_sha256"]
        exploratory = same and (_json(report) or {}).get("status", "").startswith("EXPLORATORY")
        checks.append(Check("lineage.exploration", eid, OK if exploratory else FAIL,
                            f"motivated by {lineage['exploration']} (exploratory, bound by hash)" if exploratory else
                            f"{lineage['exploration']} is missing, changed, or not an exploration report"))
    return checks


def load_dossier(layout: Layout, registry: Any, dossier: Path, definition: dict[str, Any]
                 ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The dossier a run builds on, refused unless every binding still holds."""
    broken = [c for c in dossier_checks(layout, registry, dossier, definition) if c.status == FAIL]
    if broken:
        raise DossierMismatch(f"{definition['experiment_id']}: the framing dossier does not match the registration:\n  "
                              + "\n  ".join(f"{c.name}: {c.detail}" for c in broken))
    return (_json(dossier / "framing.json"), _json(dossier / "anna_record.json"),
            _json(dossier / "panel_summary.json"))


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def _guarded(name: str, subject: str, check: Callable[[], list[Check] | Check]) -> list[Check]:
    """A check that crashes is reported as broken, never allowed to abort verification."""
    try:
        result = check()
    except Exception as exc:
        return [Check(name, subject, FAIL, f"could not be checked: {type(exc).__name__}: {exc}")]
    return result if isinstance(result, list) else [result]


def _no_history(snap: Snapshot) -> str | None:
    if not snap.history.available:
        return "not a git work tree, so history cannot be checked"
    if snap.history.shallow:
        return "shallow clone: fetch full history (git fetch --unshallow) to check it"
    return None


def _holdout_ranges(snap: Snapshot, experiment_id: str) -> list[ledger.Range]:
    for dossier in snap.dossiers.get(experiment_id, []):
        manifest = _json(dossier / "framing.json") or {}
        return [(url, tuple(span)) for url, span in manifest.get("holdout_ranges", [])]
    return []


def _registration_checks(snap: Snapshot, eid: str) -> list[Check]:
    definition = snap.definitions[eid]
    checks: list[Check] = []
    relative = snap.layout.relative(snap.registry.experiment_dir(eid) / "experiment.json")

    def history() -> Check:
        missing = _no_history(snap)
        if missing:
            return Check("registration.history", eid, SKIP, missing)
        seen = registry_stage.versions(snap.history, relative)
        if not seen:
            return Check("registration.history", eid, WARN, "not committed: no timestamp proves when it was written")
        contents = {content for _, _, content in seen if content is not None}
        if len(contents) > 1:
            return Check("registration.history", eid, FAIL,
                         f"experiment.json was changed after its first commit ({len(contents)} versions)")
        if snap.history.modified_in_worktree(relative):
            return Check("registration.history", eid, FAIL, "experiment.json is edited in the working tree")
        commit, at, _ = seen[0]
        return Check("registration.history", eid, OK, f"first committed in {commit[:10]} ({at}), unchanged since")

    checks += _guarded("registration.history", eid, history)
    checks += _guarded("registration.spec", eid, lambda: _spec_check(snap, eid, definition))

    dossiers = snap.dossiers.get(eid, [])
    if len(dossiers) != 1:
        checks.append(Check("framing.manifest", eid, FAIL if dossiers or snap.runs.get(eid) else WARN,
                            f"{len(dossiers)} framing dossiers declare {eid}; expected one"))
    else:
        checks += _guarded("framing.dossier", eid,
                           lambda: dossier_checks(snap.layout, snap.registry, dossiers[0], definition))
    ranges = _holdout_ranges(snap, eid)
    if ranges and snap.ledger is not None:
        checks += _guarded("holdout.before_registration", eid, lambda: _holdout_registration(snap, eid, ranges))
        checks += _guarded("holdout.ledger_snapshot", eid, lambda: _holdout_snapshot(snap, eid, ranges))
        checks += _guarded("holdout.before_anchor", eid, lambda: _holdout_anchor(snap, eid, ranges, relative))
    return checks


def _spec_check(snap: Snapshot, eid: str, definition: dict[str, Any]) -> Check:
    dossiers = snap.dossiers.get(eid, [])
    named = (_json(dossiers[0] / "framing.json") or {}).get("spec") if dossiers else None
    candidates = [snap.layout.resolve(named)] if named else sorted(snap.layout.specs.glob("*.json"))
    for path in candidates:
        spec = _json(path) if path.is_file() else None
        if not isinstance(spec, dict) or not isinstance(spec.get("preregistration"), dict):
            continue
        if spec["preregistration"].get("title") != definition["title"]:
            if named:
                return Check("registration.spec", eid, WARN, f"{named} now carries another title; "
                             "the registration, not the spec, is authoritative")
            continue
        changed = registry_stage.drift(definition, spec)
        where = snap.layout.relative(path)
        if changed:
            return Check("registration.spec", eid, FAIL, f"{where} was edited after registration "
                         f"({', '.join(changed)}); a run would refuse it. Restore it, or retitle it as a new experiment")
        return Check("registration.spec", eid, OK, f"{where} still says exactly what was registered")
    return Check("registration.spec", eid, WARN, "no spec file matches it any more; the registration is authoritative")


def _holdout_registration(snap: Snapshot, eid: str, ranges: list[ledger.Range]) -> Check:
    early = ledger.bytes_read_before(snap.ledger, ranges, snap.definitions[eid]["created_at"])
    total = sum(b - a + 1 for _, (a, b) in ranges)
    return Check("holdout.before_registration", eid, FAIL if early else OK,
                 f"{early:,} of {total:,} holdout bytes were first read before the registration")


def _holdout_snapshot(snap: Snapshot, eid: str, ranges: list[ledger.Range]) -> Check:
    holdout = (snap.definitions[eid]["parameters"].get("framing") or {}).get("holdout", {})
    if "ledger_sha256" not in holdout:
        return Check("holdout.ledger_snapshot", eid, WARN, "the registration bound no ledger snapshot")
    bound = holdout["ledger_sha256"]
    if bound is None:
        return Check("holdout.ledger_snapshot", eid, OK, "no ledger existed at registration: nothing had been read")
    missing = _no_history(snap)
    if missing:
        return Check("holdout.ledger_snapshot", eid, SKIP, missing)
    relative = snap.layout.relative(snap.layout.ledger)
    for commit, _, content in registry_stage.versions(snap.history, relative):
        if content is not None and provenance.sha256_bytes(content) == bound:
            earlier = ledger.parse(content.decode("utf-8"), f"{relative}@{commit[:10]}")
            problems = ledger.extends(earlier, snap.ledger)
            if problems:
                return Check("holdout.ledger_snapshot", eid, FAIL,
                             "the ledger lost or changed entries since registration: " + "; ".join(problems[:5]))
            if ledger.overlap(ranges, [(e["url"], tuple(e["byte_range"])) for e in earlier["entries"]]):
                return Check("holdout.ledger_snapshot", eid, FAIL, "the bound ledger snapshot already shows holdout reads")
            return Check("holdout.ledger_snapshot", eid, OK,
                         f"the ledger bound at registration is committed ({commit[:10]}), shows no holdout read, "
                         "and the current ledger only extends it")
    return Check("holdout.ledger_snapshot", eid, WARN,
                 "the ledger bound at registration was never committed, so continuity since then rests on the "
                 "full-history append-only check")


def _holdout_anchor(snap: Snapshot, eid: str, ranges: list[ledger.Range], relative: str) -> Check:
    missing = _no_history(snap)
    if missing:
        return Check("holdout.before_anchor", eid, SKIP, missing)
    seen = registry_stage.versions(snap.history, relative)
    if not seen:
        return Check("holdout.before_anchor", eid, WARN, "the registration is not committed, so it has no anchor")
    commit, at, _ = seen[0]
    early = ledger.bytes_read_before(snap.ledger, ranges, registry_stage.anchor_cutoff(at))
    return Check("holdout.before_anchor", eid, FAIL if early else OK,
                 f"{early:,} holdout bytes were first read before the anchor commit {commit[:10]} ({at})")


def _run_checks(snap: Snapshot, eid: str, record: dict[str, Any]) -> list[Check]:
    run_id = record["run_id"]
    definition = snap.definitions[eid]
    submission_path = snap.submissions.get((record.get("provenance") or {}).get("submission_sha256"))
    checks = _guarded("run.submission", run_id, lambda: _submission_check(snap, record, submission_path))
    checks += _guarded("run.artifacts", run_id, lambda: _artifact_check(snap, record))
    if submission_path:
        checks += _guarded("run.summary", run_id, lambda: _summary_check(snap, record, submission_path.parent))
        checks += _guarded("run.report", run_id, lambda: _report_check(snap, record, submission_path.parent))
    checks += _guarded("run.timing", run_id, lambda: _timing_check(definition, record))
    checks += _guarded("run.data", run_id, lambda: _data_check(snap, record))
    checks += _guarded("run.anchor", run_id, lambda: _anchor_check(snap, eid, record))
    checks += _guarded("run.published", run_id, lambda: _published_check(record))
    checks += _guarded("run.code", run_id, lambda: _code_check(snap, record))
    return checks


def _submission_check(snap: Snapshot, record: dict[str, Any], submission_path: Path | None) -> Check:
    if submission_path is None:
        return Check("run.submission", record["run_id"], FAIL,
                     "no submission under runs/ hashes to the recorded submission_sha256")
    diverged = registry_stage.record_divergence(record, _json(submission_path))
    return Check("run.submission", record["run_id"], FAIL if diverged else OK,
                 f"the record's {', '.join(diverged)} differ from the submission it was made from" if diverged else
                 f"{snap.layout.relative(submission_path)} is the submission R.A.I.N. recorded, and the record "
                 "still says what it said")


def _artifact_check(snap: Snapshot, record: dict[str, Any]) -> Check:
    problems, checked = [], 0
    for artifact in record["artifacts"]:
        if artifact.get("stored"):
            continue  # stored artifacts are R.A.I.N.'s to verify
        uri = artifact.get("uri")
        path = snap.layout.resolve(uri) if uri else None
        checked += 1
        if path is None or not path.is_file():
            problems.append(f"{uri or artifact['name']} missing")
        elif path.stat().st_size != artifact["bytes"] or provenance.sha256_file(path) != artifact["sha256"]:
            problems.append(f"{uri} changed")
    return Check("run.artifacts", record["run_id"], FAIL if problems else OK,
                 "; ".join(problems) or f"{checked} artifacts match their recorded SHA-256")


def _summary_check(snap: Snapshot, record: dict[str, Any], run_dir: Path) -> Check:
    summary = _json(run_dir / "summary.json")
    if summary is None:
        return Check("run.summary", record["run_id"], WARN, "summary.json is missing")
    same = (summary.get("run_id") == record["run_id"] and summary.get("status") == record["status"]
            and summary.get("verdict") == record["hypothesis_verdict"]
            and summary.get("measurements") == record["measurements"])
    return Check("run.summary", record["run_id"], OK if same else FAIL,
                 "summary.json agrees with the R.A.I.N. record" if same else
                 "summary.json disagrees with the R.A.I.N. record (run, status, verdict or measurements)")


def _report_check(snap: Snapshot, record: dict[str, Any], run_dir: Path) -> Check:
    path = run_dir / "REPORT.md"
    if not path.is_file():
        return Check("run.report", record["run_id"], WARN, "REPORT.md is missing")
    # Since 0.2 the heading is "# <run>: <STATUS>"; 0.1 prefixed the experiment ID. Either must state this outcome.
    heading = (path.read_text(encoding="utf-8").splitlines() or [""])[0]
    states = (heading.startswith("# ") and f"{record['run_id']}:" in heading.split()
              and heading.endswith(f": {record['status'].upper()}"))
    return Check("run.report", record["run_id"], OK if states else FAIL,
                 "REPORT.md states the recorded outcome" if states else
                 f"REPORT.md opens with {heading!r}, which is not {record['run_id']}: {record['status'].upper()}")


def _timing_check(definition: dict[str, Any], record: dict[str, Any]) -> Check:
    created, started = ledger.parse_time(definition["created_at"]), ledger.parse_time(record["started_at"])
    return Check("run.timing", record["run_id"], OK if created <= started else FAIL,
                 "the registration existed before the run started" if created <= started else
                 "the run started before its registration existed")


def _data_check(snap: Snapshot, record: dict[str, Any]) -> Check:
    files = ((record.get("inputs") or {}).get("dataset") or {}).get("files")
    if not files:
        return Check("run.data", record["run_id"], WARN if record["status"] == "error" else FAIL,
                     "the run records no dataset files")
    if snap.ledger is None:
        return Check("run.data", record["run_id"], SKIP, "the ledger is unreadable")
    problems = []
    for item in files:
        span = tuple(item["byte_range"])
        exact = ledger.entry_for(snap.ledger, item["url"], span)
        if exact is not None and exact["sha256"] != item["sha256"]:
            problems.append(f"{item['record']}: content differs from the ledger")
        elif exact is None and ledger.bytes_unseen(snap.ledger, [(item["url"], span)]):
            problems.append(f"{item['record']}: bytes the ledger never logged")
    return Check("run.data", record["run_id"], FAIL if problems else OK,
                 "; ".join(problems) or f"{len(files)} byte ranges logged in the ledger with identical content")


def _anchor_check(snap: Snapshot, eid: str, record: dict[str, Any]) -> Check:
    anchor = ((record.get("inputs") or {}).get("registration") or {}).get("git")
    if not anchor:
        return Check("run.anchor", record["run_id"], WARN, "the registration was not anchored in git before this run")
    missing = _no_history(snap)
    if missing:
        return Check("run.anchor", record["run_id"], SKIP, missing)
    commit = anchor["commit"]
    if not snap.history.exists(commit):
        return Check("run.anchor", record["run_id"], FAIL, f"anchor commit {commit[:10]} is not in this repository")
    relative = snap.layout.relative(snap.registry.experiment_dir(eid) / "experiment.json")
    content = snap.history.show(commit, relative)
    holds = content is not None and registry_stage.definition_sha256(json.loads(content)) == record["definition_sha256"]
    in_history = snap.history.is_ancestor(commit)
    timely = ledger.parse_time(snap.history.committed_at(commit)) <= ledger.parse_time(record["started_at"])
    problems = [text for good, text in ((holds, "it does not hold this registration"),
                                        (in_history, "it is not in the history of HEAD"),
                                        (timely, "it was committed after the run started")) if not good]
    return Check("run.anchor", record["run_id"], FAIL if problems else OK,
                 f"anchor {commit[:10]}: " + ("; ".join(problems) if problems else
                                             "holds the registration, is in history, and predates the run"))


def _published_check(record: dict[str, Any]) -> list[Check]:
    """Was the anchor on a remote when the run started? Only a push is witnessed by anyone but this machine."""
    anchor = ((record.get("inputs") or {}).get("registration") or {}).get("git")
    if not anchor:
        return []  # run.anchor already says there was no anchor at all
    pushed = anchor.get("pushed_to") or []
    return [Check("run.published", record["run_id"], OK if pushed else WARN,
                  f"the anchor was on {', '.join(pushed)} when the run started" if pushed else
                  "the anchor had not been pushed when the run started, so its time rests on one machine's clock")]


def _code_check(snap: Snapshot, record: dict[str, Any]) -> Check:
    code = ((record.get("inputs") or {}).get("code") or {}).get("pipeline") or {}
    digest = code.get("source_sha256")
    if not digest:
        return Check("run.code", record["run_id"], WARN, "the run records no pipeline source digest")
    missing = _no_history(snap)
    if missing:
        return Check("run.code", record["run_id"], SKIP, missing)
    commit = provenance.resolve_source_commit(snap.history, digest)
    return Check("run.code", record["run_id"], OK if commit else WARN,
                 f"rain-pipeline {code.get('version')} source is commit {commit[:10]}" if commit else
                 f"source {digest[:12]} is in no commit: the run used uncommitted code")


def _ledger_checks(snap: Snapshot) -> list[Check]:
    subject = snap.layout.relative(snap.layout.ledger)
    if snap.ledger is None:
        return [Check("ledger.schema", subject, FAIL, snap.ledger_error or "unreadable")]
    checks = [Check("ledger.schema", subject, OK, f"{len(snap.ledger['entries'])} well-formed entries")]

    def history() -> Check:
        missing = _no_history(snap)
        if missing:
            return Check("ledger.history", subject, SKIP, missing)
        problems, versions = [], 0
        previous = None
        for commit, _, content in registry_stage.versions(snap.history, subject):
            if content is None:
                continue
            current = ledger.parse(content.decode("utf-8"), f"{subject}@{commit[:10]}")
            if previous is not None:
                problems += [f"{commit[:10]}: {p}" for p in ledger.extends(previous, current)]
            previous, versions = current, versions + 1
        if previous is not None:
            problems += [f"working tree: {p}" for p in ledger.extends(previous, snap.ledger)]
        return Check("ledger.history", subject, FAIL if problems else OK,
                     "; ".join(problems[:5]) or f"append-only across {versions} committed versions and the working tree")

    checks += _guarded("ledger.history", subject, history)
    consumed: dict[str, list[ledger.Range]] = {}
    for eid, records in snap.runs.items():
        for record in records:
            for item in ((record.get("inputs") or {}).get("dataset") or {}).get("files") or []:
                consumed.setdefault(eid, []).append((item["url"], tuple(item["byte_range"])))
    unaccounted, foreign = [], []
    for entry in snap.ledger["entries"]:
        reader, span = entry["first_read_by"], (entry["url"], tuple(entry["byte_range"]))
        if reader == "exploration":
            foreign.append(f"{entry['url'].rsplit('/', 1)[-1]} {entry['byte_range']}")
        elif reader in snap.definitions:
            if ledger.overlap([span], consumed.get(reader, [])) != span[1][1] - span[1][0] + 1:
                unaccounted.append(f"{reader}: {entry['url'].rsplit('/', 1)[-1]} {entry['byte_range']}")
        else:
            unaccounted.append(f"{reader!r}: {entry['url'].rsplit('/', 1)[-1]} {entry['byte_range']}")
    if foreign:
        checks.append(Check("ledger.accounted", subject, FAIL,
                            "an exploration is recorded as the first reader of: " + ", ".join(foreign[:5])))
    else:
        checks.append(Check("ledger.accounted", subject, WARN if unaccounted else OK,
                            "first read, but consumed by no recorded run (an interrupted run?): "
                            + "; ".join(unaccounted[:5]) if unaccounted else
                            "every first read belongs to a recorded run of the experiment that made it"))
    return checks


def _exploration_checks(snap: Snapshot, path: Path) -> list[Check]:
    subject = snap.layout.relative(path.parent)
    report = _json(path)
    if not isinstance(report, dict):
        return [Check("exploration.label", subject, FAIL, "report.json is unreadable")]
    labelled = report.get("status") == EXPLORATORY
    checks = [Check("exploration.label", subject, OK if labelled else FAIL,
                    "labelled exploratory: not evidence" if labelled else "not labelled as exploratory")]
    match = _STAMP.match(path.parent.name)
    if snap.ledger is None or not match:
        return checks + [Check("exploration.data", subject, SKIP, "no ledger, or no time in the directory name")]
    began = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) + timedelta(seconds=1)
    problems = []
    for item in report.get("dataset_files", []):
        span = (item["url"], tuple(item["byte_range"]))
        earlier = [e for e in snap.ledger["entries"] if e["url"] == item["url"]
                   and ledger.parse_time(e["first_read_at"]) < began]
        if ledger.overlap([span], [(e["url"], tuple(e["byte_range"])) for e in earlier]) != span[1][1] - span[1][0] + 1:
            problems.append(f"{item['record']}: not all bytes were seen before the exploration")
        exact = ledger.entry_for(snap.ledger, *span)
        if exact is not None and exact["sha256"] != item["sha256"]:
            problems.append(f"{item['record']}: content differs from the ledger")
    checks.append(Check("exploration.data", subject, FAIL if problems else OK,
                        "; ".join(problems[:5]) or f"{len(report.get('dataset_files', []))} ranges, all seen before"))
    return checks


def _unrecorded_checks(snap: Snapshot) -> list[Check]:
    """Attempts with no R.A.I.N. record stay visible: a run directory nothing refers to, a dossier for nothing."""
    referenced = {path.parent for sha, path in snap.submissions.items()
                  if any((r.get("provenance") or {}).get("submission_sha256") == sha
                         for records in snap.runs.values() for r in records)}
    for records in snap.runs.values():
        for record in records:
            for artifact in record["artifacts"]:
                if artifact.get("uri"):
                    referenced.add(snap.layout.resolve(artifact["uri"]).parent)
    checks = []
    for run_dir in sorted(p for p in snap.layout.runs.glob("*") if p.is_dir()):
        if run_dir not in referenced:
            note = next((n for n in ("CRASHED.txt", "error.txt") if (run_dir / n).is_file()), None)
            first = ((run_dir / note).read_text(encoding="utf-8").strip().splitlines() or [""])[0] if note else ""
            checks.append(Check("runs.unrecorded", snap.layout.relative(run_dir), WARN,
                                "an attempt with no R.A.I.N. record" + (f" ({note}: {first})" if note else "")))
    for dossier in sorted(p for p in snap.layout.framing.glob("*") if p.is_dir()):
        manifest = _json(dossier / "framing.json")
        if not isinstance(manifest, dict) or manifest.get("experiment_id") not in snap.definitions:
            checks.append(Check("framing.unregistered", snap.layout.relative(dossier), WARN,
                                "a framing dossier no registration refers to (a registration that never completed?)"))
    return checks


def _results_check(snap: Snapshot) -> Check:
    subject = snap.layout.relative(snap.layout.results)
    expected = registry_stage.render_results(snap.registry)
    actual = snap.layout.results.read_text(encoding="utf-8") if snap.layout.results.is_file() else None
    return Check("results.page", subject, OK if actual == expected else FAIL,
                 "matches the page R.A.I.N. renders from the registry" if actual == expected else
                 ("missing" if actual is None else "differs from the page R.A.I.N. renders from the registry "
                  "(edited by hand, or stale: run `python -m rain_pipeline publish`)"))


def _receipt_checks(snap: Snapshot, path: Path) -> Check:
    subject = snap.layout.relative(path)
    receipt = _json(path)
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        return Check("receipt.binding", subject, FAIL, f"not a {RECEIPT_SCHEMA}")
    replayed = receipt["replayed"]
    result_path = snap.result_paths.get(replayed["run_id"])
    if result_path is None:
        return Check("receipt.binding", subject, FAIL, f"{replayed['run_id']} is not recorded")
    problems = []
    if provenance.sha256_file(result_path) != replayed["result_sha256"]:
        problems.append("the run record changed since the replay")
    if outcome_of(receipt["comparison"]) != receipt["outcome"]:
        problems.append(f"its comparison implies {outcome_of(receipt['comparison'])!r}, not {receipt['outcome']!r}")
    return Check("receipt.binding", subject, FAIL if problems else OK,
                 "; ".join(problems) or f"{replayed['run_id']}: {receipt['outcome']}")


def outcome_of(comparison: dict[str, Any]) -> str:
    """A replay's outcome follows from its comparison alone (never asserted separately).

    It is graded by the same line the protocol draws everywhere: registered
    measurements are evidence; series and the study report are description.
    No numeric tolerance is involved; the receipt records every difference.
    """
    if comparison.get("error"):
        return "error"
    if comparison["status"]["recorded"] != comparison["status"]["replayed"] or \
            comparison["verdict"]["recorded"] != comparison["verdict"]["replayed"]:
        return "verdict-differs"
    if comparison.get("data_identical") is False or \
            not all(m["identical"] for m in comparison["measurements"].values()):
        return "verdict-reproduced"
    descriptive = (all(s["identical"] for s in comparison["series"].values())
                   and (comparison.get("report") is None or comparison["report"]["identical"]))
    return "reproduced" if descriptive else "measurements-reproduced"


OUTCOMES = {
    "reproduced": "every registered measurement, series value and study-report value identical; same verdict",
    "measurements-reproduced": "every registered measurement identical and the same verdict; some descriptive "
                               "values (series or study report) differ, by the amount the receipt records",
    "verdict-reproduced": "the same verdict, but some registered measurement differs",
    "verdict-differs": "R.A.I.N. reaches another status on the replayed measurements",
    "error": "the replay could not complete",
}


# --------------------------------------------------------------------------- #
# Verify, claims, graph
# --------------------------------------------------------------------------- #
def verify(layout: Layout) -> Report:
    snap = snapshot(layout)
    rain = registry_stage.verify(snap.registry)
    registry_subject = snap.layout.relative(layout.experiments)
    checks = [Check("rain.verify", registry_subject, OK if rain["valid"] else FAIL,
                    f"R.A.I.N. re-derived {rain['runs']} run(s) of {rain['experiments']} experiment(s) from stored data"
                    if rain["valid"] else f"{len(rain['problems'])} problem(s), listed below")]
    checks += [Check("rain.verify", registry_subject, FAIL, problem) for problem in rain["problems"]]
    checks += [Check("rain.verify", registry_subject, WARN, warning) for warning in rain["warnings"]]
    for eid in sorted(snap.definitions):
        checks += _registration_checks(snap, eid)
        for record in snap.runs.get(eid, []):
            if record.get("status") != "running":
                checks += _run_checks(snap, eid, record)
    checks += _ledger_checks(snap)
    checks += _guarded("runs.unrecorded", snap.layout.relative(layout.runs), lambda: _unrecorded_checks(snap))
    for path in snap.explorations:
        checks += _guarded("exploration", snap.layout.relative(path.parent), lambda p=path: _exploration_checks(snap, p))
    checks += _guarded("results.page", snap.layout.relative(layout.results), lambda: _results_check(snap))
    for path in snap.receipts:
        checks += _guarded("receipt.binding", snap.layout.relative(path), lambda p=path: _receipt_checks(snap, p))
    return Report(checks=checks, claims=claims(snap, checks), rain=rain)


def _receipt_outcomes(snap: Snapshot) -> dict[str, list[dict[str, str]]]:
    found: dict[str, list[dict[str, str]]] = {}
    for path in snap.receipts:
        receipt = _json(path)
        if isinstance(receipt, dict) and receipt.get("schema") == RECEIPT_SCHEMA:
            found.setdefault(receipt["replayed"]["run_id"], []).append(
                {"receipt": snap.layout.relative(path), "outcome": receipt["outcome"],
                 "replayed_at": receipt["replayed_at"], "platform": receipt["environment"]["platform"]})
    return found


def claims(snap: Snapshot, checks: list[Check]) -> list[dict[str, Any]]:
    """One entry per run: its R.A.I.N. verdict, and how strongly the chain beneath it holds."""
    replays = _receipt_outcomes(snap)
    shared = holdout_families(snap)
    out = []
    for eid in sorted(snap.definitions):
        definition = snap.definitions[eid]
        holdout = bool(definition["parameters"]["data"].get("holdout"))
        for record in snap.runs.get(eid, []):
            run_id = record["run_id"]
            mine = [c for c in checks if c.subject in (eid, run_id)]
            failed = [f"{c.name}: {c.detail}" for c in mine if c.status == FAIL]
            anchored = any(c.name == "run.anchor" and c.status == OK and c.subject == run_id for c in mine)
            published = any(c.name == "run.published" and c.status == OK and c.subject == run_id for c in mine)
            holdout_clean = holdout and all(c.status == OK for c in mine if c.name.startswith("holdout."))
            level = ("unverified" if failed else "confirmatory" if anchored and published and holdout_clean
                     else "preregistered" if anchored else "registered")
            out.append({
                "experiment_id": eid, "run_id": run_id, "title": definition["title"],
                "status": record["status"], "verdict": record["hypothesis_verdict"],
                "assigned_by": "R.A.I.N. " + ((record.get("evaluation") or {}).get("rule") or "(not evaluated)"),
                "evidence_level": level, "meaning": LEVELS[level], "broken_links": failed,
                "weaker_links": [f"{c.name}: {c.detail}" for c in mine if c.status == WARN],
                "data": _novelty(snap, eid),
                "code": _code_of(snap, record),
                "shares_holdout_with": sorted({e for family in shared if eid in family for e in family} - {eid}),
                "replays": replays.get(run_id, []),
            })
    return out


def _code_of(snap: Snapshot, record: dict[str, Any]) -> dict[str, Any]:
    code = ((record.get("inputs") or {}).get("code") or {}).get("pipeline") or {}
    digest = code.get("source_sha256")
    commit = provenance.resolve_source_commit(snap.history, digest) if digest and not _no_history(snap) else None
    return {"version": code.get("version"), "source_sha256": digest, "commit": commit}


def _novelty(snap: Snapshot, eid: str) -> dict[str, Any]:
    """New data is not new subjects: which of this experiment's records earlier experiments already analysed."""
    definition = snap.definitions[eid]
    records = definition["parameters"]["data"]["records"]
    earlier = {r for other, d in snap.definitions.items() if d["created_at"] < definition["created_at"]
               and snap.runs.get(other) for r in d["parameters"]["data"]["records"]}
    return {"records": len(records), "records_analysed_by_earlier_experiments": sorted(set(records) & earlier),
            "held_out": bool(definition["parameters"]["data"].get("holdout"))}


def holdout_families(snap: Snapshot) -> list[list[str]]:
    """Experiments judged on overlapping holdout bytes: each is evaluated alone, with no correction across them."""
    ranges = {eid: _holdout_ranges(snap, eid) for eid in snap.definitions}
    families: list[set[str]] = []
    for eid, mine in ranges.items():
        if not mine:
            continue
        joined = {eid} | {other for other, theirs in ranges.items() if other != eid and theirs
                          and ledger.overlap(mine, theirs)}
        for family in [f for f in families if f & joined]:
            joined |= family
            families.remove(family)
        families.append(joined)
    return sorted(sorted(f) for f in families if len(f) > 1)


def graph(layout: Layout) -> dict[str, Any]:
    """The evidence chain as nodes and edges, derived from committed files only.

    Every node that stands for content carries its SHA-256, so the document can
    be checked independently, and ``digest`` (the canonical SHA-256 of nodes and
    edges) identifies the evidence state regardless of code or prose changes.
    """
    snap = snapshot(layout)
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(node_id: str, kind: str, role: str, **attrs: Any) -> str:
        """Add a node, or fill in attributes another reference to it did not know (first kind and role win)."""
        current = nodes.setdefault(node_id, {"id": node_id, "kind": kind, "role": role})
        current.update({k: v for k, v in attrs.items() if v is not None and k not in current})
        return node_id

    def file_node(path: Path, kind: str, role: str, recorded: str | None = None) -> str | None:
        """A file, identified by the SHA-256 of its bytes on disk (or its recorded hash, marked missing)."""
        if not path.is_file():
            if recorded is None:
                return None
            return node(f"file:{layout.relative(path)}", kind, role, sha256=recorded, missing=True)
        return node(f"file:{layout.relative(path)}", kind, role, sha256=provenance.sha256_file(path))

    def data_node(url: str, span: list[int] | tuple[int, int]) -> str:
        entry = ledger.entry_for(snap.ledger, url, span) if snap.ledger else None
        return node(f"data:{url}#{span[0]}-{span[1]}", "data-range", "input", sha256=(entry or {}).get("sha256"),
                    first_read_at=(entry or {}).get("first_read_at"), first_read_by=(entry or {}).get("first_read_by"))

    for path in snap.explorations:
        report = _json(path) or {}
        exploration = node(f"exploration:{layout.relative(path.parent)}", "exploration", "observation (not evidence)",
                           sha256=provenance.sha256_file(path), question=report.get("question"))
        for item in report.get("dataset_files", []):
            edges.add((exploration, "consumed", data_node(item["url"], item["byte_range"])))
        code = (report.get("code") or {}).get("pipeline") or {}
        if code.get("source_sha256"):
            edges.add((exploration, "executed", node(f"code:{code['source_sha256']}", "code", "implementation",
                                                     version=code.get("version"))))

    for eid, definition in sorted(snap.definitions.items()):
        registration = node(f"registration:{eid}", "registration", "criteria", title=definition["title"],
                            created_at=definition["created_at"],
                            definition_sha256=registry_stage.definition_sha256(definition),
                            holdout=bool(definition["parameters"]["data"].get("holdout")))
        lineage = definition["parameters"].get("lineage", {})
        if "follows" in lineage:
            parent_eid, run = lineage["follows"].split("/")
            edges.add((registration, "follows", f"run:{parent_eid}-{run}"))
        if "exploration" in lineage:
            report = layout.resolve(lineage["exploration"]).parent
            edges.add((registration, "motivated_by", f"exploration:{layout.relative(report)}"))
        for dossier in snap.dossiers.get(eid, []):
            manifest = _json(dossier / "framing.json") or {}
            if manifest.get("spec"):
                spec = file_node(layout.resolve(manifest["spec"]), "spec", "intent")
                if spec:
                    edges.add((registration, "specified_by", spec))
            for ref in manifest.get("files", []):
                target = file_node(dossier / ref["name"], "framing", "context (not evidence)")
                if target:
                    edges.add((registration, "binds", target))
            corpus = node(f"corpus:{layout.relative(dossier / 'corpus')}", "panel-corpus", "context (not evidence)",
                          sha256=panel_stage.corpus_fingerprint(dossier / "corpus"))
            edges.add((registration, "binds", corpus))
            for url, span in manifest.get("holdout_ranges", []):
                edges.add((registration, "reserves", data_node(url, span)))
        for record in snap.runs.get(eid, []):
            run_id = record["run_id"]
            run = node(f"run:{run_id}", "run", "measurement", sha256=provenance.sha256_file(snap.result_paths[run_id]),
                       submission_sha256=(record.get("provenance") or {}).get("submission_sha256"),
                       started_at=record.get("started_at"), finished_at=record.get("finished_at"))
            edges.add((run, "tests", registration))
            verdict = node(f"verdict:{run_id}", "verdict", "evaluation", status=record["status"],
                           hypothesis_verdict=record["hypothesis_verdict"],
                           rule=(record.get("evaluation") or {}).get("rule"))
            edges.add((verdict, "evaluates", run))
            inputs = record.get("inputs") or {}
            for item in (inputs.get("dataset") or {}).get("files") or []:
                edges.add((run, "consumed", data_node(item["url"], item["byte_range"])))
            anchor = (inputs.get("registration") or {}).get("git")
            if anchor:
                edges.add((run, "anchored_by", node(f"commit:{anchor['commit']}", "git-commit", "temporal anchor",
                                                    committed_at=anchor.get("committed_at"),
                                                    pushed_before_run_to=anchor.get("pushed_to"))))
            code = (inputs.get("code") or {}).get("pipeline") or {}
            if code.get("source_sha256"):
                edges.add((run, "executed", node(f"code:{code['source_sha256']}", "code", "implementation",
                                                 version=code.get("version"))))
            for artifact in record["artifacts"]:
                if artifact.get("uri"):
                    target = file_node(layout.resolve(artifact["uri"]), artifact["kind"], "artifact",
                                       recorded=artifact["sha256"])
                    edges.add((run, "produced", target))

    for path in snap.receipts:
        receipt = _json(path)
        if isinstance(receipt, dict) and receipt.get("schema") == RECEIPT_SCHEMA:
            edges.add((node(f"receipt:{layout.relative(path)}", "replay-receipt", "reproduction",
                            sha256=provenance.sha256_file(path), outcome=receipt["outcome"]),
                       "replays", f"run:{receipt['replayed']['run_id']}"))

    body = {"nodes": sorted(nodes.values(), key=lambda n: n["id"]),
            "edges": [{"from": a, "relation": r, "to": b} for a, r, b in sorted(edges)]}
    return {"schema": GRAPH_SCHEMA, "digest": provenance.canonical_sha256(body),
            "families": [{"kind": "shared-holdout", "experiments": family,
                          "note": "judged on overlapping held-out bytes; each evaluated on its own criteria, "
                                  "with no correction across them"} for family in holdout_families(snap)],
            **body}


# --------------------------------------------------------------------------- #
# Human-readable views
# --------------------------------------------------------------------------- #
def render_checks(report: Report) -> str:
    lines = []
    for check in report.checks:
        mark = {OK: "ok  ", FAIL: "FAIL", WARN: "warn", SKIP: "skip"}[check.status]
        lines.append(f"{mark}  {check.name:<28} {check.subject:<30} {check.detail}")
    lines += ["", "Claims (verdicts are R.A.I.N.'s; levels follow from the checks above):"]
    for claim in report.claims:
        lines.append(f"  {claim['run_id']:<24} {claim['status'].upper():<13} {claim['evidence_level']}")
    counts = report.counts()
    lines += ["", f"{counts[OK]} ok, {counts[FAIL]} failed, {counts[WARN]} warnings, {counts[SKIP]} skipped"
              + ("" if report.ok else "  -- the evidence chain is broken")]
    return "\n".join(lines)


def describe(report: Report, graph_doc: dict[str, Any]) -> str:
    """The lineage of every claim, as a reader would want to audit it."""
    nodes = {n["id"]: n for n in graph_doc["nodes"]}
    edges = graph_doc["edges"]

    def targets(source: str, relation: str) -> list[str]:
        return [e["to"] for e in edges if e["from"] == source and e["relation"] == relation]

    lines = [f"Evidence graph {graph_doc['digest'][:16]}  ({len(nodes)} nodes, {len(edges)} edges, derived from "
             "committed records; `lineage --json` prints it in full)", ""]
    for claim in report.claims:
        eid, run_id = claim["experiment_id"], claim["run_id"]
        registration = nodes.get(f"registration:{eid}", {})
        lines.append(f"{eid}  {claim['title']}")
        lines.append(f"  verdict      {claim['status'].upper()} ({claim['verdict'].replace('_', ' ')}), "
                     f"assigned by {claim['assigned_by']}")
        lines.append(f"  evidence     {claim['evidence_level']}: {claim['meaning']}")
        lines.append(f"  registered   {registration.get('created_at')}, definition sha256 "
                     f"{str(registration.get('definition_sha256'))[:16]}")
        for commit in targets(f"run:{run_id}", "anchored_by"):
            pushed = nodes[commit].get("pushed_before_run_to") or []
            lines.append(f"  anchored     {commit.split(':', 1)[1][:10]} ({nodes[commit].get('committed_at')}); "
                         + (f"pushed to {', '.join(pushed)} before the run" if pushed else "not pushed before the run"))
        for parent in targets(f"registration:{eid}", "follows"):
            lines.append(f"  follows      {parent.split(':', 1)[1]}")
        for exploration in targets(f"registration:{eid}", "motivated_by"):
            lines.append(f"  motivated by {exploration.split(':', 1)[1]} (exploratory, not evidence)")
        data = claim["data"]
        earlier = data["records_analysed_by_earlier_experiments"]
        lines.append(f"  data         {data['records']} records, {'held out' if data['held_out'] else 'not held out'}"
                     + (f"; new data, not new subjects ({len(earlier)} of {data['records']} records analysed "
                        "by earlier experiments)" if earlier else ""))
        if claim["shares_holdout_with"]:
            lines.append(f"  shares data  with {', '.join(claim['shares_holdout_with'])}: each judged on its own "
                         "criteria, with no correction across them")
        code = claim["code"]
        if code["source_sha256"]:
            lines.append(f"  code         rain-pipeline {code['version']}, source {code['source_sha256'][:16]}"
                         + (f" = commit {code['commit'][:10]}" if code["commit"] else " (in no commit)"))
        artifacts = targets(f"run:{run_id}", "produced")
        lines.append(f"  run          {run_id}: {len(artifacts)} artifacts, "
                     f"{len(targets(f'run:{run_id}', 'consumed'))} data ranges")
        for replay in claim["replays"]:
            lines.append(f"  replayed     {replay['outcome']} on {replay['platform']} ({replay['replayed_at'][:10]}): "
                         f"{replay['receipt']}")
        for link in claim["broken_links"]:
            lines.append(f"  BROKEN       {link}")
        for link in claim["weaker_links"]:
            lines.append(f"  weaker       {link}")
        lines.append("")
    explorations = [n for n in nodes.values() if n["kind"] == "exploration"]
    if explorations:
        lines.append("Explorations (observations on seen data, never evidence)")
        for node in explorations:
            motivated = sorted(e["from"].split(":", 1)[1] for e in edges
                               if e["to"] == node["id"] and e["relation"] == "motivated_by")
            lines.append(f"  {node['id'].split(':', 1)[1]}" + (f"  -> motivated {', '.join(motivated)}" if motivated else ""))
    return "\n".join(lines).rstrip() + "\n"
