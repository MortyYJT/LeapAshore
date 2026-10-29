from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


def merge_dict(a: dict | None, b: dict | None) -> dict:
    """Trace reducer: later writes win per key. ``None`` is the reset sentinel, because merging an
    empty dict into the old trace would leave last turn's keys behind."""
    if b is None:
        return {}
    return {**(a or {}), **b}


class AdvisorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # whole conversation, kept by the checkpointer
    intent: str  # one of intent.INTENTS
    intent_confidence: float
    evidence: str  # numbered evidence lines handed to the model
    citations: list  # the same evidence, structured, for the interface
    evidence_strong: bool  # the gate's verdict
    refusal: str  # why the gate refused: no_school, school_not_collected, no_program_in_field, ...
    refusal_text: str  # what the applicant is told, worded from the catalogue's counts
    steps: int  # model calls in this turn's ReAct loop
    trace: Annotated[dict, merge_dict]
