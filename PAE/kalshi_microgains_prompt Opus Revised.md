# Kalshi Micro-Gains: Diagnostic + Implementation Prompt
# Give this to Claude Code as-is

## DIAGNOSTIC FIRST — Run Before Any Code Changes

Drop this into `scripts/diagnose_kalshi_filters.py` and run it:

```python
"""Kalshi filter diagnostic — traces every step to find where markets are being dropped."""
import sys, os, json, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.services.trading.kalshi_interface import KalshiInterface, KalshiError

print("=" * 70)
print("KALSHI FILTER DIAGNOSTIC")
print("=" * 70)

# Step 1: Can we connect?
print("\n[1/5] Kalshi connection")
try:
    kalshi = KalshiInterface()
    print(f"  ✅ Connected (base_url={settings.kalshi_base_url})")
    print(f"  API key: {'SET' if settings.kalshi_api_key else '❌ EMPTY'}")
    print(f"  KALSHI_LIVE: {settings.kalshi_live}")
    print(f"  DRY_RUN: {settings.dry_run}")
except Exception as exc:
    print(f"  ❌ FAILED: {exc}")
    sys.exit(1)

# Step 2: What does a raw search return?
print("\n[2/5] Raw API response for 'election' search")
try:
    markets = kalshi.find_markets("election", limit=20)
    print(f"  Returned {len(markets)} markets")
    for i, m in enumerate(markets[:5]):
        print(f"\n  Market {i+1}:")
        print(f"    ticker:     {m.get('ticker', 'MISSING')}")
        print(f"    title:      {m.get('title', 'MISSING')[:80]}")
        print(f"    yes_price:  {m.get('yes_price', 'MISSING')} (type: {type(m.get('yes_price')).__name__})")
        print(f"    category:   {m.get('category', m.get('event_category', 'MISSING'))}")
        print(f"    close_time: {m.get('close_time', m.get('expiration_time', 'MISSING'))}")
        print(f"    status:     {m.get('status', 'MISSING')}")
        # Print ALL keys so we can see the actual field names
        print(f"    all_keys:   {sorted(m.keys())}")
except Exception as exc:
    print(f"  ❌ Search failed: {exc}")

# Step 3: Test specific TX election terms
print("\n[3/5] Searching for TX election markets specifically")
for term in ["Texas", "TX primary", "Republican nominee", "TX-19", "primary election"]:
    time.sleep(1.5)  # rate limit
    try:
        results = kalshi.find_markets(term, limit=10)
        high_prob = [m for m in results if int(m.get("yes_price", 50)) >= 85 or int(m.get("yes_price", 50)) <= 15]
        print(f"  '{term}': {len(results)} total, {len(high_prob)} at 85%+")
        for m in high_prob[:2]:
            print(f"    → {m.get('ticker')} YES={m.get('yes_price')} '{m.get('title','')[:60]}'")
    except Exception as exc:
        print(f"  '{term}': ❌ {exc}")

# Step 4: Simulate the filter chain on raw results
print("\n[4/5] Filter chain simulation on 'election' results")
try:
    markets = kalshi.find_markets("election", limit=50)
    
    _YES_THRESHOLD = 65  # current production value
    _SPORT_BLOCKED = ("sport", "entertainment", "pop culture", "award",
                      "nba", "nfl", "nhl", "mlb", "nascar", "golf")
    _SPORT_TITLE_KW = ("points", "rebounds", "assists", "touchdowns", "goals",
                       "james", "lebron", "westbrook", "curry", "mahomes")
    
    for m in markets[:10]:
        ticker = m.get("ticker") or m.get("market_ticker", "")
        yes_price = int(m.get("yes_price", 50))
        no_price = 100 - yes_price
        title = (m.get("title") or "")[:60]
        category = (m.get("category") or m.get("event_category") or "").lower()
        close_time = m.get("close_time") or m.get("expiration_time") or ""
        
        # Run each filter and show where it dies
        filters_passed = []
        filters_failed = []
        
        # Threshold check
        if yes_price >= _YES_THRESHOLD or yes_price <= (100 - _YES_THRESHOLD):
            filters_passed.append(f"threshold (YES={yes_price})")
        else:
            filters_failed.append(f"threshold (YES={yes_price}, need >={_YES_THRESHOLD} or <={100-_YES_THRESHOLD})")
        
        # Category check
        if any(b in category for b in _SPORT_BLOCKED):
            filters_failed.append(f"category_block ({category})")
        else:
            filters_passed.append(f"category ({category or 'empty'})")
        
        # Ticker prefix check
        if "crosscategory" in ticker.lower() or ticker.upper().startswith("KXMVE"):
            filters_failed.append(f"ticker_block ({ticker})")
        else:
            filters_passed.append(f"ticker ({ticker})")
        
        # Expiry check
        if close_time:
            try:
                close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                days_out = (close_dt - datetime.now(timezone.utc)).days
                hours_out = (close_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                if days_out > 7 or days_out < 0:
                    filters_failed.append(f"expiry ({days_out}d / {hours_out:.1f}h out)")
                else:
                    filters_passed.append(f"expiry ({hours_out:.1f}h out)")
            except:
                filters_passed.append("expiry (unparseable — allowed through)")
        else:
            filters_passed.append("expiry (no close_time)")
        
        status = "✅ WOULD SURFACE" if not filters_failed else "❌ FILTERED OUT"
        print(f"\n  {status}: {ticker} YES={yes_price}¢ '{title}'")
        if filters_passed:
            print(f"    Passed: {', '.join(filters_passed)}")
        if filters_failed:
            print(f"    BLOCKED: {', '.join(filters_failed)}")
            
except Exception as exc:
    print(f"  ❌ Simulation failed: {exc}")

# Step 5: What would micro-gains look like?
print("\n[5/5] Micro-gains candidates (85%+ YES, <48h expiry)")
print("  Scanning all search terms from _KALSHI_SIGNAL_CATEGORIES...")
from app.workers.tasks import _KALSHI_SIGNAL_CATEGORIES
all_terms = []
for terms in _KALSHI_SIGNAL_CATEGORIES.values():
    all_terms.extend(terms)
# Add election-specific terms
all_terms.extend(["Texas primary", "Republican nominee", "Democratic nominee"])

seen = set()
candidates = []
for term in all_terms[:20]:  # cap to avoid rate limits
    time.sleep(1.5)
    try:
        markets = kalshi.find_markets(term, limit=20)
        for m in markets:
            ticker = m.get("ticker", "")
            if ticker in seen:
                continue
            seen.add(ticker)
            yes_price = int(m.get("yes_price", 50))
            if yes_price < 85 and yes_price > 15:
                continue
            close_time = m.get("close_time") or m.get("expiration_time") or ""
            if close_time:
                try:
                    close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                    hours_out = (close_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                    if hours_out > 48 or hours_out < 0:
                        continue
                except:
                    continue
            side = "YES" if yes_price >= 85 else "NO"
            price = yes_price if side == "YES" else (100 - yes_price)
            roi = round((100 - price) / price * 100, 1)
            candidates.append({
                "ticker": ticker,
                "title": (m.get("title") or "")[:60],
                "side": side,
                "price": price,
                "roi": roi,
                "hours": round(hours_out, 1) if close_time else "?",
            })
    except:
        continue

candidates.sort(key=lambda c: (c["hours"] if isinstance(c["hours"], float) else 999))
print(f"\n  Found {len(candidates)} micro-gain candidates:\n")
for c in candidates[:15]:
    print(f"  {c['side']} {c['ticker']}")
    print(f"    {c['title']}")
    print(f"    {c['price']}¢ → ${1:.2f} payout = {c['roi']}% ROI in {c['hours']}h\n")

if not candidates:
    print("  ⚠️  No candidates found. This means either:")
    print("  a) No 85%+ markets exist with <48h expiry right now")
    print("  b) The search terms aren't matching available markets")
    print("  c) The Kalshi API response format doesn't match field names in the code")
    print("\n  Check the raw API response in Step 2 above — especially yes_price type and field names.")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
```

---

## IMPLEMENTATION PROMPT — Give to Claude Code After Diagnostic

```
Read the Kalshi micro-gains strategy doc at kalshi-micro-gains-strategy.md in the PAE root.
Also read the diagnostic output from scripts/diagnose_kalshi_filters.py (run it first if not yet run).
Also read app/workers/tasks.py focusing on _surface_kalshi_market_signals() starting around line 1225.

The goal: make PAE surface high-probability Kalshi markets (85%+ YES or 15%- YES) expiring within 48 hours as micro-gain opportunities. These are the immediate revenue path while the equity pipeline matures.

Current problem: The scanner runs 67 search terms but surfaces 0 opportunities. The filters are too aggressive.

Make these changes to _surface_kalshi_market_signals():

1. ADD a new parameter `micro_gains_mode: bool = False` to the function signature.

2. When micro_gains_mode=True, use these relaxed settings:
   - yes_threshold = 85 (surface markets at 85%+ YES or 15%- YES)
   - max_days = 2 (48h expiry window — we want markets resolving SOON)
   - Skip the LLM thesis generation for micro-gains (waste of tokens on near-certain outcomes). Use a simple template instead:
     f"Micro-gain: {side} @ {contract_price}¢ → ${1:.2f} payout ({roi:.1f}% ROI). Expires in {hours_out:.0f}h."
   - DO still run sports/entertainment category filter
   - DO still run 24h dedup
   - ADD a volume check: skip markets where the volume field (check actual field name from API response) is below 1000

3. When micro_gains_mode=False (default), keep existing behavior unchanged.

4. In run_detection_cycle(), add a THIRD call to _surface_kalshi_market_signals after the existing Layer A and Layer B calls:
   # ── Micro-gains: high-probability near-expiry markets ──────────────
   if not _is_worker_paused("detect_kalshi"):
       micro_gains = _surface_kalshi_market_signals(
           strategy_id=strategy_id,
           notifier=notifier,
           llm=llm,
           yes_threshold=85,
           max_days=2,
           micro_gains_mode=True,
       )
       counts["opportunities_sent"] += micro_gains

5. ADD search terms specifically for micro-gains. These should cover categories that frequently have near-certain outcomes close to expiry:
   _MICRO_GAINS_SEARCH_TERMS = [
       "election", "primary", "nominee", "runoff",
       "Fed rate", "FOMC", "jobs report", "CPI",
       "government shutdown", "debt ceiling",
       "Supreme Court", "confirmation",
   ]
   When micro_gains_mode=True, use _MICRO_GAINS_SEARCH_TERMS INSTEAD of _KALSHI_SIGNAL_CATEGORIES.

6. In the Telegram alert for micro-gains opportunities, add the expiry countdown prominently:
   f"⏰ Expires in {hours_out:.0f}h"
   And the ROI calculation:
   f"💰 ROI: {roi:.1f}% on resolution"

7. Tag micro-gains opportunities differently so they can be tracked separately:
   Set topic="kalshi_micro_gain" (instead of "kalshi_high_prob") in the opportunity dict.
   This lets you query Kalshi micro-gain P&L separately from thesis-driven Kalshi plays.

Run tests: pytest tests/ -v

After making changes, also add a note to pending-bugfix.md that BUG-09 (Kalshi approval flow) is now the critical path blocker — it must be tested end-to-end before micro-gains can generate real returns.
```
