from datetime import UTC, datetime

from app.models import ApplicantProfile, ApplicationChoice
from app.services.agent import run_recommendation_agent
from app.services.roadmap import build_roadmap, intake_anchor, task_templates


def profile(level: str = "授课型硕士", field: str = "计算机与数据") -> ApplicantProfile:
    return ApplicantProfile(
        undergraduate_school="示例大学", school_tier="双非", undergraduate_major="软件工程",
        gpa=82, gpa_scale=100, target_degree_level=level, target_field=field, intake="2027 S1",
    )


def test_intake_anchor_uses_fixed_semester_dates() -> None:
    assert intake_anchor("2027 S1") == datetime(2027, 2, 15, tzinfo=UTC)
    assert intake_anchor("2028 S2") == datetime(2028, 7, 15, tzinfo=UTC)


def test_roadmap_has_six_linear_phases_and_marks_past_suggestions_overdue() -> None:
    applicant = profile()
    result = run_recommendation_agent(applicant)
    now = datetime(2026, 7, 15, tzinfo=UTC)
    tasks = task_templates(applicant, result, [], now)
    roadmap = build_roadmap(applicant, result, [], tasks, now)
    assert [phase.id for phase in roadmap.phases] == [
        "selection", "academic", "language", "specialized", "submission", "decision",
    ]
    assert roadmap.phases[0].suggested_at == datetime(2026, 3, 22, tzinfo=UTC)
    assert roadmap.phases[0].status == "overdue"
    assert roadmap.program_branches == []


def test_degree_and_field_change_specialized_materials() -> None:
    for level, expected in [
        ("本科", "课程体系说明"),
        ("授课型硕士", "学术简历"),
        ("研究型硕士", "研究问题与方法框架"),
        ("博士", "研究问题与方法框架"),
    ]:
        applicant = profile(level)
        result = run_recommendation_agent(applicant)
        materials = next(task for task in task_templates(applicant, result, []) if task.phase == "specialized")
        assert expected in materials.detail

    design = profile("授课型硕士", "建筑规划与设计")
    design_result = run_recommendation_agent(design)
    materials = next(task for task in task_templates(design, design_result, []) if task.phase == "specialized")
    assert "作品集" in materials.detail


def test_official_deadline_overrides_system_submission_suggestion() -> None:
    applicant = profile()
    result = run_recommendation_agent(applicant)
    deadline = datetime(2026, 10, 31, tzinfo=UTC)
    choice = ApplicationChoice(
        run_id=result.run_id, program_slug=result.recommendations[0].program.slug,
        status="applying", is_primary=True, official_deadline=deadline,
        deadline_source_url="https://example.edu/deadline", updated_at=datetime.now(UTC),
    )
    task = next(item for item in task_templates(applicant, result, [choice]) if item.program_slug)
    assert task.due_at == deadline
    assert task.schedule_origin == "official"
