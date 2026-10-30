import httpx
import openai
from langchain_openai import ChatOpenAI

from app.config import settings

# What the applicant is told when the model's provider cannot answer (an outage, below).
UNAVAILABLE = "顾问暂时不可用，请稍后再试。"

# The provider refused the account: out of money (DeepSeek answers 402 "Insufficient Balance"), a key
# revoked or not allowed. Nothing changes until a person acts, so retrying within minutes is pointless.
ACCOUNT = "account"
# The provider could not answer this time: rate-limited, overloaded, timed out, unreachable.
TRANSIENT = "transient"
_ACCOUNT_STATUSES = {401, 402, 403}
_TRANSIENT_STATUSES = {408, 409, 429}


class ModelNotConfigured(RuntimeError):
    """Raised when the advisor is asked to answer but no chat key is set."""


def outage(error: BaseException | None) -> str | None:
    """`ACCOUNT` or `TRANSIENT` when `error` (or an error it was raised from) is the chat provider not
    answering, else None: a bad request or an unreadable answer is a fault of the call, not an outage.

    OpenAI-style providers use 429 with the code ``insufficient_quota`` for an exhausted account.
    """
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, openai.APIStatusError):
            code = error.code if isinstance(getattr(error, "code", None), str) else ""
            if error.status_code in _ACCOUNT_STATUSES or code == "insufficient_quota":
                return ACCOUNT
            if error.status_code in _TRANSIENT_STATUSES or error.status_code >= 500:
                return TRANSIENT
            return None
        if isinstance(error, (openai.APIConnectionError, httpx.TransportError)):
            return TRANSIENT
        error = error.__cause__ or error.__context__
    return None


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
