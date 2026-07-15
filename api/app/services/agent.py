from __future__ import annotations

import re
from uuid import uuid4

from ..models import (
    AgentRecommendationResponse,
    ApplicantProfile,
    Program,
    ProgramRecommendation,
    ToolTrace,
)
from ..catalog_data import CATALOG_COVERAGE
from ..program_data import PROGRAMS
from .recommender import normalize_gpa
from .model_provider import ModelProviderError, configured_agent_mode, generate_grounded_summary


COGNATE_KEYWORDS = {
    "计算机", "软件", "信息", "数据", "人工智能", "网络", "电子", "自动化", "computer", "software", "data", "information"
}


def is_cognate(major: str) -> bool:
    normalized = major.lower()
    return any(keyword in normalized for keyword in COGNATE_KEYWORDS)


def parse_ielts(score: str | None) -> float | None:
    if not score:
        return None
    match = re.search(r"(?:ielts\s*)?(\d(?:\.\d)?)", score.lower())
    return float(match.group(1)) if match else None


def effective_threshold(program: Program, profile: ApplicantProfile) -> float | None:
    if profile.school_tier == "双非" and program.non_211_minimum_mark:
        return program.non_211_minimum_mark
    return program.minimum_mark


def recommend_program(program: Program, profile: ApplicantProfile) -> ProgramRecommendation:
    gpa = normalize_gpa(profile)
    threshold = effective_threshold(program, profile)
    cognate = is_cognate(profile.undergraduate_major)
    prerequisite_risk = program.requires_cognate and not cognate
    gap = gpa - threshold if threshold is not None else None

    if threshold is None:
        tier = "暂不推荐"
        eligibility = "需要人工核验"
        score = 50
    elif prerequisite_risk:
        tier = "暂不推荐"
        eligibility = "存在门槛缺口"
        score = max(45, min(72, round(62 + gap / 2)))
    else:
        tier = "稳妥" if gap >= 12 else "匹配" if gap >= 4 else "冲刺" if gap >= -3 else "暂不推荐"
        eligibility = "满足基础门槛" if gap >= 0 else "需要人工核验"
        score = max(50, min(96, round(78 + gap)))

    reasons = [f"当前学术成绩标准化为 {gpa}/100。"]
    if threshold is None:
        reasons.append("该项目尚未录入可比较的课程级学术门槛，因此不进行自动分档。")
    else:
        reasons.append(f"当前公开基线按 {threshold:g}% 参与检查。")
    reasons.append(f"既往专业“{profile.undergraduate_major}”被识别为{'相关' if cognate else '非相关或待核验'}背景。")
    risks: list[str] = []
    if prerequisite_risk:
        risks.append("项目要求相关背景或指定先修课程，当前专业信息不足以确认满足。")
    if program.requires_supervisor:
        risks.append("研究型项目通常需要确认导师匹配、研究方向与接收意向。")
    if program.research_proposal_required:
        risks.append("需要准备研究计划，并由院系按研究能力单独审核。")
    if program.prerequisites:
        risks.append("需用成绩单逐项核验：" + "、".join(program.prerequisites) + "。")
    ielts = parse_ielts(profile.english_score)
    if ielts is None:
        risks.append("未提供可解析的 IELTS 成绩，语言门槛尚未完成验证。")
    elif "IELTS 6.5" in program.english_requirement and ielts < 6.5:
        risks.append(f"当前 IELTS {ielts:g} 低于页面列出的 6.5 总分要求。")
    if not risks:
        risks.append("达到最低门槛不代表录取，仍受名额和申请轮次影响。")

    return ProgramRecommendation(
        program=program,
        tier=tier,
        eligibility=eligibility,
        match_score=score,
        reasons=reasons,
        risks=risks,
        next_action="打开官方项目页核验国际学历换算、先修课和当前申请轮次。",
        citations=[program.source],
    )


def run_recommendation_agent(profile: ApplicantProfile) -> AgentRecommendationResponse:
    """Run an auditable plan-and-execute workflow with deterministic admission tools."""
    gpa = normalize_gpa(profile)
    programs = [
        program for program in PROGRAMS
        if program.field == profile.target_field and program.degree_level == profile.target_degree_level
    ]
    results = [recommend_program(program, profile) for program in programs]
    catalog_options = [
        item for item in CATALOG_COVERAGE
        if item.degree_level == profile.target_degree_level and item.field == profile.target_field
    ]
    order = {"匹配": 0, "稳妥": 1, "冲刺": 2, "暂不推荐": 3}
    results.sort(key=lambda item: (order[item.tier], -item.match_score))

    missing: list[str] = []
    if not profile.english_score:
        missing.append("语言成绩")
    if any(program.prerequisites for program in programs) and not profile.coursework_summary:
        missing.append("用于确认先修课的成绩单课程列表")
    if not profile.experience_summary:
        missing.append("相关实习、科研或项目经历")
    if not profile.career_goal:
        missing.append("毕业后的职业目标")
    if not profile.annual_budget_aud:
        missing.append("年度留学预算")
    if not programs:
        missing.insert(0, "该学位层次与专业方向的课程级核验数据")

    evidence_ids = [program.source.id for program in programs]
    trace = [
        ToolTrace(step=1, tool="normalize_gpa", status="completed", summary=f"将成绩换算为 {gpa}/100。"),
        ToolTrace(
            step=2,
            tool="retrieve_official_catalogs",
            status="completed",
            summary=f"已连接 {len(catalog_options)} 所澳洲八大的{profile.target_degree_level} · {profile.target_field}官方课程目录。",
        ),
        ToolTrace(
            step=3,
            tool="retrieve_programs",
            status="completed" if programs else "needs_input",
            summary=(
                f"检索到 {len(programs)} 个已核验的{profile.target_degree_level} · {profile.target_field}项目。"
                if programs else
                f"目录覆盖{profile.target_degree_level} · {profile.target_field}，但暂无课程级核验项目。"
            ),
            evidence_ids=evidence_ids,
        ),
        ToolTrace(step=4, tool="check_hard_constraints", status="completed" if programs else "skipped", summary="逐项检查均分、专业背景、先修课和语言门槛。" if programs else "没有课程级门槛，未执行硬条件判断。", evidence_ids=evidence_ids),
        ToolTrace(step=5, tool="rank_portfolio", status="completed" if programs else "skipped", summary="按可解释规则生成冲刺、匹配、稳妥和暂不推荐分层。" if programs else "没有已核验项目，未生成误导性分档。"),
        ToolTrace(step=6, tool="validate_citations", status="completed" if programs else "skipped", summary=f"{len(results)}/{len(results)} 条推荐均绑定官方来源。" if programs else "没有推荐结果需要引用校验。", evidence_ids=evidence_ids),
    ]

    eligible = sum(item.eligibility == "满足基础门槛" for item in results)
    result = AgentRecommendationResponse(
        run_id=f"run_{uuid4().hex[:10]}",
        workflow_version="agent-0.4.0",
        summary=(
            f"已对照 {len(programs)} 个{profile.target_degree_level}具体项目，其中 {eligible} 个达到当前公开的基础申请要求。"
            if programs else
            f"已接入{profile.target_degree_level} · {profile.target_field}的官方目录入口；课程级要求仍在核验中，暂不生成录取分档。"
        ),
        missing_information=missing,
        tool_trace=trace,
        catalog_options=catalog_options,
        recommendations=results,
    )
    if programs and configured_agent_mode() == "llm-assisted":
        try:
            result.summary = generate_grounded_summary(profile, result)
            result.agent_mode = "llm-assisted"
            result.tool_trace.append(
                ToolTrace(
                    step=7,
                    tool="llm_grounded_explainer",
                    status="completed",
                    summary="模型基于已验证工具结果生成总结，未参与硬门槛判断。",
                    evidence_ids=evidence_ids,
                )
            )
        except ModelProviderError:
            result.tool_trace.append(
                ToolTrace(
                    step=7,
                    tool="llm_grounded_explainer",
                    status="skipped",
                    summary="模型不可用，已安全降级为 deterministic-demo。",
                )
            )
    return result
