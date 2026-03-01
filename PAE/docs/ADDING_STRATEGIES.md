# Adding Strategies to PAE

A strategy is a self-contained plugin directory under `strategies/`.
The infrastructure layer loads it dynamically at runtime — no changes to
core code are required.

---

## Directory Structure

```
strategies/
└── my-new-strategy/
    ├── thesis.md          # Human-readable rationale (not loaded by code)
    ├── scraper_config.py  # Feed definitions — REQUIRED
    ├── pattern_rules.py   # Detection rules — REQUIRED
    └── llm_config.py      # LLM prompts + schema — REQUIRED
```

> Hyphens in the directory name are fine; `StrategyLoader` converts them to
> underscores when constructing the Python import path.

---

## 1. `scraper_config.py`

Defines which RSS feeds to scrape and how to classify articles.

```python
# strategies/my-new-strategy/scraper_config.py

CONFIG = {
    "name": "my-new-strategy",
    "description": "Short description of what this strategy looks for.",
    "check_interval_minutes": 60,
    "max_articles_per_cycle": 50,
}

SCRAPERS = [
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "category": "western_mainstream",   # used for coverage-gap detection
        "enabled": True,
    },
    {
        "name": "Xinhua English",
        "url": "http://www.xinhuanet.com/english/rss/businessrss.xml",
        "category": "asian_state",
        "enabled": True,
    },
    # Add as many feeds as needed
]


def get_scrapers() -> list[dict]:
    """Return only enabled scrapers."""
    return [s for s in SCRAPERS if s.get("enabled", True)]
```

### Available categories for coverage-gap detection

`PatternDetector.analyze_coverage_gaps()` groups articles by category and
looks for stories that appear in one group but not the other.

| Category value | Meaning |
|----------------|---------|
| `western_mainstream` | AP, Reuters, BBC, FT, etc. |
| `asian_state` | Xinhua, CGTN, Global Times, etc. |
| `crypto` | Coindesk, Cointelegraph, etc. |
| `tech_specialist` | The Information, TechCrunch, etc. |
| `macro` | Bloomberg, FT macroeconomics feeds |

You can define any category string; just make sure at least two categories
are represented so gaps can be detected.

---

## 2. `pattern_rules.py`

Defines keyword rules and named patterns for signal detection.

```python
# strategies/my-new-strategy/pattern_rules.py

PATTERN_RULES = [
    {
        "name": "semiconductor_supply_chain",
        "keywords": ["TSMC", "chip", "semiconductor", "fab", "wafer"],
        "tickers": ["TSM", "NVDA", "INTC", "AMAT", "ASML"],
        "min_score": 0.6,       # minimum article significance to trigger
        "signal_type": "coverage_gap",
    },
    {
        "name": "policy_announcement",
        "keywords": ["sanctions", "export control", "tariff", "ban"],
        "tickers": ["TSM", "NVDA", "AMD"],
        "min_score": 0.7,
        "signal_type": "policy_announcement",
    },
]

# Named sub-patterns (optional — used inside prompts for context)
PATTERNS = {
    "supply_disruption": {
        "description": "Physical or regulatory disruption to chip supply",
        "keywords": ["shortage", "disruption", "halt", "suspend", "restrict"],
    },
    "demand_surge": {
        "description": "Unexpected demand increase from key buyers",
        "keywords": ["orders", "stockpile", "accelerate", "rush"],
    },
}
```

### Rule fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | ✅ | Unique rule identifier |
| `keywords` | list[str] | ✅ | Case-insensitive substring matches against article text |
| `tickers` | list[str] | ✅ | Stock tickers to emit signals for when rule fires |
| `min_score` | float | — | Minimum article `significance` score (default 0.5) |
| `signal_type` | str | — | Value stored in `signals.signal_type` (default `"pattern_match"`) |

---

## 3. `llm_config.py`

Configures how the LLM generates trading theses and evaluates exit signals.

```python
# strategies/my-new-strategy/llm_config.py

LLM_CONFIG = {
    # ── Thesis generation ───────────────────────────────────────────────
    "thesis_prompt_template": """\
You are a quantitative analyst specialising in supply-chain disruptions.

Coverage analysis:
{coverage_summary}

Key articles:
{article_summaries}

Detected patterns: {patterns}

Task: Generate a trading thesis for {ticker}.
Respond in JSON matching the schema below.
""",

    # ── Exit signal analysis ────────────────────────────────────────────
    "exit_signal_prompt_template": """\
You are reviewing an open long position in {ticker}.

Entry price: {entry_price}
Current price: {current_price}
Unrealised P/L: {pnl_pct}%

Recent news context:
{news_summary}

Should this position be closed? Respond in JSON matching the schema below.
""",

    # ── Expected JSON schema from the LLM ──────────────────────────────
    "response_schema": {
        "action":     "buy | sell | hold",
        "confidence": "float 0.0–1.0",
        "thesis":     "string — 2–4 sentence rationale",
        "risk":       "string — key risks",
        "catalyst":   "string — what would invalidate this thesis",
        "stop_loss_pct": "float — suggested stop-loss as decimal (e.g. 0.05 for 5%)",
    },

    # ── Model preferences (override globals in .env) ───────────────────
    # "ollama_model": "qwen3-coder:30b",   # uncomment to override
    # "claude_model": "claude-sonnet-4-6", # uncomment to override
}
```

### Template variables

The following variables are interpolated into prompt templates by
`LLMSynthesizer`:

| Variable | Description |
|----------|-------------|
| `{ticker}` | Ticker symbol (e.g. `NVDA`) |
| `{coverage_summary}` | Text summary of western-vs-asian coverage counts |
| `{article_summaries}` | Concatenated titles + snippets of top articles |
| `{patterns}` | Comma-separated list of pattern names that fired |
| `{entry_price}` | Position entry price (exit prompt only) |
| `{current_price}` | Current broker price (exit prompt only) |
| `{pnl_pct}` | Unrealised P/L as a percentage (exit prompt only) |
| `{news_summary}` | Recent news since position was opened (exit prompt only) |

---

## 4. `thesis.md`

Plain-text rationale for the strategy.  Not parsed by code — for human
review only.  Include:

- The core hypothesis
- Which information asymmetry is being exploited
- Expected holding period
- Known limitations and risks

---

## 5. Register in the database

Run once after creating the directory:

```python
from app.core.database import db_session
from app.core.strategy_loader import StrategyLoader
from app.models import Strategy

with db_session() as db:
    StrategyLoader().register_strategy(db, "my-new-strategy")
    s = db.query(Strategy).filter_by(name="my-new-strategy").first()
    s.is_active = True
    db.commit()
    print(f"Registered strategy id={s.id}")
```

---

## 6. Test in dry-run mode

```bash
# Single manual run (no scheduler)
DRY_RUN=true python -m app.workers.tasks my-new-strategy

# Or via the full scheduler (all strategies):
DRY_RUN=true python scripts/run_workers.py
```

Check `logs/workers.log` for:

```
INFO  scrape_news — strategy=my-new-strategy articles=12 signals=3
INFO  LLMSynthesizer — thesis generated for NVDA confidence=0.72
INFO  TelegramNotifier — opportunity alert sent id=7
```

---

## 7. Write tests

Add a test file at `tests/test_my_new_strategy.py`:

```python
import pytest
from strategies.my_new_strategy.scraper_config import CONFIG, get_scrapers
from strategies.my_new_strategy.pattern_rules import PATTERN_RULES, PATTERNS
from strategies.my_new_strategy.llm_config import LLM_CONFIG


def test_config_has_required_keys():
    assert "name" in CONFIG
    assert "check_interval_minutes" in CONFIG


def test_get_scrapers_returns_enabled_only():
    scrapers = get_scrapers()
    assert all(s.get("enabled", True) for s in scrapers)
    assert len(scrapers) > 0


def test_pattern_rules_have_tickers():
    for rule in PATTERN_RULES:
        assert rule["tickers"], f"Rule '{rule['name']}' has no tickers"


def test_llm_config_has_prompts():
    assert "{ticker}" in LLM_CONFIG["thesis_prompt_template"]
    assert "response_schema" in LLM_CONFIG
```

Run:

```bash
pytest tests/test_my_new_strategy.py -v
```

---

## Checklist

- [ ] `strategies/my-new-strategy/scraper_config.py` with `CONFIG` + `get_scrapers()`
- [ ] `strategies/my-new-strategy/pattern_rules.py` with `PATTERN_RULES` + `PATTERNS`
- [ ] `strategies/my-new-strategy/llm_config.py` with `LLM_CONFIG`
- [ ] `strategies/my-new-strategy/thesis.md`
- [ ] Registered in DB and `is_active = True`
- [ ] Verified with `DRY_RUN=true` run
- [ ] Tests added to `tests/`
