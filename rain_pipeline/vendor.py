"""Locate the three vendored repositories and record exactly which code ran.

The pipeline imports Anna, R.A.I.N. and DRR in-process from ``vendor/``.
Nothing is copied: every stage calls the upstream code at the commit that is
checked out, and that commit is written into the run's provenance.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
        if not path.is_dir():
            raise RuntimeError(
                f"{path} is missing. Clone it first:\n"
                f"  git clone https://github.com/{REPOSITORIES[name][0]}.git {path}"
            )
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def git_state(path: Path) -> dict[str, Any]:
    """Commit, branch and dirtiness of one vendored checkout."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        return {
            "commit": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        }
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "branch": None, "dirty": None}


def vendored_state() -> dict[str, dict[str, Any]]:
    return {
        name: {"repository": repo, **git_state(path)}
        for name, (repo, path) in REPOSITORIES.items()
    }


def pipeline_source_sha256() -> str:
    """One digest over this package's source, so a run names the glue code that produced it."""
    digest = hashlib.sha256()
    package = Path(__file__).resolve().parent
    for path in sorted(package.glob("*.py")):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: Any) -> dict[str, Any]:
    """Write pretty JSON and return its artifact reference (name, sha256, bytes)."""
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    data = text.encode("utf-8")
    path.write_bytes(data)
    return {"name": path.name, "sha256": sha256_bytes(data), "bytes": len(data)}


def write_text(path: Path, text: str) -> dict[str, Any]:
    data = text.encode("utf-8")
    path.write_bytes(data)
    return {"name": path.name, "sha256": sha256_bytes(data), "bytes": len(data)}
