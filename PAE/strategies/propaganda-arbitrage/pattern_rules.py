"""Signal patterns for the Propaganda Arbitrage strategy.

Two complementary structures:

``PATTERN_RULES``  – keyword-based signal rules consumed by ``ArticleProcessor``
                     and ``PatternDetector.detect_policy_announcements``.
                     Each rule now carries: ``decay_days``, ``snap_back_keywords``,
                     ``direction``, and ``layer`` ("A" or "B").

``PATTERNS``       – numeric thresholds consumed by
                     ``PatternDetector.analyze_coverage_gaps``.

``WESTERN_DISMISSAL_BOOST`` / ``WESTERN_DISMISSAL_KEYWORDS``
                   – modifier applied when a Western source actively dismisses
                     an entity that already has a Layer B coverage-gap signal.
"""

# ── Coverage-gap thresholds (used by PatternDetector) ─────────────────────────

PATTERNS: dict = {
    "coverage_gap": {
        # A gap is flagged when asia sources are prominent AND west is quiet
        "min_asia_articles": 2,
        "max_western_articles": 5,
        "min_gap_ratio": 1.5,
    },
    "policy_catalyst": {
        "keywords": ["subsidy", "fund", "billion", "investment", "policy", "regulation"],
        "min_amount": 1_000_000_000,   # $1 B threshold for monetary signals
    },
    "entities_of_interest": [
        # Semiconductor / hardware
        "SMIC", "TSMC", "Intel", "NVIDIA", "AMD", "Samsung", "Huawei",
        "ASML", "Qualcomm", "Micron", "SK Hynix", "Apple", "Microsoft",
        # Topics
        "semiconductor", "chip", "AI", "lithium", "battery",
        "5G", "quantum", "solar", "EV", "drone",
        # Geographies
        "China", "Taiwan",
    ],
}

# ── Keyword signal rules (used by ArticleProcessor & PatternDetector) ─────────

PATTERN_RULES: list[dict] = [
    # ── Layer A: Government Communication Signals ─────────────────────────────
    {
        "name": "sanctions_announcement",
        "description": "New OFAC designations or export controls create forced institutional selling.",
        "keywords": ["sanctions", "sanctioned", "OFAC designates", "embargo",
                     "export controls", "entity list", "SDN list"],
        "exclude": ["lifted", "removed", "eased", "relief", "waiver", "exemption"],
        "tickers": ["LMT", "RTX", "NOC", "BA"],
        "signal_type": "bullish",
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

    # ── Layer B: Coverage Gap Signals ─────────────────────────────────────────
    # These are NOT keyword-triggered. They're detected by analyze_coverage_gaps()
    # based on article count asymmetry. Listed here for reference, snap-back
    # detection, and decay tracking.
    {
        "name": "coverage_gap_semiconductor",
        "description": "Asian coverage of chip fab milestone/funding >> Western coverage.",
        "keywords": [],
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

# ── Western Dismissal Modifier ────────────────────────────────────────────────
# Not a standalone signal. When detected alongside any coverage_gap_* signal
# on the same entity within 48h, boost signal_strength by this amount.

WESTERN_DISMISSAL_BOOST: float = 0.18

WESTERN_DISMISSAL_KEYWORDS: list[str] = [
    "skeptics say", "experts doubt", "unlikely to", "remains to be seen",
    "far behind", "years away", "propaganda", "state media claims",
    "unverified", "analysts question", "overhyped", "copycat",
]
