"""Content identity: hashes, deterministic JSON, the code that ran, and git.

Every record the pipeline keeps is identified by content, never by name:

- artifacts, data ranges, ledger snapshots and source files by the SHA-256 of
  their exact bytes;
- R.A.I.N. definitions and submissions, and the evidence graph, by the SHA-256
  of their canonical JSON (sorted keys, compact separators), the digest R.A.I.N.
  itself stores as ``definition_sha256`` and ``submission_sha256``;
- this package's own source by one digest over its modules (``source_sha256``),
  which ``resolve_source_commit`` maps back to the git commit that holds it.

Git commits anchor those identities in time. SHA-256 detects any change; it is
not a signature, so a writer able to rewrite both data and records can still
forge them. Pushed git history is the tamper-evidence layer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__
from .layout import CODE_ROOT, PACKAGE_DIR

PACKAGE = PACKAGE_DIR.name  # "rain_pipeline": the directory whose *.py files make up the source digest

# Packages whose versions can change a measurement or an artifact's bytes.
RECORDED_PACKAGES = ("numpy", "scipy", "drr-framework", "matplotlib", "jsonschema", "pgserver")


# --------------------------------------------------------------------------- #
# Hashes and serialization
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json(value: Any) -> str:
    """Compact, key-sorted JSON: the form R.A.I.N. hashes (``schema.sha256_json``)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def finite(value: Any) -> tuple[Any, int]:
    """``value`` with every NaN or infinity replaced by None (JSON null), and how many were replaced.

    Strict JSON has no NaN. A descriptive report keeps its shape and says where
    a number was undefined, instead of making the whole record unwritable.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None, 1
    if isinstance(value, dict):
        pairs = [(key, finite(item)) for key, item in value.items()]
        return {key: item for key, (item, _) in pairs}, sum(count for _, (_, count) in pairs)
    if isinstance(value, (list, tuple)):
        items = [finite(item) for item in value]
        return [item for item, _ in items], sum(count for _, count in items)
    return value, 0


def dumps(payload: Any) -> str:
    """Pretty JSON exactly as every pipeline artifact is written. NaN and infinity are refused."""
    return json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def read_json(path: Path) -> Any:
    """Parsed JSON, or None when the file is missing or unreadable (callers report that as a broken link)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def artifact_ref(path: Path, data: bytes | None = None) -> dict[str, Any]:
    """``{name, sha256, bytes}`` of a file, the reference R.A.I.N. records for an artifact."""
    data = Path(path).read_bytes() if data is None else data
    return {"name": Path(path).name, "sha256": sha256_bytes(data), "bytes": len(data)}


def fresh_dir(parent: Path, name: str) -> Path:
    """Create and return ``parent/name``, or ``name-2``, ``name-3``... when it exists: records are never merged."""
    parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 1000):
        path = parent / (name if attempt == 1 else f"{name}-{attempt}")
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise FileExistsError(f"no free name for {parent / name}")


def fresh_file(parent: Path, stem: str, suffix: str) -> Path:
    """A path ``parent/stem.suffix`` (or ``stem-2.suffix``...) that no existing record occupies."""
    parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 1000):
        path = parent / (f"{stem}{suffix}" if attempt == 1 else f"{stem}-{attempt}{suffix}")
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return path
        except FileExistsError:
            continue
    raise FileExistsError(f"no free name for {parent / stem}{suffix}")


def write_bytes(path: Path, data: bytes) -> dict[str, Any]:
    """Write atomically (a reader never sees half a file) and return the artifact reference."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return artifact_ref(path, data)


def write_json(path: Path, payload: Any) -> dict[str, Any]:
    return write_bytes(path, dumps(payload).encode("utf-8"))


def write_text(path: Path, text: str) -> dict[str, Any]:
    return write_bytes(path, text.encode("utf-8"))


# --------------------------------------------------------------------------- #
# The code that ran
# --------------------------------------------------------------------------- #
def source_sha256_of(files: dict[str, bytes]) -> str:
    """One digest over a package's modules: name, NUL, LF-normalized bytes, in name order.

    This is the algorithm every run since 0.1.0 recorded as ``source_sha256``.
    """
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(files[name].replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def _package_files(package_dir: Path = PACKAGE_DIR) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(package_dir.glob("*.py"))}


def source_sha256(package_dir: Path = PACKAGE_DIR) -> str:
    return source_sha256_of(_package_files(package_dir))


def source_files(package_dir: Path = PACKAGE_DIR) -> dict[str, str]:
    """Per-module SHA-256 (LF-normalized), so a reader can see which modules changed between runs."""
    return {name: sha256_bytes(data.replace(b"\r\n", b"\n")) for name, data in _package_files(package_dir).items()}


def code_identity() -> dict[str, Any]:
    """This package as it is about to run: version, source digests, and its git state."""
    return {
        "version": __version__,
        "source_sha256": source_sha256(),
        "files": source_files(),
        "git": git_state(CODE_ROOT, paths=(PACKAGE,)),
    }


def environment() -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version

    packages = {}
    for name in RECORDED_PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            pass
    return {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
            "platform": platform.platform(), "packages": packages}


# --------------------------------------------------------------------------- #
# Git
# --------------------------------------------------------------------------- #
class GitError(RuntimeError):
    pass


def git(cwd: Path, *args: str, binary: bool = False) -> Any:
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise GitError(exc.stderr.decode("utf-8", "replace").strip() or f"git {' '.join(args)} failed") from exc
    return done.stdout if binary else done.stdout.decode("utf-8", "replace").strip()


def git_state(path: Path, paths: tuple[str, ...] = ()) -> dict[str, Any]:
    """Commit, branch and dirtiness of a checkout (only ``paths`` count towards dirty, when given)."""
    try:
        return {
            "commit": git(path, "rev-parse", "HEAD"),
            "branch": git(path, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git(path, "status", "--porcelain", "--", *paths)),
        }
    except GitError:
        return {"commit": None, "branch": None, "dirty": None}


class History:
    """Read-only questions about one repository's committed history (cached; never writes)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        try:
            top = Path(git(self.root, "rev-parse", "--show-toplevel")).resolve()
            self.available = top == self.root.resolve()
            self.shallow = git(self.root, "rev-parse", "--is-shallow-repository") == "true"
        except GitError:
            self.available, self.shallow = False, False
        self._blobs: dict[str, bytes] = {}
        self._digests: dict[str, str] | None = None

    def _git(self, *args: str, binary: bool = False) -> Any:
        return git(self.root, *args, binary=binary)

    def commits_touching(self, relative: str) -> list[tuple[str, str]]:
        """``(commit, committer ISO time)`` of every commit that changed ``relative``, oldest first."""
        out = self._git("log", "--format=%H %cI", "--reverse", "--", relative)
        return [tuple(line.split(" ", 1)) for line in out.splitlines() if line]

    def show(self, commit: str, relative: str) -> bytes | None:
        try:
            blob = self._git("rev-parse", f"{commit}:{relative}")
        except GitError:
            return None
        if blob not in self._blobs:
            self._blobs[blob] = self._git("cat-file", "blob", blob, binary=True)
        return self._blobs[blob]

    def exists(self, commit: str) -> bool:
        try:
            return self._git("cat-file", "-t", commit) == "commit"
        except GitError:
            return False

    def committed_at(self, commit: str) -> str:
        return self._git("show", "-s", "--format=%cI", commit)

    def is_ancestor(self, commit: str, of: str = "HEAD") -> bool:
        try:
            self._git("merge-base", "--is-ancestor", commit, of)
            return True
        except GitError:
            return False

    def remote_branches_containing(self, commit: str) -> list[str]:
        try:
            out = self._git("branch", "-r", "--contains", commit)
        except GitError:
            return []
        return [line.strip() for line in out.splitlines() if line.strip() and "->" not in line]

    def modified_in_worktree(self, relative: str) -> bool:
        return bool(self._git("status", "--porcelain", "--", relative))

    def source_digests(self) -> dict[str, str]:
        """``source_sha256`` of the package at every commit that changed it -> the oldest such commit."""
        if self._digests is None:
            found: dict[str, str] = {}
            for commit, _ in self.commits_touching(PACKAGE):
                files = {}
                for line in self._git("ls-tree", commit, f"{PACKAGE}/").splitlines():
                    meta, name = line.split("\t", 1)
                    if meta.split()[1] == "blob" and name.endswith(".py") and name.count("/") == 1:
                        files[name.split("/", 1)[1]] = self.show(commit, name) or b""
                found.setdefault(source_sha256_of(files), commit)
            self._digests = found
        return self._digests


def resolve_source_commit(history: History, digest: str) -> str | None:
    """The oldest commit whose package source has ``digest``, or None if no commit holds it."""
    if not history.available:
        return None
    return history.source_digests().get(digest)
