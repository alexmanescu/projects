# Propaganda Arbitrage — Strategy Thesis

## Core Idea

Governments, central banks, and geopolitical actors release official communications
(press releases, sanctions notices, budget announcements, treaty signings) that are
systematically under-priced by retail markets for a short window after publication.

The **Propaganda Arbitrage Engine** monitors these sources continuously, detects
language patterns that have historically preceded predictable market moves, and
generates time-sensitive trade signals before consensus sentiment catches up.

---

## Edge Hypothesis

1. **Information asymmetry window** — bureaucratic press releases are published on
   government websites before major financial media aggregators re-publish them,
   creating a 15–90 minute alpha window.

2. **Sentiment anchoring** — official language uses consistent phrasing across
   administrations; pattern-matching on known phrases (e.g. *"executive order"*,
   *"export control"*, *"defence supplemental"*) is more reliable than free-form NLP.

3. **Forced allocation** — certain events (e.g. new OFAC sanctions lists) create
   mandatory sell pressure on regulated holders, creating predictable near-term price
   dislocations regardless of fundamental value.

---

## Signal Categories

| Category | Example Trigger | Typical Play |
|---|---|---|
| Sanctions | OFAC designates new entities | Short affected sector; long USD |
| Tariffs | USTR announces Section 301 tariffs | Short import-heavy retail |
| Defence | Pentagon supplemental budget | Long LMT / RTX / NOC |
| Energy Disruption | Pipeline attack / OPEC cut | Long USO / XOM |
| Rate Policy | FOMC statement hawkish pivot | Short TLT; long USD |
| Political Instability | Coup in commodity-rich country | Long GLD / SLV |

---

## Position Sizing & Risk

- Default position: **1–3% of total capital** per trade
- Stop-loss: **–5%** from entry (tightened to –3% for low-confidence signals)
- Target hold: **1–10 days** (event-driven, not momentum)
- Maximum concurrent open positions: **5**
- Universe: US-listed equities + ETFs (Alpaca); no options initially

---

## Known Limitations

- Government RSS feeds can lag the actual posting by minutes
- Sanctions language is complex; false positives on "sanctions relief" are common
- Geopolitical events often produce short-lived gaps that snap back within 24h
- Model confidence is calibrated on historical analogues, not real-time validation

---

## Development Roadmap

- [ ] RSS scraper + dedup pipeline
- [ ] Pattern rule matching (keyword + LLM hybrid)
- [ ] Signal → Opportunity scoring
- [ ] Telegram alert + manual approval flow
- [ ] Alpaca paper trading integration
- [ ] Backtesting harness on historical signals
- [ ] Prediction market correlation (Kalshi)
