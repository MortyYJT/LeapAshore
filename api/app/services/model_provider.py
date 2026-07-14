from __future__ import annotations

import json
import os

import httpx

from ..models import AgentRecommendationResponse, ApplicantProfile


class ModelProviderError(RuntimeError):
    pass


def configured_agent_mode() -> str:
    return os.getenv("AGENT_MODE", "deterministic-demo")


def generate_grounded_summary(profile: ApplicantProfile, result: AgentRecommendationResponse) -> str:
    """Generate wording only; eligibility and ranking remain deterministic tool output."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ModelProviderError("OPENAI_API_KEY is not configured")

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
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
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是留学申请规划 Agent 的解释层。只能根据给定工具结果写两句中文总结；"
                    "不得修改档位、门槛、分数或引用，不得声称录取概率。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "profile": profile.model_dump(),
                        "missing_information": result.missing_information,
                        "tool_results": evidence,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as error:
        raise ModelProviderError("model provider request failed") from error

    if not content:
        raise ModelProviderError("model provider returned an empty summary")
    return content
