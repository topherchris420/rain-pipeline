"""Experiment specs: human-written intent, checked before anything runs.

A spec is a JSON object with these sections:

    question         the question in plain language                      always
    literature       Anna's arXiv queries and the cited search           register
    lineage          what it follows: a prior run, an observation,       optional
                     the exploration report that motivated it
    data             source, records, windows, QC, holdout               always
    analysis         the DRR study and its settings                      always
    preregistration  R.A.I.N. definition: hypothesis, metrics,           register, run
                     guards, success and failure criteria, limitations

``load`` checks structure and types and reports every problem at once. A typo
is caught before the literature search, before the registration, and long
before a holdout is read. What the registration then fixes for ever is
``data`` and ``analysis`` (as parameters) and ``preregistration``.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from . import drr_stage
from .errors import SpecError

SECTIONS = ("question", "literature", "lineage", "data", "analysis", "preregistration")
REQUIRED = {
    "explore": ("question", "data", "analysis"),
    "register": ("question", "literature", "data", "analysis", "preregistration"),
    "run": ("question", "data", "analysis", "preregistration"),
}
SOURCES = ("physionet-fantasia",)
DATA_KEYS = ("source", "records", "start_s", "duration_s", "segments", "grid_hz", "highpass_hz", "qc", "holdout",
             "holdout_shared_with")
EXPERIMENT_ID = re.compile(r"^V3D-EXP-\d{4,}$")
FOLLOWS = re.compile(r"^V3D-EXP-\d{4,}/RUN-\d{4,}$")
RECORD = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Measurements the pipeline itself contributes (the study never sees the ledger).
PIPELINE_METRICS = {
    "holdout_bytes_read_before_registration":
        "bytes of the declared holdout the ledger shows were first read before the registration was created",
    "holdout_bytes_read_before_anchor":
        "bytes of the declared holdout the ledger shows were first read before the registration's git commit",
}


def load(path: Path, purpose: str = "run") -> dict[str, Any]:
    """Read and check a spec for ``purpose`` (explore, register or run); raise ``SpecError`` listing every problem."""
    path = Path(path)
    if not path.is_file():
        raise SpecError(f"{path}: no such spec file")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path}: not valid JSON ({exc})") from exc
    found = problems(spec, purpose)
    if found:
        raise SpecError(f"{path} cannot be used to {purpose}:\n  " + "\n  ".join(found))
    return spec


def problems(spec: Any, purpose: str = "run") -> list[str]:
    if purpose not in REQUIRED:
        raise ValueError(f"unknown purpose {purpose!r}")
    if not isinstance(spec, dict):
        return ["the spec must be a JSON object"]
    found = [f"'{key}': not a spec section (sections: {', '.join(SECTIONS)})" for key in spec if key not in SECTIONS]
    found += [f"'{key}': missing" for key in REQUIRED[purpose] if key not in spec]
    if not isinstance(spec.get("question", ""), str) or ("question" in spec and not spec["question"].strip()):
        found.append("question: must be a non-empty string")
    if "literature" in spec:
        found += _literature_problems(spec["literature"])
    if "lineage" in spec:
        found += _lineage_problems(spec["lineage"])
    if "data" in spec:
        found += data_problems(spec["data"])
    if "analysis" in spec:
        found += drr_stage.problems(spec["analysis"])
    if "preregistration" in spec:
        found += _preregistration_problems(spec["preregistration"], spec.get("analysis"))
    return found


def _literature_problems(literature: Any) -> list[str]:
    if not isinstance(literature, dict):
        return ["literature: must be an object"]
    found = []
    queries = literature.get("arxiv_queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q.strip() for q in queries):
        found.append("literature.arxiv_queries: a non-empty list of arXiv queries")
    if not isinstance(literature.get("search"), str) or not literature.get("search", "").strip():
        found.append("literature.search: the query whose results become the cited record")
    for key in ("limit_per_query", "max_sources"):
        if not _integer(literature.get(key)) or literature[key] < 1:
            found.append(f"literature.{key}: an integer >= 1")
    return found


def _lineage_problems(lineage: Any) -> list[str]:
    if not isinstance(lineage, dict):
        return ["lineage: must be an object"]
    found = [f"lineage.{key}: not a lineage field (follows, observation, exploration)" for key in lineage
             if key not in ("follows", "observation", "exploration")]
    if "follows" in lineage and not (isinstance(lineage["follows"], str) and FOLLOWS.match(lineage["follows"])):
        found.append("lineage.follows: the run it follows, as V3D-EXP-NNNN/RUN-NNNN")
    for key in ("observation", "exploration"):
        if key in lineage and not (isinstance(lineage[key], str) and lineage[key].strip()):
            found.append(f"lineage.{key}: a non-empty string")
    if "exploration" in lineage and isinstance(lineage["exploration"], str) and (
            lineage["exploration"].startswith("/") or ".." in lineage["exploration"].split("/")):
        found.append("lineage.exploration: a path relative to the repository root")
    return found


def data_problems(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["data: must be an object"]
    found = [f"data.{key}: not a data setting" for key in data if key not in DATA_KEYS]
    if data.get("source") not in SOURCES:
        found.append(f"data.source: one of {', '.join(SOURCES)}")
    records = data.get("records")
    if not isinstance(records, list) or not records or not all(isinstance(r, str) and RECORD.match(r) for r in records):
        found.append("data.records: a non-empty list of record names")
    elif len(set(records)) != len(records):
        found.append("data.records: listed more than once: "
                     + ", ".join(sorted({r for r in records if records.count(r) > 1})))
    if "segments" in data:
        if "start_s" in data or "duration_s" in data:
            found.append("data: give either segments or start_s/duration_s, not both")
        segments = data["segments"]
        if not isinstance(segments, dict) or set(segments) != {"first_start_s", "duration_s", "count"}:
            found.append("data.segments: {first_start_s, duration_s, count}")
        else:
            if not _number(segments["first_start_s"]) or segments["first_start_s"] < 0:
                found.append("data.segments.first_start_s: seconds >= 0")
            if not _number(segments["duration_s"]) or segments["duration_s"] <= 0:
                found.append("data.segments.duration_s: seconds > 0")
            if not _integer(segments["count"]) or segments["count"] < 1:
                found.append("data.segments.count: an integer >= 1")
    else:
        if not _number(data.get("start_s")) or data["start_s"] < 0:
            found.append("data.start_s: seconds >= 0 (or give data.segments)")
        if not _number(data.get("duration_s")) or data["duration_s"] <= 0:
            found.append("data.duration_s: seconds > 0 (or give data.segments)")
    if not _number(data.get("grid_hz")) or data["grid_hz"] <= 0:
        found.append("data.grid_hz: the resampling rate, > 0")
    if not _number(data.get("highpass_hz")) or data["highpass_hz"] <= 0 or (
            _number(data.get("grid_hz")) and data["highpass_hz"] >= data["grid_hz"] / 2):
        found.append("data.highpass_hz: > 0 and below half of grid_hz")
    qc = data.get("qc")
    if not isinstance(qc, dict) or set(qc) != {"min_valid_rr_fraction"} or not _number(qc["min_valid_rr_fraction"]) \
            or not 0 <= qc["min_valid_rr_fraction"] <= 1:
        found.append("data.qc: {\"min_valid_rr_fraction\": a share between 0 and 1}")
    if "holdout" in data and not isinstance(data["holdout"], bool):
        found.append("data.holdout: true or false")
    shared = data.get("holdout_shared_with", [])
    if "holdout_shared_with" in data and not data.get("holdout"):
        found.append("data.holdout_shared_with: only meaningful with data.holdout")
    if not isinstance(shared, list) or not all(isinstance(e, str) and EXPERIMENT_ID.match(e) for e in shared):
        found.append("data.holdout_shared_with: a list of experiment IDs (V3D-EXP-NNNN)")
    return found


def _preregistration_problems(preregistration: Any, analysis: Any) -> list[str]:
    """Shape only; R.A.I.N. validates the definition itself, and registration checks producibility."""
    if not isinstance(preregistration, dict):
        return ["preregistration: must be an object"]
    found = []
    for key in ("title", "hypothesis"):
        if not isinstance(preregistration.get(key), str) or not preregistration.get(key, "").strip():
            found.append(f"preregistration.{key}: a non-empty string")
    for key in ("experiment_id", "experiment_version", "created_at", "schema_version"):
        if key in preregistration:
            found.append(f"preregistration.{key}: assigned by R.A.I.N. at registration; remove it from the spec")
    if "parameters" in preregistration or "seed" in preregistration:
        found.append("preregistration: parameters and seed come from the data and analysis sections")
    return found


def segments_of(data: dict[str, Any]) -> tuple[float, float, int]:
    """``(first start, window length, window count)`` per record."""
    if "segments" in data:
        segments = data["segments"]
        return segments["first_start_s"], segments["duration_s"], segments["count"]
    return data["start_s"], data["duration_s"], 1  # V3D-EXP-0001: one window per record


def producible_metrics(spec: dict[str, Any]) -> list[str]:
    """Every measurement a run of this spec can submit: the study's outputs plus the pipeline's own."""
    names = drr_stage.outputs(spec["analysis"])
    if spec["data"].get("holdout"):
        names += list(PIPELINE_METRICS)
    return names


def registration_problems(spec: dict[str, Any]) -> list[str]:
    """What would make a run of this registration unable to produce, or unable to judge, its evidence.

    - every registered metric must be one the run will produce; otherwise the
      run ends as an error after it has read (and spent) the data;
    - a declared holdout must be guarded: some criterion must require zero
      holdout bytes read before the registration (or before its git anchor),
      or R.A.I.N. would never be asked whether the data was really unseen.
    """
    preregistration = spec["preregistration"]
    metrics = preregistration.get("metrics")
    if not isinstance(metrics, list):
        return []  # R.A.I.N.'s own validation reports the shape
    producible = set(producible_metrics(spec))
    found = [f"preregistration.metrics: {m.get('name')!r} is not produced by the "
             f"{drr_stage.study_name(spec['analysis'])} study with these settings"
             for m in metrics if isinstance(m, dict) and m.get("name") not in producible]
    if spec["data"].get("holdout"):
        criteria = preregistration.get("criteria")
        guards = criteria.get("guards") if isinstance(criteria, dict) else None
        if not any(_is_holdout_guard(guard) for guard in guards or []):
            found.append("preregistration.criteria.guards: a holdout needs a guard such as "
                         "{\"metric\": \"holdout_bytes_read_before_anchor\", \"op\": \"<=\", \"value\": 0}")
    return found


def _is_holdout_guard(guard: Any) -> bool:
    """A guard that holds only when no holdout byte was read early: ``<= 0`` (or ``< 1``) on a holdout metric."""
    if not isinstance(guard, dict) or guard.get("metric") not in PIPELINE_METRICS or not _number(guard.get("value")):
        return False
    return (guard.get("op") == "<=" and guard["value"] == 0) or (guard.get("op") == "<" and 0 < guard["value"] <= 1)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
