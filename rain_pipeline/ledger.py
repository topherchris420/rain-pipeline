"""The data ledger: which bytes have been read, when, and by what.

Every byte range the pipeline reads from a public dataset is logged in
``data/ledger.json`` with the SHA-256 of its content and the time of its
first read. Three rules hang off it:

- **Exploration may only touch seen data.** ``explore`` refuses any byte the
  ledger does not already cover, so trying ideas can never burn a holdout.
- **Confirmation must use unseen data.** A spec that declares ``holdout`` is
  refused at registration if any of its bytes were ever read, and at run time
  the bytes read before the registration (and before its git anchor) are
  reported to R.A.I.N. as guard metrics that must be zero.
- **The ledger only grows.** An entry is never edited or removed: ``extends``
  checks one version against a later one, and ``verify`` applies it to every
  committed version and to the snapshot each holdout registration bound.

Re-reads are not logged (only first reads matter for a holdout), but an exact
re-read must hash identically, or the source changed under us. A replay or an
exploration only ever *checks* the ledger (``require_seen``); it never adds to it.

The ledger is a log kept by this tool. It makes the holdout claim checkable
and prevents accidents; it cannot stop someone reading the data elsewhere.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import provenance
from .errors import HoldoutViolation

SCHEMA = "rain-pipeline-data-ledger/v1"
FIELDS = ("url", "byte_range", "sha256", "first_read_at", "first_read_by")

Range = tuple[str, tuple[int, int]]  # (url, (first byte, last byte)), inclusive

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LedgerError(ValueError):
    """The ledger is malformed, or a read contradicts it."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(moment: str) -> datetime:
    parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise LedgerError(f"timestamp {moment!r} has no timezone")
    return parsed


# --------------------------------------------------------------------------- #
# Load and save
# --------------------------------------------------------------------------- #
def entry_problems(entry: Any) -> list[str]:
    if not isinstance(entry, dict):
        return ["not an object"]
    found = [f"missing {key}" for key in FIELDS if key not in entry]
    if found:
        return found
    span = entry["byte_range"]
    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(b, int) and not isinstance(b, bool) for b in span)
            and 0 <= span[0] <= span[1]):
        found.append(f"byte_range {span!r} is not [first, last] with 0 <= first <= last")
    if not isinstance(entry["sha256"], str) or not _SHA256.match(entry["sha256"]):
        found.append("sha256 is not 64 lowercase hex digits")
    try:
        parse_time(entry["first_read_at"])
    except (TypeError, ValueError, AttributeError):
        found.append(f"first_read_at {entry['first_read_at']!r} is not a timezone-aware ISO time")
    if not isinstance(entry["first_read_by"], str) or not entry["first_read_by"]:
        found.append("first_read_by is empty")
    return found


def parse(text: str, where: str = "ledger") -> dict[str, Any]:
    try:
        ledger = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"{where}: not valid JSON ({exc})") from exc
    if not isinstance(ledger, dict) or ledger.get("schema") != SCHEMA or not isinstance(ledger.get("entries"), list):
        raise LedgerError(f"{where}: not a {SCHEMA} ledger")
    for index, entry in enumerate(ledger["entries"]):
        found = entry_problems(entry)
        if found:
            raise LedgerError(f"{where}: entry {index}: {'; '.join(found)}")
    return ledger


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "entries": []}
    return parse(path.read_text(encoding="utf-8"), str(path))


def dumps(ledger: dict[str, Any]) -> str:
    ledger["entries"].sort(key=lambda e: (e["first_read_at"], e["url"], e["byte_range"][0]))
    return json.dumps(ledger, indent=2) + "\n"


def save(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_bytes(path, dumps(ledger).encode("utf-8"))


@contextmanager
def _locked(path: Path, timeout_s: float = 30.0) -> Iterator[None]:
    """One writer at a time: two runs recording at once must not drop each other's reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LedgerError(f"{path} is locked by another process ({lock}); "
                                  "if none is running, delete the lock file") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def sha256_file(path: Path) -> str | None:
    return provenance.sha256_file(path) if path.exists() else None


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def entry_for(ledger: dict[str, Any], url: str, byte_range: Iterable[int]) -> dict[str, Any] | None:
    """The entry logged for exactly this range, if any."""
    wanted = [int(b) for b in byte_range]
    return next((e for e in ledger["entries"] if e["url"] == url and e["byte_range"] == wanted), None)


def record(path: Path, *, url: str, byte_range: Iterable[int], sha256: str, read_at: str, read_by: str,
           note: str | None = None) -> bool:
    """Log the first read of a byte range. Returns False when nothing new was read.

    A range read before under exactly these bounds must hash as it did then.
    A range whose every byte was already read under other bounds is not a
    first read and is not logged again.
    """
    byte_range = [int(b) for b in byte_range]
    with _locked(path):
        ledger = load(path)
        existing = entry_for(ledger, url, byte_range)
        if existing is not None:
            if existing["sha256"] != sha256:
                raise LedgerError(f"{url} {byte_range}: content differs from the first read; the source changed")
            return False
        if bytes_unseen(ledger, [(url, tuple(byte_range))]) == 0:
            return False
        entry = {"url": url, "byte_range": byte_range, "sha256": sha256, "first_read_at": read_at,
                 "first_read_by": read_by}
        if note:
            entry["note"] = note
        ledger["entries"].append(entry)
        save(path, ledger)
        return True


def require_seen(ledger: dict[str, Any], *, url: str, byte_range: Iterable[int], sha256: str) -> dict[str, Any] | None:
    """Check a read that must not be a first read (exploration, replay). Never writes.

    Raises ``HoldoutViolation`` if any byte is unseen and ``LedgerError`` if an
    exactly logged range now hashes differently. Returns the exact entry, if any.
    """
    span = tuple(int(b) for b in byte_range)
    unseen = bytes_unseen(ledger, [(url, span)])
    if unseen:
        raise HoldoutViolation(f"{url} {list(span)}: {unseen:,} bytes were never read before; "
                               "only a registered run may read unseen data")
    existing = entry_for(ledger, url, span)
    if existing is not None and existing["sha256"] != sha256:
        raise LedgerError(f"{url} {list(span)}: content differs from the first read; the source changed")
    return existing


def _overlap(a: Iterable[int], b: Iterable[int]) -> int:
    (a0, a1), (b0, b1) = a, b
    return max(0, min(a1, b1) - max(a0, b0) + 1)


def bytes_read_before(ledger: dict[str, Any], ranges: Iterable[Range], moment: str) -> int:
    """How many of the requested bytes were first read strictly before ``moment``."""
    cutoff = parse_time(moment)
    total = 0
    for url, wanted in ranges:
        earlier = [e["byte_range"] for e in ledger["entries"]
                   if e["url"] == url and parse_time(e["first_read_at"]) < cutoff]
        total += _union_overlap(wanted, earlier)
    return total


def bytes_unseen(ledger: dict[str, Any], ranges: Iterable[Range]) -> int:
    """How many of the requested bytes the ledger has no record of."""
    total = 0
    for url, wanted in ranges:
        seen = [e["byte_range"] for e in ledger["entries"] if e["url"] == url]
        total += (wanted[1] - wanted[0] + 1) - _union_overlap(wanted, seen)
    return total


def overlap(ranges: Iterable[Range], others: Iterable[Range]) -> int:
    """Bytes of ``ranges`` that also lie in ``others`` (each byte counted once)."""
    others = list(others)
    return sum(_union_overlap(wanted, [list(span) for u, span in others if u == url]) for url, wanted in ranges)


def _union_overlap(wanted: Iterable[int], others: list[list[int]]) -> int:
    """Bytes of ``wanted`` covered by the union of ``others`` (overlaps counted once)."""
    covered, position = 0, wanted[0]
    for start, end in sorted(o for o in map(tuple, others) if _overlap(wanted, o)):
        start = max(start, position)
        end = min(end, wanted[1])
        if end >= start:
            covered += end - start + 1
            position = end + 1
    return covered


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def extends(earlier: dict[str, Any], later: dict[str, Any]) -> list[str]:
    """Problems that stop ``later`` being ``earlier`` plus new entries (empty when it only grew)."""
    def key(entry: dict[str, Any]) -> tuple:
        return entry["url"], tuple(entry["byte_range"])

    now = {key(e): e for e in later["entries"]}
    found = []
    for entry in earlier["entries"]:
        current = now.get(key(entry))
        label = f"{entry['url'].rsplit('/', 1)[-1]} {entry['byte_range']}"
        if current is None:
            found.append(f"{label}: entry removed")
        elif current != entry:
            changed = sorted(k for k in set(entry) | set(current) if entry.get(k) != current.get(k))
            found.append(f"{label}: {', '.join(changed)} changed")
    return found
