from fastapi.testclient import TestClient

from app.main import app
from main import app as service_app


client = TestClient(app)


def registered_login(email: str, password: str = "demo1234"):
    registered = client.post("/auth/register", json={
        "email": email, "password": password, "display_name": "测试用户", "accepted_terms": True,
    })
    assert registered.status_code == 201
    token = registered.json()["debug_token"]
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    return client.post("/auth/login", json={"email": email, "password": password})


def test_vercel_service_entrypoint_exports_the_application() -> None:
    response = TestClient(service_app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}
    readiness = client.get("/health/readiness").json()
    assert readiness == {
        "status": "ready", "llm": "fallback", "storage": "DemoStore", "database": "connected", "email": "console",
    }


def test_llm_status_never_exposes_the_api_key(monkeypatch) -> None:
    body = client.get("/llm/status").json()
    assert body["api"] == "responses"
    assert body["model"] == "qwen2.5:0.5b"
    assert "key" not in body
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    ollama = client.get("/llm/status").json()
    assert ollama == {"configured": True, "provider": "ollama", "model": "qwen2.5:0.5b", "api": "ollama-chat"}


def test_login_rejects_a_wrong_password_after_account_creation() -> None:
    assert registered_login("secure@offerpilot.cn", "first-pass1").status_code == 200
    assert client.post("/auth/login", json={"email": "secure@offerpilot.cn", "password": "wrong-pass1"}).status_code == 401


def test_registration_requires_verification_and_logout_revokes_session() -> None:
    registered = client.post("/auth/register", json={
        "email": "lifecycle@offerpilot.cn", "password": "secure123", "display_name": "Lifecycle", "accepted_terms": True,
    })
    assert registered.status_code == 201
    assert registered.json()["user"]["email_verified"] is False
    assert registered.json()["user"]["terms_version"] == "2026-07-15"
    assert registered.json()["user"]["terms_accepted_at"] is not None
    assert client.post("/auth/login", json={"email": "lifecycle@offerpilot.cn", "password": "secure123"}).status_code == 403

    verification = registered.json()["debug_token"]
    assert client.post("/auth/verify-email", json={"token": verification}).status_code == 200
    login = client.post("/auth/login", json={"email": "lifecycle@offerpilot.cn", "password": "secure123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/me", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/me", headers=headers).status_code == 401


def test_registration_recovers_when_transactional_email_is_temporarily_unavailable(monkeypatch) -> None:
    from app.mailer import EmailDeliveryError

    def fail_delivery(*_: object) -> str:
        raise EmailDeliveryError("provider unavailable")

    monkeypatch.setattr("app.main.send_verification_email", fail_delivery)
    response = client.post("/auth/register", json={
        "email": "smtp-outage@offerpilot.cn",
        "password": "secure123",
        "display_name": "SMTP Outage",
        "accepted_terms": True,
    })
    assert response.status_code == 201
    assert response.json()["delivery"] == "disabled"
    assert "稍后点击重新发送" in response.json()["message"]


def test_registration_debug_token_requires_an_explicit_local_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("EXPOSE_DEBUG_TOKENS", "false")
    response = client.post("/auth/register", json={
        "email": "no-debug-token@offerpilot.cn",
        "password": "secure123",
        "display_name": "No Debug Token",
        "accepted_terms": True,
    })
    assert response.status_code == 201
    assert response.json()["debug_token"] is None


def test_http_only_cookie_restores_same_origin_session() -> None:
    login = registered_login("cookie-session@offerpilot.cn")
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "samesite=lax" in login.headers["set-cookie"].lower()
    assert client.get("/me").json()["email"] == "cookie-session@offerpilot.cn"
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/me").status_code == 401


def test_logout_is_idempotent_and_clears_a_stale_session_cookie() -> None:
    stale_client = TestClient(app)
    stale_client.cookies.set("offerpilot_session", "revoked-session-token")

    response = stale_client.post("/auth/logout")

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert "offerpilot_session=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "samesite=lax" in set_cookie


def test_admin_can_review_feedback_and_suspend_users() -> None:
    user_login = registered_login("feedback-user@offerpilot.cn")
    user_headers = {"Authorization": f"Bearer {user_login.json()['access_token']}"}
    feedback = client.post("/me/feedback", headers=user_headers, json={
        "category": "建议", "message": "希望增加奖学金筛选", "page": "results",
    })
    assert feedback.status_code == 201
    assert client.get("/admin/stats", headers=user_headers).status_code == 403

    admin_login = registered_login("admin@offerpilot.cn")
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    stats = client.get("/admin/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["open_feedback"] >= 1
    assert len(client.get("/admin/program-sources", headers=admin_headers).json()) >= 6
    reviewed = client.put(
        f"/admin/feedback/{feedback.json()['id']}", headers=admin_headers, json={"status": "resolved"},
    )
    assert reviewed.json()["status"] == "resolved"
    suspended = client.put(
        f"/admin/users/{feedback.json()['user_id']}", headers=admin_headers, json={"status": "suspended"},
    )
    assert suspended.json()["status"] == "suspended"
    assert client.get("/me", headers=user_headers).status_code == 401


def test_user_can_export_and_delete_account_data() -> None:
    login = registered_login("data-rights@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.post("/me/feedback", headers=headers, json={"category": "其他", "message": "export me"})

    exported = client.get("/me/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["account"]["email"] == "data-rights@offerpilot.cn"
    assert len(exported.json()["feedback"]) == 1
    assert client.request("DELETE", "/me", headers=headers, json={"password": "wrong123", "confirmation": "DELETE"}).status_code == 401
    assert client.request("DELETE", "/me", headers=headers, json={"password": "demo1234", "confirmation": "DELETE"}).status_code == 200
    assert client.get("/me", headers=headers).status_code == 401


def test_recommendations_return_all_go8_members() -> None:
    response = client.post(
        "/recommendations",
        json={
            "undergraduate_school": "示例大学",
            "school_tier": "双非",
            "undergraduate_major": "软件工程",
            "gpa": 82,
            "gpa_scale": 100,
            "target_field": "计算机与数据",
            "intake": "2027 S1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm_version"] == "0.1.0"
    assert len(body["recommendations"]) == 8


def test_agent_returns_programs_tools_and_citations() -> None:
    response = client.post(
        "/agent/recommendations",
        json={
            "undergraduate_school": "示例大学",
            "school_tier": "双非",
            "undergraduate_major": "软件工程",
            "gpa": 82,
            "gpa_scale": 100,
            "target_field": "计算机与数据",
            "intake": "2027 S1",
            "english_score": "IELTS 6.5",
            "experience_summary": "后端开发实习",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_version"] == "agent-0.5.0"
    assert body["profile_snapshot"]["undergraduate_school"] == "示例大学"
    assert len(body["tool_trace"]) == 6
    assert len(body["catalog_options"]) == 8
    assert len(body["recommendations"]) >= 6
    assert all(item["citations"] for item in body["recommendations"])
    assert all(item["program"]["source"]["url"].startswith("https://") for item in body["recommendations"])


def test_agent_flags_missing_language_and_prerequisite_evidence() -> None:
    response = client.post(
        "/agent/recommendations",
        json={
            "undergraduate_school": "示例大学",
            "school_tier": "双非",
            "undergraduate_major": "市场营销",
            "gpa": 68,
            "gpa_scale": 100,
            "target_field": "计算机与数据",
            "intake": "2027 S1",
        },
    )

    body = response.json()
    assert "语言成绩" in body["missing_information"]
    assert "用于确认先修课的成绩单课程列表" in body["missing_information"]
    assert any(item["tier"] == "暂不推荐" for item in body["recommendations"])


def test_agent_never_marks_unverified_prerequisites_or_language_as_satisfied() -> None:
    base = {
        "undergraduate_school": "示例大学",
        "school_tier": "双非",
        "undergraduate_major": "软件工程",
        "gpa": 82,
        "gpa_scale": 100,
        "target_field": "计算机与数据",
        "intake": "2027 S1",
        "english_score": "IELTS 7.0",
    }
    missing_courses = client.post("/agent/recommendations", json=base).json()
    uq = next(item for item in missing_courses["recommendations"] if item["program"]["slug"] == "uq-master-data-science")
    assert uq["eligibility"] == "需要人工核验"
    assert next(step for step in missing_courses["tool_trace"] if step["tool"] == "check_hard_constraints")["status"] == "needs_input"

    verified = client.post("/agent/recommendations", json={
        **base,
        "english_score": "IELTS 7.0，单项 6.5",
        "coursework_summary": "高等数学、线性代数、概率统计、Python 程序设计、数据库系统",
    }).json()
    verified_uq = next(item for item in verified["recommendations"] if item["program"]["slug"] == "uq-master-data-science")
    assert verified_uq["eligibility"] == "满足基础门槛"


def test_agent_treats_a_published_minimum_shortfall_as_a_hard_gap() -> None:
    response = client.post("/agent/recommendations", json={
        "undergraduate_school": "示例大学",
        "school_tier": "双非",
        "undergraduate_major": "软件工程",
        "gpa": 68,
        "gpa_scale": 100,
        "target_field": "计算机与数据",
        "english_score": "IELTS 7.0，单项 6.5",
        "coursework_summary": "高等数学、线性代数、概率统计、数据结构、数据库",
    }).json()
    unsw = next(item for item in response["recommendations"] if item["program"]["slug"] == "unsw-master-it")
    assert unsw["tier"] == "暂不推荐"
    assert unsw["eligibility"] == "存在门槛缺口"
    assert any("70%" in risk for risk in unsw["risks"])


def test_agent_covers_every_go8_degree_and_study_area_without_inventing_rules() -> None:
    facets = client.get("/catalog/facets").json()
    assert facets["coverage_cells"] == 384
    for degree_level in facets["degree_levels"]:
        for field in facets["study_areas"]:
            response = client.post("/agent/recommendations", json={
                "current_education_level": "本科",
                "undergraduate_school": "示例大学",
                "school_tier": "双非",
                "undergraduate_major": "示例专业",
                "gpa": 80,
                "gpa_scale": 100,
                "target_degree_level": degree_level,
                "target_field": field,
                "intake": "2027 S1",
            })
            assert response.status_code == 200
            body = response.json()
            assert len(body["catalog_options"]) == 8
            assert {item["degree_level"] for item in body["catalog_options"]} == {degree_level}
            assert {item["field"] for item in body["catalog_options"]} == {field}
            if not body["recommendations"]:
                assert "暂不生成录取分档" in body["summary"]


def test_complete_authenticated_product_flow() -> None:
    login = registered_login("demo@offerpilot.cn")
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    profile = {
        "undergraduate_school": "示例大学",
        "school_tier": "双非",
        "undergraduate_major": "软件工程",
        "gpa": 82,
        "gpa_scale": 100,
        "target_field": "计算机与数据",
        "intake": "2027 S1",
        "english_score": "IELTS 6.5",
        "experience_summary": "AI 应用项目",
    }
    assert client.put("/me/profile", json=profile, headers=headers).status_code == 200
    assert client.get("/me/profile", headers=headers).json()["undergraduate_major"] == "软件工程"

    run = client.post("/me/recommendation-runs", headers=headers)
    assert run.status_code == 200
    run_id = run.json()["run_id"]
    assert len(client.get("/me/recommendation-runs", headers=headers).json()) == 1

    action_plan = client.get(f"/me/recommendation-runs/{run_id}/action-plan", headers=headers)
    assert action_plan.status_code == 200
    assert len(action_plan.json()["items"]) == 6
    assert len(client.get("/me/tasks", headers=headers).json()) == 6


def test_portfolio_enforces_one_primary_and_builds_program_branches() -> None:
    login = registered_login("portfolio@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    profile = {
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "intake": "2027 S1",
    }
    assert client.put("/me/profile", json=profile, headers=headers).status_code == 200
    run = client.post("/me/recommendation-runs", headers=headers).json()
    run_id = run["run_id"]
    slugs = [item["program"]["slug"] for item in client.get(f"/me/recommendation-runs/{run_id}", headers=headers).json()["recommendations"]]

    first = client.put(
        f"/me/recommendation-runs/{run_id}/portfolio/{slugs[0]}", headers=headers,
        json={"status": "applying", "is_primary": True},
    )
    assert first.status_code == 200
    second = client.put(
        f"/me/recommendation-runs/{run_id}/portfolio/{slugs[1]}", headers=headers,
        json={"status": "applying", "is_primary": True},
    )
    assert second.status_code == 200
    portfolio = client.get(f"/me/recommendation-runs/{run_id}/portfolio", headers=headers).json()
    assert sum(item["is_primary"] for item in portfolio) == 1
    assert next(item for item in portfolio if item["program_slug"] == slugs[1])["is_primary"] is True
    assert next(item for item in portfolio if item["program_slug"] == slugs[0])["status"] == "applying"

    roadmap = client.get(f"/me/recommendation-runs/{run_id}/roadmap", headers=headers)
    assert roadmap.status_code == 200
    assert len(roadmap.json()["phases"]) == 6
    assert {item["program_slug"] for item in roadmap.json()["program_branches"]} == {slugs[0], slugs[1]}
    assert len(client.get("/me/tasks", headers=headers).json()) == 8


def test_portfolio_rejects_programs_outside_the_users_run() -> None:
    login = registered_login("portfolio-isolation@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", headers=headers, json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "intake": "2027 S1",
    })
    run_id = client.post("/me/recommendation-runs", headers=headers).json()["run_id"]
    response = client.put(
        f"/me/recommendation-runs/{run_id}/portfolio/not-in-this-run", headers=headers,
        json={"status": "applying", "is_primary": False},
    )
    assert response.status_code == 404


def test_roadmap_getters_do_not_write_tasks(monkeypatch) -> None:
    import importlib

    main_module = importlib.import_module("app.main")
    login = registered_login("roadmap-readonly@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "intake": "2027 S1",
    }, headers=headers)
    run_id = client.post("/me/recommendation-runs", headers=headers).json()["run_id"]

    def forbidden_write(*_args, **_kwargs):
        raise AssertionError("GET roadmap attempted to mutate task persistence")

    monkeypatch.setattr(main_module.store, "save_task", forbidden_write)
    assert client.get(f"/me/recommendation-runs/{run_id}/roadmap", headers=headers).status_code == 200
    assert client.get(f"/me/recommendation-runs/{run_id}/action-plan", headers=headers).status_code == 200


def test_advisor_conversation_updates_profile_and_reruns_recommendations() -> None:
    login = registered_login("advisor@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    profile = {
        "undergraduate_school": "示例大学",
        "school_tier": "双非",
        "undergraduate_major": "软件工程",
        "gpa": 82,
        "gpa_scale": 100,
        "target_field": "计算机与数据",
        "intake": "2027 S1",
    }
    client.put("/me/profile", json=profile, headers=headers)
    created = client.post("/me/advisor/threads", headers=headers)
    assert created.status_code == 200

    reply = client.post(
        f"/me/advisor/threads/{created.json()['id']}/messages",
        json={"content": "雅思 7.0，每年预算 50 万，悉尼优先，请重新推荐学校"},
        headers={**headers, "Idempotency-Key": "advisor-profile-run-1"},
    )
    assert reply.status_code == 200
    body = reply.json()
    assert body["provider"] == "deterministic-fallback"
    assert body["profile"]["english_score"] == "IELTS 7.0"
    assert body["profile"]["annual_budget_cny"] == 500000
    assert body["recommendation_run"] is not None
    assert [item["tool"] for item in body["thread"]["messages"][-1]["actions"]] == [
        "update_profile",
        "run_recommendation",
    ]
    audits = client.get("/me/advisor/audits", headers=headers).json()
    assert audits[0]["provider"] == "deterministic-fallback"
    assert audits[0]["tools"] == ["update_profile", "run_recommendation"]
    assert audits[0]["prompt_version"] == "advisor-1.0.0"


def test_transcript_analysis_maps_courses_to_program_prerequisites() -> None:
    login = registered_login("transcript@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    profile = {
        "undergraduate_school": "示例大学",
        "school_tier": "双非",
        "undergraduate_major": "软件工程",
        "gpa": 82,
        "gpa_scale": 100,
        "target_field": "计算机与数据",
    }
    client.put("/me/profile", json=profile, headers=headers)
    response = client.post(
        "/me/transcript/analyze",
        json={"transcript_text": "高等数学 88\n线性代数 85\n数据结构 90\nPython 程序设计 92\n数据库系统 87"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["courses"]) == 5
    uq = next(item for item in body["program_matches"] if item["program_slug"] == "uq-master-data-science")
    assert uq["status"] == "满足"
    assert client.get("/me/profile", headers=headers).json()["coursework_summary"].startswith("高等数学")


def test_tasks_can_be_created_and_progressed() -> None:
    login = registered_login("tasks@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = client.post(
        "/me/tasks",
        json={"title": "预约雅思考试", "detail": "选择两个月后的场次", "category": "语言", "priority": "P0"},
        headers=headers,
    )
    assert created.status_code == 200
    updated = client.put(f"/me/tasks/{created.json()['id']}", json={"status": "已完成"}, headers=headers)
    assert updated.json()["status"] == "已完成"
    assert client.get("/me/tasks", headers=headers).json()[0]["title"] == "预约雅思考试"


def test_advisor_can_create_an_application_task() -> None:
    login = registered_login("advisor-task@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据",
    }, headers=headers)
    thread = client.post("/me/advisor/threads", headers=headers).json()
    response = client.post(
        f"/me/advisor/threads/{thread['id']}/messages",
        json={"content": "提醒我准备英文成绩单"},
        headers={**headers, "Idempotency-Key": "advisor-create-task-1"},
    )
    assert response.status_code == 200
    assert client.get("/me/tasks", headers=headers).json()[0]["title"] == "准备英文成绩单"


def test_advisor_idempotency_recovers_after_actions_before_thread_write(monkeypatch) -> None:
    import importlib

    import pytest

    from app.models import AdvisorAction

    main_module = importlib.import_module("app.main")
    login = registered_login("advisor-idempotency@offerpilot.cn")
    user_id = login.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "intake": "2027 S1",
    }, headers=headers)
    run = client.post("/me/recommendation-runs", headers=headers).json()
    program_slug = run["recommendations"][0]["program"]["slug"]
    thread = client.post("/me/advisor/threads", headers=headers).json()
    content = "把悉尼设为偏好、首选当前项目，并提醒我准备材料"
    request_headers = {**headers, "Idempotency-Key": "advisor-effect-window-1"}
    plan_calls = 0

    def planned_turn(_message, _profile, _history):
        nonlocal plan_calls
        plan_calls += 1
        return (
            "已更新档案、申请组合和材料待办。",
            [
                AdvisorAction(
                    tool="update_profile",
                    summary="更新城市偏好",
                    arguments={"location_preferences": "悉尼优先"},
                ),
                AdvisorAction(
                    tool="set_application_choice",
                    summary="设置首选项目",
                    arguments={
                        "run_id": run["run_id"],
                        "program_slug": program_slug,
                        "status": "applying",
                        "is_primary": True,
                    },
                ),
                AdvisorAction(
                    tool="create_task",
                    summary="准备幂等材料",
                    arguments={"title": "准备幂等材料", "category": "材料", "priority": "P1"},
                ),
            ],
            {
                "provider": "deterministic-fallback",
                "model": "test-model",
                "latency_ms": 1,
                "input_tokens": None,
                "output_tokens": None,
            },
        )

    monkeypatch.setattr(main_module, "plan_turn", planned_turn)
    original_save_thread = main_module.store.save_thread
    fail_thread_write = True

    def injected_thread_failure(*args):
        nonlocal fail_thread_write
        if fail_thread_write:
            fail_thread_write = False
            raise RuntimeError("injected thread write failure")
        return original_save_thread(*args)

    monkeypatch.setattr(main_module.store, "save_thread", injected_thread_failure)
    with pytest.raises(RuntimeError, match="injected thread write failure"):
        client.post(
            f"/me/advisor/threads/{thread['id']}/messages",
            json={"content": content},
            headers=request_headers,
        )

    assert client.get("/me/profile", headers=headers).json()["location_preferences"] == "悉尼优先"
    choices = client.get(
        f"/me/recommendation-runs/{run['run_id']}/portfolio",
        headers=headers,
    ).json()
    assert [
        item["program_slug"] for item in choices
        if item["program_slug"] == program_slug and item["is_primary"]
    ] == [program_slug]
    assert [
        item["title"] for item in client.get("/me/tasks", headers=headers).json()
        if item["title"] == "准备幂等材料"
    ] == ["准备幂等材料"]
    assert client.get(f"/me/advisor/threads/{thread['id']}", headers=headers).json()["messages"] == thread["messages"]
    assert main_module.store.get_advisor_turn(user_id, "advisor-effect-window-1").status == "reply_ready"

    retried = client.post(
        f"/me/advisor/threads/{thread['id']}/messages",
        json={"content": content},
        headers=request_headers,
    )
    assert retried.status_code == 200
    assert plan_calls == 1
    messages = retried.json()["thread"]["messages"]
    assert sum(item["role"] == "user" and item["content"] == content for item in messages) == 1
    assert sum(item["role"] == "assistant" and item["content"] == "已更新档案、申请组合和材料待办。" for item in messages) == 1
    assert len([
        item for item in client.get("/me/tasks", headers=headers).json()
        if item["title"] == "准备幂等材料"
    ]) == 1
    assert len(client.get("/me/advisor/audits", headers=headers).json()) == 1

    conflict = client.post(
        f"/me/advisor/threads/{thread['id']}/messages",
        json={"content": "换一条不同的问题"},
        headers=request_headers,
    )
    assert conflict.status_code == 409
    assert "Idempotency-Key" in conflict.json()["detail"]


def test_concurrent_advisor_turns_use_thread_revision_cas_and_retry_without_replanning(monkeypatch) -> None:
    import importlib
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi import HTTPException

    from app.models import AdvisorMessageRequest, DemoUser

    main_module = importlib.import_module("app.main")
    login = registered_login("advisor-thread-cas@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据",
    }, headers=headers)
    thread = client.post("/me/advisor/threads", headers=headers).json()
    user = DemoUser.model_validate(client.get("/me", headers=headers).json())
    barrier = Barrier(2)
    plan_calls: list[str] = []

    def concurrent_plan(message, _profile, _history):
        plan_calls.append(message)
        barrier.wait(timeout=2)
        return (
            f"已处理：{message}",
            [],
            {
                "provider": "deterministic-fallback",
                "model": "test-model",
                "latency_ms": 1,
                "input_tokens": None,
                "output_tokens": None,
            },
        )

    monkeypatch.setattr(main_module, "plan_turn", concurrent_plan)

    def send(content: str, request_id: str):
        try:
            return main_module.send_advisor_message(
                thread["id"],
                AdvisorMessageRequest(content=content),
                user,
                request_id,
            )
        except HTTPException as error:
            return error

    requests = [
        ("并发请求一", "advisor-thread-cas-request-1"),
        ("并发请求二", "advisor-thread-cas-request-2"),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda args: send(*args), requests))

    conflicts = [item for item in outcomes if isinstance(item, HTTPException)]
    replies = [item for item in outcomes if not isinstance(item, HTTPException)]
    assert len(replies) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409
    persisted = client.get(
        f"/me/advisor/threads/{thread['id']}",
        headers=headers,
    ).json()
    assert persisted["revision"] == 1
    assert len(persisted["messages"]) == 3

    saved_contents = {item["content"] for item in persisted["messages"] if item["role"] == "user"}
    loser = next(item for item in requests if item[0] not in saved_contents)
    retried = send(*loser)
    assert not isinstance(retried, HTTPException)
    assert retried.thread.revision == 2
    assert len(retried.thread.messages) == 5
    assert {item.content for item in retried.thread.messages if item.role == "user"} == {
        "并发请求一",
        "并发请求二",
    }
    assert sorted(plan_calls) == ["并发请求一", "并发请求二"]


def test_stream_advisor_turn_emits_a_structured_thread_conflict(monkeypatch) -> None:
    import importlib

    from app.store_errors import AdvisorThreadRevisionConflictError

    main_module = importlib.import_module("app.main")
    login = registered_login("advisor-stream-thread-cas@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据",
    }, headers=headers)
    thread = client.post("/me/advisor/threads", headers=headers).json()

    def conflict(*_args):
        raise AdvisorThreadRevisionConflictError(thread["id"], 0, 1)

    monkeypatch.setattr(main_module, "commit_advisor_turn", conflict)
    response = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "触发结构化冲突"},
        headers={**headers, "Idempotency-Key": "advisor-stream-thread-cas-1"},
    )

    assert response.status_code == 200
    assert "event: conflict" in response.text
    assert '"expected_revision": 0' in response.text
    assert '"actual_revision": 1' in response.text
    assert "event: state" not in response.text
    assert "event: done" not in response.text


def test_deepseek_stream_is_consented_redacted_and_persisted(monkeypatch) -> None:
    import importlib
    import json

    main_module = importlib.import_module("app.main")
    login = registered_login("deepseek-stream@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "隐私大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "intake": "2027 S1",
    }, headers=headers)
    client.post("/me/recommendation-runs", headers=headers)
    thread = client.post("/me/advisor/threads", headers=headers).json()
    assert client.get("/me/advisor/consent", headers=headers).json() is None
    assert client.post("/me/advisor/consent", json={"accepted": True}, headers=headers).json()["accepted"] is True

    captured = {}

    async def fake_stream(context):
        captured.update(context)
        yield "delta", "建议先比较课程匹配与城市成本。"
        yield "usage", {"prompt_tokens": 120, "completion_tokens": 18}

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "never-sent-to-client")
    monkeypatch.setattr(main_module, "stream_deepseek", fake_stream)
    response = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "请比较这些项目的取舍"},
        headers={**headers, "Idempotency-Key": "deepseek-stream-1"},
    )
    assert response.status_code == 200
    assert "event: status" in response.text
    assert "event: delta" in response.text
    assert "event: actions" in response.text
    assert "event: state" in response.text
    assert "event: done" in response.text
    assert "deepseek" in response.text
    serialized = json.dumps(captured, ensure_ascii=False)
    for forbidden in ["deepseek-stream@offerpilot.cn", "测试用户", "隐私大学", "never-sent-to-client"]:
        assert forbidden not in serialized
    audits = client.get("/me/advisor/audits", headers=headers).json()
    assert audits[0]["provider"] == "deepseek"
    assert audits[0]["input_tokens"] == 120
    assert audits[0]["prompt_version"] == "advisor-2.0.0-redacted"


def test_stream_state_keeps_profile_run_portfolio_and_roadmap_on_one_snapshot() -> None:
    import json

    def state_from(response_text: str) -> dict:
        state_block = next(
            block for block in response_text.replace("\r\n", "\n").split("\n\n")
            if block.startswith("event: state\n")
        )
        return json.loads(next(
            line.removeprefix("data: ").strip()
            for line in state_block.splitlines()
            if line.startswith("data:")
        ))

    login = registered_login("stream-state-contract@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "intake": "2027 S1",
    }, headers=headers)
    old_run_id = client.post("/me/recommendation-runs", headers=headers).json()["run_id"]
    thread = client.post("/me/advisor/threads", headers=headers).json()

    response = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "我更想去悉尼，预算每年 50 万，请重新推荐学校"},
        headers={**headers, "Idempotency-Key": "stream-state-contract-1"},
    )
    assert response.status_code == 200
    state = state_from(response.text)

    assert state["profile"]["location_preferences"] == "悉尼优先"
    assert state["profile"]["annual_budget_cny"] == 500000
    assert state["recommendation_run"]["run_id"] != old_run_id
    assert state["roadmap"]["run_id"] == state["recommendation_run"]["run_id"]
    assert {item["run_id"] for item in state["portfolio"]} == {state["recommendation_run"]["run_id"]}

    replay = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "我更想去悉尼，预算每年 50 万，请重新推荐学校"},
        headers={**headers, "Idempotency-Key": "stream-state-contract-1"},
    )
    assert replay.status_code == 200
    assert state_from(replay.text)["roadmap"] == state["roadmap"]


def test_stream_prerequisite_loading_does_not_block_the_event_loop(monkeypatch) -> None:
    import asyncio
    import importlib
    from threading import Event
    from time import perf_counter

    from app.models import AdvisorMessageRequest, DemoUser

    main_module = importlib.import_module("app.main")
    login = registered_login("stream-nonblocking@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据",
    }, headers=headers)
    thread = client.post("/me/advisor/threads", headers=headers).json()
    user = DemoUser.model_validate(client.get("/me", headers=headers).json())
    original_get_thread = main_module.store.get_thread
    started = Event()
    release = Event()

    def slow_get_thread(*args):
        started.set()
        release.wait(0.8)
        return original_get_thread(*args)

    monkeypatch.setattr(main_module.store, "get_thread", slow_get_thread)

    async def exercise() -> float:
        began = perf_counter()
        request = asyncio.create_task(main_module.stream_advisor_message(
            thread["id"], AdvisorMessageRequest(content="下一步是什么"), user, "stream-nonblocking-1",
        ))
        assert await asyncio.to_thread(started.wait, 0.2)
        release.set()
        await request
        return perf_counter() - began

    assert asyncio.run(exercise()) < 0.4


def test_deepseek_stream_failure_is_explicit_and_never_falls_back_to_ollama(monkeypatch) -> None:
    import importlib

    from app.services.deepseek_advisor import DeepSeekStreamError

    main_module = importlib.import_module("app.main")
    login = registered_login("deepseek-fallback@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据",
    }, headers=headers)
    thread = client.post("/me/advisor/threads", headers=headers).json()
    client.post("/me/advisor/consent", json={"accepted": True}, headers=headers)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-only")

    async def failed_stream(_context):
        if False:
            yield "delta", ""
        raise DeepSeekStreamError("429 or zero balance")

    monkeypatch.setattr(main_module, "stream_deepseek", failed_stream)
    response = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "我下一步做什么"},
        headers={**headers, "Idempotency-Key": "deepseek-fallback-1"},
    )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "规则顾问" in response.text
    assert "ollama" not in response.text.lower()


def test_cloud_calls_are_confined_to_the_consented_streaming_boundary(monkeypatch) -> None:
    import importlib

    main_module = importlib.import_module("app.main")
    advisor_module = importlib.import_module("app.services.advisor")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-only")

    def forbidden_plan(_context):
        raise AssertionError("legacy or recommendation path attempted a cloud model call")

    monkeypatch.setattr(advisor_module, "plan_advisor_turn", forbidden_plan)
    login = registered_login("cloud-boundary@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "不应出境大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据",
    }, headers=headers)

    run = client.post("/me/recommendation-runs", headers=headers)
    assert run.status_code == 200
    assert run.json()["agent_mode"] == "deterministic-demo"

    thread = client.post("/me/advisor/threads", headers=headers).json()
    legacy = client.post(
        f"/me/advisor/threads/{thread['id']}/messages",
        json={"content": "请重新推荐学校"},
        headers={**headers, "Idempotency-Key": "cloud-boundary-sync-1"},
    )
    assert legacy.status_code == 200
    assert legacy.json()["provider"] == "deterministic-fallback"

    cloud_called = False

    async def forbidden_stream(_context):
        nonlocal cloud_called
        cloud_called = True
        if False:
            yield "delta", ""

    monkeypatch.setattr(main_module, "stream_deepseek", forbidden_stream)
    streamed = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "这些项目怎么选"},
        headers={**headers, "Idempotency-Key": "cloud-boundary-stream-1"},
    )
    assert streamed.status_code == 200
    assert "deterministic-fallback" in streamed.text
    assert cloud_called is False


def test_program_sources_expose_review_freshness() -> None:
    response = client.get("/program-sources/status")
    assert response.status_code == 200
    assert len(response.json()) >= 6
    assert all(item["url"].startswith("https://") for item in response.json())
    assert all(len(item["content_hash"]) == 64 for item in response.json())
    assert all(item["published_version_id"] for item in response.json())


def test_admin_source_versions_require_review_update_rag_and_can_rollback(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_EMAILS", "admin@offerpilot.cn,source-admin@offerpilot.cn")
    login = registered_login("source-admin@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    slug = "unsw-master-it"

    baseline_status = next(
        item for item in client.get("/program-sources/status").json()
        if item["program_slug"] == slug
    )
    baseline_program = client.get(f"/programs/{slug}").json()
    baseline_version_id = baseline_status["published_version_id"]
    baseline_hash = baseline_status["content_hash"]

    untrusted_program = {
        **baseline_program,
        "duration": "2.25 年",
        "source": {**baseline_program["source"], "url": "https://example.com/not-official"},
    }
    untrusted = client.post(
        f"/admin/program-sources/{slug}/versions",
        json={"base_hash": baseline_hash, "program": untrusted_program},
        headers=headers,
    )
    assert untrusted.status_code == 422
    assert "官方域名" in untrusted.json()["detail"]

    first_program = {**baseline_program, "duration": "2.25 年"}
    second_program = {**baseline_program, "duration": "2.5 年"}
    first = client.post(
        f"/admin/program-sources/{slug}/versions",
        json={"base_hash": baseline_hash, "program": first_program},
        headers=headers,
    )
    second = client.post(
        f"/admin/program-sources/{slug}/versions",
        json={"base_hash": baseline_hash, "program": second_program},
        headers=headers,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["status"] == "pending_review"
    assert {item["field"] for item in first.json()["changes"]} == {"duration"}
    assert client.get(f"/programs/{slug}").json()["duration"] == baseline_program["duration"]

    first_id = first.json()["version_id"]
    approved = client.put(
        f"/admin/program-sources/{slug}/versions/{first_id}",
        json={"decision": "approve", "note": "测试审核通过"},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "published"
    assert approved.json()["reviewed_by"] == login.json()["user"]["id"]
    assert client.get(f"/programs/{slug}").json()["duration"] == "2.25 年"

    rag = client.post(
        "/me/knowledge/search",
        json={"query": "UNSW 信息技术项目学制", "top_k": 3},
        headers=headers,
    )
    unsw_hit = next(item for item in rag.json()["hits"] if item["program_slug"] == slug)
    assert unsw_hit["source"]["version_id"] == first_id
    assert unsw_hit["source"]["content_hash"] == approved.json()["content_hash"]

    recommendation = client.post("/agent/recommendations", json={
        "undergraduate_school": "示例大学",
        "school_tier": "双非",
        "undergraduate_major": "软件工程",
        "gpa": 82,
        "gpa_scale": 100,
        "target_field": "计算机与数据",
    }).json()
    unsw = next(item for item in recommendation["recommendations"] if item["program"]["slug"] == slug)
    assert unsw["program"]["duration"] == "2.25 年"
    assert unsw["program"]["source"]["version_id"] == first_id

    second_id = second.json()["version_id"]
    stale = client.put(
        f"/admin/program-sources/{slug}/versions/{second_id}",
        json={"decision": "approve"},
        headers=headers,
    )
    assert stale.status_code == 409
    rejected = client.put(
        f"/admin/program-sources/{slug}/versions/{second_id}",
        json={"decision": "reject", "note": "基线已过期"},
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    rejected_rollback = client.post(
        f"/admin/program-sources/{slug}/rollback",
        json={"target_version_id": second_id},
        headers=headers,
    )
    assert rejected_rollback.status_code == 409
    assert "曾经发布" in rejected_rollback.json()["detail"]

    rollback = client.post(
        f"/admin/program-sources/{slug}/rollback",
        json={"target_version_id": baseline_version_id, "note": "测试回滚"},
        headers=headers,
    )
    assert rollback.status_code == 201
    assert rollback.json()["status"] == "published"
    assert rollback.json()["rollback_of"] == baseline_version_id
    assert rollback.json()["content_hash"] == baseline_hash
    assert rollback.json()["version_id"] != baseline_version_id
    assert client.get(f"/programs/{slug}").json()["duration"] == baseline_program["duration"]

    versions = client.get(
        f"/admin/program-sources/{slug}/versions",
        headers=headers,
    ).json()
    assert sum(item["status"] == "published" for item in versions) == 1
    assert any(item["status"] == "rejected" and item["version_id"] == second_id for item in versions)


def test_admin_can_capture_an_official_snapshot_without_auto_publishing(monkeypatch) -> None:
    import importlib
    from datetime import UTC, datetime
    from hashlib import sha256

    from app.models import ProgramSourceSnapshot

    main_module = importlib.import_module("app.main")
    monkeypatch.setenv("ADMIN_EMAILS", "admin@offerpilot.cn,snapshot-admin@offerpilot.cn")
    login = registered_login("snapshot-admin@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    slug = "monash-master-cs"
    baseline_status = next(
        item for item in client.get("/program-sources/status").json()
        if item["program_slug"] == slug
    )
    baseline_program = client.get(f"/programs/{slug}").json()
    body_text = "<html><body>Monash official course requirements snapshot</body></html>"
    captured: dict[str, object] = {}

    def fake_fetch(url: str, domains: tuple[str, ...]) -> ProgramSourceSnapshot:
        captured.update(url=url, domains=domains)
        return ProgramSourceSnapshot(
            requested_url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            content_type="text/html",
            content_sha256=sha256(body_text.encode()).hexdigest(),
            content_bytes=len(body_text.encode()),
            body_text=body_text,
        )

    monkeypatch.setattr(main_module, "fetch_official_source", fake_fetch)
    proposed = {**baseline_program, "duration": f"{baseline_program['duration']}（快照测试）"}
    response = client.post(
        f"/admin/program-sources/{slug}/versions",
        json={
            "base_hash": baseline_status["content_hash"],
            "program": proposed,
            "capture_snapshot": True,
        },
        headers=headers,
    )

    assert response.status_code == 201
    candidate = response.json()
    assert captured == {
        "url": baseline_program["source"]["url"],
        "domains": ("monash.edu",),
    }
    assert candidate["status"] == "pending_review"
    assert candidate["content_hash"] != baseline_status["content_hash"]
    assert candidate["source_snapshot"]["body_text"] == body_text
    assert candidate["source_snapshot"]["content_sha256"] == sha256(body_text.encode()).hexdigest()
    assert "source_snapshot.content_sha256" in {item["field"] for item in candidate["changes"]}
    assert client.get(f"/programs/{slug}").json()["duration"] == baseline_program["duration"]

    rejected = client.put(
        f"/admin/program-sources/{slug}/versions/{candidate['version_id']}",
        json={"decision": "reject", "note": "测试完成，不发布"},
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_authenticated_rag_search_and_advisor_fallback_share_cited_evidence() -> None:
    login = registered_login("rag-product@offerpilot.cn")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/me/profile", json={
        "undergraduate_school": "示例大学", "school_tier": "双非", "undergraduate_major": "软件工程",
        "gpa": 82, "gpa_scale": 100, "target_field": "计算机与数据", "target_degree_level": "授课型硕士",
    }, headers=headers)

    search = client.post(
        "/me/knowledge/search", json={"query": "UQ 数据科学雅思和数学先修要求", "top_k": 3}, headers=headers,
    )
    assert search.status_code == 200
    assert search.json()["hits"][0]["program_slug"] == "uq-master-data-science"
    assert search.json()["hits"][0]["source"]["url"].startswith("https://")

    thread = client.post("/me/advisor/threads", headers=headers).json()
    reply = client.post(
        f"/me/advisor/threads/{thread['id']}/messages/stream",
        json={"content": "UQ 数据科学雅思和数学先修要求是什么"},
        headers={**headers, "Idempotency-Key": "rag-advisor-stream-1"},
    )
    assert reply.status_code == 200
    assert "official-knowledge-rag" in reply.text
    assert "study.uq.edu.au" in reply.text
    assert "不是录取承诺" in reply.text
    audits = client.get("/me/advisor/audits", headers=headers).json()
    assert "retrieve_official_knowledge" in audits[0]["tools"]
