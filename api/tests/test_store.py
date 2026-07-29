from datetime import UTC, datetime

import pytest

from app.models import (
    AIConsent,
    ApplicationChoice,
    AdvisorMessage,
    AdvisorThread,
    AdvisorTurnRecord,
    ApplicantProfile,
)
from app.services.agent import run_recommendation_agent
from app.source_errors import SourceVersionConflictError
from app.source_governance import current_program, initialize_source_registry, new_candidate
from app.store import DemoStore, SQLiteStore


def sample_profile() -> ApplicantProfile:
    return ApplicantProfile(
        undergraduate_school="广东工业大学",
        school_tier="双非",
        undergraduate_major="软件工程",
        gpa=82,
        gpa_scale=100,
        target_field="计算机与数据",
        intake="2027 S1",
        english_score="IELTS 6.5",
        experience_summary="后端开发实习",
    )


def test_profile_migrates_the_legacy_aud_named_budget_to_cny() -> None:
    payload = sample_profile().model_dump()
    payload.pop("annual_budget_cny")
    profile = ApplicantProfile.model_validate({**payload, "annual_budget_aud": 450000})
    assert profile.annual_budget_cny == 450000
    dumped = profile.model_dump()
    assert dumped["annual_budget_cny"] == 450000
    assert "annual_budget_aud" not in dumped


def test_sqlite_store_survives_adapter_restart(tmp_path) -> None:
    database_path = str(tmp_path / "offerpilot.db")
    first = SQLiteStore(database_path)
    _, verification = first.register("Demo@OfferPilot.cn", "demo1234", "Demo")
    first.verify_email(verification)
    token, user = first.login("Demo@OfferPilot.cn", "demo1234")
    profile = first.save_profile(user.id, sample_profile())
    result = run_recommendation_agent(profile)
    first.save_run(user.id, profile, result)
    now = datetime.now(UTC)
    thread = AdvisorThread(
        id="thread_test",
        title="测试会话",
        messages=[AdvisorMessage(id="msg_test", role="assistant", content="你好", created_at=now)],
        created_at=now,
        updated_at=now,
    )
    first.save_thread(user.id, thread)
    turn = first.reserve_advisor_turn(user.id, AdvisorTurnRecord(
        request_id="sqlite-restart-request-1",
        thread_id=thread.id,
        mode="stream",
        content_hash="a" * 64,
        created_at=now,
        updated_at=now,
    ))
    turn = first.save_advisor_turn(user.id, turn.model_copy(update={
        "status": "planned",
        "updated_at": now,
    }))
    assert first.save_advisor_turn(
        user.id,
        turn.model_copy(update={"reply_text": "late same-stage overwrite"}),
    ) == turn
    assert first.save_advisor_turn(
        user.id,
        turn.model_copy(update={"status": "reserved"}),
    ) == turn
    choice = first.save_choice(user.id, ApplicationChoice(
        run_id=result.run_id, program_slug=result.recommendations[0].program.slug,
        status="applying", is_primary=True, updated_at=now,
    ))
    consent = first.save_ai_consent(user.id, AIConsent(accepted=True, updated_at=now))

    restarted = SQLiteStore(database_path)
    assert restarted.user_for_token(token) == user
    assert restarted.get_profile(user.id) == profile
    assert restarted.list_runs(user.id)[0].run_id == result.run_id
    assert restarted.get_run(user.id, result.run_id) == result
    assert restarted.get_thread(user.id, thread.id) == thread
    assert restarted.list_threads(user.id) == [thread]
    assert restarted.get_advisor_turn(user.id, turn.request_id) == turn
    assert restarted.get_choice(user.id, result.run_id, choice.program_slug) == choice
    assert restarted.list_choices(user.id, result.run_id) == [choice]
    assert restarted.get_ai_consent(user.id) == consent


def test_sqlite_store_keeps_users_runs_isolated(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "offerpilot.db"))
    _, first_verification = store.register("first@example.com", "demo1234", "First")
    _, second_verification = store.register("second@example.com", "demo1234", "Second")
    store.verify_email(first_verification)
    store.verify_email(second_verification)
    _, first_user = store.login("first@example.com", "demo1234")
    _, second_user = store.login("second@example.com", "demo1234")
    profile = store.save_profile(first_user.id, sample_profile())
    result = run_recommendation_agent(profile)
    store.save_run(first_user.id, profile, result)

    assert store.list_runs(second_user.id) == []
    assert store.get_run(second_user.id, result.run_id) is None


def test_sqlite_password_reset_is_single_use_and_revokes_sessions(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "offerpilot.db"))
    _, verification = store.register("reset@example.com", "before123", "Reset")
    store.verify_email(verification)
    session, _ = store.login("reset@example.com", "before123")
    _, reset_token = store.create_password_reset("reset@example.com") or (None, None)

    assert reset_token is not None
    store.reset_password(reset_token, "after1234")
    assert store.user_for_token(session) is None
    assert store.login("reset@example.com", "after1234")[1].email == "reset@example.com"


def test_choice_save_atomically_preserves_one_primary_in_memory() -> None:
    store = DemoStore()
    now = datetime.now(UTC)
    for slug in ["program-a", "program-b", "program-c"]:
        store.save_choice("user-1", ApplicationChoice(
            run_id="run-1", program_slug=slug, status="applying", is_primary=True, updated_at=now,
        ))

    choices = store.list_choices("user-1", "run-1")
    assert [choice.program_slug for choice in choices if choice.is_primary] == ["program-c"]


def test_advisor_turn_checkpoints_keep_the_first_same_stage_write_in_memory() -> None:
    store = DemoStore()
    now = datetime.now(UTC)
    reserved = store.reserve_advisor_turn("user-1", AdvisorTurnRecord(
        request_id="memory-same-stage-1",
        thread_id="thread-1",
        mode="stream",
        content_hash="a" * 64,
        created_at=now,
        updated_at=now,
    ))
    planned = store.save_advisor_turn("user-1", reserved.model_copy(update={
        "status": "planned",
        "reply_text": "first writer",
    }))

    assert store.save_advisor_turn(
        "user-1",
        planned.model_copy(update={"reply_text": "late overwrite"}),
    ) == planned
    assert store.get_advisor_turn("user-1", reserved.request_id) == planned


def test_choice_save_atomically_preserves_one_primary_in_sqlite(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "offerpilot.db"))
    _, verification = store.register("portfolio@example.com", "demo1234", "Portfolio")
    user = store.verify_email(verification)
    now = datetime.now(UTC)
    store.save_choice(user.id, ApplicationChoice(
        run_id="run-1", program_slug="program-a", status="applying", is_primary=True, updated_at=now,
    ))
    store.save_choice(user.id, ApplicationChoice(
        run_id="run-1", program_slug="program-b", status="applying", is_primary=True, updated_at=now,
    ))

    choices = store.list_choices(user.id, "run-1")
    assert [choice.program_slug for choice in choices if choice.is_primary] == ["program-b"]


def test_source_review_rejects_candidate_based_on_superseded_hash_in_memory() -> None:
    store = DemoStore()
    initialize_source_registry(store)
    published = next(
        item for item in store.list_program_source_versions("unsw-master-it")
        if item.status == "published"
    )
    first = new_candidate(
        current=published,
        proposed=published.program.model_copy(update={"duration": "2.25 年"}),
        submitted_by="reviewer-1",
    )
    second = new_candidate(
        current=published,
        proposed=published.program.model_copy(update={"duration": "2.5 年"}),
        submitted_by="reviewer-1",
    )
    store.save_program_source_version(first)
    store.save_program_source_version(second)

    approved = store.review_program_source_version(first.version_id, "approve", "reviewer-2", datetime.now(UTC))
    assert approved.status == "published"
    with pytest.raises(SourceVersionConflictError, match="发布版本已变化"):
        store.review_program_source_version(second.version_id, "approve", "reviewer-2", datetime.now(UTC))


def test_sqlite_persists_published_source_version_across_restart(tmp_path) -> None:
    database_path = str(tmp_path / "source-versions.db")
    first = SQLiteStore(database_path)
    initialize_source_registry(first)
    published = next(
        item for item in first.list_program_source_versions("uq-master-data-science")
        if item.status == "published"
    )
    candidate = new_candidate(
        current=published,
        proposed=published.program.model_copy(update={"duration": "2 年（测试版本）"}),
        submitted_by="reviewer-1",
    )
    first.save_program_source_version(candidate)
    first.review_program_source_version(candidate.version_id, "approve", "reviewer-2", datetime.now(UTC))

    restarted = SQLiteStore(database_path)
    restored = restarted.get_program_source_version(candidate.version_id)
    assert restored is not None
    assert restored.status == "published"
    assert restored.reviewed_by == "reviewer-2"
    assert next(
        item for item in restarted.list_program_source_versions("uq-master-data-science")
        if item.status == "published"
    ).version_id == candidate.version_id
    try:
        initialize_source_registry(restarted)
        assert current_program("uq-master-data-science").duration == "2 年（测试版本）"
    finally:
        initialize_source_registry(DemoStore())
