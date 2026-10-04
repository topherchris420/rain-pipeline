"""R.A.I.N. experiment registry: register once, anchor in git, submit, publish.

An experiment is registered as an *external* experiment
(``rain-experiment/v1``). A registration is write-once: if the spec no longer
matches the stored definition, the pipeline refuses to run rather than
silently move the goalposts.

The registration also *binds its framing*: hashes of the literature record,
the panel's corpus, the parent result it follows from and the holdout proof go
into ``parameters.framing``, so none of them can be swapped afterwards.

Before a run reads data, the registration must be committed to git. The
*first* commit that holds it is its anchor, the timestamp that proves the
criteria came first, and every later commit must hold the identical file:
a registration edited in history is no longer anchored.

Results come back as a ``rain-experiment-submission/v1``, which deliberately
has no status field. R.A.I.N.'s ``evaluate`` assigns passed / failed /
inconclusive from the pre-registered criteria; this module never does.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import provenance, vendor
from .errors import ProtocolRefusal

_ASSIGNED = ("schema_version", "experiment_id", "experiment_version", "created_at")


class NotAnchored(ProtocolRefusal):
    """The registration is not committed to git as first written, so nothing proves it came before the data."""


def _rain():
    vendor.ensure_importable()
    from james_library import experiments
    from james_library.experiments import evaluate, results, schema, verify

    return experiments, results, schema, verify, evaluate


def experiment_error() -> type[Exception]:
    """R.A.I.N.'s refusal type (the host would not accept a definition, record or request)."""
    return _rain()[0].ExperimentError


def open_registry(root: Path, results_path: Path | None = None):
    """R.A.I.N.'s registry at ``root``. Opening it writes nothing; R.A.I.N. creates directories on first use."""
    experiments, *_ = _rain()
    return experiments.Registry(root=root, results_path=results_path or root.parent / "RESULTS.md")


def draft_from_spec(spec: dict[str, Any], framing: dict[str, Any] | None = None) -> dict[str, Any]:
    """The registration is bound to exactly what will run: data and analysis settings."""
    drr_repo = vendor.REPOSITORIES["drr"][0]
    parameters = {"data": spec["data"], "analysis": spec["analysis"]}
    if "lineage" in spec:
        parameters["lineage"] = spec["lineage"]
    if framing is not None:
        parameters["framing"] = framing
    return {
        **spec["preregistration"],
        "runner": {
            "kind": "external",
            "repository": drr_repo,
            "adapter": "rain-pipeline: Anna -> R.A.I.N. -> DRR (rain-experiment-submission/v1)",
        },
        "subsystem": {"repository": drr_repo, "component": "RootingAnalyzer", "paths": []},
        "seed": spec["analysis"]["seed"],
        "parameters": parameters,
    }


def preflight(spec: dict[str, Any]) -> list[str]:
    """R.A.I.N.'s own validation of the definition this spec would register, without registering it."""
    _, _, schema, *_ = _rain()
    draft = {"schema_version": schema.DEFINITION_SCHEMA, "experiment_version": 1, **draft_from_spec(spec, {}),
             "experiment_id": "V3D-EXP-0000", "created_at": "2000-01-01T00:00:00.000Z"}
    return [f"R.A.I.N.: {problem}" for problem in schema.definition_errors(draft)]


def _comparable(definition: dict[str, Any]) -> dict[str, Any]:
    """What the spec controls: everything except assigned fields and the framing hashes."""
    body = {k: v for k, v in definition.items() if k not in _ASSIGNED}
    body["parameters"] = {k: v for k, v in body["parameters"].items() if k != "framing"}
    return body


def drift(definition: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """Top-level fields where ``spec`` no longer says what ``definition`` registered (empty when it matches)."""
    stored, draft = _comparable(definition), _comparable(draft_from_spec(spec))
    return sorted(k for k in set(stored) | set(draft) if stored.get(k) != draft.get(k))


def find(registry, spec: dict[str, Any]) -> dict[str, Any] | None:
    """The stored registration for this spec, or None. Refuses a spec that changed after registration."""
    experiments, *_ = _rain()
    title = spec["preregistration"]["title"]
    for experiment_id in registry.experiment_ids():
        definition = registry.load_definition(experiment_id)
        if definition["title"] != title:
            continue
        changed = drift(definition, spec)
        if not changed:
            return definition
        raise experiments.ExperimentError(
            f"{experiment_id} was pre-registered with different {', '.join(changed)}. "
            "Registrations are write-once: restore the spec, or give it a new title to register a new experiment."
        )
    return None


def register(registry, spec: dict[str, Any], framing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create the write-once registration and republish RESULTS.md (it lists planned experiments)."""
    experiments, *_ = _rain()
    if find(registry, spec) is not None:
        raise experiments.ExperimentError("this spec is already registered")
    definition = registry.create(draft_from_spec(spec, framing))
    publish(registry)
    return definition


# --------------------------------------------------------------------------- #
# Publication
# --------------------------------------------------------------------------- #
# R.A.I.N.'s renderer names commands of its own host repository. The page this
# repository publishes names the commands that work here instead; nothing else
# on the page is touched, and tests fail if the renderer stops using a phrase.
_LOCAL_COMMANDS = (
    (re.compile(r"by `python rain_lab\.py experiment results`"),
     "by `python -m rain_pipeline publish` (R.A.I.N.'s results renderer)"),
    (re.compile(r"\[EXPERIMENTS\.md\]\(EXPERIMENTS\.md\)"), "[docs/PROTOCOL.md](docs/PROTOCOL.md)"),
    (re.compile(r"`python rain_lab\.py experiment reproduce (V3D-EXP-\d+)`"), r"`python -m rain_pipeline replay \1`"),
    (re.compile(r"`[^`\n]+` via `experiment record`"),
     "`python -m rain_pipeline run` on its spec, once the registration is committed and pushed"),
)


def localize(page: str) -> str:
    for pattern, replacement in _LOCAL_COMMANDS:
        page = pattern.sub(replacement, page)
    return page


def render_results(registry) -> str:
    _, results, *_ = _rain()
    return localize(results.render_results(registry))


def publish(registry) -> None:
    provenance.write_text(registry.results_path, render_results(registry))


# --------------------------------------------------------------------------- #
# Anchoring
# --------------------------------------------------------------------------- #
def history_of(path: Path) -> tuple[provenance.History, str] | None:
    """The git history holding ``path`` and the path relative to it, or None outside a work tree."""
    try:
        top = Path(provenance.git(path.parent, "rev-parse", "--show-toplevel"))
    except provenance.GitError:
        return None
    history = provenance.History(top)
    return history, path.resolve().relative_to(top.resolve()).as_posix()


def versions(history: provenance.History, relative: str) -> list[tuple[str, str, bytes | None]]:
    """``(commit, committed_at, content)`` for every commit that changed the file, oldest first."""
    return [(commit, at, history.show(commit, relative)) for commit, at in history.commits_touching(relative)]


def anchor(registry, experiment_id: str) -> dict[str, Any]:
    """The first git commit that holds this registration, and where it has been pushed.

    Refuses when the registration is uncommitted, edited in the working tree,
    or committed in more than one version: only an unchanged registration has
    a timestamp that predates its data.
    """
    path = registry.experiment_dir(experiment_id) / "experiment.json"
    found = history_of(path)
    if found is None:
        raise NotAnchored(f"{experiment_id}: the registry is not inside a git repository")
    history, relative = found
    seen = versions(history, relative)
    if not seen or history.modified_in_worktree(relative):
        raise NotAnchored(
            f"{experiment_id} is registered but not committed. Commit and push the registration first: "
            "that commit is the proof that the criteria existed before the data was read."
        )
    contents = {content for _, _, content in seen if content is not None}
    if len(contents) > 1:
        raise NotAnchored(
            f"{experiment_id}: experiment.json was changed after its first commit ({len(contents)} versions in "
            "git history). A registration is write-once; an edited one is anchored to nothing."
        )
    commit, committed_at, _ = seen[0]
    return {"commit": commit, "committed_at": committed_at, "pushed_to": history.remote_branches_containing(commit)}


def anchor_cutoff(committed_at: str) -> str:
    """The first instant provably after an anchor commit.

    Git records whole seconds, so a read stamped within the commit's own second
    cannot be ordered against it. Holdout checks therefore count every read
    before the *next* second as a read before the anchor: the uncertainty
    always counts against the claim, never for it.
    """
    moment = datetime.fromisoformat(committed_at.replace("Z", "+00:00")).replace(microsecond=0)
    return (moment + timedelta(seconds=1)).astimezone(timezone.utc).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def definition_sha256(definition: dict[str, Any]) -> str:
    """The same digest R.A.I.N. stores as ``definition_sha256`` on every run."""
    _, _, schema, *_ = _rain()
    return schema.sha256_json(definition)


def submission_sha256(submission: dict[str, Any]) -> str:
    """The digest R.A.I.N. stores as ``provenance.submission_sha256`` for an external run."""
    _, _, schema, *_ = _rain()
    return schema.sha256_json(submission)


def select_measurements(definition: dict[str, Any], computed: dict[str, Any]) -> dict[str, Any]:
    """Exactly the pre-registered metrics, in registered order.

    The registration decides which measurements are evidence. Anything else a
    study computes stays in its report as description and is never submitted.
    """
    declared = [m["name"] for m in definition["metrics"]]
    missing = [name for name in declared if name not in computed]
    if missing:
        raise ValueError(f"the study did not produce pre-registered metrics: {missing}")
    return {name: computed[name] for name in declared}


def evaluated_metrics(definition: dict[str, Any]) -> list[str]:
    """Registered metrics that some guard, success or failure criterion reads: the ones that decide the verdict."""
    used = {c["metric"] for group in ("guards", "success", "failure") for c in definition["criteria"][group]}
    return [m["name"] for m in definition["metrics"] if m["name"] in used]


def evaluate(definition: dict[str, Any], measurements: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """R.A.I.N.'s evaluation (the only code that assigns a status), for re-derivation and replay."""
    *_, evaluate_module = _rain()
    return evaluate_module.evaluate(definition, measurements)


def record_divergence(record: dict[str, Any], submission: dict[str, Any]) -> list[str]:
    """Fields where an external run record no longer says what its submission said (empty when faithful).

    R.A.I.N. builds the record from the submission (redacting secret-like
    strings) but never compares them again; this does, field by field.
    """
    vendor.ensure_importable()
    from james_library.experiments.provenance import redact

    expected = {
        "measurements": submission["measurements"], "series": submission["series"],
        "inputs": redact(submission["inputs"]), "seed": submission["seed"], "started_at": submission["started_at"],
        "finished_at": submission["finished_at"], "experiment_id": submission["experiment_id"],
        "artifacts": [{k: a[k] for k in ("name", "sha256", "bytes", "kind")} for a in submission["artifacts"]],
    }
    actual = {key: record.get(key) for key in expected}
    actual["artifacts"] = [{k: a.get(k) for k in ("name", "sha256", "bytes", "kind")} for a in record["artifacts"]]
    return sorted(key for key in expected if actual[key] != expected[key])


def submission_errors(submission: dict[str, Any]) -> list[str]:
    _, _, schema, *_ = _rain()
    return schema.submission_errors(submission)


def submit(registry, definition: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    experiments, *_ = _rain()
    errors = submission_errors(submission)
    if errors:
        raise experiments.ExperimentError("Invalid submission:\n  " + "\n  ".join(errors))
    record = experiments.record_submission(registry, definition["experiment_id"], submission)
    publish(registry)
    return record


def verify(registry, experiment_id: str | None = None) -> dict[str, Any]:
    """R.A.I.N. re-derives every stored result from stored data (one experiment, or all)."""
    _, _, _, verify_module, _ = _rain()
    return verify_module.verify(registry, [experiment_id] if experiment_id else None)
