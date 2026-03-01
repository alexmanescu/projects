"""LLM prompting configuration for the Propaganda Arbitrage strategy.

Two complementary structures:

``LLM_CONFIG``  – routing/parameter config consumed by ``LLMSynthesizer``.

Legacy constants (``SYSTEM_PROMPT``, ``ANALYSIS_SCHEMA``, ``OLLAMA_OPTIONS``,
``CLAUDE_OPTIONS``, ``ANALYSIS_PROMPT_TEMPLATE``) are kept for backward
compatibility with any code that imports them directly.
"""

# ── Routing config (consumed by LLMSynthesizer) ───────────────────────────────

LLM_CONFIG: dict = {
    "thesis_generation": {
        "provider": "ollama",       # free; adequate for prose generation
        "fallback": "claude",
        "temperature": 0.7,
        "max_tokens": 500,
    },
    "exit_analysis": {
        "provider": "claude",       # critical decision; accuracy worth the cost
        "fallback": "ollama",
        "temperature": 0.3,
        "max_tokens": 400,
    },
    "signal_scoring": {
        "provider": "ollama",       # cheap scoring; no fallback needed
        "fallback": None,
        "temperature": 0.1,
        "max_tokens": 32,
    },
    "article_analysis": {
        "provider": "ollama",
        "fallback": "claude",
        "temperature": 0.1,
        "max_tokens": 512,
    },
}

# ── Legacy constants (kept for backward compatibility) ────────────────────────

SYSTEM_PROMPT = """You are a geopolitical financial analyst specialising in propaganda arbitrage.
Your task is to read news articles and government communications, then assess:
1. Whether the article is relevant to financial markets
2. Sentiment direction (bullish / bearish / neutral) for specific asset classes
3. Which sectors or tickers are most affected
4. Signal strength (0.0–1.0) based on novelty, credibility, and market impact

Respond ONLY with valid JSON matching the schema provided. Do not include any prose."""

ANALYSIS_SCHEMA = {
    "type": "object",
    "required": [
        "relevant", "relevance_score", "sentiment", "sentiment_score",
        "signal_strength", "tickers", "entities", "topics", "thesis_notes"
    ],
    "properties": {
        "relevant": {"type": "boolean"},
        "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
        "sentiment": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "sentiment_score": {
            "type": "number",
            "minimum": -1,
            "maximum": 1,
            "description": "-1 fully bearish, 0 neutral, +1 fully bullish",
        },
        "signal_strength": {"type": "number", "minimum": 0, "maximum": 1},
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ticker symbols most affected by this article",
        },
        "entities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Named entities: countries, companies, people",
        },
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Thematic topics: sanctions, tariffs, defence, energy, etc.",
        },
        "thesis_notes": {
            "type": "string",
            "description": "One-sentence rationale for the trade thesis",
        },
    },
}

OLLAMA_OPTIONS: dict = {
    "temperature": 0.1,
    "top_p": 0.9,
    "num_predict": 512,
}

CLAUDE_OPTIONS: dict = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 512,
    "temperature": 0.1,
}

ANALYSIS_PROMPT_TEMPLATE = """\
Analyse the following news article for propaganda arbitrage trading signals.

Article title: {title}
Article URL:   {url}
Published at:  {published_at}

Article body:
{body}

Return a JSON object matching this schema:
{schema}
"""
