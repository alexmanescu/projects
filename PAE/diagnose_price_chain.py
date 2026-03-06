# PAE Price Validation Diagnostic
# Run this on BOTH machines (Mac Mini and Windows Alienware)
# from inside the PAE project directory with the venv activated:
#
#   python scripts/diagnose_price_chain.py
#
# This will trace every step of the price validation pipeline
# and identify exactly where it breaks.

import sys
import os

# Ensure we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 70)
print("PAE PRICE VALIDATION DIAGNOSTIC")
print("=" * 70)

# ── Step 1: Which Python are we running? ──────────────────────────────
print("\n[1/8] Python environment")
print(f"  Executable: {sys.executable}")
print(f"  Version:    {sys.version}")
print(f"  Prefix:     {sys.prefix}")
print(f"  In venv:    {sys.prefix != sys.base_prefix}")

# ── Step 2: Can we import alpaca-py? ──────────────────────────────────
print("\n[2/8] alpaca-py import check")
try:
    import alpaca
    print(f"  ✅ alpaca package found: {alpaca.__file__}")
    print(f"  Version: {getattr(alpaca, '__version__', 'unknown')}")
except ImportError as exc:
    print(f"  ❌ FAILED: {exc}")
    print("  → This is the blocker. pip install alpaca-py in THIS venv:")
    print(f"    {sys.executable} -m pip install alpaca-py")
    sys.exit(1)

try:
    from alpaca.trading.client import TradingClient
    print("  ✅ TradingClient importable")
except ImportError as exc:
    print(f"  ❌ TradingClient import failed: {exc}")

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    print("  ✅ StockHistoricalDataClient + requests importable")
except ImportError as exc:
    print(f"  ❌ Data client import failed: {exc}")
    sys.exit(1)

# ── Step 3: Can we load PAE settings? ─────────────────────────────────
print("\n[3/8] PAE settings")
try:
    from app.core.config import settings
    print(f"  alpaca_api_key:    {'SET (' + settings.alpaca_api_key[:8] + '...)' if settings.alpaca_api_key else '❌ EMPTY'}")
    print(f"  alpaca_secret_key: {'SET (' + settings.alpaca_secret_key[:8] + '...)' if settings.alpaca_secret_key else '❌ EMPTY'}")
    print(f"  paper_trading:     {settings.paper_trading}")
    print(f"  dry_run:           {settings.dry_run}")
    print(f"  max_share_price:   ${settings.max_share_price}")
    print(f"  alpaca_base_url:   {settings.alpaca_base_url}")
except Exception as exc:
    print(f"  ❌ Settings load failed: {exc}")
    sys.exit(1)

# ── Step 4: Can we connect to Alpaca at all? ──────────────────────────
print("\n[4/8] Alpaca TradingClient connection")
try:
    client = TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        paper=settings.paper_trading,
    )
    acct = client.get_account()
    print(f"  ✅ Connected to Alpaca")
    print(f"  Account: {acct.account_number}")
    print(f"  Equity:  ${float(acct.equity):,.2f}")
    print(f"  Cash:    ${float(acct.cash):,.2f}")
    print(f"  Status:  {acct.status}")
except Exception as exc:
    print(f"  ❌ FAILED: {exc}")
    print("  → Check API keys and network connectivity")

# ── Step 5: Can we fetch price data? ──────────────────────────────────
print("\n[5/8] Alpaca StockHistoricalDataClient — price fetches")
data_client = StockHistoricalDataClient(
    api_key=settings.alpaca_api_key,
    secret_key=settings.alpaca_secret_key,
)

test_tickers = ["AAPL", "TSM", "NVDA", "INTC", "SOXL", "SOXS"]
for ticker in test_tickers:
    print(f"\n  Testing {ticker}:")

    # Method A: StockLatestTradeRequest
    try:
        trades = data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=ticker)
        )
        price = float(trades[ticker].price)
        cap_status = "BLOCKED by $50 cap" if price > settings.max_share_price else "PASSES cap"
        print(f"    LatestTrade: ${price:,.2f} — {cap_status}")
    except Exception as exc:
        print(f"    LatestTrade: ❌ {type(exc).__name__}: {exc}")

    # Method B: StockBarsRequest (free tier fallback)
    try:
        bars = data_client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            limit=1,
        ))
        bar_list = bars.get(ticker) if bars else None
        if bar_list:
            price = float(bar_list[-1].close)
            cap_status = "BLOCKED by $50 cap" if price > settings.max_share_price else "PASSES cap"
            print(f"    DailyBar:    ${price:,.2f} — {cap_status}")
        else:
            print(f"    DailyBar:    ❌ No bars returned")
    except Exception as exc:
        print(f"    DailyBar:    ❌ {type(exc).__name__}: {exc}")

# ── Step 6: Test the actual _get_validated_price function ─────────────
print("\n[6/8] Testing _get_validated_price() from tasks.py")
try:
    from app.workers.tasks import _get_validated_price
    for ticker in test_tickers:
        result = _get_validated_price(ticker)
        if result is None:
            print(f"  {ticker}: None (WOULD BE SKIPPED — no opportunity created)")
        elif result == 0.0:
            print(f"  {ticker}: 0.0 (PRICE UNAVAILABLE — opp created WITHOUT price)")
        else:
            print(f"  {ticker}: ${result:,.2f} (opp created WITH price)")
except Exception as exc:
    print(f"  ❌ Could not test _get_validated_price: {exc}")

# ── Step 7: What tickers would actually survive the full pipeline? ────
print("\n[7/8] Which tickers from your thesis actually pass all filters?")
thesis_tickers = [
    "TSM", "NVDA", "AMD", "INTC", "AMAT", "KLAC", "LRCX",  # semis
    "LMT", "RTX", "NOC", "GD", "BA",  # defense
    "XOM", "CVX", "COP", "USO",  # energy
    "GLD", "SLV",  # safe havens
    "MRNA", "PFE",  # pharma
    "SPY", "QQQ", "TLT",  # indices/bonds
    "WMT", "AMZN", "COST", "TGT", "NKE",  # retail
    "SOXL", "SOXS", "XLE", "TAN",  # ETFs
]

passes = []
blocked = []
errors = []

for ticker in thesis_tickers:
    try:
        result = _get_validated_price(ticker)
        if result is None:
            blocked.append(f"  {ticker}: BLOCKED (None)")
        elif result == 0.0:
            errors.append(f"  {ticker}: PRICE UNAVAILABLE (0.0)")
        elif result > settings.max_share_price:
            blocked.append(f"  {ticker}: BLOCKED @ ${result:,.2f} (> ${settings.max_share_price})")
        else:
            passes.append(f"  {ticker}: ✅ ${result:,.2f}")
    except Exception as exc:
        errors.append(f"  {ticker}: ERROR — {exc}")

print(f"\n  PASSES ($50 cap) — {len(passes)} tickers:")
for line in passes:
    print(line)
print(f"\n  BLOCKED by cap — {len(blocked)} tickers:")
for line in blocked:
    print(line)
print(f"\n  ERRORS / PRICE UNAVAILABLE — {len(errors)} tickers:")
for line in errors:
    print(line)

# ── Step 8: Summary ───────────────────────────────────────────────────
print("\n" + "=" * 70)
print("DIAGNOSIS SUMMARY")
print("=" * 70)

if passes:
    print(f"\n✅ {len(passes)} tickers pass all filters and would generate")
    print(f"   opportunities WITH share price data.")
elif blocked and not errors:
    print(f"\n⚠️  ALL thesis tickers are above the $50 cap.")
    print(f"   This means equity opportunities CAN'T include price data.")
    print(f"   Options:")
    print(f"   a) Raise MAX_SHARE_PRICE in .env (e.g. 500)")
    print(f"   b) Add lower-priced ETFs to pattern_rules.py tickers")
    print(f"      (SOXL ~$20, SOXS ~$20, TAN ~$40, XLE ~$45)")
    print(f"   c) Set MAX_SHARE_PRICE=0 to disable the cap entirely")
elif errors:
    print(f"\n❌ Price API is failing for {len(errors)} tickers.")
    print(f"   This means _get_validated_price returns 0.0, which")
    print(f"   BYPASSES the $50 cap, and opportunities are created")
    print(f"   WITHOUT price data (flat dollar display).")
    print(f"   Fix: resolve the Alpaca data API issue above.")

print(f"\n   Current MAX_SHARE_PRICE: ${settings.max_share_price}")
print(f"   Tickers in thesis universe: {len(thesis_tickers)}")
print(f"   Would pass:   {len(passes)}")
print(f"   Would block:  {len(blocked)}")
print(f"   Price errors:  {len(errors)}")
print()
