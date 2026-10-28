from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or from api/.env."""

    database_url: str = "postgresql+psycopg://offerpilot:offerpilot@localhost:55432/offerpilot"

    # Where uploaded files live. Derived from this file's own location rather than the process cwd,
    # because `make api-test`, `make api-dev` and a script run from the repository root have three
    # different working directories, and a cwd-relative default would scatter the files across all
    # three. Only a path relative to this root is ever stored in the database; see
    # `app.services.documents`.
    document_storage_root: Path = Path(__file__).resolve().parent.parent / "var" / "documents"

    # The advisor's chat model, spoken to over the OpenAI protocol. An empty key leaves the rest of
    # the API working and makes the advisor answer that it is not configured, instead of failing at
    # import time.
    chat_base_url: str = "https://api.siliconflow.cn/v1"
    chat_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    chat_api_key: str = ""
    # Upper bound on model calls in one ReAct loop; counting steps is what stops a tool loop.
    max_agent_steps: int = 6

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
