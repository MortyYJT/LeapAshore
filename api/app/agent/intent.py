"""Intent routing.

The test for an intent is which piece of application state the message wants to change, not which
words it contains. An application only changes in these five ways, so there are five intents.
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.llm import get_chat_model, outage
from app.config import settings

logger = logging.getLogger(__name__)

INTENTS = ("规划", "官方要求核验", "资料补充", "业务操作", "通用问答")

# intent -> graph exit. Only requirement questions take the deterministic retrieval path; the rest go
# to the ReAct agent, whose tools carry their own write rules.
INTENT_TO_ROUTE: dict[str, str] = {
    "官方要求核验": "requirements",
    "规划": "agent",
    "资料补充": "agent",
    "业务操作": "agent",
    "通用问答": "agent",
}

FALLBACK_INTENT = "通用问答"

_PROMPT = """你是留学申请顾问系统的意图分类器。判据是"这条消息想改变申请状态的哪一部分"，不是关键词。
五类意图：
- 规划：想改变申请哪些项目，例如选校、加减项目、换首选、问自己适合申什么
- 官方要求核验：问某个具体项目或学校的官方录取要求，例如均分、语言、背景、材料、截止日期
- 资料补充：提供了自己的新背景信息，例如学校、均分、专业、雅思成绩、预算、入学时间
- 业务操作：想修改已有的任务或材料状态
- 通用问答：以上都不是

最近对话：
{history}

当前消息：{query}"""


class IntentResult(BaseModel):
    intent: Literal["规划", "官方要求核验", "资料补充", "业务操作", "通用问答"]
    confidence: float = Field(ge=0, le=1, description="0 到 1 之间的把握程度")


async def classify(query: str, history: str) -> dict:
    """Classify one message. A failure falls back to general Q&A, the one exit that writes nothing,
    except the provider not answering at all: that is raised, because the fallback route would only
    call the same provider again, and the applicant is told the advisor is unavailable."""
    try:
        model = get_chat_model(temperature=0, max_tokens=settings.intent_max_tokens).with_structured_output(
            IntentResult, method="function_calling"
        )
        result = await model.ainvoke(_PROMPT.format(history=history or "（无）", query=query))
        return {"intent": result.intent, "confidence": result.confidence}
    except Exception as error:  # noqa: BLE001 - a router error must degrade, not break the turn
        if outage(error):
            raise
        logger.exception("intent classification failed; falling back to %s", FALLBACK_INTENT)
        return {"intent": FALLBACK_INTENT, "confidence": 0.0}
