"""System health check for PAE workers.

:func:`check_system_health` is designed to be called:
- At scheduler startup (abort early if critical services are down).
- Periodically from a monitoring script or web endpoint.
- By the ``scripts/run_workers.py`` entry point before starting the loop.

Return value example::

    {
        "overall": "healthy",          # "healthy" | "degraded" | "unhealthy"
        "database": "ok",
        "ollama": "ok",
        "broker": "ok",
        "telegram": "ok",              # config-only check — no message sent
        "details": {
            "broker_account": "paper",
            "ollama_model": "qwen3-coder:30b",
        }
    }

Status codes per component:
- ``"ok"``          — reachable and functional
- ``"degraded"``    — reachable but with warnings (e.g. broker is live, not paper)
- ``"unavailable"`` — could not connect / not configured
- ``"not_configured"`` — required env var is empty
"""

from __future__ import annotations

import logging
import time

from app.core.config import settings
from app.core.database import ping_db

logger = logging.getLogger(__name__)


def check_system_health() -> dict:
    """Run connectivity checks for all PAE subsystems.

    Returns:
        A dict with an ``"overall"`` key (``"healthy"``, ``"degraded"``, or
        ``"unhealthy"``) and one key per subsystem.  Never raises — all errors
        are caught and reported in the return value.
    """
    results: dict = {
        "overall": "healthy",
        "database": "unknown",
        "ollama": "unknown",
        "broker": "unknown",
        "telegram": "unknown",
        "details": {},
    }

    # ── Database ──────────────────────────────────────────────────────────────
    results["database"] = _check_database(results["details"])

    # ── Ollama ────────────────────────────────────────────────────────────────
    results["ollama"] = _check_ollama(results["details"])

    # ── Broker (Alpaca) ───────────────────────────────────────────────────────
    results["broker"] = _check_broker(results["details"])

    # ── Telegram ──────────────────────────────────────────────────────────────
    results["telegram"] = _check_telegram(results["details"])

    # ── Overall status ────────────────────────────────────────────────────────
    statuses = [results["database"], results["ollama"], results["broker"], results["telegram"]]

    if "unavailable" in statuses or results["database"] == "unavailable":
        results["overall"] = "unhealthy"
    elif "degraded" in statuses or "not_configured" in statuses:
        results["overall"] = "degraded"
    else:
        results["overall"] = "healthy"

    logger.info(
        "Health check: overall=%s db=%s ollama=%s broker=%s telegram=%s",
        results["overall"],
        results["database"],
        results["ollama"],
        results["broker"],
        results["telegram"],
    )
    return results


# ── Component checkers ────────────────────────────────────────────────────────

def _check_database(details: dict) -> str:
    try:
        reachable = ping_db()
        if reachable:
            details["database_url"] = _mask_url(settings.database_url)
            return "ok"
        return "unavailable"
    except Exception as exc:
        logger.warning("DB health check failed: %s", exc)
        details["database_error"] = str(exc)
        return "unavailable"


def _check_ollama(details: dict) -> str:
    if not settings.ollama_base_url:
        return "not_configured"

    try:
        import requests

        url = settings.ollama_base_url.rstrip("/") + "/api/version"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        version = resp.json().get("version", "unknown")
        details["ollama_version"] = version
        details["ollama_model"] = settings.ollama_model
        return "ok"
    except Exception as exc:
        logger.warning("Ollama health check failed: %s", exc)
        details["ollama_error"] = str(exc)
        return "unavailable"


def _check_broker(details: dict) -> str:
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        return "not_configured"

    try:
        from app.services.trading.alpaca_interface import AlpacaBroker
        from app.services.trading.broker_interface import BrokerError

        broker = AlpacaBroker()
        account = broker.get_account_info()

        details["broker_account"] = "paper" if account.is_paper else "live"
        details["broker_portfolio_value"] = f"${account.portfolio_value:,.2f}"
        details["broker_buying_power"] = f"${account.buying_power:,.2f}"

        if not account.is_paper and not settings.paper_trading:
            # Live trading is intentional but worth flagging
            details["broker_warning"] = "LIVE trading mode — not paper"
            return "degraded"

        return "ok"
    except Exception as exc:
        logger.warning("Broker health check failed: %s", exc)
        details["broker_error"] = str(exc)
        return "unavailable"


def _check_telegram(details: dict) -> str:
    """Config-only check — does not send a test message."""
    if not settings.telegram_bot_token:
        return "not_configured"
    if not settings.telegram_chat_id:
        details["telegram_warning"] = "TELEGRAM_CHAT_ID not set"
        return "not_configured"

    # Lightweight token-format check (format: "12345678:ABC-DEF...")
    token = settings.telegram_bot_token
    if ":" not in token or len(token) < 10:
        details["telegram_error"] = "Token format appears invalid"
        return "degraded"

    details["telegram_chat_id"] = settings.telegram_chat_id
    return "ok"


# ── Utility ───────────────────────────────────────────────────────────────────

def _mask_url(url: str) -> str:
    """Return database URL with password masked (for safe logging)."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(parsed.password, "****")
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return "***"
