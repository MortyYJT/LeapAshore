from datetime import UTC, datetime

from app.models import AdvisorMessage, AdvisorThread, ApplicantProfile
from app.services.agent import run_recommendation_agent
from app.store import SQLiteStore


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


def test_sqlite_store_survives_adapter_restart(tmp_path) -> None:
    database_path = str(tmp_path / "offerpilot.db")
    first = SQLiteStore(database_path)
    token, user = first.login("Demo@OfferPilot.cn")
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

    restarted = SQLiteStore(database_path)
    assert restarted.user_for_token(token) == user
    assert restarted.get_profile(user.id) == profile
    assert restarted.list_runs(user.id)[0].run_id == result.run_id
    assert restarted.get_run(user.id, result.run_id) == result
    assert restarted.get_thread(user.id, thread.id) == thread
    assert restarted.list_threads(user.id) == [thread]


def test_sqlite_store_keeps_users_runs_isolated(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "offerpilot.db"))
    _, first_user = store.login("first@example.com")
    _, second_user = store.login("second@example.com")
    profile = store.save_profile(first_user.id, sample_profile())
    result = run_recommendation_agent(profile)
    store.save_run(first_user.id, profile, result)

    assert store.list_runs(second_user.id) == []
    assert store.get_run(second_user.id, result.run_id) is None
