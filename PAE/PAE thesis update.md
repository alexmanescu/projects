# Propaganda Arbitrage — Strategy Thesis
## Version 2.0

---

## Strategic Framework

Markets misprice assets when the information available to participants is systematically
distorted — either by **speed** (official information exists but hasn't propagated yet)
or by **ideology** (information exists but consensus narrative filters it out).

This engine exploits both distortion types simultaneously via two complementary signal
layers operating at different time horizons.

**Layer A — Government Communication Arbitrage** (minutes to days)
Official communications from governments, central banks, and regulatory bodies are
published before financial media aggregators repick them up. Bureaucratic language is
formulaic and learnable. Certain event types create predictable, mechanistic market
responses independent of fundamental value.

**Layer B — Coverage Gap Arbitrage** (days to weeks)
Western mainstream media systematically underreports or dismissively frames
technological, industrial, and geopolitical developments in countries that challenge
US/EU hegemony — primarily China. This creates persistent mispricings in related
securities that correct only when Western consensus narrative catches up to material
reality. A 6-year manual track record validates this edge across semiconductors,
batteries, and renewable energy sectors.

**Confluence** — when both layers independently flag the same ticker within a 48-hour
window, position size is boosted and signal confidence is elevated. A Pentagon
supplemental budget announcement (Layer A) coinciding with an Asian coverage gap on a
defence contractor (Layer B) is a stronger signal than either generates alone.

---

## Edge Hypotheses

### Layer A Edges

1. **Publication timing gap** — government press releases appear on official websites
   15–90 minutes before major financial aggregators republish them. This window is
   shrinking but remains exploitable with direct RSS monitoring of primary sources.

2. **Sentiment anchoring** — official language is formulaic across administrations.
   Pattern-matching on known trigger phrases is more reliable than free-form NLP
   because the language is deliberately standardised. *"Executive order"*, *"export
   control"*, *"section 301"*, *"OFAC designates"* have consistent downstream effects.

3. **Forced allocation** — OFAC sanctions, export control lists, and similar regulatory
   actions create mandatory sell pressure on regulated institutional holders regardless
   of their view on fundamental value. This mechanical selling creates predictable
   dislocations that are not thesis-dependent.

### Layer B Edges

1. **Ideological filtering** — Western financial media applies a motivated skepticism
   to Chinese industrial and technological achievements that creates systematic lag
   between material reality and Western consensus narrative. The gap between SCMP
   coverage and Reuters coverage of the same event is a measurable signal.

2. **Superstructure lag** — political and media narrative (superstructure) consistently
   lags material conditions (base layer). Government subsidies, manufacturing capacity
   milestones, and supply chain shifts are observable facts that Western narrative
   resists incorporating until they become undeniable. The window between observable
   and undeniable is where the trade lives.

3. **Irrational coalition risk as hedge indicator** — motivated political actors can
   sustain irrational narratives longer than fundamentals justify and can force policy
   outcomes (tariffs, sanctions, export controls) that temporarily override material
   reality. This risk is not a reason to avoid the trade — it is a stop-loss calibration
   input. The wider the ideological resistance to acknowledging a development, the
   larger the eventual correction and the more important the exit discipline.

---

## Signal Categories

### Layer A — Government Communication Signals

These map directly to `pattern_rules.py` keyword sets.

| signal_type | Example Trigger | Typical Play | Decay Window | Snap-back Risk |
|---|---|---|---|---|
| `sanctions_announcement` | OFAC designates new entities | Short affected sector; long USD | 1–3 days | Medium — relief rallies common |
| `tariff_increase` | USTR announces Section 301 | Short import-heavy retail; long domestic producers | 2–5 days | High — implementation often delayed |
| `tariff_reduction` | USTR removes or pauses tariffs | Long import-dependent sector | 2–5 days | Medium |
| `defence_budget` | Pentagon supplemental / NDAA line items | Long LMT / RTX / NOC / GD | 3–10 days | Low — budget cycles are slow |
| `energy_supply_disruption` | Pipeline attack / OPEC cut announcement | Long USO / XOM / CVX | 1–5 days | High — supply disruptions often resolve |
| `rate_policy_hawkish` | FOMC hawkish pivot language | Short TLT; long USD; short growth | 1–3 days | Medium |
| `rate_policy_dovish` | FOMC dovish pivot or pause signal | Long TLT; long growth; short USD | 1–3 days | Medium |
| `regime_change_risk` | Coup / contested election in commodity country | Long GLD / SLV / commodity ETFs | 2–7 days | High — political situations fluid |
| `semiconductor_policy` | Export control on chips / equipment | Long domestic fabs; short affected names | 5–15 days | Low — policy changes are sticky |
| `pandemic_new_variant` | WHO or CDC emergency language | Long MRNA / PFE; short travel/hospitality | 3–7 days | High — early variant signals often downgraded |
| `central_bank_intervention` | Emergency rate action / currency intervention | Direction depends on currency pair | 1–2 days | Very high — interventions often reverse |

### Layer B — Coverage Gap Signals

These map to coverage ratio analysis between Asian/alternative and Western sources.

| signal_type | Detection Method | Typical Play | Decay Window | Snap-back Risk |
|---|---|---|---|---|
| `coverage_gap_semiconductor` | Asia articles >> Western on fab milestone / funding | Long SMIC / CXMT proxies; long upstream equipment | 2–6 weeks | Medium — narrative shift is gradual |
| `coverage_gap_battery_ev` | Asia articles >> Western on capacity / chemistry breakthrough | Long CATL / BYD proxies; long lithium supply chain | 2–8 weeks | Low — physical capacity is hard to deny |
| `coverage_gap_renewable` | Asia articles >> Western on solar / grid deployment scale | Long Chinese solar names; long polysilicon | 3–8 weeks | Low — installation data is verifiable |
| `coverage_gap_telecom` | Asia articles >> Western on 5G / infrastructure deployment | Long Huawei supply chain proxies | 2–6 weeks | Medium |
| `coverage_gap_rare_earth` | Asia articles >> Western on processing capacity / new deposits | Long MP Materials; long rare earth ETFs | 4–12 weeks | Low — supply chain shifts are structural |
| `western_dismissal_signal` | High Asian coverage + active Western skepticism / mockery | Strengthens Layer B signal — wider gap = larger correction | Extends decay | Reduces snap-back risk — deeper denial = harder correction |

---

## Signal Decay Model

This is the exit logic layer. Each signal type has a characteristic decay pattern.
The system should track signal age and degrade confidence over time.

### Decay Categories

**Fast decay (1–3 days)** — `sanctions_announcement`, `rate_policy_*`,
`central_bank_intervention`
These move fast and snap back fast. Exit at first sign of reversal or at 72h
regardless of P/L if thesis note is not confirmed by follow-on coverage.

**Medium decay (3–10 days)** — `tariff_*`, `energy_supply_disruption`,
`regime_change_risk`, `pandemic_new_variant`
Hold through initial volatility but watch for policy walk-back language.
Exit trigger: official source contradicts or softens original statement.

**Slow decay (1–8 weeks)** — `defence_budget`, `semiconductor_policy`,
all `coverage_gap_*` signals
These are structural. Hold until Western narrative catches up to Asian coverage
or until material conditions change. Exit trigger: Reuters / Bloomberg begin
running the same story SCMP ran — that is the convergence signal, not a reason
to hold longer.

### Early Exit Triggers (override decay window)

- Official source issues correction, clarification, or reversal
- Western coverage of Layer B topic suddenly spikes (narrative convergence = exit)
- Confluence score drops below 0.5 (other strategies no longer corroborating)
- Price approaches stop-loss before thesis confirms
- `western_dismissal_signal` reverses to neutral or positive framing

### Snap-back Detection Keywords

Monitor for these phrases in follow-on coverage as exit signals:

```
"walked back", "clarified", "exemption", "waiver", "paused",
"delayed implementation", "relief", "de-escalation", "sources say",
"officials later said", "revised down", "preliminary reports suggested"
```

---

## Kalshi / Prediction Market Integration

Prediction market odds are a **leading indicator layer**, not a separate strategy.

Polymarket and Kalshi odds on geopolitical events often move before price does because
prediction market participants skew toward informed, fast-moving actors. Use them as:

1. **Signal confirmation** — if a Layer A signal fires and Kalshi odds on the related
   event are already pricing high probability, the signal is stronger and decay window
   is shorter (market is ahead of you).

2. **Signal discovery** — monitor for Kalshi markets with wide spreads on
   near-certain outcomes. Wide spread = someone is wrong. Cross-reference against
   Layer B coverage gaps to find cases where prediction market is mispriced because
   Western participants are filtering Asian coverage.

3. **Exit timing** — when Kalshi odds reach >90% on an event your trade is positioned
   for, the information is fully priced. That is the exit signal regardless of where
   price is.

---

## Position Sizing & Risk

| Parameter | Layer A | Layer B | Confluence |
|---|---|---|---|
| Default position | 1–3% capital | 3–5% capital | 5–8% capital |
| Stop-loss | –5% (–3% low confidence) | –15% | –10% |
| Target hold | 1–10 days | 1–8 weeks | Determined by slower layer |
| Max concurrent | 5 | 5 | Shared pool — max 8 total |
| Universe | US equities + ETFs | US + HK listed | US + HK listed |

Layer B positions are sized larger because the edge is more validated (6-year track
record) and the stop-loss is wider because narrative shifts are gradual not sudden.

Layer A positions are smaller and tighter because snap-back risk is higher and the
timing edge is fragile — being right about the event but wrong about the timing by
48 hours is a loss.

---

## Known Limitations

**Layer A**
- Government RSS feeds can lag actual posting by minutes — direct URL polling of
  primary sources (federalregister.gov, treasury.gov, etc.) is more reliable than
  waiting for RSS propagation
- Sanctions language is complex; "sanctions relief" and "sanctions designation" require
  directional disambiguation before signal is valid
- Geopolitical events produce short-lived gaps with high snap-back frequency
- Timing edge is infrastructure-dependent and degrades as more participants adopt
  similar monitoring

**Layer B**
- Western narrative resistance can last longer than position can be held — irrational
  coalitions are real and can move policy levers even when materially wrong
- HK-listed tickers have lower liquidity than US-listed equivalents
- Coverage gap detection requires calibrated source weighting — not all Asian sources
  are equally reliable or independent of state messaging
- Exit timing is harder than entry timing — convergence signal (Western coverage spike)
  can be ambiguous

**Both**
- Confluence signals are stronger but also more correlated — a macro shock that
  invalidates both layers simultaneously creates larger drawdown than either layer alone
- Model confidence is calibrated on pattern recognition, not causal validation

---

## Implementation Notes for pattern_rules.py

Each `signal_type` value in the Signal Categories tables above corresponds directly
to a rule set in `pattern_rules.py`. Each rule set should contain:

- `keywords` — trigger phrases for detection
- `negative_keywords` — phrases that indicate false positive (e.g. "sanctions relief")
- `entities` — relevant tickers, sectors, or instruments
- `direction` — long / short / directional note
- `decay_days` — integer from decay model above
- `confidence_weight` — base confidence score before LLM scoring

The `western_dismissal_signal` type is a modifier, not a standalone signal. When
detected alongside any `coverage_gap_*` signal on the same entity within 48 hours,
it should boost the `signal_strength` score in `article_analysis` by 0.15–0.20.

---

## Thesis Swap Notes

This file defines the `propaganda-arbitrage` strategy. To add a new strategy:

1. Create `/strategies/[strategy-name]/thesis.md` with the same structure
2. Update `pattern_rules.py` with signal categories from the new thesis
3. Update `scraper_config.py` with relevant sources
4. Register strategy in DB and set `is_active = True`
5. No schema changes required

Signal types from different strategies coexist in the `signals` table via
`strategy_id`. Confluence detection across strategies is automatic.
