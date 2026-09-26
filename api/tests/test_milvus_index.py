import pytest

from app.services.milvus_index import MilvusIndex
from pymilvus import MilvusClient


class FakeClient:
    def __init__(self, collection_exists=False):
        self.collection_exists = collection_exists
        self.calls = []

    def has_collection(self, collection_name):
        return self.collection_exists

    def create_schema(self, **kwargs):
        return MilvusClient.create_schema(**kwargs)

    def prepare_index_params(self):
        class IndexParams:
            def __init__(self):
                self.indexes = []

            def add_index(self, **kwargs):
                self.indexes.append(kwargs)

        return IndexParams()

    def create_collection(self, **kwargs):
        self.calls.append(("create_collection", kwargs))
        self.collection_exists = True

    def describe_collection(self, collection_name):
        return {"fields": [{"name": "dense_vector", "params": {"dim": 2}}, {"name": "schema_version", "params": {"default_value": 1}}]}

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))
        return {"upsert_count": len(kwargs["data"])}

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"delete_count": 1}

    def list_collections(self):
        return []

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [[{"id": "chunk-1"}]]


def test_milvus_collection_uses_versioned_dense_and_bm25_schema() -> None:
    client = FakeClient()
    index = MilvusIndex(client, "offerpilot_knowledge_v1", 2)
    assert index.ensure_collection() is True
    _, args = client.calls[0]
    field_names = [field.name for field in args["schema"].fields]
    assert {"dense_vector", "sparse_vector", "text", "degree_level", "field", "source_version_id", "source_content_hash"} <= set(field_names)
    assert args["schema"].functions[0].name == "text_bm25"


def test_upsert_is_idempotent_by_chunk_id_and_rejects_wrong_dimensions() -> None:
    client = FakeClient(collection_exists=True)
    index = MilvusIndex(client, "offerpilot_knowledge_v1", 2)
    chunk = {
        "chunk_id": "chunk-1", "content": "approved fact", "program_slug": "uq-master-data-science",
        "degree_level": "授课型硕士", "field": "计算机与数据",
        "section": "学术与背景", "source_version_id": "v-1", "source_content_hash": "a" * 64,
        "source_id": "source-1", "source_title": "Official title", "source_url": "https://official.example", "verification_date": "2026-09-25",
        "embedding_model_version": "bge-test", "index_version": "index-1",
    }
    assert index.upsert([chunk], [[0.1, 0.2]]) == 1
    row = client.calls[-1][1]["data"][0]
    assert row["chunk_id"] == "chunk-1"
    assert row["dense_vector"] == [0.1, 0.2]
    with pytest.raises(ValueError, match="dimension"):
        index.upsert([chunk], [[0.1]])


def test_delete_source_version_uses_an_exact_safe_filter() -> None:
    client = FakeClient(collection_exists=True)
    index = MilvusIndex(client, "offerpilot_knowledge_v1", 2)
    index.delete_source_version("source-v2")
    assert client.calls[-1][1]["filter"] == 'source_version_id == "source-v2"'
    with pytest.raises(ValueError, match="invalid source version"):
        index.delete_source_version('x" or true')


def test_search_filters_are_built_from_validated_facets_only() -> None:
    client = FakeClient(collection_exists=True)
    index = MilvusIndex(client, "offerpilot_knowledge_v1", 2)
    assert index.search_dense([0.2, 0.3], program_slugs=["uq-master-data-science"], section="学术与背景")
    assert client.calls[-1][1]["filter"] == 'program_slug in ["uq-master-data-science"] and section == "学术与背景"'
    assert index._filter_expr(degree_level="授课型硕士", field="计算机与数据") == 'degree_level == "授课型硕士" and field == "计算机与数据"'
    with pytest.raises(ValueError, match="invalid program filter"):
        index.search_bm25("q", program_slugs=['x" or true'])


def test_existing_collection_with_wrong_vector_dimension_fails_closed() -> None:
    index = MilvusIndex(FakeClient(collection_exists=True), "offerpilot_knowledge_v1", 3)
    with pytest.raises(ValueError, match="dimension mismatch"):
        index.ensure_collection()
