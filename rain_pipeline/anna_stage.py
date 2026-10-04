"""Stage 1 — Anna: literature in, a sealed and verified research record out.

Runs Anna's own engine in-process against an embedded PostgreSQL (``pgserver``
bundles Postgres 16 + pgvector, so no Docker or system install is needed):

1. ingest arXiv metadata for the spec's queries with Anna's arXiv plugin;
2. hybrid search (Anna's lexical + vector legs fused with RRF);
3. Anna's extractive, citation-first summary;
4. package everything as an ``anna-research-record/v1`` packet, sealed with
   Anna's canonical-JSON SHA-256 fingerprint, and immediately re-verified
   against the index with Anna's own ``records.verify_record``.

Embeddings use Anna's documented deterministic fallback (token hashing). That
is honest lexical-ish retrieval, not semantic search; the retrieval report in
the record says so (``"embedding": "hashing"``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import vendor

DATABASE = "anna"
INDEX = "rain_pipeline_docs"


@dataclass(frozen=True)
class AnnaResult:
    packet: dict[str, Any]          # {captured_at, content_sha256, record}
    verification: dict[str, Any]    # records.verify_record report
    ingestion: list[dict[str, Any]]
    documents: list[Any]            # engine.documents.Document, in rank order

    @property
    def fingerprint(self) -> str:
        return self.packet["content_sha256"]


class EmbeddedPostgres:
    """Start (or reuse) the pipeline's private PostgreSQL under ``.pgdata``."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._server = None

    def __enter__(self) -> str:
        import pgserver

        self._server = pgserver.get_server(self.data_dir, cleanup_mode="stop")
        self._server.psql(
            f"select 'create database {DATABASE}' "
            f"where not exists (select from pg_database where datname='{DATABASE}')\\gexec"
        )
        return self._server.get_uri().rsplit("/", 1)[0] + f"/{DATABASE}"

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.cleanup()


def configure_engine(database_url: str) -> None:
    """Anna reads its config once (``lru_cache``); set it before the first engine import."""
    os.environ.update(
        ENGINE_BACKEND="postgres",
        ENGINE_EMBEDDING_FALLBACK="true",
        DATABASE_URL=database_url,
        ENGINE_INDEX=INDEX,
    )
    vendor.ensure_importable()


def ingest(queries: list[str], limit_per_query: int) -> list[dict[str, Any]]:
    """Pull arXiv metadata into the index. One failing query never aborts the rest."""
    from engine import backend
    from engine.ingest import IngestionPipeline

    backend.create_index()
    pipeline = IngestionPipeline()
    report = []
    for query in queries:
        try:
            stats = pipeline.run("arxiv", query=query, limit=limit_per_query)
            report.append({"query": query, **stats.as_dict()})
        except Exception as exc:  # network down, arXiv throttling, ...
            report.append({"query": query, "indexed": 0, "error": f"{type(exc).__name__}: {exc}"})
    return report


def search_and_seal(query: str, per_page: int) -> tuple[dict[str, Any], list[Any]]:
    """Search, summarize and build the record exactly as Anna's workbench exports it."""
    from allthethings.engine_api.serialize import results_to_dict
    from engine import backend, records
    from engine.summarize import Summarizer

    config = backend.get_config()
    results = backend.get_search_service(config).search(
        query, mode="hybrid", page=1, per_page=per_page, include_facets=False
    )
    documents = [hit.document for hit in results.hits]
    summary = Summarizer(config).summarize(results.query, documents).to_dict() if documents else None
    data = results_to_dict(results)

    # Mirrors createRecord() in vendor/anna/frontend/evidence.js field for field.
    record = {
        "schema": records.RECORD_SCHEMA,
        "provider": "live",
        "request": {"q": query, "mode": "hybrid", "page": 1, "per_page": per_page, "filters": {}},
        "retrieval": data["retrieval"],
        "result_count": data["total"],
        "scope": "current-page",
        "hits": [_record_hit(hit) for hit in data["hits"]],
        "summary": summary,
    }
    packet = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "content_sha256": records.fingerprint(record),
        "record": record,
    }
    return packet, documents


def _record_hit(hit: dict[str, Any]) -> dict[str, Any]:
    doc = hit["document"]
    entry = {
        "score": hit["score"],
        "explanation": hit.get("explanation"),
        "document": {
            "id": doc["id"],
            "title": doc["title"],
            "source": doc["source"],
            "url": doc.get("url") or "",
            "pdf_url": doc.get("pdf_url") or "",
            "authors": doc.get("authors") or [],
            "published": doc.get("published") or "",
            "version": doc.get("version") or "",
            "abstract": doc.get("abstract") or "",
        },
        "highlights": hit.get("highlights") or [],
    }
    if hit.get("relevance") is not None:
        entry["relevance"] = hit["relevance"]
    return entry


def verify(packet: dict[str, Any]) -> dict[str, Any]:
    """Re-read every cited excerpt from the live index (Anna's own verifier)."""
    from engine import backend, records

    config = backend.get_config()
    return records.verify_record(
        packet,
        backend.get_document,
        checked_against={"backend": config.backend, "index": config.index_name},
    )


def run(spec: dict[str, Any], *, pgdata: Path, offline: bool) -> AnnaResult:
    literature = spec["literature"]
    with EmbeddedPostgres(pgdata) as database_url:
        configure_engine(database_url)
        if offline:
            ingestion = [{"skipped": "offline; searching the existing index only"}]
        else:
            ingestion = ingest(literature["arxiv_queries"], literature["limit_per_query"])

        from engine import backend

        if backend.count() == 0:
            raise RuntimeError(
                "Anna's index is empty. Run once without --offline so arXiv metadata can be ingested."
            )
        packet, documents = search_and_seal(literature["search"], literature["max_sources"])
        if not documents:
            raise RuntimeError(f"Anna found no sources for {literature['search']!r}; refine 'literature.search'.")
        verification = verify(packet)
    return AnnaResult(packet=packet, verification=verification, ingestion=ingestion, documents=documents)
