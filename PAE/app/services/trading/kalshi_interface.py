"""Kalshi prediction-market interface for PAE.

Wraps the Kalshi REST API v2 using direct HTTP requests with RSA-PKCS1v15
signing.  Keeps the SDK optional — falls back to ``requests`` + the
``cryptography`` package which is already a common dependency.

Authentication headers:
    KALSHI-ACCESS-KEY        — API key ID from settings.kalshi_api_key
    KALSHI-ACCESS-TIMESTAMP  — Unix timestamp in milliseconds (string)
    KALSHI-ACCESS-SIGNATURE  — base64( RSA_PKCS1v15_sign(private_key,
                                timestamp + METHOD + path) )

The private key is stored as PEM text in settings.kalshi_secret.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class KalshiError(Exception):
    """Raised on Kalshi API errors."""


class KalshiInterface:
    """Thin wrapper around the Kalshi trade-api/v2 REST endpoints.

    All methods respect ``settings.dry_run`` — in dry-run mode no orders are
    placed; find/read operations still execute so the pipeline can evaluate
    markets.
    """

    def __init__(self) -> None:
        self._base = settings.kalshi_base_url.rstrip("/")
        self._key_id = settings.kalshi_api_key
        self._private_key_pem = settings.kalshi_secret
        self._session = None   # lazy

    # ── Public API ────────────────────────────────────────────────────────────

    def find_markets(
        self,
        search_term: str,
        limit: int = 10,
    ) -> list[dict]:
        """Return active Kalshi markets matching *search_term*.

        The Kalshi REST API v2 does not support free-text search on the
        ``/markets`` endpoint.  We use two strategies:

        1. ``GET /events?status=active&with_nested_markets=true`` — fetch up to
           100 events with their nested markets, then filter client-side by
           whether any search word appears in the event title.
        2. Fallback: ``GET /markets?status=active`` — fetch up to 200 markets
           and filter client-side by market title.

        Args:
            search_term: Free-text query (e.g. "China tariff", "semiconductor").
            limit: Maximum results to return.

        Returns:
            List of market dicts, each augmented with ``yes_price`` and
            ``no_price`` fields (cents, 0–99).
        """
        # Build filter words — require length > 2 to skip common prepositions
        search_words = [w for w in search_term.lower().split() if len(w) > 2]
        if not search_words:
            search_words = [search_term.lower()]

        def _title_matches(title: str) -> bool:
            t = (title or "").lower()
            return any(w in t for w in search_words)

        def _augment(m: dict) -> dict:
            # Prefer bid (reliable mid-market proxy) over ask; last_price as fallback
            yes_price = m.get("yes_bid") or m.get("yes_ask") or m.get("last_price") or 50
            return {**m, "yes_price": yes_price, "no_price": 100 - yes_price}

        results: list[dict] = []

        # ── Strategy 1: events with nested markets (title-filtered) ───────────
        try:
            data = self._get("/events", params={
                "status": "active",
                "limit": 100,
                "with_nested_markets": "true",
            })
            for event in data.get("events", []):
                if not _title_matches(event.get("title", "")):
                    continue
                for m in event.get("markets", []):
                    results.append(_augment(m))
                    if len(results) >= limit:
                        return results
        except KalshiError as exc:
            logger.warning("find_markets(%r): /events failed: %s", search_term, exc)

        if results:
            return results

        # ── Strategy 2: /markets fallback (title-filtered) ────────────────────
        try:
            data = self._get("/markets", params={"status": "active", "limit": 200})
            for m in data.get("markets", []):
                if not _title_matches(m.get("title", "")):
                    continue
                results.append(_augment(m))
                if len(results) >= limit:
                    break
        except KalshiError as exc:
            logger.warning("find_markets(%r): /markets fallback failed: %s", search_term, exc)

        return results

    def get_market(self, market_ticker: str) -> dict:
        """Return full market details for *market_ticker*.

        Args:
            market_ticker: Kalshi market ticker (e.g. ``"PRES-2024-DJT"``).

        Returns:
            Market dict with ``yes_price`` and ``no_price`` fields.

        Raises:
            KalshiError: If the market is not found or the request fails.
        """
        data = self._get(f"/markets/{market_ticker}")
        market = data.get("market", data)
        yes_price = market.get("yes_ask") or market.get("yes_bid") or 50
        return {**market, "yes_price": yes_price, "no_price": 100 - yes_price}

    def buy_contracts(
        self,
        market_ticker: str,
        side: str,
        count: int,
        max_price_cents: int,
    ) -> dict:
        """Submit a limit order for prediction-market contracts.

        Args:
            market_ticker: Kalshi market ticker.
            side: ``"yes"`` or ``"no"``.
            count: Number of contracts (each pays $1 if correct).
            max_price_cents: Maximum price to pay in cents (1–99).

        Returns:
            Order response dict from the API (or a dry-run stub).

        Raises:
            KalshiError: If the order is rejected or ``count``/``side`` invalid.
        """
        if side not in ("yes", "no"):
            raise KalshiError(f"side must be 'yes' or 'no', got {side!r}")
        if not 1 <= max_price_cents <= 99:
            raise KalshiError(f"max_price_cents must be 1–99, got {max_price_cents}")

        if settings.dry_run or not settings.kalshi_live:
            label = "DRY_RUN" if settings.dry_run else "KALSHI_LIVE=false"
            logger.info(
                "[%s] Kalshi buy: %s %s x%d @ max %d¢",
                label, market_ticker, side, count, max_price_cents,
            )
            return {
                "order_id": "dry-run",
                "market_ticker": market_ticker,
                "side": side,
                "count": count,
                "price": max_price_cents,
                "status": "dry_run",
            }

        payload = {
            "ticker": market_ticker,
            "side": side,
            "count": count,
            "type": "limit",
            "yes_price" if side == "yes" else "no_price": max_price_cents,
            "action": "buy",
        }
        data = self._post("/portfolio/orders", payload)
        logger.info(
            "Kalshi order placed: %s %s x%d @ %d¢ → %s",
            market_ticker, side, count, max_price_cents,
            data.get("order", {}).get("status", "unknown"),
        )
        return data.get("order", data)

    def get_positions(self) -> list[dict]:
        """Return all open Kalshi positions.

        Returns:
            List of position dicts with ``market_ticker``, ``position``
            (net contracts), ``market_exposure``, and ``realised_pnl``.
        """
        try:
            data = self._get("/portfolio/positions")
            return data.get("market_positions", [])
        except KalshiError as exc:
            logger.warning("get_positions failed: %s", exc)
            return []

    def sell_position(self, market_ticker: str) -> dict:
        """Close (sell) the full open position for *market_ticker*.

        Determines current side from open positions, then submits a sell order
        at market price (99¢ for yes, 1¢ for no = limit at best available).

        Args:
            market_ticker: Kalshi market ticker to close.

        Returns:
            Order response dict (or dry-run stub).

        Raises:
            KalshiError: If no open position is found or the sell fails.
        """
        positions = self.get_positions()
        pos = next(
            (p for p in positions if p.get("ticker") == market_ticker),
            None,
        )
        if not pos:
            raise KalshiError(f"No open position for {market_ticker!r}")

        net = pos.get("position", 0)
        if net == 0:
            raise KalshiError(f"Position for {market_ticker!r} has zero contracts")

        side = "yes" if net > 0 else "no"
        count = abs(net)

        if settings.dry_run or not settings.kalshi_live:
            label = "DRY_RUN" if settings.dry_run else "KALSHI_LIVE=false"
            logger.info("[%s] Kalshi sell: %s %s x%d", label, market_ticker, side, count)
            return {"status": "dry_run", "market_ticker": market_ticker}

        # Sell at 1¢ limit = accept any price (market order equivalent for binary)
        sell_price = 1
        payload = {
            "ticker": market_ticker,
            "side": side,
            "count": count,
            "type": "limit",
            "yes_price" if side == "yes" else "no_price": sell_price,
            "action": "sell",
        }
        data = self._post("/portfolio/orders", payload)
        return data.get("order", data)

    def get_balance(self) -> float:
        """Return available cash balance in USD.

        Returns:
            Balance in dollars (API returns cents).
        """
        data = self._get("/portfolio/balance")
        cents = data.get("balance", 0)
        return cents / 100.0

    # ── HTTP layer ────────────────────────────────────────────────────────────

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _auth_headers(self, method: str, path: str) -> dict:
        """Build the three Kalshi RSA-signing authentication headers."""
        timestamp_ms = str(int(time.time() * 1000))
        msg_to_sign = timestamp_ms + method.upper() + path

        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            pem_data = self._private_key_pem
            if not pem_data.startswith("-----"):
                # Treat as file path
                with open(pem_data) as f:
                    pem_data = f.read()

            private_key = serialization.load_pem_private_key(
                pem_data.encode(), password=None
            )
            signature = private_key.sign(
                msg_to_sign.encode(), padding.PKCS1v15(), hashes.SHA256()
            )
            sig_b64 = base64.b64encode(signature).decode()
        except Exception as exc:
            raise KalshiError(f"Failed to sign request: {exc}") from exc

        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self._key_id or not self._private_key_pem:
            raise KalshiError("Kalshi credentials not configured (KALSHI_API_KEY / KALSHI_SECRET)")

        import requests

        url = self._base + path
        headers = self._auth_headers("GET", path)
        try:
            resp = self._get_session().get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            raise KalshiError(f"GET {path} → {exc.response.status_code}: {exc.response.text[:200]}") from exc
        except Exception as exc:
            raise KalshiError(f"GET {path} failed: {exc}") from exc

    def _post(self, path: str, payload: dict) -> dict:
        if not self._key_id or not self._private_key_pem:
            raise KalshiError("Kalshi credentials not configured (KALSHI_API_KEY / KALSHI_SECRET)")

        import json
        import requests

        url = self._base + path
        headers = self._auth_headers("POST", path)
        try:
            resp = self._get_session().post(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            raise KalshiError(f"POST {path} → {exc.response.status_code}: {exc.response.text[:200]}") from exc
        except Exception as exc:
            raise KalshiError(f"POST {path} failed: {exc}") from exc
