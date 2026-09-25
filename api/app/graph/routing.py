from typing import Any

Intent = str


def classify_intent(message: str) -> Intent:
    text = message.casefold()
    if any(term in text for term in ("创建", "添加", "删除", "提交", "create", "delete", "submit")):
        return "action"
    if any(term in text for term in ("补充", "还需要", "我的资料", "缺少", "profile", "what do you need")):
        return "profile_clarification"
    if any(term in text for term in ("要求", "官网", "截止", "学费", "语言", "requirement", "deadline", "tuition")):
        return "official_knowledge"
    if any(term in text for term in ("规划", "推荐", "申请", "路线", "plan", "recommend")):
        return "planning"
    return "other"


def route_intent(
    intent: Intent,
    *,
    ambiguous: bool,
    profile_snapshot: dict[str, Any] | None,
    high_impact: bool = False,
) -> str:
    if ambiguous or intent == "profile_clarification" or (intent == "planning" and not profile_snapshot):
        return "clarify"
    if high_impact or intent == "action":
        return "deterministic_action"
    if intent == "official_knowledge":
        return "retrieve_official_facts"
    if intent == "planning":
        return "deterministic_recommendation"
    return "general_response"
