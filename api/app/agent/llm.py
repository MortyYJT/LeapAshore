import httpx
import openai
from langchain_openai import ChatOpenAI

from app.agent import model_key
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
# How often the SDK sends a call again after a 429, a 5xx or a timeout (its own default).
MAX_RETRIES = 2


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

    Inside `model_key.in_use` the call goes to the applicant's provider with the applicant's key
    instead; everything else about it is the same.

    Classification calls pass ``temperature=0``: a router that answers differently on a replay is a
    router whose mistakes cannot be reproduced.

    Every call carries an output cap, ``max_tokens`` (default ``CHAT_MAX_TOKENS``). It goes in
    ``extra_body`` rather than LangChain's ``max_tokens`` field, which is sent as
    ``max_completion_tokens``: DeepSeek ignored that field in a measured call (206 tokens back with a
    cap of 8) and honoured ``max_tokens`` (8 back, finish reason ``length``). ``stream_usage`` makes a
    streamed reply report its tokens, which the advisor's daily caps count.
    """
    borrowed = model_key.current()
    output_cap = {"max_tokens": max_tokens or settings.chat_max_tokens}
    if borrowed is not None:
        # This turn runs on the applicant's own key, at the listed provider it names.
        provider = borrowed.provider
        upstream = {"model": provider.model, "base_url": provider.base_url, "api_key": borrowed.reveal(),
                    "extra_body": {**output_cap, **provider.extra_body}}
    elif model_configured():
        upstream = {"model": settings.chat_model, "base_url": settings.chat_base_url,
                    "api_key": settings.chat_api_key, "extra_body": output_cap}
    else:
        raise ModelNotConfigured("CHAT_API_KEY is not set")
    return ChatOpenAI(
        **upstream,
        streaming=streaming,
        temperature=temperature,
        timeout=settings.chat_timeout_seconds,
        max_retries=MAX_RETRIES,
        stream_usage=True,
    )
