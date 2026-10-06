from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or from api/.env."""

    database_url: str = "postgresql+psycopg://offerpilot:offerpilot@localhost:55432/offerpilot"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
