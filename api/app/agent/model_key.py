"""An applicant's own model key (docs/product/PRD-multi-device.md, 3.5).

The advisor runs on the owner's key unless a request brings one of its own. The applicant's key comes
in a request header, never in a URL or a body, and it is used in memory for that one request:

- It is read into an `ApplicantKey`, which prints as a placeholder and refuses to be pickled, copied or
  turned into JSON, so a mistake that tries to store it fails where it is made.
- `in_use` holds it in a context variable for the length of the turn. `llm.get_chat_model` reads it
  from there. It is not put in the graph's config or state, because LangGraph saves both with the
  checkpoint; a turn resumed later (a confirm) gets its key from the request that resumes it.
- While a turn runs on a key, what that turn logs and what it saves with its checkpoint is scrubbed
  of the key (`scrub`, `scrub_bytes`, `install_log_scrubbing`; `app.agent.checkpoint`), and the text
  of an exception is not kept at all, only its class and HTTP status. A provider can repeat the key,
  or the end of it, in an error body, and an exception can print the request it came from. LangGraph
  saves the exception of a failed step with the checkpoint, so without this a provider's 401 that
  repeats the key would put it in the database.
- Scrubbing follows the turn's own context, never a list shared by the process: a key is whatever
  string a caller sends, and one caller's string must not be cut out of another's conversation.

The key travels in `Authorization: Bearer`, the header that proxies and log tools already treat as a
secret. Caddy writes the headers of a request it could not proxy to its error log and redacts that
one; a custom header would be written in full (measured on Caddy 2.11.4, docs/measurements.md).

What this does not do: hide the key from this server. It passes through the process in memory, and
whoever operates the server could read it there. The privacy page says so.

The provider is chosen from a fixed list. A request names one by id and can never supply a URL, so the
server cannot be made to call an address of the caller's choosing.
"""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx
import openai

KEY_HEADER = "Authorization"
KEY_SCHEME = "Bearer "
PROVIDER_HEADER = "X-Model-Provider"

# Letters, digits and the few marks keys are made of. None of them is escaped in JSON, in a Python
# repr or in a URL, so a key that turns up in any text turns up exactly as it was sent, and `scrub`
# finds it.
_KEY = re.compile(r"^[A-Za-z0-9._~+/=-]{20,256}$")
_REMOVED = "[key removed]"


@dataclass(frozen=True)
class Provider:
    """One allowed upstream: where it is and which model the advisor asks it for."""

    id: str
    label: str
    base_url: str
    model: str
    # Sent with every chat request to this provider, beside the output cap.
    extra_body: dict = field(default_factory=dict)


# Checked against the providers' documentation on 2026-11-20 (docs/measurements.md, "Own model key").
PROVIDERS: dict[str, Provider] = {
    provider.id: provider
    for provider in (
        # api-docs.deepseek.com: base URL https://api.deepseek.com, model `deepseek-flash`. Thinking is
        # on unless a request turns it off, and a named tool choice (which the intent router and the
        # judge use) is refused with 400 while thinking, so it is turned off here.
        Provider("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash",
                 {"thinking": {"type": "disabled"}}),
        # docs.siliconflow.cn: base URL https://api.siliconflow.cn/v1. The same model the owner's key
        # uses in production (`CHAT_MODEL`), sent the same way.
        Provider("siliconflow", "硅基流动", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V4-Flash"),
    )
}


class Refused(Exception):
    """The key headers cannot be used. Its message never repeats what the headers held."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class ApplicantKey:
    """An applicant's key for one request. It has no printable and no storable form."""

    __slots__ = ("provider", "_value")

    def __init__(self, provider: Provider, value: str) -> None:
        self.provider = provider
        self._value = value

    def reveal(self) -> str:
        """The key itself, for the one place that sends it to the provider."""
        return self._value

    def __repr__(self) -> str:
        return f"<an applicant's key for {self.provider.id}>"

    __str__ = __repr__

    def _never_stored(self, *args, **kwargs):
        raise TypeError("an applicant's key is never copied or stored")

    __reduce__ = __reduce_ex__ = __copy__ = __deepcopy__ = __getstate__ = _never_stored


def from_headers(headers: Mapping[str, str]) -> ApplicantKey | None:
    """The key a request brought, or None when it brought none. Raises `Refused` for a key that names
    no listed provider or is not shaped like a key."""
    carried = headers.get(KEY_HEADER) or headers.get(KEY_HEADER.lower()) or ""
    if carried[: len(KEY_SCHEME)].lower() != KEY_SCHEME.lower():
        return None
    value = carried[len(KEY_SCHEME):].strip()
    if not value:
        return None
    provider = PROVIDERS.get((headers.get(PROVIDER_HEADER) or headers.get(PROVIDER_HEADER.lower()) or "").strip())
    if provider is None:
        listed = "、".join(p.label for p in PROVIDERS.values())
        raise Refused("model_provider_unknown", f"不支持这个模型服务商。可以用的有：{listed}。")
    if not _KEY.match(value):
        raise Refused("model_key_malformed", "这把密钥的格式不对：应该是一串 20 位以上、不带空格的英文字符。请重新粘贴。")
    return ApplicantKey(provider, value)


_current: ContextVar[ApplicantKey | None] = ContextVar("applicant_model_key", default=None)


@contextmanager
def in_use(key: ApplicantKey | None) -> Iterator[None]:
    """Run the enclosed turn on `key`. Tasks and threads started inside inherit it (asyncio and
    LangGraph copy the context); nothing outside sees it."""
    if key is None:
        yield
        return
    token = _current.set(key)
    try:
        yield
    finally:
        try:
            _current.reset(token)
        except ValueError:  # closed from another context: this one ends with the task anyway
            _current.set(None)


def current() -> ApplicantKey | None:
    return _current.get()


def scrub(text: str) -> str:
    """`text` without the key this turn runs on."""
    key = _current.get()
    if key is not None and key.reveal() in text:
        text = text.replace(key.reveal(), _REMOVED)
    return text


def scrub_bytes(data: bytes) -> bytes:
    """`data` with this turn's key overwritten by filler of the same length, so a serialised value
    that states its own length (msgpack) stays readable."""
    key = _current.get()
    if key is not None:
        raw = key.reveal().encode()
        if raw in data:
            data = data.replace(raw, b"*" * len(raw))
    return data


def scrub_json(value):
    """A JSON-like value with every string in it scrubbed."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {scrub_json(k): scrub_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub_json(v) for v in value)
    return value


def error_text(error: BaseException, limit: int = 200) -> str:
    """An error as it may be kept with a turn: class and message, or on an applicant's key the
    classes and HTTP status only, because a provider's message can repeat the key or part of it."""
    if _current.get() is not None:
        return kinds(error)
    return f"{type(error).__name__}: {str(error)}"[:limit]


def _scrub_record(record: logging.LogRecord) -> None:
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 - a record whose arguments do not fit is logged as it stands
        message = str(record.msg)
    cleaned = scrub(message)
    if cleaned != message:
        record.msg, record.args = cleaned, None
    if isinstance(record.exc_info, tuple) and record.exc_info[1] is not None:
        # Where it was raised and what kind of error it was, without its message: the exception
        # object carries the provider's words, so the record keeps the text and drops the object.
        error = record.exc_info[1]
        record.exc_text = f"Traceback (most recent call last):\n{frames(error)}\n{kinds(error)}"
        record.exc_info = None


def install_log_scrubbing() -> None:
    """Make every log record created while a turn runs on an applicant's key pass through `scrub`,
    whichever logger made it (ours, the HTTP client's, the SDK's). A record made anywhere else is
    left alone, at the cost of reading one context variable."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "scrubs_model_keys", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if _current.get() is not None:
            _scrub_record(record)
        return record

    factory.scrubs_model_keys = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


@dataclass(frozen=True)
class Failure:
    """Why a call on an applicant's key did not work, in words that say what to do."""

    code: str
    message: str


_SETTINGS = "「设置 → 模型密钥」"


def _failure(provider: Provider, kind: str, status: int | None = None) -> Failure:
    label = provider.label
    messages = {
        "own_key_rejected": f"{label} 没有接受这把密钥。请到{_SETTINGS}核对或换一把；删除它之后，顾问会改用本站的默认额度。",
        "own_key_no_balance": f"这把密钥所在的 {label} 账户余额不足。充值后再试；也可以到{_SETTINGS}删除它，改用本站的默认额度。",
        "own_key_rate_limited": f"{label} 对这把密钥限流了，过一会儿再发。",
        "own_key_provider_down": f"{label} 没有响应，问题不在密钥上。请稍后再试。",
        "own_key_request_refused": (
            f"{label} 拒绝了这次请求（HTTP {status}）。这把密钥的账户可能用不了 {provider.model}；"
            f"换一把密钥，或者到{_SETTINGS}删除它。"
        ),
    }
    return Failure(kind, messages[kind])


def _by_status(provider: Provider, status: int, code: str = "") -> Failure | None:
    if 200 <= status < 300:
        return None
    if status == 402 or code == "insufficient_quota":
        return _failure(provider, "own_key_no_balance")
    if status in (401, 403):
        return _failure(provider, "own_key_rejected")
    if status == 429:
        return _failure(provider, "own_key_rate_limited")
    if status in (408, 409) or status >= 500:
        return _failure(provider, "own_key_provider_down")
    return _failure(provider, "own_key_request_refused", status)


def failure(error: BaseException | None, provider: Provider) -> Failure | None:
    """What the provider did to a turn on an applicant's key, or None when the fault is not the
    provider's (a bug of ours, an answer that could not be read)."""
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, openai.APIStatusError):
            code = error.code if isinstance(getattr(error, "code", None), str) else ""
            return _by_status(provider, error.status_code, code)
        if isinstance(error, (openai.APIConnectionError, httpx.TransportError)):
            return _failure(provider, "own_key_provider_down")
        error = error.__cause__ or error.__context__
    return None


def kinds(error: BaseException | None) -> str:
    """The classes of an error and of what caused it, with an HTTP status where there is one. Safe to
    log: no message, no request."""
    names: list[str] = []
    seen: set[int] = set()
    while error is not None and id(error) not in seen and len(names) < 6:
        seen.add(id(error))
        status = getattr(error, "status_code", None)
        names.append(type(error).__name__ + (f"[{status}]" if isinstance(status, int) else ""))
        error = error.__cause__ or error.__context__
    return " <- ".join(names) or "unknown"


def frames(error: BaseException) -> str:
    """Where an error was raised: file, line and function of each frame, without the message."""
    return "".join(traceback.format_tb(error.__traceback__)[-12:]).rstrip("\n")


async def check(key: ApplicantKey, timeout: float) -> Failure | None:
    """Ask the provider for its model list with `key`: a request that spends no tokens and is refused
    for a wrong key. None when the provider accepted it."""
    with in_use(key):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"{key.provider.base_url}/models", headers={"Authorization": f"Bearer {key.reveal()}"}
                )
        except httpx.HTTPError:
            return _failure(key.provider, "own_key_provider_down")
        return _by_status(key.provider, response.status_code)
