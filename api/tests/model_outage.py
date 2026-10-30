"""A chat model whose provider answers every call the way DeepSeek did with the account out of money.

The body is the one `api.deepseek.com/chat/completions` returned on 2026-10-30 at a balance of
-0.06 CNY (HTTP 402). The model is a real `ChatOpenAI` over a mock transport, so the error reaches the
code under test through the same OpenAI client and LangChain layers as in production.
"""

import httpx
from langchain_openai import ChatOpenAI

INSUFFICIENT_BALANCE = {
    "error": {
        "message": "Insufficient Balance (request_id: 00000000-0000-0000-0000-000000000000)",
        "type": "insufficient_balance_error",
        "param": None,
        "code": "invalid_request_error",
    }
}


def status_error(status: int, body: dict | None = None):
    """The exception the OpenAI client raises for an HTTP `status` answer."""
    import openai

    request = httpx.Request("POST", "https://api.deepseek.test/chat/completions")
    response = httpx.Response(status, json=body or INSUFFICIENT_BALANCE, request=request)
    client = openai.OpenAI(api_key="test", base_url="https://api.deepseek.test")
    return client._make_status_error_from_response(response)


def out_of_balance_model(calls: list | None = None, **kwargs) -> ChatOpenAI:
    """A `ChatOpenAI` whose every request gets DeepSeek's 402 answer; `calls` collects the requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(402, json=INSUFFICIENT_BALANCE)

    return ChatOpenAI(
        model="deepseek-chat",
        api_key="test-key",
        base_url="https://api.deepseek.test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        stream_usage=True,
        **kwargs,
    )
