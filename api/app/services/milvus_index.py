from collections.abc import Sequence
import os
import re
from typing import Any

from pymilvus import DataType, Function, FunctionType

from .knowledge_chunks import PublishedKnowledgeChunk

_SAFE_SOURCE_REF = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_PROGRAM_SLUG = re.compile(r"^[a-z0-9-]{1,128}$")
_SECTIONS = {"项目概览", "学术与背景", "先修课与语言"}
OUTPUT_FIELDS = [
    "chunk_id", "text", "program_slug", "section", "source_version_id", "source_content_hash",
    "source_id", "source_title", "source_url", "verification_date", "embedding_model_version", "index_version", "schema_version",
]


class MilvusIndex:
    def __init__(self, client: Any, collection_name: str, dimensions: int, *, timeout_seconds: float = 5.0):
        if not collection_name or dimensions < 1:
            raise ValueError("collection name and positive embedding dimensions are required")
        self._client = client
        self.collection_name = collection_name
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def ensure_collection(self) -> bool:
        if self._client.has_collection(collection_name=self.collection_name):
            description = self._client.describe_collection(collection_name=self.collection_name)
            fields = {field["name"]: field for field in description.get("fields", [])}
            dense = fields.get("dense_vector", {})
            if int(dense.get("params", {}).get("dim", -1)) != self.dimensions:
                raise ValueError("Milvus collection embedding dimension mismatch")
            if "schema_version" not in fields:
                raise ValueError("Milvus collection schema version is unsupported")
            return False

        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=8192, enable_analyzer=True, analyzer_params={"type": "standard"})
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=self.dimensions)
        for name, length in (("program_slug", 128), ("section", 64), ("source_version_id", 128), ("source_content_hash", 64), ("source_id", 128), ("source_title", 512), ("source_url", 2048), ("verification_date", 32), ("embedding_model_version", 128), ("index_version", 128)):
            schema.add_field(field_name=name, datatype=DataType.VARCHAR, max_length=length)
        schema.add_field(field_name="schema_version", datatype=DataType.INT64)
        schema.add_function(Function(
            name="text_bm25",
            input_field_names=["text"],
            output_field_names=["sparse_vector"],
            function_type=FunctionType.BM25,
        ))
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )
        return True

    def upsert(self, chunks: Sequence[PublishedKnowledgeChunk | dict[str, Any]], embeddings: Sequence[Sequence[float]]) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunk and embedding counts must match")
        rows = []
        for chunk, vector in zip(chunks, embeddings, strict=True):
            if len(vector) != self.dimensions:
                raise ValueError("embedding dimension mismatch")
            get = (lambda key: getattr(chunk, key)) if isinstance(chunk, PublishedKnowledgeChunk) else chunk.__getitem__
            rows.append({
                "chunk_id": get("chunk_id"), "text": get("content"), "program_slug": get("program_slug"),
                "section": get("section"), "source_version_id": get("source_version_id"),
                "source_content_hash": get("source_content_hash"), "source_id": get("source_id"),
                "source_title": get("source_title"), "source_url": get("source_url"),
                "verification_date": get("verification_date"), "embedding_model_version": get("embedding_model_version"),
                "index_version": get("index_version"), "schema_version": 1, "dense_vector": [float(value) for value in vector],
            })
        if rows:
            self._client.upsert(collection_name=self.collection_name, data=rows, timeout=self.timeout_seconds)
        return len(rows)

    def delete_source_version(self, source_version_id: str) -> int:
        if not _SAFE_SOURCE_REF.fullmatch(source_version_id):
            raise ValueError("invalid source version identifier")
        result = self._client.delete(
            collection_name=self.collection_name,
            filter=f'source_version_id == "{source_version_id}"',
            timeout=self.timeout_seconds,
        )
        return int(result.get("delete_count", 0))

    @staticmethod
    def _filter_expr(program_slugs: Sequence[str] = (), section: str | None = None) -> str:
        clauses = []
        if program_slugs:
            if any(not _SAFE_PROGRAM_SLUG.fullmatch(slug) for slug in program_slugs):
                raise ValueError("invalid program filter")
            quoted = ", ".join(f'"{slug}"' for slug in sorted(set(program_slugs)))
            clauses.append(f"program_slug in [{quoted}]")
        if section:
            if section not in _SECTIONS:
                raise ValueError("invalid section filter")
            clauses.append(f'section == "{section}"')
        return " and ".join(clauses)

    def search_dense(self, embedding: Sequence[float], *, top_k: int = 10, program_slugs: Sequence[str] = (), section: str | None = None) -> list[Any]:
        if len(embedding) != self.dimensions:
            raise ValueError("embedding dimension mismatch")
        result = self._client.search(
            collection_name=self.collection_name,
            data=[[float(value) for value in embedding]],
            anns_field="dense_vector",
            filter=self._filter_expr(program_slugs, section),
            output_fields=OUTPUT_FIELDS,
            limit=top_k,
            timeout=self.timeout_seconds,
        )
        return result[0] if result else []

    def search_bm25(self, query: str, *, top_k: int = 10, program_slugs: Sequence[str] = (), section: str | None = None) -> list[Any]:
        if not query.strip():
            return []
        result = self._client.search(
            collection_name=self.collection_name,
            data=[query],
            anns_field="sparse_vector",
            filter=self._filter_expr(program_slugs, section),
            output_fields=OUTPUT_FIELDS,
            limit=top_k,
            timeout=self.timeout_seconds,
        )
        return result[0] if result else []

    def healthcheck(self) -> bool:
        try:
            self._client.list_collections()
            return True
        except Exception:
            return False


def milvus_index_from_env() -> MilvusIndex:
    uri = os.getenv("MILVUS_URI", "").strip()
    if not uri:
        raise ValueError("MILVUS_URI is required")
    collection = os.getenv("MILVUS_COLLECTION", "offerpilot_knowledge_v1")
    dimensions = int(os.getenv("MILVUS_EMBEDDING_DIMENSIONS", "1024"))
    timeout = max(1.0, float(os.getenv("MILVUS_TIMEOUT_SECONDS", "5")))
    from pymilvus import MilvusClient

    client = MilvusClient(uri=uri, token=os.getenv("MILVUS_TOKEN", ""), timeout=timeout)
    return MilvusIndex(client, collection, dimensions, timeout_seconds=timeout)
