"""Kalshi market discovery and relevance scoring for PAE signals.

Given a detected signal (entity + direction), searches the Kalshi API for
open markets that could be a good bet, then uses the LLM to score relevance
and recommend YES or NO.

Typical usage in the pipeline::

    finder = KalshiMarketFinder(kalshi, llm)
    candidates = finder.find_for_signal(
        entity="China",
        signal_type="sanctions_announcement",
        direction="bullish",         # bullish on US defence names
        context="OFAC designates new Chinese tech entities under Section 301",
    )
    # → [{"market_ticker": "...", "side": "yes", "yes_price": 42, ...}, ...]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.trading.kalshi_interface import KalshiInterface
    from app.services.analysis.llm_synthesizer import LLMSynthesizer

logger = logging.getLogger(__name__)

# How many search terms to try per entity (keeps API calls bounded)
_MAX_SEARCH_TERMS = 3
# How many candidate markets to return per signal
_MAX_CANDIDATES = 3
# Minimum volume to consider a market liquid enough
_MIN_VOLUME = 5
# Minimum days to expiry to avoid near-expiry contracts
_MIN_DAYS_TO_EXPIRY = 3


class KalshiMarketFinder:
    """Find and rank Kalshi markets relevant to a PAE signal.

    Args:
        kalshi: Initialised :class:`~app.services.trading.kalshi_interface.KalshiInterface`.
        llm: Initialised :class:`~app.services.analysis.llm_synthesizer.LLMSynthesizer`
            used for relevance scoring and YES/NO recommendation.
    """

    def __init__(self, kalshi: "KalshiInterface", llm: "LLMSynthesizer") -> None:
        self._kalshi = kalshi
        self._llm = llm

    # ── Public API ────────────────────────────────────────────────────────────

    def find_for_signal(
        self,
        entity: str,
        signal_type: str,
        direction: str,
        context: str,
        max_candidates: int = _MAX_CANDIDATES,
    ) -> list[dict]:
        """Return ranked Kalshi market candidates for a PAE signal.

        Args:
            entity: Primary entity from the signal (e.g. ``"China"``,
                ``"NVDA"``, ``"tariff"``).
            signal_type: PAE rule name (e.g. ``"sanctions_announcement"``).
            direction: ``"bullish"`` or ``"bearish"`` for the underlying asset.
            context: Short description of what triggered the signal (for LLM).
            max_candidates: Maximum markets to return.

        Returns:
            List of candidate dicts::

                {
                    "market_ticker": str,
                    "title": str,
                    "side": "yes" | "no",
                    "yes_price": int,        # cents, 0–99
                    "suggested_contracts": int,
                    "relevance_score": float, # 0–1 from LLM
                    "llm_rationale": str,
                }

            Empty list if Kalshi credentials are not configured or no
            relevant markets are found.
        """
        from app.core.config import settings

        if not settings.kalshi_api_key:
            return []

        search_terms = _build_search_terms(entity, signal_type)
        markets_seen: dict[str, dict] = {}

        for term in search_terms[:_MAX_SEARCH_TERMS]:
            try:
                results = self._kalshi.find_markets(term, limit=10)
            except Exception as exc:
                logger.warning("KalshiMarketFinder: search %r failed: %s", term, exc)
                continue

            for m in results:
                ticker = m.get("ticker") or m.get("market_ticker", "")
                if not ticker or ticker in markets_seen:
                    continue
                # Basic liquidity filter
                volume = m.get("volume", 0) or 0
                if volume < _MIN_VOLUME:
                    continue
                markets_seen[ticker] = m

        if not markets_seen:
            logger.debug("KalshiMarketFinder: no markets found for %r / %r", entity, signal_type)
            return []

        # Ask LLM to score and pick the best ones
        candidates = self._llm_score_markets(
            list(markets_seen.values())[:10],
            entity=entity,
            signal_type=signal_type,
            direction=direction,
            context=context,
        )

        # Sort by relevance and return top N
        candidates.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return candidates[:max_candidates]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _llm_score_markets(
        self,
        markets: list[dict],
        entity: str,
        signal_type: str,
        direction: str,
        context: str,
    ) -> list[dict]:
        """Use the LLM to score market relevance and recommend YES/NO."""
        if not markets:
            return []

        market_summaries = "\n".join(
            f"- [{i+1}] {m.get('ticker','?')}: {m.get('title','?')} "
            f"(yes_price={m.get('yes_price',50)}¢, volume={m.get('volume',0)})"
            for i, m in enumerate(markets)
        )

        prompt = f"""You are a prediction market analyst for a news-driven trading system.

Signal detected: {signal_type}
Entity: {entity}
Direction: {direction} on related assets
Context: {context}

Available Kalshi markets:
{market_summaries}

For each market:
1. Score its relevance to the signal (0.0 = unrelated, 1.0 = directly related).
2. Recommend YES or NO based on whether the signal suggests the event is MORE or LESS likely.
3. Give a one-sentence rationale.

Reply in this exact format for each relevant market (relevance >= 0.4 only):
MARKET: <ticker>
RELEVANCE: <0.0-1.0>
SIDE: <YES|NO>
RATIONALE: <one sentence>
---
"""

        try:
            raw = self._llm.generate_raw(prompt)
        except Exception as exc:
            logger.warning("KalshiMarketFinder: LLM scoring failed: %s", exc)
            return _fallback_score(markets)

        return _parse_llm_scores(raw, markets)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_search_terms(entity: str, signal_type: str) -> list[str]:
    """Generate Kalshi search terms from entity + signal type."""
    terms = [entity]

    # Add signal-type-specific terms
    _SIGNAL_TERMS: dict[str, list[str]] = {
        "sanctions_announcement": ["sanctions", "export control"],
        "tariff_increase": ["tariff", "trade war"],
        "tariff_reduction": ["trade deal", "tariff"],
        "defence_spending_increase": ["defense", "military"],
        "semiconductor_policy": ["semiconductor", "chip"],
        "energy_supply_disruption": ["oil", "energy"],
        "central_bank_hawkish": ["interest rate", "Fed rate"],
        "central_bank_dovish": ["interest rate cut", "Fed"],
        "regime_change_risk": ["election", "government"],
        "pandemic_new_variant": ["pandemic", "virus", "WHO"],
        "coverage_gap": [entity],
    }
    extra = _SIGNAL_TERMS.get(signal_type, [])
    for t in extra:
        if t.lower() != entity.lower():
            terms.append(t)

    return terms


def _parse_llm_scores(raw: str, markets: list[dict]) -> list[dict]:
    """Parse structured LLM output into candidate dicts."""
    import re

    market_by_ticker = {
        (m.get("ticker") or m.get("market_ticker", "")).upper(): m
        for m in markets
    }

    results = []
    blocks = raw.split("---")
    for block in blocks:
        ticker_match = re.search(r"MARKET:\s*(\S+)", block, re.IGNORECASE)
        relevance_match = re.search(r"RELEVANCE:\s*([\d.]+)", block, re.IGNORECASE)
        side_match = re.search(r"SIDE:\s*(YES|NO)", block, re.IGNORECASE)
        rationale_match = re.search(r"RATIONALE:\s*(.+)", block, re.IGNORECASE)

        if not (ticker_match and relevance_match and side_match):
            continue

        ticker = ticker_match.group(1).upper().strip()
        try:
            relevance = float(relevance_match.group(1))
        except ValueError:
            continue

        if relevance < 0.4:
            continue

        side = side_match.group(1).lower()
        rationale = rationale_match.group(1).strip() if rationale_match else ""

        market = market_by_ticker.get(ticker)
        if not market:
            # Try partial match
            market = next(
                (m for k, m in market_by_ticker.items() if ticker in k),
                None,
            )
        if not market:
            continue

        yes_price = market.get("yes_price", 50)
        results.append({
            "market_ticker": market.get("ticker") or market.get("market_ticker", ticker),
            "title": market.get("title", ""),
            "side": side,
            "yes_price": yes_price,
            "suggested_contracts": 10,   # base, sized by position manager
            "relevance_score": relevance,
            "llm_rationale": rationale,
        })

    return results


def _fallback_score(markets: list[dict]) -> list[dict]:
    """Return top markets by volume with neutral scoring (no LLM available)."""
    sorted_m = sorted(markets, key=lambda m: m.get("volume", 0), reverse=True)
    return [
        {
            "market_ticker": m.get("ticker") or m.get("market_ticker", ""),
            "title": m.get("title", ""),
            "side": "yes",
            "yes_price": m.get("yes_price", 50),
            "suggested_contracts": 10,
            "relevance_score": 0.4,
            "llm_rationale": "Fallback: LLM unavailable, ranked by volume.",
        }
        for m in sorted_m[:3]
    ]
