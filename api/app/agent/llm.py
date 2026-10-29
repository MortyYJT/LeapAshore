from langchain_openai import ChatOpenAI

from app.config import settings


class ModelNotConfigured(RuntimeError):
    """Raised when the advisor is asked to answer but no chat key is set."""


def model_configured() -> bool:
    return bool(settings.chat_api_key)


def get_chat_model(
    streaming: bool = False, temperature: float = 0.3, max_tokens: int | None = None
) -> ChatOpenAI:
    """The chat upstream, over the OpenAI protocol, so the provider is a matter of three settings.

    Classification calls pass ``temperature=0``: a router that answers differently on a replay is a
    router whose mistakes cannot be reproduced.

    Every call carries an output cap, ``max_tokens`` (default ``CHAT_MAX_TOKENS``). It goes in
    ``extra_body`` rather than LangChain's ``max_tokens`` field, which is sent as
    ``max_completion_tokens``: DeepSeek ignored that field in a measured call (206 tokens back with a
    cap of 8) and honoured ``max_tokens`` (8 back, finish reason ``length``). ``stream_usage`` makes a
    streamed reply report its tokens, which the advisor's daily caps count.
    """
    if not model_configured():
        raise ModelNotConfigured("CHAT_API_KEY is not set")
    return ChatOpenAI(
        model=settings.chat_model,
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key,
        streaming=streaming,
        temperature=temperature,
        timeout=60,
        stream_usage=True,
        extra_body={"max_tokens": max_tokens or settings.chat_max_tokens},
    )
