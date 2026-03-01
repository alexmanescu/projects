# PAE Architecture

## Overview

PAE is split into two conceptual layers:

```
┌─────────────────────────────────────────────────────────────┐
│  Infrastructure Layer  (app/)                               │
│  • ORM models, database session, config                     │
│  • Scraping, deduplication, article processing              │
│  • LLM synthesizer, pattern detection                       │
│  • Broker interface, position manager                       │
│  • Telegram notifier, approval handler                      │
│  • Scheduled workers, health checks                         │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │  loads plugin via importlib
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Strategy Layer  (strategies/<name>/)                       │
│  • scraper_config.py  — which feeds to scrape               │
│  • pattern_rules.py   — what signals to detect              │
│  • llm_config.py      — prompts + response schema           │
│  • thesis.md          — human-readable rationale            │
└─────────────────────────────────────────────────────────────┘
```

The infrastructure layer is strategy-agnostic.  A strategy is nothing more
than a directory of plain Python dicts/lists that the infrastructure reads
at runtime via `StrategyLoader`.

---

## Database Schema

All tables live in a single MySQL database (`pae`).

```
strategies
  id            INT PK
  name          VARCHAR(100) UNIQUE
  is_active     BOOL
  config_path   VARCHAR(500)
  created_at    DATETIME

article_registry
  id            INT PK
  url_canonical VARCHAR(2048) UNIQUE
  url_hash      CHAR(32) UNIQUE           ← MD5 of normalised URL
  title         VARCHAR(500)
  source_name   VARCHAR(200)
  published_at  DATETIME
  content_hash  CHAR(32)                  ← MD5 of full body text
  scraped_at    DATETIME

article_url_aliases
  id            INT PK
  article_id    INT FK → article_registry
  url_raw       VARCHAR(2048)
  url_hash      CHAR(32) UNIQUE

article_analyses
  id            INT PK
  article_id    INT FK → article_registry
  strategy_id   INT FK → strategies
  relevance     FLOAT
  sentiment     FLOAT                     ← -1.0 … +1.0
  significance  FLOAT
  entities_detected  TEXT (JSON)
  analyzed_at   DATETIME

signals
  id            INT PK
  strategy_id   INT FK → strategies
  ticker        VARCHAR(20)
  signal_type   VARCHAR(50)               ← e.g. "coverage_gap"
  confidence    FLOAT
  raw_data      TEXT (JSON)
  created_at    DATETIME

opportunities
  id            INT PK
  strategy_id   INT FK → strategies
  ticker        VARCHAR(20)
  action        VARCHAR(10)               ← "buy" | "sell"
  thesis        TEXT
  confidence    FLOAT
  max_loss_pct  FLOAT
  stop_loss_pct FLOAT
  status        VARCHAR(20)               ← "pending" | "approved" | "rejected" | "executed"
  created_at    DATETIME

trades
  id            INT PK
  opportunity_id INT FK → opportunities (nullable)
  strategy_id   INT FK → strategies (nullable)
  ticker        VARCHAR(20)
  action        VARCHAR(10)               ← "buy" | "sell"
  quantity      FLOAT
  entry_price   FLOAT (nullable)          ← set on buy
  exit_price    FLOAT (nullable)          ← set on sell
  stop_loss     FLOAT (nullable)
  approved      BOOL
  executed_at   DATETIME
  closed_at     DATETIME (nullable)
  notes         TEXT

positions
  id            INT PK
  trade_id      INT FK → trades (nullable)
  ticker        VARCHAR(20) UNIQUE
  quantity      FLOAT
  avg_entry_price FLOAT
  current_price FLOAT
  stop_loss     FLOAT (nullable)
  opened_at     DATETIME
  updated_at    DATETIME
```

### Relationships

```
Strategy ──< ArticleAnalysis >── Article
Strategy ──< Signal
Strategy ──< Opportunity ──< Trade ──< Position
```

---

## Deduplication Flow

Three-tier deduplication prevents the same article being processed twice
even if it appears under different URLs (tracking params, CDN mirrors, etc.).

```
Incoming URL
     │
     ▼
1.  url_normalizer.normalize()
     • Strip scheme (https → /)
     • Remove known tracking params (utm_*, ref, fbclid…)
     • Sort remaining query params
     • Produce canonical string
     │
     ▼
2.  Check article_url_aliases.url_hash = MD5(raw_url)
     if found → already seen, skip
     │
     ▼
3.  Check article_registry.url_hash = MD5(canonical)
     if found → register alias, skip
     │
     ▼
4.  Fetch content, compute content_hash = MD5(body_text)
     Check article_registry.content_hash
     if found → near-duplicate by content, skip
     │
     ▼
5.  Fuzzy title match: SequenceMatcher ratio > 0.85
     over recent articles (last 24 h window)
     if match → skip
     │
     ▼
   New article — insert into article_registry + alias
```

`should_scrape(db, url)` in `app/utils/dedup.py` encapsulates tiers 1–3.
Tiers 4–5 run inside `ArticleProcessor.process()`.

---

## Strategy Plugin System

`StrategyLoader` (in `app/core/strategy_loader.py`) discovers and loads
strategy plugins at runtime:

```python
loader = StrategyLoader()
cfg = loader.load_strategy(db, "propaganda-arbitrage")
# cfg is a dict:
# {
#   "strategy": <Strategy ORM instance>,
#   "scrapers": <list from get_scrapers()>,
#   "pattern_rules": <PATTERN_RULES list>,
#   "patterns": <PATTERNS dict>,
#   "llm_config": <LLM_CONFIG dict>,
# }
```

The loader uses `importlib.import_module` with the path
`strategies.<slug>.<module>` (e.g., `strategies.propaganda-arbitrage.scraper_config`).
Hyphens in the slug are replaced with underscores for the Python import.

To add a new strategy, see [ADDING_STRATEGIES.md](ADDING_STRATEGIES.md).

---

## LLM Routing Logic

`LLMSynthesizer` (in `app/services/analysis/llm_synthesizer.py`) routes each
call to one of two backends depending on availability and task:

```
generate_thesis()          ──▶  Ollama (primary)
                                 │ on failure or unavailable
                                 └──▶  Claude API (fallback)

analyze_exit_signal()      ──▶  Claude API (primary — exit signals
                                              benefit from stronger reasoning)
                                 │ on failure
                                 └──▶  Ollama (fallback)

score_signal_strength()    ──▶  Ollama (primary)
                                 │ on failure
                                 └──▶  default score 0.5 (graceful degrade)
```

Ollama is called via its HTTP REST API (`/api/generate`) against the local
instance at `OLLAMA_BASE_URL`.  Claude is called via the `anthropic` SDK
using `ANTHROPIC_API_KEY`.

The `llm_config.py` in each strategy defines:
- `LLM_CONFIG["thesis_prompt_template"]` — Jinja-style template
- `LLM_CONFIG["exit_signal_prompt_template"]`
- `LLM_CONFIG["response_schema"]` — expected JSON keys for structured output

---

## Trading Workflow

```
Opportunity (status="pending")
     │
     │  Telegram: YES <id>
     ▼
ApprovalHandler.handle_approval(id)
     │
     ├─ Load Opportunity from DB
     ├─ _score_to_conviction(confidence)   → "low"|"medium"|"high"
     ├─ PositionManager.validate_trade()   → pre-flight checks
     │     • can_add_position()  (max 10, max 90%)
     │     • calculate_shares()  (conviction % × portfolio)
     │     • calculate_stop_loss()  (1–25% range)
     │
     ├─ AlpacaBroker.execute_buy()
     │     • DRY_RUN → return fake OrderResult immediately
     │     • Live: submit MarketOrderRequest
     │             _poll_fill() (10 × 1 s)
     │             attach StopOrderRequest
     │
     ├─ Trade.log_execution()  → write Trade row (entry_price set)
     ├─ Update Position row (create or upsert)
     └─ Opportunity.status = "approved"
          TelegramNotifier.send_execution_confirmation()
```

**Stop-loss attachment** happens immediately after fill poll as a separate
`StopOrderRequest` (type=`stop`, side=`sell`) at price = `entry × (1 − pct)`.

**Exit monitoring** runs every 15 minutes via `monitor_positions()`:
- Compares current broker price against stop-loss threshold
- If within 4.5% of stop, calls `LLMSynthesizer.analyze_exit_signal()`
- Result triggers a Telegram `send_position_alert()` of type "exit_signal"

---

## Concurrency Model

All scheduled jobs run on the APScheduler thread pool.  Telegram I/O is
async; the bridge is `_async_notify(coro)` in `app/workers/tasks.py`:

```python
def _async_notify(coro):
    try:
        asyncio.run(coro)
    except RuntimeError:
        # Already inside an event loop (e.g. pytest-asyncio)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, coro).result()
```

The Telegram bot (`run_telegram_bot.py`) runs in a **separate process**
with its own event loop managed by `python-telegram-bot`'s
`Application.run_polling()`.
