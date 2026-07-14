from fastapi.testclient import TestClient

from app.main import app
from main import app as service_app


client = TestClient(app)


def test_vercel_service_entrypoint_exports_the_application() -> None:
    response = TestClient(service_app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_llm_status_never_exposes_the_api_key() -> None:
    body = client.get("/llm/status").json()
    assert body["api"] == "responses"
    assert body["model"] == "gpt-5-mini"
    assert "key" not in body


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
    assert body["workflow_version"] == "agent-0.2.0"
    assert len(body["tool_trace"]) == 5
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


def test_complete_authenticated_product_flow() -> None:
    login = client.post("/auth/login", json={"email": "demo@offerpilot.cn", "password": "demo1234"})
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
    login = client.post("/auth/login", json={"email": "advisor@offerpilot.cn", "password": "demo1234"})
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


def test_transcript_analysis_maps_courses_to_program_prerequisites() -> None:
    login = client.post("/auth/login", json={"email": "transcript@offerpilot.cn", "password": "demo1234"})
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
    login = client.post("/auth/login", json={"email": "tasks@offerpilot.cn", "password": "demo1234"})
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
    login = client.post("/auth/login", json={"email": "advisor-task@offerpilot.cn", "password": "demo1234"})
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
