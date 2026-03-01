"""Signal patterns for the Propaganda Arbitrage strategy.

Two complementary structures:

``PATTERN_RULES``  – keyword-based signal rules consumed by ``ArticleProcessor``
                     and ``PatternDetector.detect_policy_announcements``.

``PATTERNS``       – numeric thresholds consumed by
                     ``PatternDetector.analyze_coverage_gaps``.
"""

# ── Coverage-gap thresholds (used by PatternDetector) ─────────────────────────

PATTERNS: dict = {
    "coverage_gap": {
        # A gap is flagged when asia sources are prominent AND west is quiet
        "min_asia_articles": 5,
        "max_western_articles": 2,
        "min_gap_ratio": 3.0,
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
    {
        "name": "sanctions_announcement",
        "description": (
            "New sanctions imposed on a country or sector often cause "
            "defence/energy plays in the opposing blocs."
        ),
        "keywords": ["sanctions", "sanctioned", "embargo", "export controls"],
        "exclude": ["lifted", "removed", "eased", "relief"],
        "tickers": ["LMT", "RTX", "NOC", "BA"],
        "signal_type": "bullish",
        "confidence": 0.60,
    },
    {
        "name": "sanctions_relief",
        "description": "Easing of sanctions — potential upside for commodities/energy.",
        "keywords": ["sanctions relief", "sanctions lifted", "embargo lifted", "eased sanctions"],
        "exclude": [],
        "tickers": ["XOM", "CVX", "OXY"],
        "signal_type": "bullish",
        "confidence": 0.55,
    },
    {
        "name": "tariff_increase",
        "description": "New or raised tariffs compress margins for import-heavy sectors.",
        "keywords": ["tariff", "tariffs", "import duty", "trade war", "Section 301"],
        "exclude": ["reduced", "lowered", "removed", "exemption"],
        "tickers": ["WMT", "AMZN", "COST"],
        "signal_type": "bearish",
        "confidence": 0.55,
    },
    {
        "name": "tariff_reduction",
        "description": "Lower tariffs benefit import-dependent consumer goods companies.",
        "keywords": ["tariff reduction", "tariff cut", "trade deal", "trade agreement"],
        "exclude": ["failed", "collapsed", "stalled"],
        "tickers": ["WMT", "TGT", "NKE"],
        "signal_type": "bullish",
        "confidence": 0.55,
    },
    {
        "name": "defence_spending_increase",
        "description": "Government announcement of higher defence budgets.",
        "keywords": ["defence budget", "defense spending", "military aid",
                     "Pentagon budget", "NATO spending"],
        "exclude": ["cut", "reduction", "freeze"],
        "tickers": ["LMT", "RTX", "NOC", "GD", "BA"],
        "signal_type": "bullish",
        "confidence": 0.70,
    },
    {
        "name": "semiconductor_policy",
        "description": "Government chip subsidies or export controls move semis.",
        "keywords": ["CHIPS Act", "chip subsidy", "semiconductor funding",
                     "export control", "chip ban", "chip restriction"],
        "exclude": ["reversed", "cancelled"],
        "tickers": ["NVDA", "AMD", "INTC", "AMAT", "KLAC", "LRCX"],
        "signal_type": "bullish",
        "confidence": 0.65,
    },
    {
        "name": "energy_supply_disruption",
        "description": "Geopolitical event threatening oil/gas supply routes.",
        "keywords": ["pipeline attack", "Strait of Hormuz", "OPEC cut",
                     "oil supply", "gas supply disruption"],
        "exclude": [],
        "tickers": ["XOM", "CVX", "COP", "USO"],
        "signal_type": "bullish",
        "confidence": 0.65,
    },
    {
        "name": "central_bank_hawkish",
        "description": "Central bank signalling rate hikes or quantitative tightening.",
        "keywords": ["rate hike", "interest rate increase", "hawkish",
                     "quantitative tightening", "inflation fight"],
        "exclude": ["pause", "cut", "dovish"],
        "tickers": ["TLT", "SHY", "GLD"],
        "signal_type": "bearish",
        "confidence": 0.60,
    },
    {
        "name": "central_bank_dovish",
        "description": "Central bank pivoting toward cuts or stimulus.",
        "keywords": ["rate cut", "rate reduction", "dovish", "quantitative easing",
                     "stimulus", "accommodative"],
        "exclude": ["hawkish", "hike"],
        "tickers": ["SPY", "QQQ", "GLD"],
        "signal_type": "bullish",
        "confidence": 0.60,
    },
    {
        "name": "regime_change_risk",
        "description": "Political instability in a commodity-rich country.",
        "keywords": ["coup", "regime change", "civil unrest", "political crisis",
                     "government collapse"],
        "exclude": [],
        "tickers": ["GLD", "SLV", "USO"],
        "signal_type": "bullish",
        "confidence": 0.50,
    },
    {
        "name": "pandemic_new_variant",
        "description": "Novel pathogen or variant causing travel/supply chain concern.",
        "keywords": ["new variant", "pandemic", "lockdown", "WHO emergency",
                     "outbreak", "epidemic"],
        "exclude": ["contained", "mild", "no concern"],
        "tickers": ["MRNA", "PFE", "BNTX", "ZM"],
        "signal_type": "bullish",
        "confidence": 0.45,
    },
]
