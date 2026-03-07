# Kalshi Micro-Gains Strategy

## Core Thesis

Use high-probability prediction markets (>85% YES or <15% YES) expiring within 48h as a low-risk capital accumulation engine. Profits compound into the equity trading pipeline (FEAT-01 proxy tickers, coverage gap trades).

## How It Works

1. PAE scans Kalshi for markets where outcome is near-certain (85%+ or 15%-)
2. Prioritize markets closing within 24-48h (less time for reversal)
3. Telegram notification sent to user with market, odds, expiry, and suggested position
4. User approves/rejects in 2 seconds (80/20 automation)
5. PAE executes YES or NO order on Kalshi
6. Market resolves, profit collected
7. Profits feed back into Kalshi bankroll or are allocated to equity trades

## Capital Progression Path

```
Phase 1: Kalshi micro-gains (current priority)
  - Low barrier: small position sizes, near-certain outcomes
  - Unregulated on small volume, minimal friction
  - Goal: build initial capital base through compounding

Phase 2: Kalshi profits fund equity pipeline (FEAT-01)
  - Coverage gap detection finds sector signals (TSM, NVDA, etc.)
  - LLM proxy discovery suggests $5-$20 small-caps in same sector
  - Position sizing funded by Kalshi gains
  - Larger returns (3-5x potential) with higher conviction from news edge

Phase 3: Dual-engine compounding
  - Kalshi micro-gains run continuously (low-risk, steady)
  - Equity trades run on coverage gap signals (higher-risk, higher-reward)
  - Both pipelines feed each other's capital base
```

## Example Markets (TX Elections, Mar 2026)

| Market | YES Price | Expiry | Return |
|--------|-----------|--------|--------|
| TX-19 Republican nominee? (Tom Sell) | 90c | Hours | 11% |
| TX-07 Republican nominee? (Alexander Hale) | 93c | Hours | 7.5% |
| TX-09 Republican nominee? (del Moral Mealer) | 94c | Hours | 6.4% |
| TX-17 Democratic nominee? (Milah Flores) | 95c | Hours | 5.3% |

At 5-10% per trade with daily compounding, even small starting capital grows meaningfully.

## Risk Profile

- **Per-trade risk:** Low. 85%+ markets rarely flip in final 48h.
- **Black swan:** A market at 90% can still resolve NO. Position sizing must account for this (never all-in on one market).
- **Kalshi fees:** ~2-7% of profit depending on volume tier. Must be factored into minimum viable trade size.
- **Liquidity:** Some markets have thin order books. PAE should check volume before proposing.
- **Correlation:** Don't stack 10 positions on the same event category (e.g., all TX elections from one party).

## What PAE Needs (Implementation)

### Current State
- Kalshi scanner runs 47+20 search terms per cycle
- Searches returning markets but all filtered out (thresholds too aggressive)
- Approval flow exists but unconfirmed (BUG-09)

### Changes Needed

1. **Filter tuning** — Surface markets at 85%+ YES or 15%- YES (currently probably set higher)
2. **Expiry-first ranking** — Sort by hours-to-close, prioritize soonest
3. **Volume check** — Skip markets with <$1000 volume (thin books = bad fills)
4. **Category expansion** — Don't limit to geopolitical. Elections, economic data, policy votes are all valid for micro-gains
5. **Position sizing** — Start with $10-25 per trade, scale up as bankroll grows
6. **Telegram alert format** — Show: market title, YES/NO price, expiry countdown, suggested side, suggested size, one-tap approve
7. **Approval flow validation** — Confirm BUG-09 (Kalshi order execution after Telegram approval)
8. **Profit tracking** — Track Kalshi P&L separately so progression from Phase 1 to Phase 2 is visible
9. **Compounding logic** — Reinvest Kalshi profits automatically (configurable % to equity bankroll)

### Nice-to-Have (Phase 2+)
- Auto-approve markets above 95% with <24h expiry and volume >$5000 (full automation for near-certainties)
- Diversification guard: max N positions per event category
- Kalshi bankroll dashboard on Telegram (/kalshi_balance, /kalshi_pnl)

## Open Questions for Brainstorming

1. What's the minimum viable position size after Kalshi fees make it worthwhile?
2. Should we differentiate between election markets (one-time resolution) vs. recurring markets (economic data, weekly events)?
3. At what bankroll size does it make sense to start splitting profits into equity trades?
4. How aggressive should auto-approve thresholds be? 95%+ with <12h expiry? 97%+?
5. Are there market categories that are systematically mispriced on Kalshi (e.g., local elections with low attention)?
6. What's the optimal scan frequency? Every 30 min? Every hour? More frequent near market close times?

---

## System Status (as of 2026-03-07)

### Opus Synthesis Prompts — All 8 Complete

The following changes from `PAE_Opus_Synthesis.md` have been implemented and tested in production:

1. **DECIMAL fix** — `stop_loss_pct` and `confluence_score` widened from `DECIMAL(3,2)` to `DECIMAL(5,2)`. Migration restored 158 truncated rows.
2. **Price pipeline fix** — `BarSet.get()` replaced with `try: bars[ticker]` / `except KeyError` (alpaca-py 0.43.2 breaking change). Fixed in both `tasks.py` and `telegram_notifier.py`. Falsy-zero bug fixed (`share_price if share_price` → `share_price is not None`).
3. **Ticker validation** — `_is_plausible_us_ticker()` blocks geographic strings (TAIWAN, CHINA, IRAN, etc.) and exchange-suffixed symbols before Alpaca API calls. Removed duplicate pre-validation `_write_signal()` that wrote raw entity names.
4. **72h novelty suppression** — Jaccard keyword overlap (threshold 0.60) replaces 24h simple dedup. Applied in both `_run_strategy_pipeline()` and `run_detection_cycle()`. Fixed `DetachedInstanceError` by querying `_Opp.thesis` strings instead of full ORM objects.
5. **Source rebalancing** — 7 new Asian sources added (Caixin Global, Nikkei Asia, Semiconductor Engineering, EE Times Asia, The Diplomat, Korea JoongAng Daily, Taipei Times). Weight system: government/Asian press = 1.5, western = 1.0, social = 0.5. Total: 25 sources, 1248 articles/cycle.
6. **PatternDetector weighted counting** — `len(v)` → `sum(a.get("weight", 1.0) for a in v)` for both western_count and asia_count in `analyze_coverage_gaps()`.
7. **pattern_rules.py rebuild** — All 11 Layer A rules now have `decay_days`, `snap_back_keywords`, `direction`, `layer="A"`. Added 3 Layer B stubs (semiconductor, battery_ev, renewable). Added `WESTERN_DISMISSAL_BOOST` and keywords.
8. **Kalshi expiry expansion** — `_surface_kalshi_market_signals()` now accepts `max_days` and `category_filter`. Layer A: 7 days, all categories. Layer B: 90 days, taiwan/tech_policy/geopolitical.

### Production Test Results (2026-03-07 00:36)

- 1248 articles across 26 sources (up from 954 pre-fixes)
- 9 coverage gaps detected
- 0 equity opportunities (all tickers above $30 — needs FEAT-01)
- Kalshi scan: 47 terms Layer A + 20 terms Layer B completed without errors
- 0 Kalshi opportunities surfaced (filter tuning needed — see Changes Needed above)
- Telegram notifications working (cycle summary delivered)
- `DetachedInstanceError` fixed and confirmed
- Broken RSS feeds fixed: Caixin (new URL), Nikkei (new URL), Korea JoongAng (Google News proxy), Taipei Times (replaced Taiwan News)
- State Dept RSS still failing (their feed has malformed HTML — not fixable on our end)

### Open Bugs

| ID | Description | Severity | Blocker? |
|----|-------------|----------|----------|
| BUG-03 | Share price missing from alerts | High | Blocked by $30 cap + FEAT-01 |
| BUG-04 | Sub-lane pause/resume not working by trade channel | High | No |
| BUG-05 | `httpx.ConnectError` on Windows bot (Telegram API) | High | Bot runs on Mac instead |
| BUG-06 | `source_region` not populated on articles | Medium | No |
| BUG-08 | Low article relevance scores (bulk < 0.3) | Medium | No |
| BUG-09 | Kalshi approval flow unconfirmed | Medium | **Yes — blocks Phase 1** |
| BUG-10 | Exit/SELL flow unconfirmed | Medium | Blocks equity trades |

### Planned Features

| ID | Description | Priority |
|----|-------------|----------|
| FEAT-01 | Two-stage ticker pipeline (sector sensor → LLM proxy discovery) | Phase 2 |
| Kalshi filter tuning | Lower thresholds, add expiry ranking, category expansion | **Phase 1 — immediate** |
| Kalshi profit tracking | Separate P&L, bankroll dashboard | Phase 1 |
| Auto-approve | 95%+ markets with <24h expiry | Phase 2+ |

### Deployment Architecture

| Machine | Role | Process |
|---------|------|---------|
| Mac Mini M4 | Scrape + detect + monitor (scheduled) | `bash start-workers.sh` |
| Mac Mini M4 | Telegram bot (commands, approvals) | `bash start-bot.sh` |
| Windows Alienware (RTX GPU) | Detection only (GPU inference) | `pae-detect` (PowerShell profile) |
| Web hosting | MySQL database | SSH tunnel from both machines |

---

*This document is designed to be handed to a brainstorming/inference session for deeper analysis.*
