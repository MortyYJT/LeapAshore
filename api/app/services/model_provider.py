from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import AgentRecommendationResponse, ApplicantProfile


class ModelProviderError(RuntimeError):
    pass


@dataclass
class ModelResult:
    payload: dict[str, Any]
    model: str
    input_tokens: int | None
    output_tokens: int | None


def configured_agent_mode() -> str:
    if os.getenv("OPENAI_API_KEY"):
        return "llm-assisted"
    return os.getenv("AGENT_MODE", "deterministic-demo")


def configured_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5-mini")


def llm_is_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _output_text(body: dict[str, Any]) -> str:
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                return str(part.get("text", "")).strip()
    return ""


def plan_advisor_turn(context: dict[str, Any]) -> ModelResult:
    """Ask the model for a constrained plan; server-side code executes every mutation."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ModelProviderError("OPENAI_API_KEY is not configured")
    model = configured_model()
    argument_properties: dict[str, Any] = {
        "undergraduate_school": {"type": ["string", "null"]},
        "school_tier": {"enum": ["985", "211/双一流", "双非", "海外重点", "其他", None]},
        "undergraduate_major": {"type": ["string", "null"]},
        "gpa": {"type": ["number", "null"]},
        "gpa_scale": {"type": ["number", "null"]},
        "target_field": {"enum": ["计算机与数据", "商科与金融", "工程", "教育与社会科学", "生命科学", None]},
        "intake": {"type": ["string", "null"]},
        "english_score": {"type": ["string", "null"]},
        "coursework_summary": {"type": ["string", "null"]},
        "experience_summary": {"type": ["string", "null"]},
        "career_goal": {"type": ["string", "null"]},
        "location_preferences": {"type": ["string", "null"]},
        "annual_budget_aud": {"type": ["number", "null"]},
        "title": {"type": ["string", "null"]},
        "detail": {"type": ["string", "null"]},
        "category": {"enum": ["选校", "成绩单", "语言", "材料", "截止日期", "其他", None]},
        "priority": {"enum": ["P0", "P1", "P2", None]},
        "due_at": {"type": ["string", "null"]},
        "reminder_at": {"type": ["string", "null"]},
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reply": {"type": "string"},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tool": {"type": "string", "enum": ["update_profile", "run_recommendation", "create_task", "answer"]},
                        "summary": {"type": "string"},
                        "arguments": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": argument_properties,
                            "required": list(argument_properties),
                        },
                    },
                    "required": ["tool", "summary", "arguments"],
                },
            },
        },
        "required": ["reply", "actions"],
    }
    payload = {
        "model": model,
        "instructions": (
            "你是 OfferPilot 澳洲硕士申请顾问。基于用户档案和已验证项目数据回答。"
            "主动指出缺失信息；不承诺录取，不编造截止日期、费用或要求。"
            "需要修改档案时调用 update_profile；需要重算选校时调用 run_recommendation；"
            "需要加入待办时调用 create_task。一次最多 3 个动作。"
        ),
        "input": json.dumps(context, ensure_ascii=False),
        "text": {"format": {"type": "json_schema", "name": "advisor_turn", "strict": True, "schema": schema}},
        "store": False,
    }
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{base_url}/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        parsed = json.loads(_output_text(body))
        usage = body.get("usage", {})
        return ModelResult(parsed, model, usage.get("input_tokens"), usage.get("output_tokens"))
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ModelProviderError("model provider request failed") from error


def generate_grounded_summary(profile: ApplicantProfile, result: AgentRecommendationResponse) -> str:
    """Generate wording only; eligibility and ranking remain deterministic tool output."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ModelProviderError("OPENAI_API_KEY is not configured")

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = configured_model()
    evidence = [
        {
            "program": item.program.name,
            "tier": item.tier,
            "eligibility": item.eligibility,
            "reasons": item.reasons,
            "risks": item.risks,
            "source_id": item.program.source.id,
        }
        for item in result.recommendations
    ]
    payload = {
        "model": model,
        "instructions": "你是留学申请规划 Agent 的解释层。只能根据工具结果写两句中文总结；不得修改档位、门槛、分数或引用，不得声称录取概率。",
        "input": json.dumps({"profile": profile.model_dump(), "missing_information": result.missing_information, "tool_results": evidence}, ensure_ascii=False),
        "store": False,
    }

    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                f"{base_url}/responses",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        content = _output_text(response.json())
    except (httpx.HTTPError, KeyError, TypeError) as error:
        raise ModelProviderError("model provider request failed") from error

    if not content:
        raise ModelProviderError("model provider returned an empty summary")
    return content
