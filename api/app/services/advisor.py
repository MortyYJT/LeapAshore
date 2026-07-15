from __future__ import annotations

import re
from time import perf_counter
from typing import Any

from ..models import AdvisorAction, ApplicantProfile
from .model_provider import ModelProviderError, configured_model, plan_advisor_turn


PROFILE_FIELDS = set(ApplicantProfile.model_fields)


def fallback_plan(message: str, profile: ApplicantProfile) -> dict[str, Any]:
    """Small, predictable fallback keeps the product usable without a paid model key."""
    updates: dict[str, Any] = {}
    budget = re.search(r"(?:预算|每年).*?(\d{2,3})(?:\s*万)", message)
    if budget:
        updates["annual_budget_aud"] = float(budget.group(1)) * 10000
    ielts = re.search(r"(?:ielts|雅思)\s*(\d(?:\.\d)?)", message, re.I)
    if ielts:
        updates["english_score"] = f"IELTS {ielts.group(1)}"
    intake = re.search(r"(20\d{2})\s*(?:年)?\s*(S[12]|[12]月|[27]月)", message, re.I)
    if intake:
        semester = "S1" if intake.group(2).upper() in {"S1", "2月"} else "S2"
        updates["intake"] = f"{intake.group(1)} {semester}"
    city_names = [city for city in ["悉尼", "墨尔本", "布里斯班", "珀斯", "阿德莱德", "堪培拉"] if city in message]
    if city_names and any(word in message for word in ["想去", "优先", "城市", "偏好"]):
        updates["location_preferences"] = "、".join(city_names) + "优先"

    actions: list[dict[str, Any]] = []
    if updates:
        actions.append({"tool": "update_profile", "summary": "已根据你的说明更新申请档案", "arguments": updates})
        actions.append({"tool": "run_recommendation", "summary": "按新条件重新评估选校组合", "arguments": {}})
        reply = "我已记录你的新条件，并重新评估选校组合。你可以继续告诉我更看重城市、预算、课程匹配还是就业方向。"
    elif any(word in message for word in ["提醒我", "加入待办", "创建任务"]):
        title = re.sub(r"^(请|帮我)?(提醒我|加入待办|创建任务)", "", message).strip("：: ，,") or "跟进申请事项"
        actions.append({"tool": "create_task", "summary": "已加入申请待办", "arguments": {"title": title[:80], "category": "其他", "priority": "P1"}})
        reply = f"好的，已把“{title[:80]}”加入申请待办。你可以继续补充具体截止日期。"
    elif any(word in message for word in ["推荐", "选校", "学校", "项目", "方案"]):
        actions.append({"tool": "run_recommendation", "summary": "重新评估选校组合", "arguments": {}})
        reply = "我会先按公开硬门槛排除明显不匹配项目，再结合课程、城市、预算和职业目标给出冲刺、匹配与稳妥组合。"
    else:
        missing = []
        if not profile.coursework_summary:
            missing.append("核心课程")
        if not profile.english_score:
            missing.append("语言成绩")
        if not profile.career_goal:
            missing.append("职业目标")
        reply = "我可以帮你调整选校、解释项目要求或拆解申请任务。" + (f"目前最值得先补充：{'、'.join(missing[:2])}。" if missing else "你的档案已经比较完整，可以直接讨论项目取舍。")
        actions.append({"tool": "answer", "summary": "基于当前档案提供申请建议", "arguments": {}})
    return {"reply": reply, "actions": actions}


def plan_turn(message: str, profile: ApplicantProfile, history: list[dict[str, str]]) -> tuple[str, list[AdvisorAction], dict[str, Any]]:
    started = perf_counter()
    provider = "deterministic-fallback"
    tokens: dict[str, Any] = {"input_tokens": None, "output_tokens": None}
    try:
        model_result = plan_advisor_turn({
            "profile": profile.model_dump(),
            "recent_messages": history[-8:],
            "user_message": message,
        })
        raw = model_result.payload
        provider = model_result.provider
        model = model_result.model
        tokens = {"input_tokens": model_result.input_tokens, "output_tokens": model_result.output_tokens}
    except ModelProviderError:
        raw = fallback_plan(message, profile)
        model = configured_model()
        provider = "deterministic-fallback"

    actions = []
    for item in raw.get("actions", [])[:3]:
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        arguments = {key: value for key, value in arguments.items() if value is not None}
        if item.get("tool") == "update_profile":
            arguments = {key: value for key, value in arguments.items() if key in PROFILE_FIELDS}
        actions.append(AdvisorAction(tool=item.get("tool", "answer"), summary=item.get("summary", "已处理"), arguments=arguments))
    metadata = {"provider": provider, "model": model, "latency_ms": round((perf_counter() - started) * 1000), **tokens}
    return str(raw.get("reply", "我已完成分析。")), actions, metadata
