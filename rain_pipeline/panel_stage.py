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

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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


def run(question: str, documents: list[Any], corpus_dir: Path) -> PanelResult:
    vendor.ensure_importable()
    from james_library.launcher.offline_meeting import build_offline_meeting
    from james_library.launcher.offline_meeting_view import render_markdown

    sources = write_corpus(documents, corpus_dir)
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
