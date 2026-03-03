# PAE — Proposed Changes

Ideas captured during development for future implementation.

---

## Configuration

### Separate scrape / detect interval settings
Currently `CHECK_INTERVAL_MINUTES` controls both workers with one value.
Split into two settings so each machine can be tuned independently:
- `SCRAPE_INTERVAL_MINUTES` (Mac) — default 60; limited by Ollama LLM throughput
- `DETECT_INTERVAL_MINUTES` (Windows) — default 30; fast RSS + pattern match, can run more frequently

---

## Signal Quality

### Signal accumulation / conviction building
Currently a gap detected once triggers an immediate alert. Instead, track signal persistence across cycles:
- First detection: log internally as "tracking", no alert yet
- 2nd consecutive cycle: surface with "building" confidence label
- 3rd+ cycle or Kalshi confluence present: alert as "confirmed"
- Add `hit_count` + `first_detected_at` + `last_detected_at` to `Opportunity`
- Separate threshold for Kalshi contract signals (price stability across cycles is stronger signal)

---

## Funding / Accounts

### Coinbase integration for funding pipeline
User has a Coinbase account to act as a funding source for trading accounts.
Future: automate transfer flow from Coinbase → Alpaca / Kalshi as a separate controlled process.
Keep entirely separate from trade execution; require explicit manual trigger or its own flag.

---

## Data Sources

### RSS / scraper source expansion
Add more Asian-language and alternative sources to widen the coverage gap detection surface.
Priority: wire/agency feeds from Xinhua, TASS, Al Jazeera, Nikkei Asia.

---
