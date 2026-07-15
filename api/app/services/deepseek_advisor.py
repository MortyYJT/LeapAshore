from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..models import (
    AgentRecommendationResponse,
    ApplicantProfile,
    ApplicationChoice,
    ApplicationRoadmap,
    ApplicationTask,
    AdvisorAction,
)
from .advisor import fallback_plan


class DeepSeekStreamError(RuntimeError):
    """Cloud model failures that should enter the deterministic fallback immediately."""


SYSTEM_PROMPT = """你是 OfferPilot 的澳洲留学申请顾问，覆盖本科、授课型硕士、研究型硕士和博士。
只能使用上下文中的已核验项目事实和引用；不得编造门槛、截止日期、费用或录取概率。
Python 工具已经负责 GPA、硬门槛、项目排序和所有写操作，你不能改变这些结果。
回答应直接、专业、可执行；缺少事实时明确说需要去学校官网核验。不要索取姓名、邮箱、账号或原始成绩单。"""


def _redact_text(value: str, sensitive_values: list[str]) -> str:
    redacted = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已脱敏]", value)
    redacted = re.sub(r"\b(?:user|account|wxid)[_-][A-Za-z0-9_-]{6,}\b", "[账户标识已脱敏]", redacted, flags=re.I)
    for sensitive in sorted({item.strip() for item in sensitive_values if item and item.strip()}, key=len, reverse=True):
        redacted = re.sub(re.escape(sensitive), "[个人信息已脱敏]", redacted, flags=re.I)
    return redacted


def build_redacted_context(
    profile: ApplicantProfile,
    result: AgentRecommendationResponse | None,
    choices: list[ApplicationChoice],
    roadmap: ApplicationRoadmap | None,
    history: list[dict[str, str]],
    user_message: str,
    sensitive_values: list[str],
) -> dict[str, Any]:
    """Create the only payload allowed to leave the service boundary."""
    safe_profile = {
        "current_education_level": profile.current_education_level,
        "school_tier": profile.school_tier,
        "undergraduate_major": profile.undergraduate_major,
        "gpa_percent": round(profile.gpa / profile.gpa_scale * 100, 2),
        "target_degree_level": profile.target_degree_level,
        "target_field": profile.target_field,
        "intake": profile.intake,
        "english_score": profile.english_score,
        "coursework_summary": profile.coursework_summary,
        "experience_summary": profile.experience_summary,
        "career_goal": profile.career_goal,
        "location_preferences": profile.location_preferences,
        "annual_budget_aud": profile.annual_budget_aud,
    }
    recommendations = [] if not result else [
        {
            "program_slug": item.program.slug,
            "university": item.program.university,
            "program": item.program.name,
            "tier": item.tier,
            "eligibility": item.eligibility,
            "reasons": item.reasons,
            "risks": item.risks,
            "citations": [{"id": source.id, "title": source.title, "url": source.url} for source in item.citations],
        }
        for item in result.recommendations
    ]
    tasks = [] if not roadmap else [
        {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "phase": task.phase,
            "program_slug": task.program_slug,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        }
        for task in [
            *[task for phase in roadmap.phases for task in phase.tasks],
            *[task for branch in roadmap.program_branches for task in branch.tasks],
        ]
    ]
    payload = {
        "profile": safe_profile,
        "recommendations": recommendations,
        "application_portfolio": [choice.model_dump(mode="json") for choice in choices],
        "roadmap_tasks": tasks,
        "recent_messages": history[-10:],
        "user_message": user_message,
    }
    # Summaries and chat text can contain user-entered identifiers, so redact the serialized payload as a final boundary check.
    return json.loads(_redact_text(json.dumps(payload, ensure_ascii=False), sensitive_values))


def safe_tool_actions(
    message: str,
    profile: ApplicantProfile,
    result: AgentRecommendationResponse | None,
    tasks: list[ApplicationTask],
) -> list[AdvisorAction]:
    """Select mutations deterministically; a model can never invent or broaden a write."""
    lowered = message.lower().replace(" ", "")
    if result and any(word in message for word in ["首选", "确定申请", "不考虑", "改成待定", "设为待定"]):
        matches = []
        for item in result.recommendations:
            program = item.program
            aliases = [program.slug.lower().replace("-", ""), program.university.lower().replace(" ", ""), program.name.lower().replace(" ", "")]
            slug_prefix = program.slug.split("-")[0]
            aliases.append(slug_prefix)
            if any(alias and alias in lowered.replace("-", "") for alias in aliases):
                matches.append(program)
        if len(matches) == 1:
            status = "excluded" if "不考虑" in message else "considering" if "待定" in message else "applying"
            primary = "首选" in message and "取消首选" not in message
            return [AdvisorAction(
                tool="set_application_choice",
                summary=f"将 {matches[0].university} {matches[0].name} 更新为{'首选项目' if primary else {'applying': '确定申请', 'considering': '待定', 'excluded': '不考虑'}[status]}",
                arguments={"run_id": result.run_id, "program_slug": matches[0].slug, "status": status, "is_primary": primary},
            )]

    if any(word in message for word in ["标记完成", "设为完成", "已经完成", "开始处理", "设为进行中"]):
        matched = [task for task in tasks if task.title in message or any(part and part in message for part in re.split(r"[与和、 ]", task.title))]
        if len(matched) == 1:
            status = "进行中" if any(word in message for word in ["开始处理", "设为进行中"]) else "已完成"
            return [AdvisorAction(tool="update_task", summary=f"把“{matched[0].title}”标记为{status}", arguments={"task_id": matched[0].id, "status": status})]

    raw = fallback_plan(message, profile)
    return [AdvisorAction(
        tool=item.get("tool", "answer"),
        summary=item.get("summary", "已处理"),
        arguments=item.get("arguments") if isinstance(item.get("arguments"), dict) else {},
    ) for item in raw["actions"][:3]]


async def stream_deepseek(context: dict[str, Any]) -> AsyncIterator[tuple[str, Any]]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekStreamError("DeepSeek API Key 未配置")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "thinking": {"type": "disabled"},
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.2,
        "max_tokens": 1000,
    }
    try:
        timeout = httpx.Timeout(connect=5, read=10, write=5, pool=5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    body = json.loads(data)
                    usage = body.get("usage")
                    if usage:
                        yield "usage", usage
                    choices = body.get("choices") or []
                    content = choices[0].get("delta", {}).get("content") if choices else None
                    if content:
                        yield "delta", content
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise DeepSeekStreamError("DeepSeek 暂时不可用或余额不足") from error
