"""R.A.I.N. experiment registry: register once, anchor in git, submit, publish.

An experiment is registered as an *external* experiment
(``rain-experiment/v1``). A registration is write-once: if the spec no longer
matches the stored definition, the pipeline refuses to run rather than
silently move the goalposts.

The registration also *binds its framing*: hashes of the literature record,
the panel's corpus, the parent result it follows from and the holdout proof go
into ``parameters.framing``, so none of them can be swapped afterwards.

Before a run reads data, the registration must be committed to git: the
commit (ideally pushed) is the timestamp that proves the criteria came first.

Results come back as a ``rain-experiment-submission/v1``, which deliberately
has no status field. R.A.I.N.'s ``evaluate`` assigns passed / failed /
inconclusive from the pre-registered criteria; this module never does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import vendor

_ASSIGNED = ("schema_version", "experiment_id", "experiment_version", "created_at")


class NotAnchored(RuntimeError):
    """The registration is not committed to git, so nothing proves it came before the data."""


def _rain():
    vendor.ensure_importable()
    from james_library import experiments
    from james_library.experiments import results, schema, verify

    return experiments, results, schema, verify


def open_registry(root: Path):
    experiments, *_ = _rain()
    root.mkdir(parents=True, exist_ok=True)
    return experiments.Registry(root=root, results_path=root.parent / "RESULTS.md")


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


def _comparable(definition: dict[str, Any]) -> dict[str, Any]:
    """What the spec controls: everything except assigned fields and the framing hashes."""
    body = {k: v for k, v in definition.items() if k not in _ASSIGNED}
    body["parameters"] = {k: v for k, v in body["parameters"].items() if k != "framing"}
    return body


def find(registry, spec: dict[str, Any]) -> dict[str, Any] | None:
    """The stored registration for this spec, or None. Refuses a spec that changed after registration."""
    experiments, *_ = _rain()
    draft = _comparable(draft_from_spec(spec))
    for experiment_id in registry.experiment_ids():
        definition = registry.load_definition(experiment_id)
        if definition["title"] != draft["title"]:
            continue
        stored = _comparable(definition)
        if stored == draft:
            return definition
        changed = sorted(k for k in set(stored) | set(draft) if stored.get(k) != draft.get(k))
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


def publish(registry) -> None:
    _, results, *_ = _rain()
    registry.results_path.write_text(results.render_results(registry), encoding="utf-8", newline="\n")


def anchor(registry, experiment_id: str) -> dict[str, Any]:
    """The git commit that holds this registration, and where it has been pushed."""
    path = registry.experiment_dir(experiment_id) / "experiment.json"

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(path.parent), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    try:
        committed = git("log", "-1", "--format=%H %cI", "--", path.name)
        modified = git("status", "--porcelain", "--", path.name)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NotAnchored(f"{experiment_id}: the registry is not inside a git repository") from exc
    if not committed or modified:
        raise NotAnchored(
            f"{experiment_id} is registered but not committed. Commit and push the registration first: "
            "that commit is the proof that the criteria existed before the data was read."
        )
    commit, committed_at = committed.split(" ", 1)
    remotes = [line.strip() for line in git("branch", "-r", "--contains", commit).splitlines()
               if line.strip() and "->" not in line]
    return {"commit": commit, "committed_at": committed_at, "pushed_to": remotes}


def definition_sha256(definition: dict[str, Any]) -> str:
    """The same digest R.A.I.N. stores as ``definition_sha256`` on every run."""
    _, _, schema, _ = _rain()
    return schema.sha256_json(definition)


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


def submit(registry, definition: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    experiments, _, schema, _ = _rain()
    errors = schema.submission_errors(submission)
    if errors:
        raise experiments.ExperimentError("Invalid submission:\n  " + "\n  ".join(errors))
    record = experiments.record_submission(registry, definition["experiment_id"], submission)
    publish(registry)
    return record


def verify(registry, experiment_id: str | None = None) -> dict[str, Any]:
    """R.A.I.N. re-derives every stored result from stored data (one experiment, or all)."""
    *_, verify_module = _rain()
    return verify_module.verify(registry, [experiment_id] if experiment_id else None)
