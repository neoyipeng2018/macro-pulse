"""Signal source classification for the three-phase pipeline.

Separates sources into consensus-revealing (positioning + narrative)
and alpha-candidate categories. Some sources are dual-role.
"""

# Quantitative positioning: how money is actually deployed
POSITIONING_SOURCES = {
    "options",
    "derivatives_consensus",
    "etf_flows",
    "funding_rates",
    "market_data",
    "cot_reports",
}

# Qualitative narrative: what people believe and talk about
NARRATIVE_CONSENSUS_SOURCES = {
    "news",
    "reddit",
    "fear_greed",
    "prediction_markets",
    "central_bank",
    "economic_calendar",
}

# All sources that feed into Phase 1 consensus picture
CONSENSUS_SOURCES = POSITIONING_SOURCES | NARRATIVE_CONSENSUS_SOURCES

# Sources that may contain alpha (information not yet priced in).
# Some overlap with consensus sources — Phase 2 re-examines them through an alpha lens.
ALPHA_SOURCES = {
    "news",
    "reddit",
    "spreads",
    "google_trends",
    "onchain",
    "economic_data",
    "central_bank",
    "economic_calendar",
}
