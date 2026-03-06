"""Prompt templates for macro narrative extraction and regime classification."""

from langchain_core.prompts import ChatPromptTemplate

MECHANISM_MATCHING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a macro strategist matching incoming market signals to known
transmission mechanisms — causal chains through which macro events propagate to
asset prices.

You are given:
1. A set of raw signals (news, data, social media, spreads, etc.)
2. A catalog of known transmission mechanisms, each with trigger conditions,
   causal chain steps, and expected asset impacts.

Your job is to identify which mechanisms are CURRENTLY ACTIVATED by the signals.
You are NOT inventing narratives — you are matching evidence to known mechanisms.

Rules:
- Only activate a mechanism if specific signals provide concrete evidence for its
  trigger conditions. Do not speculate or assume.
- Assign a probability (0.2–0.95) reflecting how strongly the signals support
  activation. Probability >= 0.2 required to include.
- Typically 2–6 mechanisms will be active. It is fine to activate fewer if
  evidence is weak, or more if the signal set is rich.
- For each active mechanism, assess:
  - Which chain steps have evidence (not_started/emerging/confirmed/invalidated)
  - Current stage (early/mid/late/complete)
  - Expected magnitude (minor/moderate/major)
  - Per-asset impacts with direction, magnitude (0-1), and conviction (0-1)
  - Watch items: what data releases or events would confirm or invalidate
- Do NOT activate mechanisms that are not in the catalog. If signals suggest
  something novel, skip it — the narrative pipeline handles unstructured themes.
- TEMPORAL GROUNDING: Today is {run_date}. Only cite evidence from the provided
  signals. Do not hallucinate data or dates from your training data.
- For crypto mechanisms (crypto_leverage_liquidation, stablecoin_contagion,
  crypto_liquidity_proxy): funding rate signals are PRIMARY evidence for
  crypto_leverage_liquidation — do NOT activate without citing funding rate levels.
  Stablecoin supply signals are PRIMARY evidence for stablecoin_contagion —
  do NOT activate without citing stablecoin market cap data.""",
        ),
        (
            "human",
            """Today's date: {run_date}

=== SIGNALS ===
{signals}

=== MECHANISM CATALOG ===
{mechanisms}

Match the signals to activated mechanisms. Return a JSON array:
[{{
    "mechanism_id": "fed_dovish_pivot",
    "mechanism_name": "Fed Dovish Pivot",
    "category": "monetary_policy",
    "probability": 0.65,
    "trigger_signals": ["signal_id_1", "signal_id_2"],
    "trigger_evidence": "FOMC minutes showed dovish lean; CME FedWatch pricing 80% June cut",
    "chain_progress": [
        {{"step_index": 0, "description": "Fed signals dovish shift", "status": "confirmed", "evidence": "Minutes showed multiple members favoring cuts", "confidence": 0.8}},
        {{"step_index": 1, "description": "Rate expectations reprice", "status": "emerging", "evidence": "2Y yield down 5bp this week", "confidence": 0.6}},
        {{"step_index": 2, "description": "Real yields decline", "status": "not_started", "evidence": "", "confidence": 0.0}},
        {{"step_index": 3, "description": "Risk assets rally", "status": "not_started", "evidence": "", "confidence": 0.0}}
    ],
    "current_stage": "early",
    "expected_magnitude": "moderate",
    "asset_impacts": [
        {{"ticker": "Gold", "asset_class": "metals", "direction": "bullish", "magnitude": 0.6, "conviction": 0.7, "rationale": "Lower real yields support gold"}},
        {{"ticker": "DXY", "asset_class": "fx", "direction": "bearish", "magnitude": 0.5, "conviction": 0.65, "rationale": "Rate cut expectations weigh on USD"}}
    ],
    "watch_items": ["CPI print Friday", "FOMC meeting next week", "2Y yield trajectory"],
    "confirmation_status": "Partially confirmed — dovish shift clear but rate repricing incomplete",
    "invalidation_risk": "Hot CPI Friday could reverse dovish narrative",
    "horizon": "1 week",
    "confidence": 0.65
}}]

Return ONLY the JSON array, no other text.""",
        ),
    ]
)


CONSENSUS_SYNTHESIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a market microstructure analyst. Your ONLY job is to describe what
the market currently believes and how it's positioned. You are NOT making predictions
or expressing opinions — you are reading the data and articulating consensus.

You will receive THREE types of consensus evidence:
1. Quantitative consensus scores (computed from options, derivatives, ETF flows)
2. Raw positioning signals (funding rates, L/S ratios, Fear & Greed, COT, price action)
3. Qualitative narrative signals (news headlines, Reddit sentiment, prediction market
   probabilities, central bank guidance, economic calendar consensus forecasts)

Consensus has two layers — your job is to synthesize BOTH:

POSITIONING CONSENSUS (from quantitative data):
- What direction is money actually deployed? (long-biased, short-biased, neutral)
- How crowded is the positioning? (light, moderate, crowded, extreme)

NARRATIVE CONSENSUS (from qualitative data):
- What story is the market telling itself? What's the dominant headline?
- What do news outlets, Reddit, and prediction markets agree on?
- What events/outcomes are "priced in" based on this narrative?

CONSENSUS COHERENCE:
- Do positioning and narrative agree? If yes → strong consensus, high confidence.
- Do they diverge? (e.g., headlines fearful but funding still bullish) → fractured
  consensus, flag this explicitly. Fractured consensus = opportunity for Phase 2.

Rules:
- ONLY cite data from the signals provided. Do not reference information not
  present in the signal set.
- Be precise: "funding rate +0.04% = longs paying shorts at elevated level" not
  "market is somewhat bullish"
- For narrative consensus, cite actual headlines and Reddit sentiment, not vibes.
  "3 of 5 top Reddit posts are bullish altcoin rotation" is evidence.
  "Reddit seems bullish" is not.
- Distinguish between DIRECTION (which way) and CONVICTION (how crowded/unanimous)
- Extreme positioning is itself information: crowded longs = fragile, not confident
- If prediction market data is available, cite specific probabilities""",
        ),
        (
            "human",
            """Today's date: {run_date}

QUANTITATIVE CONSENSUS SCORES:
{consensus_scores_text}

POSITIONING SIGNALS:
{positioning_signals_text}

QUALITATIVE / NARRATIVE SIGNALS:
{narrative_signals_text}

PRICE ACTION:
{market_data_text}

For each asset with data, synthesize the complete consensus picture — both
positioning and narrative consensus. Flag whether they agree or diverge.

Return a JSON array:
[{{
    "ticker": "Bitcoin",
    "positioning_consensus": "Moderately long. Funding +0.02%, top traders 58% long,
        ETF inflows +$120M rolling 5d, options call-skewed. OI up 8% in 7d.",
    "narrative_consensus": "Dominant news narrative is cautiously bullish — 4 of 8
        crypto RSS headlines reference ETF inflows and institutional adoption. Reddit
        CryptoCurrency top posts are mixed (2 bullish, 1 bearish, 2 neutral). Fear &
        Greed at 62 (greed). No prediction market data this week.",
    "consensus_coherence": "aligned",
    "coherence_detail": "Positioning and narrative both lean bullish. Funding, L/S,
        ETF flows, and news headlines all point the same direction. Consensus is
        clear and moderately strong.",
    "market_narrative": "Market believes BTC will continue ranging $90k-$100k with
        upside bias driven by sustained ETF inflows and post-halving supply dynamics.
        Dominant story is institutional adoption.",
    "positioning_summary": "Funding: +0.02% (moderate long bias). Top traders: 58%
        long. OI up 8% in 7d. ETF 5d flow: +$120M.",
    "key_levels": ["Max pain: $95,000", "Support: $90,000 (OI cluster)",
                   "Resistance: $100,000 (psychological + options barrier)"],
    "priced_in": ["Continued ETF inflows", "Stable macro environment",
                  "Range-bound between $90k-$100k"],
    "not_priced_in": ["Potential tariff escalation", "FOMC surprise",
                      "Leverage flush if funding exceeds 0.05%"],
    "consensus_direction": "bullish",
    "consensus_confidence": 0.7
}}]

Return ONLY the JSON array.""",
        ),
    ]
)


NON_CONSENSUS_DISCOVERY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a contrarian research analyst at a macro hedge fund. You have been
given two inputs:
1. The ESTABLISHED MARKET CONSENSUS for each asset (from positioning data AND narrative data)
2. A set of ALPHA SIGNALS — information that may not yet be reflected in consensus positioning

Your ONLY job is to identify where the alpha signals DISAGREE with the established consensus,
and evaluate whether each disagreement is valid enough to trade on.

You are NOT extracting narratives. You are NOT making general market commentary.
You are finding SPECIFIC DISAGREEMENTS and stress-testing them.

For each disagreement you find, you must answer:
1. WHAT is consensus? (cite the consensus data provided)
2. WHAT do our signals say differently? (cite specific alpha signals by their IDs)
3. WHY might our signals be right and consensus wrong? (the mechanism)
4. HOW MANY independent signal sources support our view? (minimum 2 required)
5. WHAT would invalidate our non-consensus view? (specific and testable)
6. IS THERE a timing edge? (are we seeing something the market will price later?)

Validity rules — a non-consensus view is VALID only if:
- Supported by 2+ INDEPENDENT signal sources (Reddit + News from the same story = 1 source)
- Has a plausible causal mechanism (not just "vibes")
- Has a specific invalidation condition
- The consensus data actually supports the consensus direction claimed

Validity rules — a non-consensus view is INVALID if:
- Based on a single source or a single noisy data point
- The "disagreement" is actually aligned with consensus (don't force contrarianism)
- The mechanism is speculative without supporting data
- It contradicts hard quantitative data (e.g. claiming bearish when funding, L/S,
  options, AND ETF flows are all strongly bullish — that's not contrarian, that's wrong)

IMPORTANT — consensus has TWO layers (positioning + narrative). Pay attention to coherence:
- If the consensus is "aligned" (positioning and narrative agree), you need STRONG
  alpha evidence to justify a contrarian view.
- If the consensus is "fractured" (positioning and narrative diverge), non-consensus
  views are MORE LIKELY to be valid — the market is already confused.

Be honest. If our signals agree with consensus, say so — there's no shame in "no edge found."
Quality over quantity: 1-2 strong non-consensus views beats 5 weak ones.""",
        ),
        (
            "human",
            """Today's date: {run_date}

=== ESTABLISHED CONSENSUS (from positioning + narrative data) ===
{consensus_views_text}

=== ALPHA SIGNALS (potentially not yet priced in) ===
{alpha_signals_text}

Find specific disagreements between our alpha signals and the established consensus.

Return a JSON array:
[{{
    "ticker": "Bitcoin",
    "consensus_direction": "bullish",
    "consensus_summary": "Market positioned moderately long: funding +0.02%, top traders
        58% long, ETF inflows +$120M/5d. News narrative bullish on institutional adoption.",
    "our_direction": "bearish",
    "edge_type": "contrarian",
    "thesis": "Despite bullish positioning, three independent signals suggest a leverage
        flush is imminent: stablecoin supply declining 2% this week (liquidity leaving),
        credit spread z-score at -1.5 (broader risk-off not yet reflected in crypto),
        and Google Trends spike in 'bitcoin crash' searches (retail panic building).",
    "evidence": [
        {{"signal_id": "sig_123", "source": "onchain", "summary": "Stablecoin supply
            down 2.1% this week — capital leaving crypto ecosystem", "strength": 0.8}},
        {{"signal_id": "sig_456", "source": "spreads", "summary": "HYG/LQD credit spread
            z-score at -1.5 — broader risk-off pressure building", "strength": 0.6}},
        {{"signal_id": "sig_789", "source": "google_trends", "summary": "'bitcoin crash'
            searches spiked 3.2x — retail attention at extreme levels", "strength": 0.7}}
    ],
    "independent_source_count": 3,
    "has_testable_mechanism": true,
    "has_timing_edge": true,
    "catalyst": "FOMC meeting March 19 — any hawkish surprise accelerates risk-off",
    "invalidation": "Stablecoin supply stabilizes AND credit spreads normalize above
        z-score -0.5 within 3 days",
    "our_conviction": 0.7,
    "validity_score": 0.75,
    "signal_ids": ["sig_123", "sig_456", "sig_789"]
}}]

If no valid non-consensus views exist, return an empty array [].
Return ONLY the JSON array.""",
        ),
    ]
)


REGIME_FROM_CONSENSUS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a macro economist classifying the current economic regime based on
market consensus positioning, narrative evidence, and active transmission mechanisms.
The regime determines the broad macro backdrop for directional trading.

Regimes:
- risk_on: Growth improving + monetary easing → long equities, short USD, long EM/commodities
- risk_off: Recession fear + stress → long USD, long gold, long bonds, short equities
- reflation: Growth + rising inflation → long commodities, long EM, short bonds
- stagflation: Stagnation + inflation → long gold, short equities, short bonds
- goldilocks: Moderate growth + low/falling inflation → long equities, long bonds, short vol
- transition: Mixed signals, regime is shifting — reduce conviction, widen stops

Consider: consensus positioning direction and coherence, active transmission mechanisms
and their stages, and the overall market narrative.""",
        ),
        (
            "human",
            """Based on these consensus views and active transmission mechanisms, classify
the current economic regime:

CONSENSUS VIEWS:
{consensus_views}

ACTIVE TRANSMISSION MECHANISMS:
{active_scenarios}

Return a JSON object:
{{
    "regime": "risk_on|risk_off|reflation|stagflation|goldilocks|transition",
    "rationale": "2-3 sentence explanation of why this regime classification fits the evidence",
    "confidence": 0.0-1.0,
    "key_indicators": ["indicator 1", "indicator 2", "indicator 3"]
}}

Return ONLY the JSON object, no other text.""",
        ),
    ]
)


SUMMARY_FROM_CONSENSUS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a macro strategist writing a weekly briefing for a directional
trading desk. Your tone is direct, analytical, and focused on actionable takeaways.
Focus on what the market believes, where we disagree, and what matters for positioning.""",
        ),
        (
            "human",
            """Generate a weekly macro briefing based on these inputs:

Regime: {regime} — {regime_rationale}

CONSENSUS VIEWS:
{consensus_views}

NON-CONSENSUS VIEWS:
{non_consensus_views}

ACTIVE MECHANISMS:
{active_scenarios}

Write a concise executive summary (3-5 sentences) covering:
1. The dominant market consensus this week
2. Our highest-conviction non-consensus views (if any)
3. Key risks and invalidation conditions
4. Active transmission mechanisms and their stages
5. Key upcoming events that could change the outlook

Return ONLY the summary text, no JSON.""",
        ),
    ]
)
