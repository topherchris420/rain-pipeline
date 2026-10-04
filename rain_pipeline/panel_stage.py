"""Stage 2a — R.A.I.N. Research Panel over Anna's sources.

Anna's retrieved documents become the panel's corpus: one Markdown file per
source, abstract verbatim. R.A.I.N.'s offline meeting (James, Jasmine, Luca,
Elena) then ranks quotable sentences, has each agent argue through its lens,
and re-verifies every quote against the corpus.

The offline panel needs no model and is deterministic. Its reasoning text is
scripted by R.A.I.N.; the quotes are not. It informs the human-authored
pre-registration — it never writes criteria and never decides an outcome.
"""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import vendor


@dataclass(frozen=True)
class PanelResult:
    markdown: str
    summary: dict[str, Any]


def write_corpus(documents: list[Any], corpus_dir: Path) -> dict[str, dict[str, str]]:
    """One ``.md`` per Anna document; returns ``{file name: {anna_id, title, url}}``."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    sources: dict[str, dict[str, str]] = {}
    for rank, doc in enumerate(documents, start=1):
        slug = re.sub(r"[^a-z0-9]+", "-", doc.title.lower()).strip("-")[:60].rstrip("-")
        name = f"{rank:02d}-{slug or 'source'}.md"
        byline = "; ".join(filter(None, [", ".join(doc.authors[:4]), (doc.published or "")[:10], doc.url]))
        text = (
            f"# {doc.title}\n\n"
            f"{byline}\n"
            f"Anna document {doc.id}\n\n"
            f"Abstract\n\n"
            f"{doc.abstract.strip()}\n"
        )
        (corpus_dir / name).write_text(text, encoding="utf-8", newline="\n")
        sources[name] = {"anna_id": doc.id, "title": doc.title, "url": doc.url}
    return sources


def corpus_fingerprint(corpus_dir: Path) -> str:
    """The digest R.A.I.N.'s citation audit records as ``corpus_sha256``, recomputed from the files on disk.

    It mirrors the offline meeting's fingerprint (path, NUL, SHA-256 per
    discovered corpus file, in path order) using R.A.I.N.'s own discovery and
    hashing helpers, so a registration's ``panel_corpus_sha256`` can be checked
    without convening the panel again.
    """
    vendor.ensure_importable()
    from james_library.utilities.citation_corpus import discover_corpus_files, hash_corpus_files

    files = discover_corpus_files(corpus_dir) if corpus_dir.is_dir() else []
    digest = hashlib.sha256()
    for row in hash_corpus_files(files, corpus_dir) if files else []:
        digest.update(f"{row['path']}\0{row['sha256']}\n".encode())
    return digest.hexdigest()


@contextmanager
def _cwd(path: Path | None) -> Iterator[None]:
    previous = os.getcwd()
    if path is not None:
        os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def run(question: str, documents: list[Any], corpus_dir: Path, relative_to: Path | None = None) -> PanelResult:
    """Convene the offline panel over ``documents``; its transcript names paths relative to ``relative_to``."""
    vendor.ensure_importable()
    from james_library.launcher.offline_meeting import build_offline_meeting
    from james_library.launcher.offline_meeting_view import render_markdown

    sources = write_corpus(documents, corpus_dir)
    with _cwd(relative_to):  # the transcript prints the corpus path relative to the working directory
        meeting = build_offline_meeting(question, corpus_dir)
        markdown = render_markdown(meeting, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    summary = {
        "engine": "R.A.I.N. offline meeting (deterministic, no model)",
        "question": meeting.question,
        "grounding": meeting.grounding,
        "matched_terms": list(meeting.matched_terms),
        "missing_terms": list(meeting.missing_terms),
        "corpus_files": meeting.corpus_files,
        "quotable_passages": meeting.quotable_passages,
        "citation_audit": {
            "checked": meeting.audit.checked,
            "verified": meeting.audit.verified,
            "passed": meeting.audit.passed,
            "corpus_sha256": meeting.audit.corpus_sha256,
        },
        "verdict": {
            "agreed": meeting.verdict.agreed,
            "contested": meeting.verdict.contested,
            "next_move": meeting.verdict.next_move,
        },
        "quotes": [
            {
                "speaker": turn.speaker,
                "move": turn.move,
                "text": quote.text,
                "corpus_file": quote.source,
                "line": quote.line,
                **{k: v for k, v in sources.get(quote.source, {}).items() if k in ("anna_id", "url")},
            }
            for turn in meeting.turns
            for quote in turn.quotes
        ],
        "sources": sources,
    }
    return PanelResult(markdown=markdown, summary=summary)
