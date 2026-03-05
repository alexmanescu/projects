# PAE — Pending Bug Fixes

Tracked bugs and data quality issues. Check off with agent approval as fixes are confirmed working in production.

---

## Critical (block trade execution)

### BUG-01 — `opportunities.stop_loss_pct` DECIMAL truncation
- **Status:** ❌ Open
- **Symptom:** `stop_loss_pct` column is `DECIMAL(3,2)`, silently truncates values ≥ 10% to 9.99. Opportunity shows `Stop Loss: 15.0%` in Telegram but DB stores 9.99, causing downstream position sizing errors.
- **Fix:** Run migration on remote MySQL:
  ```sql
  ALTER TABLE opportunities MODIFY COLUMN stop_loss_pct DECIMAL(5,2);
  ```
- **File:** `app/models/opportunity.py` — update column definition to match after migration

### BUG-02 — `alpaca-py` not installed on Windows detect worker
- **Status:** ❌ Open
- **Symptom:** `❌ Unexpected error: alpaca-py is not installed. Run: pip install alpaca-py` — detect worker on Windows doesn't have the package, causing price lookups and trade execution to fail entirely
- **Fix:** On the Windows venv: `pip install alpaca-py`
- **Affects:** `_get_validated_price()`, `telegram_notifier.py` price fallback, `approval_handler.py` order execution

---

## High (broken features)

### BUG-03 — Share price and suggested share quantity missing from opportunity alerts
- **Status:** ❌ Open
- **Symptom:** Opportunity alert shows `Amount: $10,000 / Stop Loss: 15.0% / Max Loss: $1,500` but no share price or suggested share count. Expected: `Price: $185.20 / Shares: ~54`
- **Root cause:** `_get_validated_price()` returns `None`/`0.0` — `StockLatestTradeRequest` fails (likely free-tier Alpaca), `StockBarsRequest` fallback added in code but unconfirmed working; may also be blocked by BUG-02 (alpaca-py missing)
- **Files:** `app/workers/tasks.py` → `_get_validated_price()`, `app/services/notifications/telegram_notifier.py` → price fallback block

### BUG-04 — Sub-lane pause/resume not recognized by trade channel
- **Status:** ❌ Open
- **Symptom:** `/pause detect kalshi` and `/pause detect stock` commands respond in Telegram but detection worker doesn't appear to respect the sub-lane flags — all or nothing pause still the effective behavior
- **Root cause:** Likely `_is_worker_paused("detect_kalshi")` / `_is_worker_paused("detect_stock")` not being called on the right code path, or the DB write from `bot_listener.py` isn't reaching the detect worker's MySQL connection
- **Files:** `app/workers/tasks.py` → `run_detection_cycle()`, `app/workers/bot_listener.py`

### BUG-05 — `httpx.ConnectError` on external API calls
- **Status:** ❌ Open
- **Symptom:** `❌ Unexpected error: httpx.ConnectError: [error details]` — intermittent connection failures, exact endpoint unknown (likely Kalshi or Alpaca)
- **Fix:** Identify which call is failing (check logs for surrounding context), add retry with backoff or graceful skip
- **Files:** Unknown until log context captured — likely `app/services/trading/kalshi_interface.py` or Alpaca data client calls

---

## Medium (data quality / signal accuracy)

### BUG-06 — `source_region` not populated on articles
- **Status:** ❌ Open
- **Symptom:** Articles in DB have no Asia/West region tag; Layer B coverage-gap detection is effectively blind
- **Root cause:** `article_processor.py` or scraper config doesn't assign `source_region` during ingestion
- **Files:** `app/services/scrapers/article_processor.py`, `strategies/propaganda-arbitrage/scraper_config.py`

### BUG-07 — Non-US / non-tradeable tickers surfacing as equity opportunities
- **Status:** ❌ Open
- **Symptom:** Tickers like TSM (ADR, not directly shortable on all accounts), and potentially others, slip through the pattern detector. Creates noise and likely-invalid trade suggestions.
- **Fix:** Post-detection filter: validate ticker against Alpaca's asset list (`is_tradable=True, asset_class=us_equity`) before sending opportunity alert
- **Files:** `app/workers/tasks.py` → `run_detection_cycle()`

### BUG-08 — Low article relevance scores (bulk < 0.3)
- **Status:** ❌ Open
- **Symptom:** Most scraped articles score below 0.3 relevance, limiting signal quality. Coverage gap detection fires on weak signals.
- **Fix:** Tune relevance threshold or review scoring weights in article processor / pattern rules
- **Files:** `app/services/scrapers/article_processor.py`, `strategies/propaganda-arbitrage/pattern_rules.py`

### BUG-09 — Kalshi order approval flow unconfirmed / potentially broken
- **Status:** ❌ Unconfirmed (untested)
- **Symptom:** No Kalshi opportunity has been approved and executed end-to-end. `KALSHI_LIVE=false` by default gates orders, but even with it enabled the full path (`YES <id>` → `approval_handler` → `kalshi_interface.place_order()`) has never been exercised.
- **Risk areas:** RSA signing on order POST, response parsing, opportunity `status` update after fill, Telegram confirmation message
- **Files:** `app/services/notifications/approval_handler.py`, `app/services/trading/kalshi_interface.py`

### BUG-10 — Exit / SELL approval flow unconfirmed / potentially broken
- **Status:** ❌ Unconfirmed (untested)
- **Symptom:** No position has ever been closed via `SELL <ticker>` or an LLM-triggered exit signal. The full path (`SELL` command / `monitor_positions` → `approval_handler` → `AlpacaBroker.close_position()` → `position` row update) has never been exercised in production.
- **Risk areas:** `SELL` command parsing, broker close call, stop-loss cancellation on exit, P/L calculation, Telegram confirmation
- **Files:** `app/services/notifications/approval_handler.py`, `app/services/trading/alpaca_interface.py`, `app/workers/tasks.py` → `monitor_positions()`

---

## Fixed / Confirmed

### ~~BUG-F01~~ — Kalshi API 400 `bad_request` on `/events`
- **Status:** ✅ Fixed (2026-03-02)
- `status=active` → `status=open` in `kalshi_interface.py`

### ~~BUG-F02~~ — Kalshi API 400 `invalid status filter` on `/markets`
- **Status:** ✅ Fixed (2026-03-02)
- Added `status=open` to `/markets` fallback params

### ~~BUG-F03~~ — `stop_loss_pct` percentage/decimal mismatch in approval handler
- **Status:** ✅ Fixed (2026-03-02)
- `approval_handler.py`: converts `15.0` → `0.15` before passing to `position_manager`

### ~~BUG-F04~~ — Kalshi notification spam (year-long markets)
- **Status:** ✅ Fixed (2026-03-02)
- 7-day expiry filter added in `tasks.py` and `approval_handler.py`

### ~~BUG-F05~~ — Repeated identical equity opportunities (TSM spam)
- **Status:** ✅ Fixed (2026-03-02)
- 24h dedup check added before equity opportunity alert in `run_detection_cycle()`
