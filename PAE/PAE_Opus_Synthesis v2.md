# PAE — Opus Synthesis Document
## Complete Bug Fix Sequence, Signal Quality Specs, and Implementation Prompts

*Generated from full codebase review of `alexmanescu/projects/PAE` @ commit `ba7d91c`*

---

## Status Update (2026-03-07)

**All 8 prompts from Section 5 have been executed and confirmed working in production.**
Key results: 1248 articles/cycle across 26 sources, 9 coverage gaps detected, weighted
gap analysis live, 72h novelty suppression active, pattern_rules.py rebuilt with full
thesis fields, Kalshi expiry expanded to 90 days for Layer B.

**Current blockers:**
- 0 equity opportunities surfacing (all thesis tickers above $30 cap → needs FEAT-01 proxy ticker discovery)
- 0 Kalshi opportunities surfacing (filter thresholds too aggressive → see Kalshi Micro-Gains addendum below)
- BUG-09: Kalshi approval → order execution flow has never been exercised end-to-end

**Immediate priority has shifted to Kalshi micro-gains** as the fastest path to real revenue.
See `kalshi-micro-gains-strategy.md` and `kalshi_microgains_prompt.md` for the implementation
plan and Claude Code prompt. The equity pipeline (FEAT-01 proxy tickers) is Phase 2.

---

## Section 1: Bug Fix Sequence — Ordered by Priority

The milestone is **first paper trade executing successfully via `YES {id}` in Telegram**. Every bug below is ordered by what stands between you and that milestone.

> **⚡ DIAGNOSTIC FIRST:** Before applying any code fixes for BUG-02/03, run
> `python scripts/diagnose_price_chain.py` on both machines. This script
> (delivered alongside this document) tests every step of the price validation
> pipeline and will identify the exact failure point in 30 seconds. The fix
> depends on what the diagnostic reveals.

### Tier 1: Blocking the first paper trade

**BUG-01 → DECIMAL(3,2) stop_loss_pct truncation**
The `opportunities` table defines `stop_loss_pct DECIMAL(3,2)` — max storable value is 9.99. Every Layer B opportunity writes `15.0`, which MySQL silently truncates to `9.99`. When `approval_handler.py` line 187 reads it back:
```python
raw_sl = float(opp.stop_loss_pct or 5.0)
stop_loss_pct = raw_sl / 100.0 if raw_sl > 1.0 else raw_sl
```
It gets `9.99 / 100 = 0.0999` instead of `0.15`. This means the stop-loss is placed at 10% instead of 15%. More critically, **`position_manager.validate_trade()` enforces `_MAX_STOP_LOSS_PCT = 0.25`** — so the 0.0999 would pass, but the position sizing math is wrong.

Additionally: `confluence_score` on the same table is also `DECIMAL(3,2)`. Values > 9.99 would truncate. Current data tops at ~1.0 so this isn't actively corrupting, but fix it while you're in the schema.

Fix: One SQL migration + one model file update.

**BUG-02 → Price validation pipeline failure (multiple possible causes)**
**Status: Requires diagnostic — see `scripts/diagnose_price_chain.py`**

User has confirmed `alpaca-py` is installed and `max_share_price` is intentionally $50 (the strategy targets small-cap affordable shares for capital building). The pipeline has a subtle interaction between three code paths that can mask the real failure:

`_get_validated_price()` in `tasks.py` has two early-exit paths that return `0.0`:
```python
# Line 313 — price fetch returned nothing
if price is None:
    return 0.0  # "allowing through without price"

# Line 322 — entire price block threw an exception
except Exception as exc:
    return 0.0  # "ticker is known but price unavailable → allow through"
```

If the Alpaca data client throws (wrong venv context, auth issue, free-tier rejection of `StockLatestTradeRequest`), the function catches the exception and returns `0.0`. Then the $50 cap check — `price > settings.max_share_price` — evaluates `0.0 > 50.0` = `False`. **The cap is silently bypassed.** The opportunity reaches Telegram with no price data.

This explains BUG-03 (missing share price in alerts): opportunities ARE being created, but with `suggested_price=None` because the `0.0` return from `_get_validated_price()` is falsy in the dict constructor.

Three possible root scenarios:
1. **Price API works, cap blocks legitimately:** TSM ($170), NVDA ($130), INTC ($60) all exceed $50. They return `None`, opportunities get `continue`'d. But 371 pending opps exist — so they're being created via a different path (Layer A signals skip price validation, Kalshi signals skip it). Equity gap opportunities would be silently dropped. Fix: add lower-priced ETFs to thesis tickers (SOXL ~$20, SOXS ~$20, TAN ~$40) — or raise cap for equities you do want to trade.
2. **Price API fails, cap is bypassed:** Exception handler returns `0.0`, which passes `> 50` check. Opportunities reach Telegram without price data. The package may be installed in your shell but the detect worker's PowerShell script may activate a different venv path.
3. **Mixed:** `StockLatestTradeRequest` fails (requires paid SIP feed) but `StockBarsRequest` fallback works for some tickers. Partial price data.

**Diagnostic:** Run `python scripts/diagnose_price_chain.py` on BOTH machines with the PAE venv activated. The script (included with this document) tests every step: Python path, alpaca import, API auth, both price methods, the actual `_get_validated_price()` function, and which tickers from your thesis universe survive the full pipeline. Output will definitively identify which scenario you're in.

**Likely fix path after diagnosis:**
- If Scenario 1: Add lower-priced ETFs (SOXL, SOXS, XLE, TAN, SMH) to `pattern_rules.py` ticker lists. These are leveraged/sector ETFs that trade under $50 and track the same sectors your thesis targets.
- If Scenario 2: Fix the venv path in `start-detect.ps1` so the worker process uses the correct Python with alpaca-py.
- If Scenario 3: Ensure `StockBarsRequest` fallback is working, or switch to a data source that works on Alpaca's free tier.

**BUG-03 → Share price / share count missing from alerts**
This is a downstream symptom of BUG-02. In `telegram_notifier.py` line 138, `share_price = opportunity.get("suggested_price")`. In `tasks.py` line 681:
```python
"suggested_price": share_price if share_price and share_price > 0 else None,
```
When `_get_validated_price()` returns `0.0` (price unavailable), `0.0` is falsy in Python so this evaluates to `None`. The notifier falls back to flat-amount display.

The notifier has a fallback price fetch (lines 143-167) but it's inside a bare `except Exception: pass` — silent failure.

Fix: After BUG-02 root cause is resolved, also fix the falsy-zero issue (`share_price is not None and share_price > 0` instead of `share_price and share_price > 0`) and add WARNING-level logging to the notifier fallback.

### Tier 2: Signal quality (post-first-trade)

**BUG-06 → source_region not populated**
Articles have `category` from scraper config at runtime, but no persistent `source_region` column in `article_registry`. The `PatternDetector.analyze_coverage_gaps()` works fine on the in-memory article list (it uses `category`), but retrospective queries against the DB can't determine article provenance. This doesn't block trades but blocks analytics.

**BUG-07 → Non-US ticker leakage**
Already partially addressed: `_get_validated_price()` (line 273) rejects tickers with `.` suffixes, and line 278 checks against the Alpaca asset cache. But `_write_signal()` happens *before* ticker validation in `run_detection_cycle()` (line 801 writes signal for raw `entity`, line 835 writes again for validated `primary_ticker`). This means geographic entities like "Taiwan" and "Japan" still generate Signal rows even when the corresponding ticker is rejected.

**BUG-04 → Sub-lane pause not working**
In `run_detection_cycle()`, the sub-lane checks work correctly in code: line 790 checks `_is_worker_paused("detect_stock")` and line 892 checks `_is_worker_paused("detect_kalshi")`. The issue is likely in `bot_listener.py` — the `/pause detect kalshi` command needs to write `worker_name="detect_kalshi"` to the `worker_controls` table, and both machines must share the same MySQL. If the bot_listener writes to a local DB or a different connection string, the detect worker never sees the flag.

**BUG-05 → httpx.ConnectError**
This is likely the Kalshi API hitting rate limits or timeouts. The `KalshiInterface` uses `requests` (not httpx), so the error is probably coming from `alpaca-py` which uses httpx internally. Fix: wrap the Alpaca data client calls in retry logic.

**BUG-08 → Low relevance scores**
87% of articles score < 0.3 relevance. This is a source mix problem (too much Middle East content) plus a scoring calibration issue in the LLM prompts. Source rebalancing (Section 2b) addresses the root cause.

**BUG-09 → LLM thesis notes are templates**
"Geopolitical event threatening oil/gas supply routes" appears 5+ times. The `ANALYSIS_PROMPT_TEMPLATE` in `llm_config.py` is adequate — the issue is that the Qwen model at 3-bit quantization pattern-matches into archetypes rather than generating article-specific analysis. Fix: add 2-3 few-shot examples to the prompt showing article-specific output.

---

## Section 2: Signal Quality Fix Specs

### 2a. Novelty Suppression Logic

**Problem:** 371 pending opportunities, ~20 of last 30 are identical TSM coverage-gap alerts. The 24h dedup (line 856-868 in `tasks.py`) prevents the same ticker in the same 24h window, but a new cycle 25 hours later re-fires the identical thesis.

**Proposed implementation: Embedding-based similarity check**

Since Ollama is already running on both machines at 40-150 tok/s, use Ollama's embedding endpoint for cheap similarity. The `/api/embeddings` endpoint takes ~10ms per call.

Pipeline position: Insert **after** thesis generation, **before** opportunity creation. In `_run_strategy_pipeline()` at line 670 (and the equivalent in `run_detection_cycle()` at line 871), before constructing the opportunity dict:

```
1. Generate thesis text (already done by this point)
2. Call Ollama /api/embeddings on the thesis text
3. Query the last 72h of opportunities for same ticker
4. For each existing opp, compute cosine similarity against stored embedding
5. If max similarity > 0.85: suppress (log but don't alert)
6. If 0.70-0.85: tag as "related" and include reference to prior opp ID
7. If < 0.70: novel — proceed normally
```

Schema change: Add `thesis_embedding BLOB` column to `opportunities` table. Store the raw float32 vector (768 dims for most models = 3KB per row).

**Simpler alternative (no embeddings):** Keyword overlap ratio. Extract the top 10 non-stopword tokens from the new thesis and the most recent thesis for the same ticker. If Jaccard overlap > 0.6, suppress. This is cruder but zero-dependency and no API calls.

**Recommendation:** Start with keyword overlap (it's a 30-line function, no schema change needed). Graduate to embeddings when you have enough data to calibrate the threshold.

### 2b. Source Rebalancing

**Current state:** 18 sources across 6 categories. Only 2 are `alternative_asia` (SCMP, Global Times). 4 Reddit subs + Google Trends flood the corpus with noise. Iran is 2x more detected than China because general news sources dominate.

**Specific RSS sources to add:**

| Source | URL | Category | Priority | Why |
|--------|-----|----------|----------|-----|
| Caixin Global | `https://www.caixinglobal.com/rss/` | `alternative_asia` | 1 | Chinese Bloomberg — financial focus, English language |
| Nikkei Asia | `https://asia.nikkei.com/rss` | `alternative_asia` | 2 | Japan-based pan-Asian business coverage |
| Semiconductor Engineering | `https://semiengineering.com/feed/` | `western_tech` | 2 | Deep chip industry coverage, catches fab milestones |
| EE Times Asia | `https://www.eetasia.com/feed/` | `alternative_asia` | 2 | Asian electronics trade press |
| The Diplomat | `https://thediplomat.com/feed/` | `alternative_asia` | 3 | Asia-Pacific geopolitics |
| Korea JoongAng Daily | `https://koreajoongangdaily.joins.com/section/rss` | `alternative_asia` | 3 | Korean business/tech |
| Taiwan News | `https://www.taiwannews.com.tw/en/rss` | `alternative_asia` | 2 | Taiwan-specific coverage |

**Sources to deprioritize (don't remove, reduce weight):**
- Reddit WallStreetBets, Reddit WorldNews, Reddit Investing — set priority 5, reduce scrape frequency
- Google Trends — useful as sentiment but floods entity extraction with noise

**Source weight field:** Add `weight: float` to each source config dict. Default 1.0. Asian tech/business sources: 1.5. Social media: 0.5. The `PatternDetector.analyze_coverage_gaps()` should multiply article counts by source weight before computing gap ratio:

```python
weighted_asia = sum(
    len(v) * source_weights.get(k, 1.0)
    for k, v in cat_map.items() if k in _ASIA_CATEGORIES
)
```

This makes one Caixin article count as 1.5 articles while one Reddit post counts as 0.5.

### 2c. Kalshi Threshold Redesign

**Current:** Flat 65¢ threshold. Markets where YES ≥ 65 or NO ≥ 65 (i.e., YES ≤ 35) are surfaced. 7-day expiry window.

**Problem:** At 65%, the easy money is already made. The Taiwan signal was found only because you manually directed the system to look wider.

**Proposed tiered system:**

| Band | YES Price Range | Logic | Position Size |
|------|----------------|-------|---------------|
| **Discovery** | 30-55¢ | Coverage gap analysis suggests true probability higher than market. Signal must have a corroborating Layer A or B signal for the same entity within 48h. | 1-2% capital |
| **Entry** | 55-75¢ | Confirmed mispricing. At least one of: (a) coverage gap ratio > 3x, (b) Layer A signal fired, (c) Kalshi odds moved 10+ cents toward signal direction in last 24h. | 2-4% capital |
| **Consensus** | 75-90¢ | Market catching up. Hold existing position but don't add. | Hold only |
| **Exit** | >90¢ | Information fully priced. Close position regardless of P/L. | Exit signal |

**Active signal-driven search:** Instead of scanning all open markets against static categories, add a function that takes the current active Layer A/B signals and constructs targeted Kalshi search queries:

```python
def build_kalshi_searches_from_signals(active_signals: list[Signal]) -> list[str]:
    """Convert active PAE signals into Kalshi search terms."""
    searches = []
    for sig in active_signals:
        if sig.signal_type == "coverage_gap" and "Taiwan" in sig.ticker:
            searches.extend(["Taiwan", "Taiwan Strait", "TSMC"])
        elif sig.signal_type == "sanctions_announcement":
            searches.extend(["sanctions", "OFAC", sig.ticker])
        # ... map each signal_type to relevant Kalshi terms
    return list(set(searches))
```

**Expiry window:** Expand from 7 days to 90 days for Layer B signals (slow decay). Keep 7 days for Layer A signals (fast decay). The current hardcoded `days_out > 7` at line 1324 needs to become signal-type-aware.

### 2d. Ticker Validation

**Current state:** `_get_validated_price()` already does most of the work (rejects `.` suffixes, checks Alpaca asset cache). But the signal is written *before* validation in `run_detection_cycle()`.

**Spec: Move validation before signal write. Add a local whitelist check as fast-path.**

```python
_US_TICKER_RE = re.compile(r'^[A-Z]{1,5}$')
_KNOWN_ADRS = {"TSM", "BABA", "NIO", "XPEV", "LI", "BIDU", "JD", "PDD"}
_BLOCKED_STRINGS = {"NONE", "N/A", "UNKNOWN", "GENERAL", "CHINA", "TAIWAN",
                    "JAPAN", "KOREA", "US", "USA", "EU", "EUROPE", "INDIA",
                    "RUSSIA", "UK", "IRAN"}

def is_valid_us_ticker(ticker: str) -> bool:
    if not ticker or ticker.upper() in _BLOCKED_STRINGS:
        return False
    if "." in ticker and not ticker.upper() in _KNOWN_ADRS:
        return False
    if not _US_TICKER_RE.match(ticker.upper()):
        return False
    return True
```

Call this *before* `_write_signal()` in both `_run_strategy_pipeline()` and `run_detection_cycle()`. This prevents geographic entity strings from ever becoming signal rows.

---

## Section 3: Revised pattern_rules.py Spec

The current `pattern_rules.py` has 11 rules in `PATTERN_RULES` but they're missing fields specified in `thesis.md`: `decay_days`, `snap_back_keywords`, `direction`. Here's the complete spec:

```python
PATTERN_RULES: list[dict] = [
    # ── Layer A: Government Communication Signals ─────────────────────
    {
        "name": "sanctions_announcement",
        "description": "New OFAC designations or export controls create forced institutional selling.",
        "keywords": ["sanctions", "sanctioned", "OFAC designates", "embargo",
                     "export controls", "entity list", "SDN list"],
        "exclude": ["lifted", "removed", "eased", "relief", "waiver", "exemption"],
        "tickers": ["LMT", "RTX", "NOC", "BA"],
        "signal_type": "bullish",  # bullish for defense contractors
        "direction": "long_defense_short_affected",
        "decay_days": 2,
        "confidence": 0.60,
        "snap_back_keywords": ["walked back", "exemption", "waiver", "paused",
                               "delayed implementation", "sources say"],
        "layer": "A",
    },
    {
        "name": "sanctions_relief",
        "description": "Easing of sanctions — upside for commodities and energy companies.",
        "keywords": ["sanctions relief", "sanctions lifted", "embargo lifted",
                     "eased sanctions", "license granted"],
        "exclude": ["new sanctions", "additional", "expanded"],
        "tickers": ["XOM", "CVX", "OXY"],
        "signal_type": "bullish",
        "direction": "long_energy_commodities",
        "decay_days": 3,
        "confidence": 0.55,
        "snap_back_keywords": ["re-imposed", "conditions not met", "temporary"],
        "layer": "A",
    },
    {
        "name": "tariff_increase",
        "description": "New or raised tariffs compress margins for import-heavy sectors.",
        "keywords": ["tariff", "tariffs", "import duty", "trade war",
                     "Section 301", "Section 232", "retaliatory tariff"],
        "exclude": ["reduced", "lowered", "removed", "exemption", "paused"],
        "tickers": ["WMT", "AMZN", "COST", "TGT"],
        "signal_type": "bearish",
        "direction": "short_importers",
        "decay_days": 4,
        "confidence": 0.55,
        "snap_back_keywords": ["delayed", "exemption", "negotiating", "paused",
                               "90 day", "temporary"],
        "layer": "A",
    },
    {
        "name": "tariff_reduction",
        "description": "Lower tariffs benefit import-dependent consumer goods.",
        "keywords": ["tariff reduction", "tariff cut", "trade deal",
                     "trade agreement", "tariff pause"],
        "exclude": ["failed", "collapsed", "stalled", "increased"],
        "tickers": ["WMT", "TGT", "NKE", "COST"],
        "signal_type": "bullish",
        "direction": "long_importers",
        "decay_days": 4,
        "confidence": 0.55,
        "snap_back_keywords": ["reversed", "walked back", "conditions"],
        "layer": "A",
    },
    {
        "name": "defence_spending_increase",
        "description": "Government announcement of higher defence budgets or supplementals.",
        "keywords": ["defence budget", "defense spending", "military aid",
                     "Pentagon budget", "NATO spending", "NDAA", "supplemental"],
        "exclude": ["cut", "reduction", "freeze", "sequester"],
        "tickers": ["LMT", "RTX", "NOC", "GD", "BA"],
        "signal_type": "bullish",
        "direction": "long_defense",
        "decay_days": 7,
        "confidence": 0.70,
        "snap_back_keywords": ["vetoed", "blocked", "reduced from"],
        "layer": "A",
    },
    {
        "name": "semiconductor_policy",
        "description": "Government chip subsidies or export controls on semiconductor equipment.",
        "keywords": ["CHIPS Act", "chip subsidy", "semiconductor funding",
                     "export control", "chip ban", "chip restriction",
                     "fab construction", "foundry subsidy"],
        "exclude": ["reversed", "cancelled", "delayed indefinitely"],
        "tickers": ["NVDA", "AMD", "INTC", "AMAT", "KLAC", "LRCX", "TSM"],
        "signal_type": "bullish",
        "direction": "long_domestic_semis",
        "decay_days": 10,
        "confidence": 0.65,
        "snap_back_keywords": ["reversed", "exemption granted", "scaled back"],
        "layer": "A",
    },
    {
        "name": "energy_supply_disruption",
        "description": "Geopolitical event threatening oil/gas supply routes.",
        "keywords": ["pipeline attack", "Strait of Hormuz", "OPEC cut",
                     "oil supply disruption", "gas supply disruption",
                     "refinery attack", "tanker seized"],
        "exclude": ["resolved", "reopened", "supply restored"],
        "tickers": ["XOM", "CVX", "COP", "USO", "XLE"],
        "signal_type": "bullish",
        "direction": "long_energy",
        "decay_days": 3,
        "confidence": 0.65,
        "snap_back_keywords": ["resolved", "ceasefire", "supply restored",
                               "strategic reserve release"],
        "layer": "A",
    },
    {
        "name": "central_bank_hawkish",
        "description": "Central bank signalling rate hikes or quantitative tightening.",
        "keywords": ["rate hike", "interest rate increase", "hawkish",
                     "quantitative tightening", "inflation fight",
                     "higher for longer"],
        "exclude": ["pause", "cut", "dovish", "considering cuts"],
        "tickers": ["TLT", "SHY", "GLD"],
        "signal_type": "bearish",
        "direction": "short_bonds_short_growth",
        "decay_days": 2,
        "confidence": 0.60,
        "snap_back_keywords": ["revised down", "softer than expected", "dovish pivot"],
        "layer": "A",
    },
    {
        "name": "central_bank_dovish",
        "description": "Central bank pivoting toward cuts or stimulus.",
        "keywords": ["rate cut", "rate reduction", "dovish", "quantitative easing",
                     "stimulus", "accommodative", "pivot"],
        "exclude": ["hawkish", "hike", "higher for longer"],
        "tickers": ["SPY", "QQQ", "GLD", "TLT"],
        "signal_type": "bullish",
        "direction": "long_growth_long_bonds",
        "decay_days": 2,
        "confidence": 0.60,
        "snap_back_keywords": ["hawkish surprise", "inflation reaccelerate", "data dependent"],
        "layer": "A",
    },
    {
        "name": "regime_change_risk",
        "description": "Political instability in a commodity-rich country.",
        "keywords": ["coup", "regime change", "civil unrest", "political crisis",
                     "government collapse", "martial law", "state of emergency"],
        "exclude": ["peaceful transition", "democratic", "resolved"],
        "tickers": ["GLD", "SLV", "USO", "XLE"],
        "signal_type": "bullish",
        "direction": "long_safe_havens",
        "decay_days": 5,
        "confidence": 0.50,
        "snap_back_keywords": ["stabilized", "ceasefire", "interim government",
                               "negotiations"],
        "layer": "A",
    },
    {
        "name": "pandemic_new_variant",
        "description": "Novel pathogen or variant causing travel/supply chain concern.",
        "keywords": ["new variant", "pandemic", "lockdown", "WHO emergency",
                     "outbreak", "epidemic", "novel pathogen"],
        "exclude": ["contained", "mild", "no concern", "endemic"],
        "tickers": ["MRNA", "PFE", "BNTX", "ZM"],
        "signal_type": "bullish",
        "direction": "long_pharma_short_travel",
        "decay_days": 5,
        "confidence": 0.45,
        "snap_back_keywords": ["contained", "mild", "no evidence of", "preliminary",
                               "revised down"],
        "layer": "A",
    },

    # ── Layer B: Coverage Gap Signals (detected by PatternDetector, not keyword rules) ──
    # These are NOT keyword-triggered. They're detected by analyze_coverage_gaps()
    # based on article count asymmetry. Listed here for reference and snap-back detection.
    {
        "name": "coverage_gap_semiconductor",
        "description": "Asian coverage of chip fab milestone/funding >> Western coverage.",
        "keywords": [],  # detected by gap ratio, not keywords
        "exclude": [],
        "tickers": ["TSM", "INTC", "AMAT", "KLAC", "LRCX"],
        "signal_type": "bullish",
        "direction": "long_semis",
        "decay_days": 28,
        "confidence": 0.50,
        "snap_back_keywords": ["delays", "yield issues", "cancelled", "overcapacity"],
        "layer": "B",
    },
    {
        "name": "coverage_gap_battery_ev",
        "description": "Asian coverage of battery capacity/chemistry >> Western coverage.",
        "keywords": [],
        "exclude": [],
        "tickers": ["BYDDF", "ALB", "LAC", "SQM", "TSLA"],
        "signal_type": "bullish",
        "direction": "long_battery_supply_chain",
        "decay_days": 42,
        "confidence": 0.50,
        "snap_back_keywords": ["safety recall", "overcapacity", "demand slowdown"],
        "layer": "B",
    },
    {
        "name": "coverage_gap_renewable",
        "description": "Asian coverage of solar/grid deployment scale >> Western coverage.",
        "keywords": [],
        "exclude": [],
        "tickers": ["FSLR", "ENPH", "SEDG", "TAN"],
        "signal_type": "bullish",
        "direction": "long_solar_supply_chain",
        "decay_days": 42,
        "confidence": 0.50,
        "snap_back_keywords": ["tariff", "anti-dumping", "subsidy cut", "oversupply"],
        "layer": "B",
    },
]

# ── Western dismissal modifier ────────────────────────────────────────────
# Not a standalone signal. When detected alongside any coverage_gap_* signal
# on the same entity within 48h, boost signal_strength by this amount.
WESTERN_DISMISSAL_BOOST = 0.18

WESTERN_DISMISSAL_KEYWORDS = [
    "skeptics say", "experts doubt", "unlikely to", "remains to be seen",
    "far behind", "years away", "propaganda", "state media claims",
    "unverified", "analysts question", "overhyped", "copycat",
]
```

The `western_dismissal_signal` implementation: In `article_processor.py`, after scoring an article, check if the article is from a `western_mainstream` source AND contains any `WESTERN_DISMISSAL_KEYWORDS` AND the entity overlaps with a recent `coverage_gap_*` signal entity. If so, add `WESTERN_DISMISSAL_BOOST` to the `signal_strength` score and set a flag `western_dismissal=True` on the analysis row.

---

## Section 4: Track 2 Strategy Thesis

```markdown
# Track 2: Capital Building — Strategy Thesis
## Version 1.0

---

## Strategic Framework

This strategy generates low-risk positive EV returns through two systematic
approaches that require minimal thesis judgment and no geopolitical analysis.
Profits fund Track 1 (Propaganda Arbitrage) position sizes.

**Sub-strategy A — Post-Earnings Announcement Drift (PEAD)**
Long positions after positive earnings surprises, held 3-5 trading days.
One of the most documented anomalies in academic finance. Alpaca executes.

**Sub-strategy B — Prediction Market Base Rate Arbitrage**
Find Kalshi/prediction market contracts where implied probability diverges
from historical base rates. Example: "Will monthly jobs report beat consensus?"
has a known historical beat rate (~60-65%) that is often mispriced.

---

## Edge Hypotheses

### PEAD Edge
1. Institutional rebalancing creates predictable post-earnings drift
2. Retail overreaction to headline numbers fades over 3-5 days
3. Analyst estimate revisions lag actual results by 48-72h

### Base Rate Edge
1. Prediction market participants overweight narrative and underweight
   base rates for recurring events (economic reports, Fed decisions)
2. Geographic access restrictions (PA residents can't use Polymarket)
   create structural liquidity gaps on Kalshi
3. Low-volume contracts on known-outcome-distribution events are
   systematically mispriced because informed participants concentrate
   on high-volume contracts

---

## Signal Categories

### PEAD Signals

| signal_type | Detection | Play | Hold Period |
|---|---|---|---|
| `earnings_beat_large` | EPS surprise > 10% | Long at open next day | 3-5 days |
| `earnings_beat_moderate` | EPS surprise 5-10% | Long at open next day | 3 days |
| `earnings_revenue_beat` | Both EPS + revenue beat | Long (higher conviction) | 5 days |

Data source: Alpaca's earnings calendar + aftermarket price reaction.
No scraping infrastructure needed — pure API.

### Base Rate Signals

| signal_type | Detection | Play | Hold Period |
|---|---|---|---|
| `econ_report_beat_rate` | Known beat rate > 60%, Kalshi YES < 55¢ | Buy YES | Until report release |
| `econ_report_miss_rate` | Known miss rate > 60%, Kalshi NO < 55¢ | Buy NO | Until report release |
| `fed_hold_rate` | Fed Funds futures imply hold > 85%, Kalshi YES < 80¢ | Buy YES | Until FOMC |

---

## Position Sizing & Risk

| Parameter | PEAD | Base Rate |
|---|---|---|
| Default position | 2-3% capital | 3-5% capital |
| Stop-loss | -3% (tight — earnings drift is fast) | N/A (binary outcome) |
| Max concurrent | 5 | 3 |
| Universe | US equities (Alpaca) | Kalshi contracts |

---

## Implementation Notes for pattern_rules.py

PEAD requires NO RSS scraping. It needs:
1. Alpaca earnings calendar API (upcoming earnings dates)
2. Post-earnings price reaction detection (compare close vs open)
3. EPS surprise calculation (requires consensus estimate source)

Simplest MVP: Monitor Alpaca's `corporate_actions` endpoint for earnings
dates, then check next-day gap-up > 3% as a proxy for positive surprise.

Base Rate requires:
1. Historical economic report outcome data (BLS, Fed, Census)
2. Kalshi market discovery for matching contracts
3. Comparison logic: historical_beat_rate vs kalshi_implied_probability
```

This drops into `/strategies/track2-capital/thesis.md` with no schema changes.

### Section 4b: Kalshi Micro-Gains — Addendum (2026-03-07)

The Kalshi micro-gains approach (documented in `kalshi-micro-gains-strategy.md`) is effectively
a **fast-track implementation of Track 2 Sub-strategy B** with one critical difference:
it doesn't require base rate analysis. It's pure probability harvesting — buy near-certain
outcomes close to expiry and collect the spread.

**Why this works as Phase 1:** The math is simple. Buy YES at 90¢, collect $1 at resolution = 11% return in hours. Kalshi fees eat 2-7% depending on volume tier, so net return is 4-9% per trade. At one trade per day with $25 starting capital and 5% net return, you reach $100 in ~28 days through compounding. That's enough to fund meaningful equity positions.

**Why it's currently blocked:** The scanner runs 67 search terms per cycle but surfaces 0 opportunities. After reviewing the filter chain in `_surface_kalshi_market_signals()`:

1. The `yes_threshold=65` means markets at 85%+ YES DO pass — this isn't the blocker
2. The most likely blocker is either (a) search terms not matching available market titles in Kalshi's event-based API, or (b) a field name mismatch in the API response (`yes_price` might be returned differently than expected)
3. The `diagnose_kalshi_filters.py` script tests this definitively by printing raw API responses with all field names

**Implementation path:** The `kalshi_microgains_prompt.md` contains a Claude Code prompt that adds a `micro_gains_mode=True` parameter to the scanner with relaxed thresholds (85%+, 48h window), dedicated search terms for elections/economic data/policy votes, volume checking, and ROI-focused Telegram alerts.

**Critical dependency:** BUG-09 (Kalshi approval → order execution) must be validated before any micro-gains generate real revenue. The approval flow exists in `approval_handler.py` lines 233-288 (`_handle_kalshi_approval`) but has never been exercised. Testing it with a single small-stakes trade ($5-10) on a near-certain market is the validation step.

---

## Section 5: Prioritized Claude Code Prompt Sequence

---

### PROMPT 1 — Fix DECIMAL(3,2) Schema Truncation
**Priority:** Critical — blocks every trade
**Touches:** `app/models/opportunity.py`, MySQL remote schema
**Context for Claude Code:** The `opportunities` table has `stop_loss_pct DECIMAL(3,2)` which truncates values ≥ 10 to 9.99. Same issue on `confluence_score`. Need to fix the model definition AND generate the migration SQL.

---
```
Read app/models/opportunity.py. Two columns have DECIMAL(3,2) which is too small:

1. stop_loss_pct (line 33) — needs DECIMAL(5,2) to hold values like 15.0
2. confluence_score (line 21) — needs DECIMAL(5,2) to hold values up to 100.0 if needed

Make these changes:
- Change both DECIMAL(3,2) to DECIMAL(5,2) in the model file
- Create a new file scripts/migrate_fix_decimals.py that:
  a. Connects to the DB using app.core.database
  b. Runs: ALTER TABLE opportunities MODIFY COLUMN stop_loss_pct DECIMAL(5,2);
  c. Runs: ALTER TABLE opportunities MODIFY COLUMN confluence_score DECIMAL(5,2);
  d. Prints confirmation of each ALTER
  e. Queries one row to verify the change took effect

Also update any existing pending opportunities where stop_loss_pct = 9.99 back to 15.0 (these were Layer B opportunities that got truncated):
  UPDATE opportunities SET stop_loss_pct = 15.0 WHERE stop_loss_pct = 9.99 AND status = 'pending';

Print the count of rows updated.
```
---

### PROMPT 2 — Diagnose and Fix Price Validation Pipeline
**Priority:** Critical — must diagnose before fixing
**Touches:** `scripts/diagnose_price_chain.py` (new), `app/workers/tasks.py`, `app/services/notifications/telegram_notifier.py`
**Context for Claude Code:** The price validation pipeline has a subtle failure mode where exceptions return 0.0, bypassing the $50 cap and creating opportunities without price data. A diagnostic script (included separately as `scripts/diagnose_price_chain.py`) must be run on both machines first. After diagnosis, fix the specific failure point.

---
```
Read app/workers/tasks.py (specifically _get_validated_price around line 256) and app/services/notifications/telegram_notifier.py (lines 138-183).

There are two bugs interacting in the price pipeline:

BUG A — Falsy zero in opportunity dict:
In tasks.py, the opportunity dict does:
    "suggested_price": share_price if share_price and share_price > 0 else None
The problem: _get_validated_price() returns 0.0 for "valid ticker, price unavailable" (lines 313, 323). But 0.0 is falsy in Python so `share_price and share_price > 0` is always False when price is 0.0.

Fix in BOTH locations (around line 681 in _run_strategy_pipeline and line 882 in run_detection_cycle):
    "suggested_price": share_price if share_price is not None and share_price > 0 else None

BUG B — Silent exception swallowing in notifier fallback:
In telegram_notifier.py, the fallback price fetch (lines 143-167) is inside:
    except Exception:
        pass  # remain with simple format if all fetches fail

Change this to log the error at WARNING level:
    except Exception as _price_exc:
        logger.warning("Price fallback failed for %s: %s", ticker, _price_exc)

Also add a note to the flat-amount display path (lines 178-183). After "• Max Loss:" add:
    "\n\n⚠️ <i>Live price unavailable — run REVIEW {opp_id} for updated pricing</i>"

Run the test suite to make sure nothing breaks: pytest tests/ -v
```
---

### PROMPT 3 — Ticker Validation Before Signal Write
**Priority:** High — prevents junk signals polluting the DB
**Touches:** `app/workers/tasks.py` (lines 800-840 in run_detection_cycle)
**Context for Claude Code:** Signal rows are written for raw geographic entities ("Taiwan", "Japan", "South Korea") before ticker validation. These create 100+ junk signal rows per cycle. The validation needs to happen BEFORE _write_signal(), not after.

---
```
Read app/workers/tasks.py, specifically the run_detection_cycle() function (starts around line 693).

There's a signal quality issue: in the gap detection loop (starting ~line 793), _write_signal() is called TWICE:
1. Line ~801: writes a signal for the raw entity (e.g. "Taiwan", "Japan") BEFORE ticker validation
2. Line ~835: writes ANOTHER signal for the resolved primary_ticker AFTER validation

Fix:
1. REMOVE the first _write_signal() call at line ~801 (the one that writes raw entity names as tickers)
2. Keep only the second _write_signal() at line ~835 which uses the validated primary_ticker
3. Add a fast-path ticker validation function at the top of the file:

import re
_US_TICKER_RE = re.compile(r'^[A-Z]{1,5}$')
_BLOCKED_TICKER_STRINGS = frozenset({
    "NONE", "N/A", "UNKNOWN", "GENERAL", "CHINA", "TAIWAN",
    "JAPAN", "KOREA", "US", "USA", "EU", "EUROPE", "INDIA",
    "RUSSIA", "UK", "IRAN", "FRANCE", "GERMANY", "BRITAIN",
})

def _is_plausible_us_ticker(ticker: str) -> bool:
    """Fast check before expensive Alpaca validation."""
    if not ticker:
        return False
    t = ticker.upper()
    if t in _BLOCKED_TICKER_STRINGS:
        return False
    if "." in t:  # exchange-suffixed (005930.KS, 0939.HK)
        return False
    if not _US_TICKER_RE.match(t):
        return False
    return True

4. In both _run_strategy_pipeline() and run_detection_cycle(), after llm.extract_tickers() resolves the primary_ticker, add:
    if not _is_plausible_us_ticker(primary_ticker):
        logger.info("Skipping %s — not a plausible US ticker", primary_ticker)
        continue

This goes BEFORE the _get_validated_price() call to avoid wasting an Alpaca API call on obviously invalid tickers.

Also do the same check in _run_strategy_pipeline() around line 636.

Run tests: pytest tests/ -v
```
---

### PROMPT 4 — Novelty Suppression (72h Keyword Overlap Dedup)
**Priority:** High — stops the 20-identical-TSM-alerts problem
**Touches:** `app/workers/tasks.py`
**Context for Claude Code:** The 24h dedup check prevents same-ticker alerts within 24 hours. But 25 hours later, an identical thesis fires again. Need a 72h similarity check that compares thesis TEXT content, not just ticker + time window.

---
```
Read app/workers/tasks.py. There's a 24h dedup check in run_detection_cycle() around line 856 that prevents the same TICKER from alerting twice in 24h. But it doesn't check if the THESIS is the same — so after 24h expires, an identical thesis fires again.

Add a 72h novelty check based on keyword overlap. Create this helper function:

import re as _re
from collections import Counter

_STOP_WORDS = frozenset({"the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "shall", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "and", "but", "or", "not", "no", "this", "that", "these",
    "those", "it", "its", "their", "our", "your", "his", "her"})

def _thesis_keyword_overlap(new_thesis: str, existing_thesis: str) -> float:
    """Return Jaccard similarity of top keywords between two thesis texts."""
    def _extract_keywords(text: str, top_n: int = 15) -> set[str]:
        words = _re.findall(r'[a-zA-Z]{3,}', text.lower())
        words = [w for w in words if w not in _STOP_WORDS]
        counts = Counter(words)
        return set(w for w, _ in counts.most_common(top_n))

    kw_new = _extract_keywords(new_thesis)
    kw_old = _extract_keywords(existing_thesis)
    if not kw_new or not kw_old:
        return 0.0
    intersection = kw_new & kw_old
    union = kw_new | kw_old
    return len(intersection) / len(union) if union else 0.0

Then in run_detection_cycle(), REPLACE the existing 24h dedup block (around line 856-869) with an expanded version:

    # 72h novelty dedup — skip if we already alerted on this ticker with similar thesis
    with db_session() as db_dedup:
        from app.models import Opportunity as _Opp
        _recent_opps = (
            db_dedup.query(_Opp)
            .filter(
                _Opp.ticker == primary_ticker,
                _Opp.status.in_(["pending", "approved"]),
                _Opp.created_at >= datetime.now(timezone.utc) - timedelta(hours=72),
            )
            .all()
        )
    if _recent_opps:
        # Check if any existing opp has similar thesis content
        max_overlap = max(
            _thesis_keyword_overlap(thesis, (opp.thesis or ""))
            for opp in _recent_opps
        )
        if max_overlap > 0.60:
            logger.info(
                "detection_cycle: suppressing %s — thesis %.0f%% similar to recent opp",
                primary_ticker, max_overlap * 100,
            )
            continue
        logger.debug(
            "detection_cycle: %s has recent opps but thesis is novel (max overlap=%.2f)",
            primary_ticker, max_overlap,
        )

Apply the same change in _run_strategy_pipeline() where the equity opportunity is created (around line 670-688).

Run tests: pytest tests/ -v
```
---

### PROMPT 5 — Source Rebalancing: Add Asian Tech/Business RSS Sources
**Priority:** Medium — improves signal quality
**Touches:** `strategies/propaganda-arbitrage/scraper_config.py`
**Context for Claude Code:** The current source mix has only 2 Asian sources (SCMP, Global Times) vs 6+ Western sources. Iran is detected 2x more than China. Need to add 7 Asian tech/business sources and add a `weight` field for coverage gap weighting.

---
```
Read strategies/propaganda-arbitrage/scraper_config.py.

The current source list has 18 sources but only 2 are alternative_asia (SCMP, Global Times). This causes Middle East content to dominate over Asia/tech content.

Make these changes:

1. Add a "weight" field to every existing source dict. Default weight is 1.0. Set social_media sources (Reddit subs, Google Trends) to weight: 0.5. Set government_official to weight: 1.5.

2. Add these new sources in the alternative_asia section:

{
    "name": "Caixin Global",
    "url": "https://www.caixinglobal.com/rss/",
    "type": "rss",
    "bias": "center",
    "category": "alternative_asia",
    "tags": ["china", "finance", "business", "technology"],
    "priority": 1,
    "weight": 1.5,
},
{
    "name": "Nikkei Asia",
    "url": "https://asia.nikkei.com/rss",
    "type": "rss",
    "bias": "center",
    "category": "alternative_asia",
    "tags": ["japan", "asia", "business", "technology"],
    "priority": 2,
    "weight": 1.5,
},
{
    "name": "Semiconductor Engineering",
    "url": "https://semiengineering.com/feed/",
    "type": "rss",
    "bias": "center",
    "category": "western_tech",
    "tags": ["semiconductor", "chip", "technology"],
    "priority": 2,
    "weight": 1.5,
},
{
    "name": "EE Times Asia",
    "url": "https://www.eetasia.com/feed/",
    "type": "rss",
    "bias": "center",
    "category": "alternative_asia",
    "tags": ["electronics", "semiconductor", "asia"],
    "priority": 2,
    "weight": 1.5,
},
{
    "name": "The Diplomat",
    "url": "https://thediplomat.com/feed/",
    "type": "rss",
    "bias": "center",
    "category": "alternative_asia",
    "tags": ["asia", "geopolitics", "diplomacy"],
    "priority": 3,
    "weight": 1.0,
},
{
    "name": "Korea JoongAng Daily",
    "url": "https://koreajoongangdaily.joins.com/section/rss",
    "type": "rss",
    "bias": "center",
    "category": "alternative_asia",
    "tags": ["korea", "business", "technology"],
    "priority": 3,
    "weight": 1.0,
},
{
    "name": "Taiwan News",
    "url": "https://www.taiwannews.com.tw/en/rss",
    "type": "rss",
    "bias": "center",
    "category": "alternative_asia",
    "tags": ["taiwan", "technology", "business"],
    "priority": 2,
    "weight": 1.5,
},

3. Set existing SCMP and Global Times sources to weight: 1.5
4. Set all 4 Reddit sources and Google Trends to weight: 0.5

This gives you 9 alternative_asia sources (up from 2) with higher weights, which will significantly improve coverage gap detection for Asian tech.

The weight field isn't consumed by PatternDetector yet — that's a separate change. For now just add the field to every source config so it's available when we update the detector.
```
---

### PROMPT 6 — Update PatternDetector to Use Source Weights
**Priority:** Medium — makes gap detection more accurate
**Touches:** `app/services/analysis/pattern_detector.py`, `app/workers/tasks.py`
**Context for Claude Code:** Source configs now have a `weight` field. The PatternDetector's coverage gap analysis should use these weights when counting articles per category, so one Caixin article (weight 1.5) counts more than one Reddit post (weight 0.5).

---
```
Read app/services/analysis/pattern_detector.py, focusing on analyze_coverage_gaps() starting at line 123.

Currently, the gap analysis counts articles per category equally:
    western_count = sum(len(v) for k, v in cat_map.items() if k in _WESTERN_CATEGORIES)
    asia_count = sum(len(v) for k, v in cat_map.items() if k in _ASIA_CATEGORIES)

Articles now carry a "weight" field from scraper_config (default 1.0). Update the counting to use weighted sums:

    western_count = sum(
        sum(a.get("weight", 1.0) for a in v)
        for k, v in cat_map.items() if k in _WESTERN_CATEGORIES
    )
    asia_count = sum(
        sum(a.get("weight", 1.0) for a in v)
        for k, v in cat_map.items() if k in _ASIA_CATEGORIES
    )

Also need to propagate the weight from the source config into each article dict. In tasks.py, where articles are tagged with category (line 557 in _run_strategy_pipeline and line 753 in run_detection_cycle), also include the weight:

    tagged = {**article, "category": category, "weight": source.get("weight", 1.0)}

Run tests: pytest tests/test_pattern_detector.py -v
```
---

### PROMPT 7 — Update pattern_rules.py with Full Thesis Fields
**Priority:** Medium — enables decay tracking and snap-back detection
**Touches:** `strategies/propaganda-arbitrage/pattern_rules.py`
**Context for Claude Code:** The thesis.md defines fields like decay_days, snap_back_keywords, direction, and layer for each signal type. The current pattern_rules.py only has keywords, exclude, tickers, signal_type, and confidence. Need to add the missing fields.

---
```
Read strategies/propaganda-arbitrage/pattern_rules.py.

Replace the entire PATTERN_RULES list with the expanded version below. Each rule now includes all fields specified in thesis.md: decay_days, snap_back_keywords, direction, and layer.

Also add two new module-level constants for the western_dismissal_signal modifier:

WESTERN_DISMISSAL_BOOST: float = 0.18

WESTERN_DISMISSAL_KEYWORDS: list[str] = [
    "skeptics say", "experts doubt", "unlikely to", "remains to be seen",
    "far behind", "years away", "propaganda", "state media claims",
    "unverified", "analysts question", "overhyped", "copycat",
]

Here is the complete replacement for PATTERN_RULES (keep the existing PATTERNS dict unchanged):

Each rule should have these fields: name, description, keywords (list), exclude (list), tickers (list), signal_type, direction (string describing the trade), decay_days (int), confidence (float 0-1), snap_back_keywords (list of exit trigger phrases), layer ("A" or "B").

Add these decay_days and snap_back_keywords to every existing rule:
- sanctions_announcement: decay_days=2, snap_back_keywords=["walked back", "exemption", "waiver", "paused", "delayed implementation"]
- sanctions_relief: decay_days=3, snap_back_keywords=["re-imposed", "conditions not met", "temporary"]
- tariff_increase: decay_days=4, snap_back_keywords=["delayed", "exemption", "negotiating", "paused", "90 day"]
- tariff_reduction: decay_days=4, snap_back_keywords=["reversed", "walked back", "conditions"]
- defence_spending_increase: decay_days=7, snap_back_keywords=["vetoed", "blocked", "reduced from"]
- semiconductor_policy: decay_days=10, snap_back_keywords=["reversed", "exemption granted", "scaled back"]
- energy_supply_disruption: decay_days=3, snap_back_keywords=["resolved", "ceasefire", "supply restored", "strategic reserve release"]
- central_bank_hawkish: decay_days=2, snap_back_keywords=["revised down", "softer than expected", "dovish pivot"]
- central_bank_dovish: decay_days=2, snap_back_keywords=["hawkish surprise", "inflation reaccelerate"]
- regime_change_risk: decay_days=5, snap_back_keywords=["stabilized", "ceasefire", "interim government"]
- pandemic_new_variant: decay_days=5, snap_back_keywords=["contained", "mild", "no evidence of", "preliminary"]

Add layer="A" to all existing rules. Add direction strings matching the signal_type (e.g. "long_defense" for defence_spending_increase).

Also add three Layer B stub rules (with empty keywords, since they're detected by gap ratio not keywords):
- coverage_gap_semiconductor: decay_days=28, tickers=["TSM","INTC","AMAT","KLAC","LRCX"], layer="B"
- coverage_gap_battery_ev: decay_days=42, tickers=["BYDDF","ALB","LAC","SQM","TSLA"], layer="B"
- coverage_gap_renewable: decay_days=42, tickers=["FSLR","ENPH","SEDG","TAN"], layer="B"

Make sure PATTERN_RULES, PATTERNS, WESTERN_DISMISSAL_BOOST, and WESTERN_DISMISSAL_KEYWORDS are all exported at module level.

Run: pytest tests/test_pattern_detector.py -v
```
---

### PROMPT 8 — Expand Kalshi Expiry Window Based on Signal Layer
**Priority:** Medium — lets the system find structural prediction market opportunities
**Touches:** `app/workers/tasks.py` (lines 1318-1327)
**Context for Claude Code:** Kalshi market scanning currently filters out any market expiring more than 7 days out. This is correct for Layer A signals (fast decay) but wrong for Layer B (slow decay, 2-8 weeks). The Taiwan travel advisory signal was only found because the user manually directed the system to look wider.

---
```
Read app/workers/tasks.py, specifically the _surface_kalshi_market_signals() function starting around line 1225.

The hardcoded 7-day expiry filter at line ~1324:
    if days_out > 7 or days_out < 0:
        continue

needs to become context-aware. The search terms come from two sources:
1. Static _KALSHI_SIGNAL_CATEGORIES — these are general scans, keep 7-day default
2. DB-approved terms from kalshi_categories — these may relate to Layer B signals

Change the function signature to accept an optional max_days parameter:

def _surface_kalshi_market_signals(
    strategy_id: int | None,
    notifier,
    llm,
    yes_threshold: int = 65,
    max_days: int = 7,
) -> int:

Then replace the hardcoded check with:
    if days_out > max_days or days_out < 0:
        continue

In run_detection_cycle(), call it twice:
1. First call with default max_days=7 (Layer A / general scan)
2. Second call with max_days=90, using only Taiwan-specific and semiconductor-specific search terms (Layer B structural opportunities)

For the second call, filter search_terms to only include terms from the "taiwan" and "tech_policy" categories in _KALSHI_SIGNAL_CATEGORIES, plus any approved DB terms with category="geopolitical" or "tech_policy".

Run tests: pytest tests/ -v
```
---

## Section 6: One Thing You Haven't Thought Of

**The feedback loop between approved/rejected opportunities and the LLM scoring prompt is the missing compounding mechanism.**

You have 371 opportunities, all pending. When you start approving and rejecting them, you'll build the most valuable dataset in the system: **your judgment encoded as labels on LLM-generated theses**. But nothing currently uses this data to improve future output.

Here's the gap: the `article_processor.py` uses the same static `ANALYSIS_PROMPT_TEMPLATE` and `ANALYSIS_SCHEMA` from `llm_config.py` for every article, every cycle, forever. The LLM scores relevance 0-1, sentiment -1 to +1, signal_strength 0-1 — but it never learns which scores lead to approved vs rejected opportunities.

**What to build:** A nightly job that:

1. Pulls all `approved` and `rejected` opportunities from the last 30 days
2. Joins back to the article_analysis rows that generated those signals (via the signal → article chain)
3. Computes: for approved opps, what was the average `relevance_score`, `signal_strength`, `sentiment_score` of the source articles? For rejected opps?
4. Generates a **calibration prompt addendum** that gets prepended to the `ANALYSIS_PROMPT_TEMPLATE`:

```
Based on recent human review:
- Approved opportunities had average signal_strength 0.62 and relevance 0.45
- Rejected opportunities had average signal_strength 0.31 and relevance 0.18
- The most common reason for rejection was: non-actionable / no clear trade
Calibrate your scores accordingly. A signal_strength below 0.3 is almost never approved.
```

This is a 50-line script. It doesn't require ML. It doesn't require embeddings. It's just statistical feedback from your approve/reject decisions injected into the LLM prompt — and it compounds every week as your decision history grows.

The second gap: **you have no way to track outcomes of approved trades back to the signals that generated them.** The `trades` table has `opportunity_id` which links to `opportunities`, but `opportunities` doesn't link back to `signals` (the signal is written separately in `_write_signal()` with no FK back to the opportunity). Add a `signal_id` column to `opportunities` so you can trace: signal → opportunity → trade → return. This closes the loop and lets you answer "which signal types produce profitable trades?" — the single most important question for the system's long-term edge.

Neither of these is hard. Both compound over time. Both are invisible because the system has never executed a trade, so the feedback path has never been exercised. The moment you start approving trades, this becomes the highest-value work in the system.
