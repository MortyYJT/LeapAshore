from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


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
    assert "用于核验先修课的成绩单课程列表" in body["missing_information"]
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
