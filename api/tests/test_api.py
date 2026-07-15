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


def test_http_only_cookie_restores_same_origin_session() -> None:
    login = registered_login("cookie-session@offerpilot.cn")
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "samesite=lax" in login.headers["set-cookie"].lower()
    assert client.get("/me").json()["email"] == "cookie-session@offerpilot.cn"
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/me").status_code == 401


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
    assert body["workflow_version"] == "agent-0.4.0"
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
    assert len(action_plan.json()["items"]) == 5
    assert len(client.get("/me/tasks", headers=headers).json()) == 5


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
        headers=headers,
    )
    assert reply.status_code == 200
    body = reply.json()
    assert body["provider"] == "deterministic-fallback"
    assert body["profile"]["english_score"] == "IELTS 7.0"
    assert body["profile"]["annual_budget_aud"] == 500000
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
        json={"content": "提醒我准备英文成绩单"}, headers=headers,
    )
    assert response.status_code == 200
    assert client.get("/me/tasks", headers=headers).json()[0]["title"] == "准备英文成绩单"


def test_program_sources_expose_review_freshness() -> None:
    response = client.get("/program-sources/status")
    assert response.status_code == 200
    assert len(response.json()) >= 6
    assert all(item["url"].startswith("https://") for item in response.json())
