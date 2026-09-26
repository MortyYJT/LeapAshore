from typing import Any

Intent = str


def classify_intent(message: str) -> Intent:
    text = message.casefold()
    if any(term in text for term in ("创建", "添加", "提醒我", "加入待办", "删除", "提交", "create", "delete", "submit")):
        return "action"
    if any(term in text for term in ("补充", "还需要", "我的资料", "缺少", "profile", "what do you need")):
        return "profile_clarification"
    if any(term in text for term in ("规划", "重新推荐", "选校", "方案", "recommend", "make a plan")):
        return "planning"
    if any(term in text for term in (
        "要求", "官网", "截止", "学费", "语言", "政策", "成绩", "均分", "gpa", "背景",
        "先修", "课程", "算法", "门槛", "数学", "雅思", "ielts", "双非", "非 it", "非it",
        "requirement", "deadline", "tuition", "policy", "prerequisite", "minimum mark",
    )):
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
