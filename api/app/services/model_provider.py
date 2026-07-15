from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import AgentRecommendationResponse, ApplicantProfile
from ..taxonomy import DEGREE_LEVELS, STUDY_AREAS


class ModelProviderError(RuntimeError):
    pass


@dataclass
class ModelResult:
    payload: dict[str, Any]
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


def configured_agent_mode() -> str:
    if configured_provider() in {"openai", "ollama", "deepseek"}:
        return "llm-assisted"
    return os.getenv("AGENT_MODE", "deterministic-demo")


def configured_model() -> str:
    if configured_provider() == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-5-mini")
    if configured_provider() == "deepseek":
        return os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    return os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")


def configured_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "deterministic").lower()
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        return "deterministic"
    if provider == "deepseek" and not os.getenv("DEEPSEEK_API_KEY"):
        return "deterministic"
    return provider if provider in {"openai", "ollama", "deepseek"} else "deterministic"


def llm_is_configured() -> bool:
    return configured_provider() in {"openai", "ollama", "deepseek"}


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
    provider = configured_provider()
    if provider == "deterministic":
        raise ModelProviderError("no model provider is configured")
    model = configured_model()
    argument_properties: dict[str, Any] = {
        "current_education_level": {"enum": ["高中", "本科", "硕士", "其他", None]},
        "undergraduate_school": {"type": ["string", "null"]},
        "school_tier": {"enum": ["高中/国际课程", "985", "211/双一流", "双非", "海外重点", "其他", None]},
        "undergraduate_major": {"type": ["string", "null"]},
        "gpa": {"type": ["number", "null"]},
        "gpa_scale": {"type": ["number", "null"]},
        "target_degree_level": {"enum": [*DEGREE_LEVELS, None]},
        "target_field": {"enum": [*STUDY_AREAS, None]},
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
    instructions = (
        "你是 OfferPilot 澳洲留学申请顾问，覆盖本科、授课型硕士、研究型硕士和博士。基于用户档案和已验证项目数据回答。"
        "主动指出缺失信息；不承诺录取，不编造截止日期、费用或要求。"
        "研究型申请需要额外考虑研究经历、研究计划和导师匹配；本科申请需要考虑高中课程与成绩体系。"
        "需要修改档案时调用 update_profile；需要重算选校时调用 run_recommendation；"
        "需要加入待办时调用 create_task。一次最多 3 个动作。"
    )
    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(f"{base_url}/api/chat", json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                    ],
                    "format": schema,
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0, "num_ctx": 4096},
                })
                response.raise_for_status()
            body = response.json()
            parsed = json.loads(body["message"]["content"])
            return ModelResult(parsed, "ollama", model, body.get("prompt_eval_count"), body.get("eval_count"))
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ModelProviderError("ollama request failed") from error

    if provider == "deepseek":
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        try:
            with httpx.Client(timeout=25) as client:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": instructions + "只输出合法 JSON。"},
                            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                        ],
                        "response_format": {"type": "json_object"},
                        "thinking": {"type": "disabled"},
                        "stream": False,
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
            body = response.json()
            parsed = json.loads(body["choices"][0]["message"]["content"])
            usage = body.get("usage", {})
            return ModelResult(parsed, "deepseek", model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ModelProviderError("deepseek request failed") from error

    api_key = os.getenv("OPENAI_API_KEY")
    payload = {
        "model": model,
        "instructions": instructions,
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
        return ModelResult(parsed, "openai", model, usage.get("input_tokens"), usage.get("output_tokens"))
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ModelProviderError("model provider request failed") from error


def generate_grounded_summary(profile: ApplicantProfile, result: AgentRecommendationResponse) -> str:
    """Generate wording only; eligibility and ranking remain deterministic tool output."""
    provider = configured_provider()
    if provider == "deterministic":
        raise ModelProviderError("no model provider is configured")

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
    instructions = "你是留学申请规划 Agent 的解释层。只能根据工具结果写两句中文总结；不得修改档位、门槛、分数或引用，不得声称录取概率。"
    grounded_input = json.dumps({"profile": profile.model_dump(), "missing_information": result.missing_information, "tool_results": evidence}, ensure_ascii=False)
    if provider == "ollama":
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    f"{os.getenv('OLLAMA_BASE_URL', 'http://ollama:11434').rstrip('/')}/api/chat",
                    json={"model": model, "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": grounded_input},
                    ], "stream": False, "keep_alive": "30m", "options": {"temperature": 0}},
                )
                response.raise_for_status()
            content = response.json()["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, TypeError) as error:
            raise ModelProviderError("ollama request failed") from error
        if not content:
            raise ModelProviderError("ollama returned an empty summary")
        return content

    if provider == "deepseek":
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(
                    f"{os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": instructions},
                            {"role": "user", "content": grounded_input},
                        ],
                        "thinking": {"type": "disabled"},
                        "stream": False,
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, TypeError) as error:
            raise ModelProviderError("deepseek request failed") from error
        if not content:
            raise ModelProviderError("deepseek returned an empty summary")
        return content

    api_key = os.getenv("OPENAI_API_KEY")
    payload = {
        "model": model,
        "instructions": instructions,
        "input": grounded_input,
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
