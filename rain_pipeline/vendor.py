"""Locate the three vendored repositories and record exactly which code ran.

The pipeline imports Anna, R.A.I.N. and DRR in-process from ``vendor/``, where
they are git submodules pinned to the commits that produced the committed
results. Nothing is copied: every stage calls the upstream code at the commit
that is checked out, and that commit, its dirtiness and whether it matches the
pin are written into each run's provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import provenance
from .layout import CODE_ROOT

PROJECT_ROOT = CODE_ROOT
VENDOR = PROJECT_ROOT / "vendor"

ANNA = VENDOR / "anna"
RAIN = VENDOR / "james_library"
DRR = VENDOR / "dynamic-resonance-rooting"

REPOSITORIES = {
    "anna": ("topherchris420/anna", ANNA),
    "rain": ("topherchris420/james_library", RAIN),
    "drr": ("topherchris420/dynamic-resonance-rooting", DRR),
}


def ensure_importable() -> None:
    """Put Anna and R.A.I.N. on ``sys.path``. DRR is pip-installed (editable)."""
    for name in ("anna", "rain"):
        path = REPOSITORIES[name][1]
        if not path.is_dir() or not any(path.iterdir()):
            raise RuntimeError(
                f"{path} is missing. Fetch the pinned submodules first:\n"
                "  git submodule update --init --recursive"
            )
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def git_state(path: Path) -> dict[str, Any]:
    """Commit, branch and dirtiness of one vendored checkout."""
    return provenance.git_state(path)


def pinned_commit(path: Path) -> str | None:
    """The commit the code repository pins for a submodule (its gitlink at HEAD)."""
    try:
        listing = provenance.git(PROJECT_ROOT, "ls-tree", "HEAD", path.relative_to(PROJECT_ROOT).as_posix())
    except (provenance.GitError, ValueError):
        return None
    fields = listing.split()
    return fields[2] if len(fields) >= 3 and fields[1] == "commit" else None


def vendored_state() -> dict[str, dict[str, Any]]:
    state = {}
    for name, (repo, path) in REPOSITORIES.items():
        checkout = git_state(path)
        state[name] = {"repository": repo, **checkout, "pinned": pinned_commit(path)}
    return state


def unpinned(state: dict[str, dict[str, Any]]) -> list[str]:
    """Vendored checkouts that are dirty, unreadable, or not at the commit the repository pins."""
    problems = []
    for name, checkout in state.items():
        if checkout["commit"] is None:
            problems.append(f"{name}: not a git checkout")
        elif checkout["dirty"]:
            problems.append(f"{name}: uncommitted changes in {checkout['repository']}")
        elif checkout.get("pinned") and checkout["commit"] != checkout["pinned"]:
            problems.append(f"{name}: at {checkout['commit'][:10]}, but the repository pins {checkout['pinned'][:10]}")
    return problems


# Kept for callers of the 0.2 API; the implementations live in ``provenance``.
sha256_bytes = provenance.sha256_bytes
write_json = provenance.write_json
write_text = provenance.write_text
pipeline_source_sha256 = provenance.source_sha256
