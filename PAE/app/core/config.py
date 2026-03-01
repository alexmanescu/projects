"""Application settings loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="mysql+pymysql://user:password@localhost/pae",
        description="SQLAlchemy connection URL for MySQL",
    )

    # ── LLMs ─────────────────────────────────────────────────────────────────
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen3-coder:30b")
    anthropic_api_key: str = Field(default="")
    claude_model: str = Field(default="claude-sonnet-4-6")

    # ── Brokers ───────────────────────────────────────────────────────────────
    alpaca_api_key: str = Field(default="")
    alpaca_secret_key: str = Field(default="")
    alpaca_base_url: str = Field(default="https://paper-api.alpaca.markets")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # ── Prediction Markets ────────────────────────────────────────────────────
    kalshi_api_key: str = Field(default="")
    kalshi_secret: str = Field(default="")

    # ── Runtime ───────────────────────────────────────────────────────────────
    paper_trading: bool = Field(default=True)
    dry_run: bool = Field(default=True, description="Skip all external side-effects")
    check_interval_minutes: int = Field(default=60)
    log_level: str = Field(default="INFO")


settings = Settings()
