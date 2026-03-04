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
    ollama_fallback_url: str = Field(
        default="",
        description="Secondary Ollama endpoint (e.g. Windows GPU). Tried after primary fails.",
    )
    ollama_model: str = Field(default="hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_M")
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
    kalshi_base_url: str = Field(default="https://api.elections.kalshi.com/trade-api/v2")

    # ── Signal surfacing ──────────────────────────────────────────────────────
    layer_a_signal_min_strength: float = Field(
        default=0.4,
        description="Minimum signal_strength to surface a Layer A opportunity",
    )
    layer_a_signal_lookback_hours: int = Field(
        default=2,
        description="How far back to query article_analysis for Layer A signals",
    )

    # ── Runtime ───────────────────────────────────────────────────────────────
    # dry_run=True  → master kill-switch; no orders anywhere, no Telegram sends
    # paper_trading=True  → Alpaca uses paper account (paper-api.alpaca.markets)
    # kalshi_live=True  → actually place Kalshi orders (requires dry_run=False)
    dry_run: bool = Field(default=True, description="Master kill-switch — skips all external side-effects")
    paper_trading: bool = Field(default=True, description="Use Alpaca paper account instead of live")
    kalshi_live: bool = Field(default=False, description="Place real Kalshi orders (dry_run must also be False)")
    check_interval_minutes: int = Field(default=60)
    max_share_price: float = Field(
        default=50.0,
        description="Skip equity opportunities where the current share price exceeds this (USD). Set to 0 to disable.",
    )
    log_level: str = Field(default="INFO")


settings = Settings()
