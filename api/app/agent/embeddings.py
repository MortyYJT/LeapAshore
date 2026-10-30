"""Embeddings for the advisor's hybrid retrieval (openspec hybrid-retrieval D4, D5).

Programs and questions are embedded by SiliconFlow's ``BAAI/bge-m3`` over the OpenAI-compatible
``/embeddings`` endpoint. Nothing here runs without ``EMBED_API_KEY``: retrieval then ranks by full
text alone, and nothing about a question leaves the server.

A program's vector is stored in ``program_embeddings`` with the model and the sha256 of the text it was
made from. The backfill embeds exactly the programs whose row is missing or whose model or hash no
longer match, in batches that each commit, so it can be stopped at any point and run again: a second
run over an unchanged catalogue sends nothing.

    python -m app.agent.embeddings [--dry-run] [--limit N] [--batch-size N]
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.program import EMBEDDING_DIM, Program, ProgramEmbedding

log = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """The embedding service did not return a usable answer."""


@dataclass
class Embedded:
    vectors: list[list[float]]
    tokens: int  # as the service reported it; 0 when it reported nothing


class OpenAIEmbeddings:
    """A minimal client for an OpenAI-compatible ``POST {base_url}/embeddings``."""

    def __init__(self, base_url: str, model: str, api_key: str, timeout: float,
                 transport: httpx.BaseTransport | None = None):
        self.model = model
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout
        self._transport = transport

    def embed(self, texts: list[str]) -> Embedded:
        if not texts:
            return Embedded([], 0)
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(self._url, headers=self._headers, json={
                    "model": self.model, "input": texts, "encoding_format": "float",
                })
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"{exc.__class__.__name__}: {exc}") from exc
        if response.status_code != 200:
            # The body can echo the request; keep the status and a short head of it only.
            raise EmbeddingError(f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
            rows = sorted(body["data"], key=lambda d: d["index"])
            vectors = [list(map(float, d["embedding"])) for d in rows]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"unexpected response: {exc.__class__.__name__}") from exc
        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIM for v in vectors):
            raise EmbeddingError(
                f"expected {len(texts)} vectors of {EMBEDDING_DIM}, got {[len(v) for v in vectors]}"
            )
        usage = body.get("usage") or {}
        return Embedded(vectors, int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0))


def configured_client() -> OpenAIEmbeddings | None:
    """The client for the configured service, or None when no key is set."""
    if not settings.embed_api_key.strip():
        return None
    return OpenAIEmbeddings(settings.embed_base_url, settings.embed_model, settings.embed_api_key,
                            settings.embed_timeout_seconds)


def embed_query(text: str, client: OpenAIEmbeddings | None = None) -> list[float] | None:
    """The question's vector, or None when embeddings are off or the service failed. A failure is
    logged and the caller ranks by full text, so the advisor keeps answering (D5)."""
    client = client or configured_client()
    if client is None or not text.strip():
        return None
    try:
        return client.embed([text]).vectors[0]
    except EmbeddingError as exc:
        log.warning("query embedding failed, ranking by full text only: %s", exc)
        return None


# ---- programs ---------------------------------------------------------------------------------


def program_text(name: str | None, name_en: str | None, field: str | None) -> str:
    """What a program's vector is made from: its names and study area, never its school (the school is
    a filter, not a similarity)."""
    parts = [name_en or name or ""]
    if name and name != name_en:
        parts.append(name)
    if field:
        parts.append(field)
    return "\n".join(p for p in parts if p)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Pending:
    program_id: str
    text: str
    sha256: str


def stale_programs(session: Session, model: str) -> list[Pending]:
    """Programs with no vector for `model`, or one made from different text; in id order, so a
    resumed run continues where the last one stopped."""
    rows = session.execute(
        select(Program.id, Program.name, Program.name_en, Program.field,
               ProgramEmbedding.model, ProgramEmbedding.content_sha256)
        .outerjoin(ProgramEmbedding, ProgramEmbedding.program_id == Program.id)
        .order_by(Program.id)
    ).all()
    out = []
    for r in rows:
        text = program_text(r.name, r.name_en, r.field)
        digest = content_hash(text)
        if r.model != model or r.content_sha256 != digest:
            out.append(Pending(r.id, text, digest))
    return out


def _store(session: Session, model: str, batch: list[Pending], vectors: list[list[float]]) -> None:
    statement = insert(ProgramEmbedding).values([
        {"program_id": p.program_id, "model": model, "content_sha256": p.sha256, "embedding": v}
        for p, v in zip(batch, vectors)
    ])
    session.execute(statement.on_conflict_do_update(
        index_elements=[ProgramEmbedding.program_id],
        set_={"model": statement.excluded.model, "content_sha256": statement.excluded.content_sha256,
              "embedding": statement.excluded.embedding, "embedded_at": statement.excluded.embedded_at},
    ))


def backfill(session_factory, client: OpenAIEmbeddings, batch_size: int = 32, limit: int | None = None,
             dry_run: bool = False) -> dict:
    """Embed the stale programs, one committed batch at a time. Stops at the first service error and
    reports it; whatever was stored before stays, and the next run picks up the rest."""
    started = time.monotonic()
    with session_factory() as session:
        todo = stale_programs(session, client.model)
    stale = len(todo)
    if limit is not None:
        todo = todo[:limit]
    report = {
        "model": client.model, "stale": stale, "embedded": 0, "skipped": 0, "batches": 0, "tokens": 0,
        "characters": sum(len(p.text) for p in todo),
    }
    if dry_run:
        report["seconds"] = round(time.monotonic() - started, 2)
        return report
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        try:
            result = client.embed([p.text for p in batch])
        except EmbeddingError as exc:
            report["error"] = str(exc)
            break
        with session_factory() as session:
            try:
                _store(session, client.model, batch, result.vectors)
                session.commit()
            except IntegrityError:
                # A program deleted since the list was read; the rest of the batch goes next run.
                session.rollback()
                report["skipped"] += len(batch)
                continue
        report["embedded"] += len(batch)
        report["batches"] += 1
        report["tokens"] += result.tokens
    report["cost_cny"] = round(report["tokens"] * settings.embed_price_cny_per_mtok / 1_000_000, 6)
    report["seconds"] = round(time.monotonic() - started, 2)
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Embed the programs whose vector is missing or stale.")
    parser.add_argument("--dry-run", action="store_true", help="count what would be sent, send nothing")
    parser.add_argument("--limit", type=int, help="embed at most this many programs")
    parser.add_argument("--batch-size", type=int, default=settings.embed_batch_size)
    args = parser.parse_args(argv)
    from app.db import SessionLocal

    client = configured_client()
    if client is None:
        if not args.dry_run:
            print("EMBED_API_KEY is not set; nothing sent.", file=sys.stderr)
            return 2
        client = OpenAIEmbeddings(settings.embed_base_url, settings.embed_model, "", 1.0)
    report = backfill(SessionLocal, client, batch_size=args.batch_size, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False))
    return 1 if "error" in report else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
