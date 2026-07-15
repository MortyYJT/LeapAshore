from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from ..models import (
    AgentRecommendationResponse,
    ApplicantProfile,
    ApplicationChoice,
    ApplicationRoadmap,
    ApplicationTask,
    ProgramRoadmapBranch,
    RoadmapPhase,
)


PHASES = [
    ("selection", "锁定申请组合", "确定申请项目，并从中标记一个首选项目。", 330),
    ("academic", "学术与身份材料", "整理成绩单、在读或学位证明、护照及认证材料。", 270),
    ("language", "语言准备", "完成语言考试规划，并核验每个项目的总分与单项要求。", 240),
    ("specialized", "专项申请材料", "准备简历、陈述、推荐信及学位或专业特有材料。", 210),
    ("submission", "提交申请", "核验官方截止日期，逐个完成并检查申请提交。", 150),
    ("decision", "Offer 与入学", "跟进补件、Offer、押金、签证和最终入学安排。", 60),
]


def intake_anchor(intake: str) -> datetime:
    match = re.search(r"(20\d{2}).*?S([12])", intake, re.IGNORECASE)
    if not match:
        return datetime(datetime.now(UTC).year + 1, 2, 15, tzinfo=UTC)
    year, semester = int(match.group(1)), match.group(2)
    return datetime(year, 2 if semester == "1" else 7, 15, tzinfo=UTC)


def _specialized_materials(profile: ApplicantProfile) -> tuple[str, str]:
    if profile.target_degree_level in {"研究型硕士", "博士"}:
        return (
            "完成研究计划、导师匹配与推荐信",
            "形成研究问题与方法框架，筛选潜在导师，准备学术简历、写作样本和推荐信。",
        )
    if profile.target_degree_level == "本科":
        detail = "准备课程体系说明、预估或最终成绩、活动经历与个人陈述。"
    else:
        detail = "准备学术简历、个人陈述、推荐人信息及项目要求的补充材料。"
    if profile.target_field in {"建筑规划与设计", "传媒艺术与音乐"}:
        detail += " 同步整理作品集，并逐校核对格式、页数和文件限制。"
    return "完成专项申请材料", detail


def task_templates(
    profile: ApplicantProfile,
    result: AgentRecommendationResponse,
    choices: list[ApplicationChoice],
    now: datetime | None = None,
) -> list[ApplicationTask]:
    generated_at = now or datetime.now(UTC)
    anchor = intake_anchor(profile.intake)
    dates = {phase_id: anchor - timedelta(days=offset) for phase_id, _, _, offset in PHASES}
    run = result.run_id
    specialized_title, specialized_detail = _specialized_materials(profile)
    tasks = [
        ApplicationTask(
            id=f"task_{run}_shortlist", title="确认最终申请组合", detail="把项目标记为待定、确定申请或不考虑，并为一个确定项目设置首选。",
            category="选校", priority="P0", phase="selection", due_at=dates["selection"], source_run_id=run,
            created_at=generated_at, updated_at=generated_at,
        ),
        ApplicationTask(
            id=f"task_{run}_verify-transcript", title="整理学术与身份材料", detail="准备中英文成绩单、在读或学位证明、评分说明与护照，并核验先修课程。",
            category="成绩单", priority="P0", phase="academic", due_at=dates["academic"], source_run_id=run,
            dependencies=[f"task_{run}_shortlist"], created_at=generated_at, updated_at=generated_at,
        ),
        ApplicationTask(
            id=f"task_{run}_verify-language", title="确认语言考试与小分", detail="对照确定申请项目的英语要求，安排考试并记录总分、单项和有效期。",
            category="语言", priority="P0", phase="language", due_at=dates["language"], source_run_id=run,
            dependencies=[f"task_{run}_verify-transcript"], created_at=generated_at, updated_at=generated_at,
        ),
        ApplicationTask(
            id=f"task_{run}_materials", title=specialized_title, detail=specialized_detail,
            category="材料", priority="P1", phase="specialized", due_at=dates["specialized"], source_run_id=run,
            dependencies=[f"task_{run}_verify-language"], created_at=generated_at, updated_at=generated_at,
        ),
        ApplicationTask(
            id=f"task_{run}_deadlines", title="核验申请开放时间与截止日期", detail="逐校查看官方申请页面；系统建议日期不是学校官方截止日期。",
            category="截止日期", priority="P0", phase="submission", due_at=dates["submission"], source_run_id=run,
            dependencies=[f"task_{run}_materials"], created_at=generated_at, updated_at=generated_at,
        ),
        ApplicationTask(
            id=f"task_{run}_offer-visa", title="跟进 Offer、押金、签证与入学", detail="跟进补件和结果，比较 Offer 条件，确认接受期限、CoE、签证与住宿安排。",
            category="其他", priority="P1", phase="decision", due_at=dates["decision"], source_run_id=run,
            dependencies=[f"task_{run}_deadlines"], created_at=generated_at, updated_at=generated_at,
        ),
    ]
    programs = {item.program.slug: item.program for item in result.recommendations}
    for choice in choices:
        if choice.status != "applying" or choice.program_slug not in programs:
            continue
        program = programs[choice.program_slug]
        tasks.append(ApplicationTask(
            id=f"task_{run}_submit-{program.slug}",
            title=f"提交 {program.university} · {program.name}",
            detail="完成在线表格、材料上传和最终检查；提交前再次核对项目官网。",
            category="截止日期", priority="P0" if choice.is_primary else "P1", phase="submission",
            program_slug=program.slug, due_at=choice.official_deadline or dates["submission"],
            schedule_origin="official" if choice.official_deadline else "system_suggestion",
            source_run_id=run, dependencies=[f"task_{run}_deadlines"],
            created_at=generated_at, updated_at=generated_at,
        ))
    return tasks


def merge_tasks(templates: list[ApplicationTask], existing: list[ApplicationTask]) -> list[ApplicationTask]:
    existing_by_id = {task.id: task for task in existing}
    merged = []
    for template in templates:
        prior = existing_by_id.get(template.id)
        if not prior:
            merged.append(template)
            continue
        updates = {
            "status": prior.status,
            "reminder_at": prior.reminder_at,
            "created_at": prior.created_at,
            "updated_at": prior.updated_at,
        }
        if prior.schedule_origin == "user":
            updates.update({"due_at": prior.due_at, "schedule_origin": "user"})
        merged.append(template.model_copy(update=updates))
    return merged


def build_roadmap(
    profile: ApplicantProfile,
    result: AgentRecommendationResponse,
    choices: list[ApplicationChoice],
    tasks: list[ApplicationTask],
    now: datetime | None = None,
) -> ApplicationRoadmap:
    generated_at = now or datetime.now(UTC)
    anchor = intake_anchor(profile.intake)
    run_tasks = [task for task in tasks if task.source_run_id == result.run_id]
    phases = []
    for phase_id, title, detail, offset in PHASES:
        phase_tasks = [task for task in run_tasks if task.phase == phase_id and not task.program_slug]
        suggested_at = anchor - timedelta(days=offset)
        if phase_tasks and all(task.status == "已完成" for task in phase_tasks):
            status = "completed"
        elif any(task.status == "进行中" for task in phase_tasks):
            status = "in_progress"
        elif suggested_at < generated_at:
            status = "overdue"
        else:
            status = "pending"
        phases.append(RoadmapPhase(
            id=phase_id, title=title, detail=detail, suggested_at=suggested_at, status=status, tasks=phase_tasks,
        ))

    programs = {item.program.slug: item.program for item in result.recommendations}
    branches = []
    for choice in sorted(choices, key=lambda item: (not item.is_primary, item.updated_at)):
        program = programs.get(choice.program_slug)
        if choice.status != "applying" or not program:
            continue
        branches.append(ProgramRoadmapBranch(
            program_slug=program.slug, program_name=program.name, university=program.university,
            is_primary=choice.is_primary, official_deadline=choice.official_deadline,
            deadline_source_url=choice.deadline_source_url,
            tasks=[task for task in run_tasks if task.program_slug == program.slug],
        ))
    visible_tasks = [task for task in run_tasks if not task.program_slug] + [task for branch in branches for task in branch.tasks]
    return ApplicationRoadmap(
        run_id=result.run_id, intake=profile.intake, anchor_at=anchor, generated_at=generated_at,
        phases=phases, program_branches=branches,
        completed_tasks=sum(task.status == "已完成" for task in visible_tasks), total_tasks=len(visible_tasks),
    )
