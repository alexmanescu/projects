# PAE — Propaganda Arbitrage Engine

Automated multi-strategy trading system that detects **information asymmetries** between
Western and Asian news coverage, routes signals through an LLM thesis layer, and executes
positions via Alpaca with human-in-the-loop Telegram approval.

---

## How it works

```
RSS Feeds (14 sources across 5 categories)
         │
         ▼
  ┌─────────────────────────────────┐
  │  3-Tier Deduplication           │
  │  1. URL normalisation           │
  │  2. Content fingerprint (MD5)   │
  │  3. Fuzzy title match (0.85)    │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐
  │  Article Processor              │
  │  • Rule-based entity scoring    │
  │  • Relevance / sentiment / sig  │
  │  • Raw content → SQLite store   │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐
  │  Pattern Detector               │
  │  • Coverage gap (Asia vs West)  │
  │  • Policy announcements         │
  │  • Entity extraction            │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐     ┌──────────────┐
  │  LLM Synthesizer                │────▶│  Ollama      │
  │  • generate_thesis()  Ollama→   │     │  (local)     │
  │  • analyze_exit_signal() →Cl.   │     └──────────────┘
  │  • score_signal_strength Ollama │     ┌──────────────┐
  └──────────────┬──────────────────┘────▶│  Claude API  │
                 │                        └──────────────┘
                 ▼
  ┌─────────────────────────────────┐
  │  Signal + Opportunity           │
  │  • Signal row (ticker+conf.)    │
  │  • Opportunity row (thesis+amt) │
  │  • detect_confluence() (48h)    │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐
  │  Telegram Alert                 │
  │  👤 YES 42 / NO 42 / INFO 42    │
  └──────────────┬──────────────────┘
                 │  approved
                 ▼
  ┌─────────────────────────────────┐
  │  Position Manager               │
  │  • Conviction sizing (5/10/15%) │
  │  • Max 10 positions / 90% exp.  │
  │  • Stop-loss calculation        │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐
  │  AlpacaBroker (paper / live)    │
  │  • Market order + fill poll     │
  │  • Stop-loss attachment         │
  │  • DRY_RUN mode (no API calls)  │
  └──────────────┬──────────────────┘
                 │
                 ▼
         Trade + Position
         (MySQL, shared DB)
```

**Deployment split:** Scraping and the Telegram bot run on a Mac Mini; GPU-heavy
detection runs on a Windows machine.  MySQL and a future web dashboard live on
shared web hosting.

---

## Where things run

PAE uses a **three-machine deployment**.

| What | Where |
|------|-------|
| Scrape worker + Telegram bot | Mac Mini |
| Ollama (local LLM, GPU inference) | Windows GPU host |
| Detection worker (`app.workers.tasks --mode detect`) | Windows GPU host |
| Bot listener (`app.workers.bot_listener`) | Windows GPU host |
| MySQL database | Web hosting (cPanel/phpMyAdmin) |
| Future web dashboard | Web hosting |

Both Mac Mini and Windows connect to the same remote MySQL via an SSH tunnel
(`127.0.0.1:3307 → server:3306`).  The `start-detect.ps1` script opens this
tunnel automatically.  Shared hosting cannot run long-lived processes or
Ollama, so those stay on local machines.

---

## Prerequisites

All prerequisites are installed on the **Mac Mini**:

| Component | Minimum | Notes |
|-----------|---------|-------|
| Python | 3.11 | `python3.11 --version` |
| Ollama | latest | `ollama pull qwen3-coder:30b` |
| Alpaca account | Paper | [alpaca.markets](https://alpaca.markets) |
| Telegram Bot | — | Create via [@BotFather](https://t.me/BotFather) |
| Anthropic API key | — | Optional — Ollama is primary LLM |

MySQL lives on your **web hosting** — create the database there via cPanel
or phpMyAdmin, then point `DATABASE_URL` at it from the Mac Mini.

---

## Installation (run on the Mac Mini)

```bash
# 1. Clone and enter project
cd PAE

# 2. Create virtualenv
python3.11 -m venv venv
source venv/bin/activate          # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
# Upload your .env file via FileZilla (contains real credentials — not on GitHub)
# Or for local dev: cp .env.development .env

# 5. Create database tables (connects to MySQL on web hosting)
python -c "from app.core.database import init_db; init_db(); print('Tables created')"
```

---

## Environment Variables

Copy `.env.development` to `.env` and fill in your values.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `mysql+pymysql://user:pass@localhost/pae` | ✅ | SQLAlchemy connection string |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | — | Ollama server URL |
| `OLLAMA_MODEL` | `qwen3-coder:30b` | — | Model pulled via `ollama pull` |
| `ANTHROPIC_API_KEY` | _(empty)_ | — | Claude API key (fallback LLM) |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | — | Claude model ID |
| `ALPACA_API_KEY` | _(empty)_ | ✅ | From Alpaca dashboard |
| `ALPACA_SECRET_KEY` | _(empty)_ | ✅ | From Alpaca dashboard |
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | ✅ | From @BotFather |
| `TELEGRAM_CHAT_ID` | _(empty)_ | ✅ | Your Telegram user/chat ID |
| `PAPER_TRADING` | `true` | — | Route orders to paper account |
| `DRY_RUN` | `true` | — | Skip all external side-effects |
| `KALSHI_API_KEY` | _(empty)_ | — | Kalshi member ID for RSA auth |
| `KALSHI_SECRET` | _(empty)_ | — | PEM private key (RSA-PKCS1v15) |
| `KALSHI_BASE_URL` | `https://api.elections.kalshi.com/trade-api/v2` | — | Kalshi REST base URL |
| `KALSHI_LIVE` | `false` | — | Enable Kalshi order placement (reads always work) |
| `CHECK_INTERVAL_MINUTES` | `60` | — | Scrape cycle cadence (legacy single-strategy mode) |
| `LOG_LEVEL` | `INFO` | — | Python logging level |

---

## Running the System

### Scheduler (recommended — runs all tasks)

```bash
python scripts/run_workers.py
```

Starts an APScheduler loop with 5 jobs:

| Job | Interval | What it does |
|-----|----------|-------------|
| `scrape_news` | 60 min | Scrape all active strategies, detect gaps, alert |
| `monitor_positions` | 15 min | LLM exit-signal check on open positions |
| `detect_confluence` | 30 min | Cross-strategy signal aggregation |
| `check_stops` | 5 min | Stop-loss proximity alerts |
| `update_prices` | 1 min | Refresh position prices from broker |

### Telegram bot (separate process)

```bash
python scripts/run_telegram_bot.py
```

Listens for commands in your chat:

```
YES  42           → Approve opportunity #42 and execute buy
NO   42           → Reject opportunity
INFO 42           → Show full thesis and coverage analysis
REVIEW KALSHI 42  → Fetch current Kalshi market price for opportunity
ADDCAT <text>     → Add a signal category note to the latest opportunity
SELL NVDA         → Close NVDA position
HOLD NVDA         → Acknowledge alert, keep monitoring
STATUS            → Portfolio snapshot with P/L
HELP              → Command reference
```

### Bot listener — worker pause/resume control

```bash
# Windows (runs alongside the detect worker)
python -m app.workers.bot_listener
# or via PowerShell shortcut: pae-bot
```

Telegram commands for live worker control:

```
/status                   → Show pause state of all workers and sub-lanes
/pause scrape             → Pause the Mac Mini scrape worker
/pause detect             → Pause the Windows detect worker entirely
/pause detect kalshi      → Pause Kalshi prediction market scanning only
/pause detect stock       → Pause equity coverage-gap alerting only
/resume <same args>       → Resume a paused worker or sub-lane
/help                     → Show all bot commands
```

Pause flags are written to the `worker_controls` DB table and take effect
at the start of the next detection cycle.

---

### Single-strategy manual run (legacy)

```bash
python -m app.workers.tasks propaganda-arbitrage
```

### Register a strategy in the DB

```python
from app.core.database import db_session
from app.core.strategy_loader import StrategyLoader

with db_session() as db:
    StrategyLoader().register_strategy(db, "propaganda-arbitrage")
    # Then activate:
    from app.models import Strategy
    s = db.query(Strategy).filter_by(name="propaganda-arbitrage").first()
    s.is_active = True
```

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Single module
pytest tests/test_pattern_detector.py -v

# With coverage (requires pytest-cov)
pytest tests/ --cov=app --cov-report=term-missing
```

All tests use mocked external dependencies (broker, Telegram, DB, LLMs) and
run without any live services.

---

## Detection Layers

The detection worker runs four signal-sourcing layers per cycle:

| Layer | Source | Trigger |
|-------|--------|---------|
| **A — Pattern rules** | Scraped articles matching `PATTERN_RULES` | Named-entity + keyword match |
| **B — Coverage gap** | Articles with high Asia/West asymmetry score | Asymmetry > threshold |
| **Kalshi direct** | Prediction market scan (`/events?status=open`) | Market close within 7 days |
| **Confluence** | Cross-strategy signal aggregation (48 h window) | Multiple corroborating signals |

Layer A and Layer B feed into equity opportunities (Alpaca).
Kalshi direct feeds into prediction market opportunities (Kalshi).
All layers share the same Telegram approval flow.

---

## Kalshi Integration

PAE scans Kalshi prediction markets for opportunities that align with the
current propaganda/news thesis.

**Auth:** RSA-PKCS1v15 signing.  Set `KALSHI_API_KEY` (member ID) and
`KALSHI_SECRET` (PEM private key) in `.env`.

**Flow:**
1. `kalshi_interface.py` fetches `/events?status=open` (with nested markets)
2. Markets expiring within 7 days are kept; others are filtered out
3. LLM scores each market for thesis alignment
4. A high-scoring market triggers a Telegram opportunity alert (same YES/NO flow as equities)
5. Approved opportunities call `kalshi_interface.place_order()` — gated by `KALSHI_LIVE=true`
6. `KALSHI_LIVE=false` (default) means reads and alerts work, but no orders are placed

**Key file:** [app/services/trading/kalshi_interface.py](app/services/trading/kalshi_interface.py)

---

## Project Structure

```
PAE/
├── app/
│   ├── core/
│   │   ├── config.py           # Pydantic-settings (reads .env)
│   │   ├── database.py         # SQLAlchemy engine + db_session()
│   │   └── strategy_loader.py  # Dynamic strategy importer
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── strategy.py
│   │   ├── article.py          # ArticleRegistry, ArticleUrlAlias, ArticleAnalysis
│   │   ├── signal.py
│   │   ├── opportunity.py
│   │   ├── trade.py            # + log_execution / get_active_trades / calculate_returns
│   │   ├── position.py
│   │   └── worker_control.py   # WorkerControl — pause/resume flags per worker
│   ├── services/
│   │   ├── scrapers/
│   │   │   ├── rss_scraper.py        # feedparser + retry
│   │   │   └── article_processor.py  # dedup → DB → scoring
│   │   ├── analysis/
│   │   │   ├── llm_synthesizer.py    # Ollama↔Claude hybrid router
│   │   │   └── pattern_detector.py   # Coverage gaps, policy announcements
│   │   ├── trading/
│   │   │   ├── broker_interface.py   # Abstract BrokerInterface + dataclasses
│   │   │   ├── alpaca_interface.py   # AlpacaBroker (fill poll, stop-loss)
│   │   │   ├── kalshi_interface.py   # KalshiBroker (RSA auth, market scan, orders)
│   │   │   └── position_manager.py   # Conviction sizing + risk limits
│   │   └── notifications/
│   │       ├── telegram_notifier.py  # Push alerts to Telegram
│   │       └── approval_handler.py   # Inbound command router
│   ├── utils/
│   │   ├── url_normalizer.py   # 3-tier URL canonicalisation
│   │   └── dedup.py            # should_scrape() + register_alias()
│   └── workers/
│       ├── tasks.py            # All 5 scheduled task functions + detection layers
│       ├── scheduler.py        # APScheduler BlockingScheduler
│       ├── bot_listener.py     # Telegram /pause /resume /status bot (worker control)
│       └── health.py           # check_system_health() → dict
├── strategies/
│   └── propaganda-arbitrage/
│       ├── thesis.md           # Strategy rationale
│       ├── scraper_config.py   # CONFIG dict + get_scrapers()
│       ├── pattern_rules.py    # PATTERN_RULES list + PATTERNS dict
│       └── llm_config.py       # LLM_CONFIG + prompts + schema
├── scripts/
│   ├── run_workers.py          # Scheduler entry point (Mac Mini)
│   └── run_telegram_bot.py     # Bot entry point (Mac Mini)
├── start-detect.ps1            # Windows: opens SSH tunnel + starts detect worker
├── start-bot.ps1               # Windows: starts bot listener
├── deploy/
│   ├── pae-workers.service     # systemd unit (Linux)
│   └── com.pae.workers.plist   # launchd plist (macOS)
├── tests/                      # pytest suite (all dependencies mocked)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   └── ADDING_STRATEGIES.md
└── requirements.txt
```

---

## Safety Defaults

| Feature | Default | Override |
|---------|---------|---------|
| `DRY_RUN` | `true` | `DRY_RUN=false` in `.env` |
| `PAPER_TRADING` | `true` | `PAPER_TRADING=false` in `.env` |
| Approval gate | Manual Telegram YES | Hardcoded — remove approval gate in `approval_handler.py` to automate |
| Stop-loss attachment | Auto (5%) | `stop_loss_pct` field on `Opportunity` |
| Max open positions | 10 | `_MAX_POSITIONS` in `position_manager.py` |
| Max portfolio exposure | 90% | `_MAX_EXPOSURE_RATIO` in `position_manager.py` |

**Live trading requires explicitly setting both `DRY_RUN=false` AND `PAPER_TRADING=false`.**

---

## Current State & Known Issues

**Live as of 2026-03-02.** Paper trading active; no real-money orders executed yet.

### What's working
- Scrape worker on Mac Mini: ~512 articles per run, 14 RSS sources
- Ollama LLM analysis (qwen3-coder:30b): ~532 analyses per run
- Kalshi prediction market scanning: `status=open` filter + 7-day expiry window
- Telegram approval flow for both equity and Kalshi opportunities
- Sub-lane pause/resume via `/pause detect kalshi` and `/pause detect stock`
- 24 h deduplication for equity opportunities (prevents repeated TSM-style spam)

### Known data issues
- **Iran dominance:** ~80% of high-signal articles are Iran-related; geographic
  diversity filters or source rebalancing may be needed
- **Low relevance scores:** Bulk of scraped articles score < 0.3; coverage-gap
  signal quality depends heavily on source mix
- **Non-US ticker leakage:** Pattern detector occasionally surfaces non-US tickers
  (e.g. TSM ADR variants); equity filter improvements pending
- **`source_region` not populated:** Articles lack the Asia/West region tag needed
  for asymmetry scoring; this limits Layer B effectiveness

### Known schema issues
- **`opportunities.stop_loss_pct DECIMAL(3,2)`** silently truncates values ≥ 10%
  to 9.99.  Run the following migration before live trading:
  ```sql
  ALTER TABLE opportunities MODIFY COLUMN stop_loss_pct DECIMAL(5,2);
  ```

---

## Further Reading

- [Architecture](docs/ARCHITECTURE.md) — component design and DB schema
- [Deployment](docs/DEPLOYMENT.md) — production setup on Mac Mini + web hosting
- [Adding Strategies](docs/ADDING_STRATEGIES.md) — create a new strategy plugin
