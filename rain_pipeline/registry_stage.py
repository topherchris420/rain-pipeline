"""Stage 2b/4 — R.A.I.N. experiment registry: pre-register, submit, publish.

The experiment is registered as an *external* experiment
(``rain-experiment/v1``) before any data is fetched. A registration is
write-once: if the spec no longer matches the stored definition, the pipeline
refuses to run rather than silently move the goalposts.

Results come back as a ``rain-experiment-submission/v1``, which deliberately
has no status field. R.A.I.N.'s ``evaluate`` assigns passed / failed /
inconclusive from the pre-registered criteria; this module never does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import vendor

_ASSIGNED = ("schema_version", "experiment_id", "experiment_version", "created_at")


def _rain():
    vendor.ensure_importable()
    from james_library import experiments
    from james_library.experiments import results, schema, verify

    return experiments, results, schema, verify


def open_registry(root: Path):
    experiments, *_ = _rain()
    root.mkdir(parents=True, exist_ok=True)
    return experiments.Registry(root=root, results_path=root.parent / "RESULTS.md")


def draft_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """The registration is bound to exactly what will run: data and analysis settings."""
    drr_repo = vendor.REPOSITORIES["drr"][0]
    return {
        **spec["preregistration"],
        "runner": {
            "kind": "external",
            "repository": drr_repo,
            "adapter": "rain-pipeline: Anna -> R.A.I.N. -> DRR (rain-experiment-submission/v1)",
        },
        "subsystem": {"repository": drr_repo, "component": "RootingAnalyzer", "paths": []},
        "seed": spec["analysis"]["seed"],
        "parameters": {"data": spec["data"], "analysis": spec["analysis"]},
    }


def preregister(registry, spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return ``(definition, created)``. Reuses an identical registration; refuses a changed one."""
    experiments, *_ = _rain()
    draft = draft_from_spec(spec)
    for experiment_id in registry.experiment_ids():
        definition = registry.load_definition(experiment_id)
        if definition["title"] != draft["title"]:
            continue
        stored = {k: v for k, v in definition.items() if k not in _ASSIGNED}
        if stored == draft:
            return definition, False
        changed = sorted(k for k in set(stored) | set(draft) if stored.get(k) != draft.get(k))
        raise experiments.ExperimentError(
            f"{experiment_id} was pre-registered with different {', '.join(changed)}. "
            "Registrations are write-once: restore the spec, or give it a new title to register a new experiment."
        )
    return registry.create(draft), True


def definition_sha256(definition: dict[str, Any]) -> str:
    """The same digest R.A.I.N. stores as ``definition_sha256`` on every run."""
    _, _, schema, _ = _rain()
    return schema.sha256_json(definition)


def check_measurements(definition: dict[str, Any], measurements: dict[str, Any]) -> None:
    declared = {m["name"] for m in definition["metrics"]}
    if set(measurements) != declared:
        raise ValueError(
            f"measurements do not match the pre-registered metrics: "
            f"missing {sorted(declared - set(measurements))}, undeclared {sorted(set(measurements) - declared)}"
        )


def submit(registry, definition: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    experiments, results, schema, _ = _rain()
    errors = schema.submission_errors(submission)
    if errors:
        raise experiments.ExperimentError("Invalid submission:\n  " + "\n  ".join(errors))
    record = experiments.record_submission(registry, definition["experiment_id"], submission)
    registry.results_path.write_text(results.render_results(registry), encoding="utf-8", newline="\n")
    return record


def verify(registry, experiment_id: str | None = None) -> dict[str, Any]:
    """R.A.I.N. re-derives every stored result from stored data (one experiment, or all)."""
    *_, verify_module = _rain()
    return verify_module.verify(registry, [experiment_id] if experiment_id else None)
