import json

import httpx

from app.models import ApplicantProfile
from app.services.deepseek_advisor import build_redacted_context
from app.services import model_provider


def test_ollama_provider_uses_private_chat_endpoint_and_records_usage(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "qwen2.5:0.5b"
        assert payload["stream"] is False
        assert payload["format"]["type"] == "object"
        return httpx.Response(200, json={
            "message": {"content": json.dumps({
                "reply": "我会先核验你的申请条件。",
                "actions": [{"tool": "answer", "summary": "解释申请条件", "arguments": {}}],
            }, ensure_ascii=False)},
            "prompt_eval_count": 120,
            "eval_count": 24,
        })

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(model_provider.httpx, "Client", lambda timeout: original_client(transport=transport, timeout=timeout))

    result = model_provider.plan_advisor_turn({"user_message": "帮我看看选校"})
    assert result.provider == "ollama"
    assert result.model == "qwen2.5:0.5b"
    assert result.input_tokens == 120
    assert result.output_tokens == 24


def test_deepseek_configuration_and_redacted_context_exclude_direct_identifiers(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-secret")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    assert model_provider.configured_provider() == "deepseek"
    assert model_provider.configured_model() == "deepseek-v4-flash"

    profile = ApplicantProfile(
        undergraduate_school="绝密大学", school_tier="双非", undergraduate_major="软件工程",
        gpa=82, gpa_scale=100, target_field="计算机与数据", coursework_summary="数据结构、数据库",
    )
    context = build_redacted_context(
        profile, None, [], None,
        [{"role": "user", "content": "我是测试用户，邮箱 pii@example.com"}],
        "请给测试用户建议", ["测试用户", "pii@example.com", "user_secret", "绝密大学"],
    )
    serialized = json.dumps(context, ensure_ascii=False)
    for forbidden in ["测试用户", "pii@example.com", "user_secret", "绝密大学"]:
        assert forbidden not in serialized
    assert context["profile"]["gpa_percent"] == 82
    assert "undergraduate_school" not in context["profile"]
