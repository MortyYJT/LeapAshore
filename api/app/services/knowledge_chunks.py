from dataclasses import dataclass
from hashlib import sha256
import re

from ..models import Program
from .knowledge_rag import build_knowledge_chunks

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PublishedProgramSnapshot:
    program: Program
    source_version_id: str
    content_hash: str
    status: str = "published"


@dataclass(frozen=True)
class PublishedKnowledgeChunk:
    chunk_id: str
    program_slug: str
    degree_level: str
    field: str
    section: str
    content: str
    source_version_id: str
    source_content_hash: str
    source_id: str
    source_title: str
    source_url: str
    verification_date: str
    embedding_model_version: str
    index_version: str


def build_published_chunks(
    snapshots: list[PublishedProgramSnapshot],
    *,
    embedding_model_version: str = "bge-m3-compatible-v1",
    index_version: str = "offerpilot-knowledge-v1",
) -> list[PublishedKnowledgeChunk]:
    chunks: list[PublishedKnowledgeChunk] = []
    for snapshot in snapshots:
        if snapshot.status != "published" or not snapshot.source_version_id or not _SHA256.fullmatch(snapshot.content_hash):
            continue
        for source_chunk in build_knowledge_chunks([snapshot.program]):
            source = snapshot.program.source.model_copy(update={
                "version_id": snapshot.source_version_id,
                "content_hash": snapshot.content_hash,
            })
            digest = sha256(
                f"{snapshot.program.slug}\0{snapshot.source_version_id}\0{source_chunk.section}\0{source_chunk.content}".encode()
            ).hexdigest()
            chunks.append(PublishedKnowledgeChunk(
                chunk_id=digest,
                program_slug=snapshot.program.slug,
                degree_level=snapshot.program.degree_level,
                field=snapshot.program.field,
                section=source_chunk.section,
                content=source_chunk.content,
                source_version_id=snapshot.source_version_id,
                source_content_hash=snapshot.content_hash,
                source_id=source.id,
                source_title=source.title,
                source_url=source.url,
                verification_date=source.verified_at,
                embedding_model_version=embedding_model_version,
                index_version=index_version,
            ))
    return chunks
