# Milvus Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the MewHelp Milvus hybrid retrieval stack as a shadowable, rebuildable index of approved OfferPilot program facts.

**Architecture:** Build chunks from the same published program/source snapshot used by current BM25. Store dense and BM25 fields in Milvus Standalone backed by isolated etcd/MinIO volumes. Keep current BM25 as an always-available fallback and compare both retrievers on the same labeled Eval set before cutover.

**Tech Stack:** pymilvus, Milvus Standalone 2.6 series, etcd, MinIO, BGE-M3-compatible embedding API, BM25, RRF, optional Cross-Encoder reranker, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- Index only currently published and human-reviewed official facts.
- Store source ID, published version, content hash, verification date, chunk schema, embedding model, and index version.
- Apply structured program/degree/field filters before ranking; every result must retain citation metadata.
- MySQL, Milvus, etcd, and MinIO use distinct services, volumes, credentials, and network bindings from MewHelp and Langfuse.
- Never send user profile or applicant conversation text to embedding/reranker providers.

## Review Focus

- Published source rollback or withdrawal removes old index results even if the vector delete is delayed.
- Duplicate build event does not duplicate chunks; stale event cannot restore older facts.
- Wrong embedding dimension/model version fails closed rather than mixing incompatible vectors.
- Empty, typo, bilingual alias, and out-of-corpus query preserve honest no-answer behavior.
- Milvus/embed/rerank outage returns bounded fallback and never invents a hit.

---

### Task 1: Extend Eval and freeze corpus/index contract

**Files:**
- Modify: `api/evals/run_rag_eval.py`, `api/tests/test_rag.py`
- Create: `api/evals/data/rag_hybrid_cases.json`
- Create: `docs/superpowers/plans/evidence/2026-09-25-rag-hybrid-baseline.md`

**Interfaces:** Case fields: `query`, `program_slug`, `section`, `expected_source_id`, `must_reject`, `language`, and `query_type`. Results report Recall@3, MRR, top-1 program/section accuracy, citation correctness, no-answer accuracy, latency, and cost.

- [ ] Expand labeled cases for bilingual aliases, spelling variants, comparisons, score prerequisites, stale/withdrawn sources, and negative questions.
- [ ] Add a deterministic JSON schema check for each case and fail on an unknown program/source ID.
- [ ] Run `python -m evals.run_rag_eval` from `web/api/`; save baseline metrics and case-set hash.
- [ ] Record current BM25 thresholds and the exact current RAG gate from `docs/RAG_ARCHITECTURE.md`.
- [ ] Review the corpus contract for privacy and ensure no applicant-profile fields appear in fixtures.

### Task 2: Add versioned chunker and embedding adapter

**Files:**
- Create: `api/app/services/knowledge_chunks.py`
- Create: `api/app/services/embedding_provider.py`
- Create: `api/tests/test_knowledge_chunks.py`
- Create: `api/tests/test_embedding_provider.py`
- Modify: `api/app/settings.py`, `api/pyproject.toml`, `api/requirements.txt`

**Interfaces:** `build_published_chunks(snapshot) -> list[KnowledgeChunk]`; `embed_documents(texts, model_version) -> list[Embedding]`. Each chunk includes stable `chunk_id`, source version/hash, section, program facets, and content.

- [ ] Add tests proving only published source snapshot records yield chunks.
- [ ] Add chunk boundary tests ensuring requirement clauses remain attached to their exceptions and citations.
- [ ] Add provider tests for configured base URL/model, missing key, timeout, rate limit, response dimension mismatch, and redacted error logging.
- [ ] Implement stable IDs from program slug, section, and normalized published content hash.
- [ ] Run chunker and provider unit tests with stubbed HTTP responses; do not call paid upstream APIs in unit tests.

### Task 3: Deploy isolated Milvus dependencies and schema

**Files:**
- Modify: `compose.yaml`, `compose.production.yaml`
- Create: `api/app/services/milvus_index.py`
- Create: `api/tests/test_milvus_index.py`
- Modify: `.env.example`, `api/app/settings.py`

**Interfaces:** `MilvusIndex.ensure_collection(schema_version)`, `upsert(chunks)`, `delete_source_version(source_version_id)`, `search_dense(...)`, `search_bm25(...)`, `healthcheck()`.

- [ ] Add isolated Milvus, etcd, and MinIO services with health checks, private ports, named volumes, and non-default generated credentials.
- [ ] Define collection schema, BM25 analyzer, dense vector dimension, scalar filters, source metadata, and index version.
- [ ] Add adapter tests for idempotent upsert/delete, metadata filters, dimension mismatch, and unavailable service.
- [ ] Run disposable compose services and verify health checks without exposing MinIO/etcd to public interfaces.
- [ ] Document index recreation from PostgreSQL published-source records.

### Task 4: Implement RRF, optional reranking, and shadow comparison

**Files:**
- Modify: `api/app/services/knowledge_rag.py`
- Create: `api/app/services/hybrid_retrieval.py`
- Create: `api/app/services/reranker.py`
- Create: `api/evals/run_hybrid_rag_eval.py`
- Modify: `api/tests/test_rag.py`

**Interfaces:** `retrieve_hybrid(request, *, index, embedding, reranker=None) -> KnowledgeSearchResponse`. Return order is structured filter → BM25+dense retrieval → RRF → optional bounded rerank → source freshness validation.

- [ ] Add tests that each channel's rank contributes to RRF, duplicate chunks merge once, and scalar filters exclude unrelated programs.
- [ ] Add tests that reranker sees no more than configured candidate count and cannot add/remove citations.
- [ ] Add tests that expired or unpublished source hits are filtered before returning evidence.
- [ ] Implement feature flag default-off; shadow output stores rank/hash/score metadata only, no query or content.
- [ ] Run hybrid Eval against the same frozen case hash as Task 1 and compare every gate against current BM25.
- [ ] Enable hybrid reads only if the specified accuracy gates pass and latency/cost budget is approved; otherwise retain BM25 and keep Milvus build tooling available.

### Task 5: Add source outbox projection and index recovery

**Files:**
- Modify: `api/app/source_governance.py`, `api/app/postgres_store.py`
- Create: `api/app/services/milvus_projector.py`
- Create: `api/tests/test_milvus_projector.py`
- Create: `deploy/milvus-restore-smoke.sh`

**Interfaces:** Projector consumes approved/published source-version events and records applied source revision. Reconciliation reports missing, stale, duplicate, and hash-mismatch counts.

- [ ] Add tests that draft/rejected source versions never reach the projector.
- [ ] Add tests that rollback, withdrawal, and newer revisions tombstone or replace older index entries.
- [ ] Apply outbox event idempotency and revision checks from the data ownership contract.
- [ ] Add a rebuild command that drops/recreates only a named disposable collection and rebuilds from published PostgreSQL facts.
- [ ] Run source update → projector → query, and source rollback → projector → no stale query hit scenarios.
- [ ] Run RAG Eval, API tests, and Milvus restore/rebuild smoke before enabling the shadow flag.
