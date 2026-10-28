from langchain_openai import ChatOpenAI

from app.config import settings


class ModelNotConfigured(RuntimeError):
    """Raised when the advisor is asked to answer but no chat key is set."""


def model_configured() -> bool:
    return bool(settings.chat_api_key)


def get_chat_model(streaming: bool = False, temperature: float = 0.3) -> ChatOpenAI:
    """The chat upstream, over the OpenAI protocol, so the provider is a matter of three settings.

    Classification calls pass ``temperature=0``: a router that answers differently on a replay is a
    router whose mistakes cannot be reproduced.
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
    )
