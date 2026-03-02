"""Hybrid LLM router: Ollama (local) for cheap tasks, Claude for critical decisions.

Routing policy
--------------
- ``generate_thesis``      → Ollama primary, Claude fallback
- ``analyze_exit_signal``  → Claude primary, Ollama fallback
- ``score_signal_strength``→ Ollama primary, hard default (0.5) on total failure

Availability is checked once at construction time and cached.  Individual
call failures trigger per-call retry with exponential backoff before
attempting the fallback backend.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Timeouts ──────────────────────────────────────────────────────────────────

_OLLAMA_PING_TIMEOUT: int = 2    # availability check
_OLLAMA_CALL_TIMEOUT: int = 30   # generation call
_CLAUDE_CALL_TIMEOUT: int = 60   # generation call

# ── Retry policy ──────────────────────────────────────────────────────────────

_MAX_RETRIES: int = 2
_RETRY_BASE_DELAY: float = 2.0   # seconds; doubles each attempt

# ── Exceptions ────────────────────────────────────────────────────────────────


class LLMUnavailableError(Exception):
    """Raised when all available LLM backends fail for a given call."""


# ── Value object ──────────────────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """Structured result from any LLM backend."""

    text: str
    backend: str        # "ollama" | "claude"
    model: str
    latency_ms: int
    tokens_in: int | None = None
    tokens_out: int | None = None

    @property
    def tokens_used(self) -> int | None:
        if self.tokens_in is not None and self.tokens_out is not None:
            return self.tokens_in + self.tokens_out
        return None


# ── Prompt templates ──────────────────────────────────────────────────────────

_THESIS_PROMPT = """\
You are an investment analyst specializing in geopolitical market inefficiencies.

COVERAGE DATA:
Topic: {topic}
Western mainstream coverage: {western_count} articles
Asian/alternative coverage: {asia_count} articles
Gap ratio: {gap_ratio}x

SAMPLE HEADLINES:
{article_titles}

Generate a 2-3 sentence investment thesis explaining:
1. Why this coverage gap indicates potential mispricing
2. Which specific stocks/sectors could benefit
3. The likely catalyst or timeline

Be concise and actionable. Focus on the opportunity, not the politics.

THESIS:"""

_EXIT_PROMPT = """\
You are a risk analyst reviewing an existing position for exit signals.

POSITION:
Ticker: {ticker}
Entry: ${entry_price}
Current: ${current_price}
Thesis: {original_thesis}
P/L: {return_pct}%

RECENT NEWS (48h):
{news_headlines}

Analyze:
1. Has the original thesis been validated or invalidated?
2. Are there signs of narrative reversal?
3. Recommendation: HOLD / REDUCE / EXIT

Be direct. Prioritize capital preservation.

ANALYSIS:"""

_SCORE_PROMPT = """\
You are a quantitative analyst. Given the following trading signal data, \
return ONLY a single decimal number between 0.0 and 1.0 representing \
overall signal confidence. No explanation, no text — just the number.

Entities: {entities}
Sentiment data: {sentiment}

Confidence score (0.0–1.0):"""

_DEFAULT_SYSTEM = (
    "You are a concise, professional financial analyst. "
    "Provide direct, actionable analysis. Do not add disclaimers."
)

# ── Thinking-tag pattern (qwen3 and other reasoning models) ──────────────────

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FLOAT_RE = re.compile(r"\b(1\.0+|0\.\d+)\b")


# ── Main synthesizer ──────────────────────────────────────────────────────────


class LLMSynthesizer:
    """Hybrid LLM router with Ollama ↔ Claude failover.

    Args:
        ollama_url:    Override for ``settings.ollama_base_url``.
        ollama_model:  Override for ``settings.ollama_model``.
        claude_key:    Override for ``settings.anthropic_api_key``.
        claude_model:  Override for ``settings.claude_model``.
    """

    def __init__(
        self,
        ollama_url: str | None = None,
        ollama_model: str | None = None,
        claude_key: str | None = None,
        claude_model: str | None = None,
    ) -> None:
        self._ollama_url = (ollama_url or settings.ollama_base_url).rstrip("/")
        self._ollama_fallback_url = (
            settings.ollama_fallback_url.rstrip("/")
            if settings.ollama_fallback_url
            else None
        )
        self._ollama_model = ollama_model or settings.ollama_model
        self._claude_key = claude_key or settings.anthropic_api_key
        self._claude_model = claude_model or settings.claude_model

        self._http = requests.Session()
        self._http.headers.update({"Content-Type": "application/json"})

        self._ollama_available: bool = False
        self._ollama_fallback_available: bool = False
        self._claude_available: bool = False
        self._check_availability()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_thesis(self, pattern_data: dict, strategy_id: int) -> str:
        """Generate a 2-3 sentence investment thesis from coverage gap data.

        Routes to **Ollama** (free, adequate for prose generation).
        Falls back to Claude if Ollama is unavailable or errors.

        Args:
            pattern_data: Dict with keys ``topic``, ``western_count``,
                ``asia_count``, ``gap_ratio``, ``article_titles`` (list[str]).
            strategy_id: Unused at call-time; reserved for future per-strategy
                model selection.

        Returns:
            Generated thesis text (stripped of thinking tags).

        Raises:
            LLMUnavailableError: When both backends fail after retries.
        """
        prompt = self._build_thesis_prompt(pattern_data)
        return self._route(
            prompt=prompt,
            primary="ollama",
            fallback="claude",
            temperature=0.7,
            max_tokens=500,
            context=f"generate_thesis(strategy_id={strategy_id})",
        ).text

    def analyze_exit_signal(self, position: dict, recent_news: list[dict]) -> str:
        """Analyse whether an open position should be held, reduced, or exited.

        Routes to **Claude** (critical decision; accuracy worth the API cost).
        Falls back to Ollama if Claude is unavailable.

        Args:
            position: Dict with ``ticker``, ``entry_price``, ``current_price``,
                ``thesis``, ``return_pct``.
            recent_news: List of article dicts, each with at least a ``title``
                key. Only the titles are included in the prompt.

        Returns:
            Analysis text including HOLD / REDUCE / EXIT recommendation.

        Raises:
            LLMUnavailableError: When both backends fail after retries.
        """
        prompt = self._build_exit_prompt(position, recent_news)
        return self._route(
            prompt=prompt,
            primary="claude",
            fallback="ollama",
            temperature=0.3,
            max_tokens=400,
            context=f"analyze_exit_signal(ticker={position.get('ticker')})",
        ).text

    def score_signal_strength(
        self, entities: list[str], sentiment: dict
    ) -> float:
        """Return a 0–1 confidence float for a trading signal.

        Routes to **Ollama** (simple scoring task, doesn't need Claude).
        Returns the hard default ``0.5`` on total failure rather than raising,
        since a missed score is less harmful than a crashed pipeline.

        Args:
            entities: Named entities detected in the article.
            sentiment: Dict with ``sentiment`` (bullish/bearish/neutral),
                ``relevance_score``, ``signal_strength``.

        Returns:
            Confidence score in ``[0.0, 1.0]``.
        """
        prompt = self._build_score_prompt(entities, sentiment)
        try:
            resp = self._route(
                prompt=prompt,
                primary="ollama",
                fallback=None,      # no Claude fallback for scoring
                temperature=0.1,
                max_tokens=32,
                context="score_signal_strength",
            )
            return self._parse_float(resp.text, default=0.5)
        except LLMUnavailableError:
            logger.warning("score_signal_strength: all backends failed — returning default 0.5")
            return 0.5

    def is_available(self) -> bool:
        """Return True if at least one backend is reachable."""
        return self._ollama_available or self._claude_available

    # ── Availability ──────────────────────────────────────────────────────────

    def _check_availability(self) -> None:
        """Probe backends and cache results.  Never raises."""
        # ── Ollama primary ────────────────────────────────────────────────────
        try:
            resp = self._http.get(
                f"{self._ollama_url}/api/version",
                timeout=_OLLAMA_PING_TIMEOUT,
            )
            self._ollama_available = resp.status_code == 200
        except Exception as exc:
            self._ollama_available = False
            logger.debug("Ollama primary not reachable at %s: %s", self._ollama_url, exc)

        # ── Ollama fallback (e.g. Windows GPU) ────────────────────────────────
        if self._ollama_fallback_url:
            try:
                resp = self._http.get(
                    f"{self._ollama_fallback_url}/api/version",
                    timeout=_OLLAMA_PING_TIMEOUT,
                )
                self._ollama_fallback_available = resp.status_code == 200
            except Exception as exc:
                self._ollama_fallback_available = False
                logger.debug("Ollama fallback not reachable at %s: %s", self._ollama_fallback_url, exc)

        # ── Claude ────────────────────────────────────────────────────────────
        self._claude_available = bool(self._claude_key)

        logger.info(
            "LLM backends — ollama_primary: %s (%s)  ollama_fallback: %s (%s)  claude: %s  model: %s",
            "✓" if self._ollama_available else "✗",
            self._ollama_url,
            "✓" if self._ollama_fallback_available else "✗" if self._ollama_fallback_url else "n/a",
            self._ollama_fallback_url or "not configured",
            "✓" if self._claude_available else "✗ (no API key)",
            self._ollama_model,
        )

    # ── Routing ───────────────────────────────────────────────────────────────

    def _route(
        self,
        prompt: str,
        primary: str,
        fallback: str | None,
        temperature: float,
        max_tokens: int,
        context: str = "",
    ) -> LLMResponse:
        """Call primary backend with retries; try fallback on failure.

        For the ``"ollama"`` backend the routing order is:
        1. Primary Ollama URL  (``OLLAMA_BASE_URL``)
        2. Fallback Ollama URL (``OLLAMA_FALLBACK_URL``, e.g. Windows GPU)
        3. Claude (if configured as the fallback backend)

        Args:
            primary:  ``"ollama"`` or ``"claude"``.
            fallback: ``"ollama"``, ``"claude"``, or ``None`` (no fallback).
        """
        backends = [(primary, True)]
        if fallback:
            backends.append((fallback, False))

        last_exc: Exception | None = None

        for backend_name, is_primary in backends:
            if backend_name == "ollama":
                # Build ordered list of Ollama URLs to try
                ollama_urls: list[tuple[str, bool]] = []
                if self._ollama_available:
                    ollama_urls.append((self._ollama_url, True))
                if self._ollama_fallback_available and self._ollama_fallback_url:
                    ollama_urls.append((self._ollama_fallback_url, False))

                if not ollama_urls:
                    logger.debug("%s: no Ollama endpoints available", context)
                    continue

                for url, is_primary_url in ollama_urls:
                    try:
                        resp = self._call_with_retry(
                            self._call_ollama,
                            prompt=prompt,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            url=url,
                        )
                        if not is_primary_url:
                            logger.info("%s: primary Ollama failed, used fallback %s", context, url)
                        elif not is_primary:
                            logger.info("%s: Claude failed, used Ollama fallback %s", context, url)
                        return resp
                    except Exception as exc:
                        last_exc = exc
                        logger.warning("%s: Ollama at %s failed after retries: %s", context, url, exc)

            else:  # claude
                if not self._claude_available:
                    logger.debug("%s: skipping unavailable backend claude", context)
                    continue
                try:
                    resp = self._call_with_retry(
                        self._call_claude,
                        prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    if not is_primary:
                        logger.info("%s: primary failed, used fallback claude", context)
                    return resp
                except Exception as exc:
                    last_exc = exc
                    logger.warning("%s: claude failed after retries: %s", context, exc)

        raise LLMUnavailableError(
            f"{context}: no backend succeeded. Last error: {last_exc}"
        ) from last_exc

    # ── Retry wrapper ─────────────────────────────────────────────────────────

    def _call_with_retry(
        self,
        fn: Callable,
        max_retries: int = _MAX_RETRIES,
        base_delay: float = _RETRY_BASE_DELAY,
        **kwargs,
    ) -> LLMResponse:
        """Call ``fn(**kwargs)`` up to ``max_retries`` times with exponential backoff.

        Raises the last exception if all attempts fail.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM attempt %d/%d failed (%s) — retrying in %.1fs",
                        attempt, max_retries, exc, delay,
                    )
                    time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    # ── Backend: Ollama ───────────────────────────────────────────────────────

    def _call_ollama(
        self,
        prompt: str,
        system: str = _DEFAULT_SYSTEM,
        temperature: float = 0.7,
        max_tokens: int = 500,
        url: str | None = None,
    ) -> LLMResponse:
        """POST to Ollama /api/chat; return stripped response text."""
        base = (url or self._ollama_url).rstrip("/")
        url = f"{base}/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._ollama_model,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        t0 = time.monotonic()
        resp = self._http.post(url, json=payload, timeout=_OLLAMA_CALL_TIMEOUT)
        resp.raise_for_status()
        latency_ms = int((time.monotonic() - t0) * 1000)

        data = resp.json()
        raw_text = data.get("message", {}).get("content", "").strip()
        text = self._strip_thinking_tags(raw_text)
        tokens = data.get("eval_count")  # output tokens

        logger.info(
            "Ollama ← model=%s latency=%dms tokens=%s",
            self._ollama_model, latency_ms, tokens,
        )
        return LLMResponse(
            text=text,
            backend="ollama",
            model=self._ollama_model,
            latency_ms=latency_ms,
            tokens_out=tokens,
        )

    # ── Backend: Claude ───────────────────────────────────────────────────────

    def _call_claude(
        self,
        prompt: str,
        system: str = _DEFAULT_SYSTEM,
        temperature: float = 0.3,
        max_tokens: int = 400,
    ) -> LLMResponse:
        """Call Anthropic Messages API; return response text with usage logged."""
        import anthropic  # deferred: only required when Claude path is taken

        client = anthropic.Anthropic(
            api_key=self._claude_key,
            timeout=_CLAUDE_CALL_TIMEOUT,
        )

        t0 = time.monotonic()
        message = client.messages.create(
            model=self._claude_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        text = message.content[0].text.strip()
        tokens_in = message.usage.input_tokens
        tokens_out = message.usage.output_tokens

        logger.info(
            "Claude ← model=%s latency=%dms tokens_in=%d tokens_out=%d",
            self._claude_model, latency_ms, tokens_in, tokens_out,
        )
        return LLMResponse(
            text=text,
            backend="claude",
            model=self._claude_model,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    # ── Prompt builders ───────────────────────────────────────────────────────

    @staticmethod
    def _build_thesis_prompt(pattern_data: dict) -> str:
        titles = pattern_data.get("article_titles", [])
        formatted_titles = "\n".join(f"  • {t}" for t in titles[:10]) or "  (none)"
        western = pattern_data.get("western_count", 0)
        asia = pattern_data.get("asia_count", 0)
        gap = pattern_data.get("gap_ratio", round(western / asia, 1) if asia else 0)
        return _THESIS_PROMPT.format(
            topic=pattern_data.get("topic", "Unknown"),
            western_count=western,
            asia_count=asia,
            gap_ratio=gap,
            article_titles=formatted_titles,
        )

    @staticmethod
    def _build_exit_prompt(position: dict, recent_news: list[dict]) -> str:
        headlines = "\n".join(
            f"  • {a.get('title', '(no title)')}"
            for a in recent_news[:10]
        ) or "  (no recent news)"
        return _EXIT_PROMPT.format(
            ticker=position.get("ticker", "N/A"),
            entry_price=position.get("entry_price", "N/A"),
            current_price=position.get("current_price", "N/A"),
            original_thesis=position.get("thesis", "N/A"),
            return_pct=position.get("return_pct", "N/A"),
            news_headlines=headlines,
        )

    @staticmethod
    def _build_score_prompt(entities: list[str], sentiment: dict) -> str:
        return _SCORE_PROMPT.format(
            entities=", ".join(entities) if entities else "(none)",
            sentiment=sentiment,
        )

    # ── Response parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _strip_thinking_tags(text: str) -> str:
        """Remove ``<think>…</think>`` blocks emitted by reasoning models."""
        return _THINK_TAG_RE.sub("", text).strip()

    @staticmethod
    def _parse_float(text: str, default: float = 0.5) -> float:
        """Extract the first 0.0–1.0 float from a model response string."""
        # Try exact "1.0" first, then "0.XX"
        match = _FLOAT_RE.search(text.strip())
        if match:
            val = float(match.group(1))
            return max(0.0, min(1.0, val))
        # Fallback: any decimal number in the text
        any_num = re.search(r"\b(\d+\.?\d*)\b", text)
        if any_num:
            val = float(any_num.group(1))
            if 0.0 <= val <= 1.0:
                return val
        logger.debug("_parse_float: could not parse %r — using default %.2f", text, default)
        return default
