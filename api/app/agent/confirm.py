"""What the advisor's tools share: the words of a confirm question and of a tool's reply.

A tool that changes something the applicant chose stops the graph with `interrupt` and writes only
after the applicant says yes. The question it asks lists every stored value the change replaces beside
the value it becomes; the answer comes back with that list (`routers.advisor`), and the tool writes
only when what it would write is still what was listed.

A reply starts with one of four phrases, and `app.agent.steps` and `routers.advisor` read the outcome
from the phrase: `CHANGED` (it wrote), `ALREADY` (an earlier run of the same confirmed call wrote, this
one wrote nothing), `DECLINED` (the applicant said no) and `REFUSED` (nothing was asked or written,
with the reason).
"""

import json
from decimal import Decimal

from langchain_core.runnables import RunnableConfig

from app.models.application import ApplicationStatus

CHANGED = "已执行："
ALREADY = "已生效："
DECLINED = "用户取消了操作："
REFUSED = "未执行："

# The applicant's words for each stored status: the ones the overview and 「我的申请」 use
# (`web/lib/taxonomy.ts`), so a confirm card, a tool's reply and every page say the same thing.
STATUS_LABELS = {
    ApplicationStatus.CONSIDERING: "考虑中",
    ApplicationStatus.APPLYING: "准备中",
    ApplicationStatus.SUBMITTED: "已提交",
    ApplicationStatus.OFFERED: "收到录取",
    ApplicationStatus.REJECTED: "未录取",
    ApplicationStatus.EXCLUDED: "已放弃",
}


def status_label(value: str) -> str:
    try:
        return STATUS_LABELS[ApplicationStatus(value)]
    except ValueError:
        return value


def client_id(config: RunnableConfig) -> str:
    """The signed-in applicant, from the run's config and never from the model's arguments."""
    return config["configurable"]["client_id"]


def to_json(value) -> str:
    def default(o):
        return float(o) if isinstance(o, Decimal) else str(o)

    return json.dumps(value, ensure_ascii=False, default=default)


def change(label: str, before: str | None, after: str) -> dict:
    """One line of a confirm question: the value a change replaces and the value it becomes. `before`
    is None for a value that does not exist yet."""
    return {"label": label, "before": before, "after": after}


def answer_of(answer) -> tuple[bool, list | None, dict | None]:
    """The applicant's answer as `routers.advisor` resumes a paused tool with it: whether they said
    yes, the changes the question listed, and the base the question was drawn from. A bare yes or no
    is an answer from before those were sent."""
    if isinstance(answer, dict):
        base = answer.get("base")
        return bool(answer.get("approved")), answer.get("changes"), base if isinstance(base, dict) else None
    return bool(answer), None, None
