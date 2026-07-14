import json

import httpx

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
