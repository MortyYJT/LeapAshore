from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_catalog_facets_meet_initial_coverage_target() -> None:
    response = client.get("/catalog/facets")

    assert response.status_code == 200
    body = response.json()
    assert len(body["universities"]) == 8
    assert body["degree_levels"] == ["本科", "授课型硕士", "研究型硕士", "博士"]
    assert len(body["study_areas"]) == 12
    assert body["coverage_cells"] == 384
    assert body["verified_programs"] == 6


def test_catalog_coverage_can_filter_any_level_and_field() -> None:
    response = client.get(
        "/catalog/coverage",
        params={"degree_level": "博士", "field": "法律与犯罪学"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 8
    assert all(row["degree_level"] == "博士" for row in rows)
    assert all(row["field"] == "法律与犯罪学" for row in rows)
    assert all(row["catalog_url"].startswith("https://") for row in rows)
    assert all(row["status"] == "目录已接入，待课程级核验" for row in rows)


def test_verified_program_search_is_separate_from_catalog_coverage() -> None:
    verified = client.get(
        "/programs",
        params={"degree_level": "授课型硕士", "field": "计算机与数据"},
    )
    not_yet_verified = client.get(
        "/programs",
        params={"degree_level": "本科", "field": "工程"},
    )

    assert verified.status_code == 200
    assert len(verified.json()) == 6
    assert not_yet_verified.status_code == 200
    assert not_yet_verified.json() == []


def test_agent_returns_an_honest_empty_state_for_unverified_scope() -> None:
    response = client.post(
        "/agent/recommendations",
        json={
            "current_education_level": "高中",
            "undergraduate_school": "示例国际高中",
            "school_tier": "高中/国际课程",
            "undergraduate_major": "A-Level Mathematics, Physics",
            "gpa": 90,
            "gpa_scale": 100,
            "target_degree_level": "本科",
            "target_field": "工程",
            "intake": "2027 S1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert "暂不生成录取分档" in body["summary"]
    assert body["tool_trace"][1]["tool"] == "retrieve_official_catalogs"
    assert body["tool_trace"][1]["status"] == "completed"
    assert body["tool_trace"][2]["status"] == "needs_input"
    assert body["tool_trace"][3]["status"] == "skipped"
    assert "该学位层次与专业方向的课程级核验数据" in body["missing_information"]
