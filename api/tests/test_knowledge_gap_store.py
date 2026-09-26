from datetime import UTC, datetime

import pytest

from app.services.flywheel import knowledge_gap_candidate
from app.store import DemoStore, SQLiteStore


@pytest.mark.parametrize("store_factory", [DemoStore, lambda: SQLiteStore(":memory:")])
def test_knowledge_gaps_aggregate_without_persisting_raw_question_and_dedupe_events(store_factory) -> None:
    store = store_factory()
    now = datetime.now(UTC)
    first = knowledge_gap_candidate("UNSW 成绩门槛是什么？我的邮箱 pii@example.com", now=now)
    duplicate_form = knowledge_gap_candidate("UNSW 入学成绩要求", now=now)

    once = store.record_knowledge_gap(first, "turn-1")
    replay = store.record_knowledge_gap(duplicate_form, "turn-1")
    second = store.record_knowledge_gap(duplicate_form, "turn-2")

    assert once.id == replay.id == second.id
    assert second.occurrence_count == 2
    assert "pii@example.com" not in second.model_dump_json()
    assert "成绩门槛" not in second.model_dump_json()
    assert len(store.list_knowledge_gaps()) == 1


@pytest.mark.parametrize("store_factory", [DemoStore, lambda: SQLiteStore(":memory:")])
def test_knowledge_gap_updates_use_revision_compare_and_swap(store_factory) -> None:
    store = store_factory()
    candidate = knowledge_gap_candidate("UQ 学费 tuition fee")
    saved = store.record_knowledge_gap(candidate, "feedback-1")
    reviewed = saved.model_copy(update={"status": "reviewing"})

    updated = store.update_knowledge_gap(reviewed, expected_revision=0)

    assert updated and updated.revision == 1 and updated.status == "reviewing"
    assert store.update_knowledge_gap(reviewed, expected_revision=0) is None
