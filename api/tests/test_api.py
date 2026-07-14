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
