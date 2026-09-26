from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STATE_SCHEMA_VERSION = 1


class AdvisorState(BaseModel):
    """Checkpoint-safe state for one advisor request; identifiers are opaque refs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = STATE_SCHEMA_VERSION
    user_id: str = ""
    thread_id: str = ""
    request_id: str = ""
    expected_revision: int = Field(default=0, ge=0)
    profile_snapshot: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    intent: Literal["planning", "official_knowledge", "profile_clarification", "action", "other"] = "other"
    route: str = ""
    recommendation: dict[str, Any] | None = None
    context_layers: dict[str, str] = Field(default_factory=dict)
    knowledge_evidence: list[dict[str, Any]] = Field(default_factory=list)
    confidence_decision: dict[str, Any] = Field(default_factory=dict)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    provider_usage: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    final_reply: str = ""

    @model_validator(mode="before")
    @classmethod
    def require_supported_schema(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("schema_version", STATE_SCHEMA_VERSION) != STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {value.get('schema_version')}")
        return value
