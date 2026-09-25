# OfferPilot Projection Event Contract — 2026-09-25

Events are internal, versioned instructions for rebuilding MySQL/Milvus projections from PostgreSQL. They are not a public API and do not carry raw applicant data.

## Envelope

```json
{
  "event_id": "019c8f31-5f28-7b2a-9d42-0e4e0a5a8801",
  "event_type": "advisor.thread.changed",
  "schema_version": 1,
  "aggregate_type": "advisor_thread",
  "aggregate_id": "thread_7f2a8c91",
  "source_revision": 12,
  "occurred_at": "2026-09-25T12:00:00Z",
  "projection_targets": ["mysql-agent"],
  "payload": {
    "source_ref": "pg_thread_7f2a8c91",
    "content_hash": null,
    "status": "active"
  }
}
```

`event_id` is generated once and never changes on retry. `schema_version` versions this envelope and the named payload contract. `aggregate_id` is an opaque domain key, not email or account ID. `source_revision` is a monotonic per-aggregate revision. `occurred_at` is UTC. `projection_targets` is a fixed allowlist; handlers cannot accept a caller-provided URL or code. `payload` contains a lookup reference or approved content hash, never a password, bearer token, raw applicant profile, raw user question, model prompt/response, or source excerpt.

## Event types

| Event | Authority / revision | Payload | Projection behavior |
|---|---|---|---|
| `advisor.thread.changed` | PostgreSQL advisor thread revision | opaque owner ref, thread ref, current revision, message count, safe title hash | Fetch current thread by internal ref, then update MySQL projection only if revision is newer. Message-content projection, if retained, is fetched from PostgreSQL and protected by the data-ownership deletion/retention policy. |
| `advisor.thread.deleted` | PostgreSQL account/thread deletion revision | opaque owner ref, thread ref, deletion timestamp | Delete thread/message projection and checkpoint; write an idempotent deletion receipt. |
| `advisor.turn.completed` | PostgreSQL request ID and turn stage | request ref, workflow version, fixed provider class, tool names from registry, outcome, token counts | Write audit metadata only. Do not include prompt/reply text, personal identifiers, or arbitrary exception strings. |
| `program.source.published` | PostgreSQL published source `version_id` and source revision | program slug, version ID, content hash, verification time, publication status | Fetch the immutable published version; chunk and index in Milvus; record source revision and model/index versions. |
| `program.source.withdrawn` | PostgreSQL source revision and withdrawal status | program slug, version ID, content hash, withdrawn status | Tombstone the exact source-version chunks and prevent return before acknowledging. |
| `review.candidate.changed` | Approved review workflow revision | opaque candidate ref, owner ref if user-linked, status, candidate hash | Update MySQL review projection. It cannot publish a source or insert Milvus chunks. |
| `privacy.subject.deleted` | PostgreSQL account deletion transaction | opaque owner ref, tombstone revision, deletion time | Purge all owner-linked MySQL rows and checkpoints; delete indexed Langfuse traces when the protected trace-ID index is available; persist per-projection acknowledgement. |

## Transaction and delivery rules

1. A PostgreSQL outbox event is committed in the same transaction as the authoritative mutation it represents. The projection worker cannot observe an event for a rolled-back write.
2. The worker leases bounded batches, processes an event in a MySQL transaction, writes `(event_id, projection_name)` receipt, applies a compare-and-set revision, commits, then acknowledges the PostgreSQL outbox.
3. A crash after projection commit but before acknowledgement replays the same event; the receipt makes the replay a no-op.
4. If `source_revision <= applied_revision`, record the event receipt as stale and do not overwrite current state. For same revision with a different content hash, stop that aggregate and report a reconciliation conflict.
5. Projection failures retain the event with bounded retries and safe error class. Dead-letter state is operator-visible and replayable; event payload is not printed in logs.
6. Event handlers are deterministic and have no provider/model calls. Milvus embeddings are a separate idempotent job keyed by source version, chunk hash, model version, and collection version.
7. Projection reconciliation compares aggregate keys, source revisions, status, and content hashes. It never compares or logs raw user text.

## Current Store adapter caveat

`PostgresStore` currently performs some entity writes through autocommit helpers and separates advisor request reservation, action application, and final thread commit. The implementation must identify the authoritative transaction boundaries before adding outbox writes. PostgreSQL can provide durable outbox semantics; MemoryStore and SQLiteStore can provide test-compatible event behavior only and must not advertise production durability.

## Schema evolution

- Event consumers reject unknown major `schema_version` values without acknowledging them.
- Additive optional fields keep the same version only when old consumers safely ignore them.
- Breaking payload changes require a new version and a tested dual-reader or explicit drain/replay migration.
- Keep event records until all projection targets acknowledge or are explicitly rebuilt from the source of truth.
- Rebuild uses a named disposable projection namespace; it does not truncate a live collection or overwrite a non-empty production database.
