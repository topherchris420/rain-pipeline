"""The data ledger: which bytes have been read, when, and by what.

Every byte range the pipeline reads from a public dataset is logged in
``data/ledger.json`` with the time of its first read. Two rules hang off it:

- **Exploration may only touch seen data.** ``explore`` refuses any byte the
  ledger does not already cover, so trying ideas can never burn a holdout.
- **Confirmation must use unseen data.** A spec that declares ``holdout`` is
  refused at registration if any of its bytes were ever read, and at run time
  the count of bytes read before the registration existed is reported to
  R.A.I.N. as a guard metric (it must be zero).

The ledger is a log kept by this tool. It makes the holdout claim checkable
and prevents accidents; it cannot stop someone reading the data elsewhere.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "rain-pipeline-data-ledger/v1"

Range = tuple[str, tuple[int, int]]  # (url, (first byte, last byte)), inclusive


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(moment: str) -> datetime:
    return datetime.fromisoformat(moment.replace("Z", "+00:00"))


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "entries": []}
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("schema") != SCHEMA:
        raise ValueError(f"{path}: not a {SCHEMA} ledger")
    return ledger


def save(path: Path, ledger: dict[str, Any]) -> None:
    ledger["entries"].sort(key=lambda e: (e["first_read_at"], e["url"], e["byte_range"][0]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(ledger, indent=2) + "\n").encode("utf-8"))


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def record(path: Path, *, url: str, byte_range: Iterable[int], sha256: str, read_at: str, read_by: str,
           note: str | None = None) -> bool:
    """Log the first read of a byte range. Returns False when it was already logged."""
    ledger = load(path)
    byte_range = [int(b) for b in byte_range]
    for entry in ledger["entries"]:
        if entry["url"] == url and entry["byte_range"] == byte_range:
            if entry["sha256"] != sha256:
                raise ValueError(f"{url} {byte_range}: content differs from the first read; the source changed")
            return False
    entry = {"url": url, "byte_range": byte_range, "sha256": sha256, "first_read_at": read_at, "first_read_by": read_by}
    if note:
        entry["note"] = note
    ledger["entries"].append(entry)
    save(path, ledger)
    return True


def _overlap(a: Iterable[int], b: Iterable[int]) -> int:
    (a0, a1), (b0, b1) = a, b
    return max(0, min(a1, b1) - max(a0, b0) + 1)


def bytes_read_before(ledger: dict[str, Any], ranges: Iterable[Range], moment: str) -> int:
    """How many of the requested bytes were first read strictly before ``moment``."""
    cutoff = _parse(moment)
    total = 0
    for url, wanted in ranges:
        earlier = [e["byte_range"] for e in ledger["entries"]
                   if e["url"] == url and _parse(e["first_read_at"]) < cutoff]
        total += _union_overlap(wanted, earlier)
    return total


def bytes_unseen(ledger: dict[str, Any], ranges: Iterable[Range]) -> int:
    """How many of the requested bytes the ledger has no record of."""
    total = 0
    for url, wanted in ranges:
        seen = [e["byte_range"] for e in ledger["entries"] if e["url"] == url]
        total += (wanted[1] - wanted[0] + 1) - _union_overlap(wanted, seen)
    return total


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
