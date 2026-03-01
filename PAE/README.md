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

**Deployment split:** Workers and Telegram bot run on a Mac Mini.
MySQL and a future web dashboard live on shared web hosting.

---

## Where things run

PAE uses a two-machine deployment.  **All Python code runs on the Mac Mini —
nothing is installed on the web server.**

| What | Where |
|------|-------|
| Python workers + Telegram bot | Mac Mini |
| Ollama (local LLM) | Mac Mini |
| MySQL database | Web hosting (cPanel/phpMyAdmin) |
| Future web dashboard | Web hosting |

The web server is used only as a MySQL host.  Shared hosting cannot run
long-lived background processes or Ollama, so those stay on the Mac Mini.

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
YES  42      → Approve opportunity #42 and execute buy
NO   42      → Reject opportunity
INFO 42      → Show full thesis and coverage analysis
SELL NVDA    → Close NVDA position
HOLD NVDA    → Acknowledge alert, keep monitoring
STATUS       → Portfolio snapshot with P/L
HELP         → Command reference
```

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
│   │   └── position.py
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
│   │   │   └── position_manager.py   # Conviction sizing + risk limits
│   │   └── notifications/
│   │       ├── telegram_notifier.py  # Push alerts to Telegram
│   │       └── approval_handler.py   # Inbound command router
│   ├── utils/
│   │   ├── url_normalizer.py   # 3-tier URL canonicalisation
│   │   └── dedup.py            # should_scrape() + register_alias()
│   └── workers/
│       ├── tasks.py            # All 5 scheduled task functions
│       ├── scheduler.py        # APScheduler BlockingScheduler
│       └── health.py           # check_system_health() → dict
├── strategies/
│   └── propaganda-arbitrage/
│       ├── thesis.md           # Strategy rationale
│       ├── scraper_config.py   # CONFIG dict + get_scrapers()
│       ├── pattern_rules.py    # PATTERN_RULES list + PATTERNS dict
│       └── llm_config.py       # LLM_CONFIG + prompts + schema
├── scripts/
│   ├── run_workers.py          # Scheduler entry point
│   └── run_telegram_bot.py     # Bot entry point
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

## Further Reading

- [Architecture](docs/ARCHITECTURE.md) — component design and DB schema
- [Deployment](docs/DEPLOYMENT.md) — production setup on Mac Mini + web hosting
- [Adding Strategies](docs/ADDING_STRATEGIES.md) — create a new strategy plugin
