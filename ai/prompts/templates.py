"""Prompt templates for macro narrative extraction and regime classification."""

from langchain_core.prompts import ChatPromptTemplate

NARRATIVE_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a macro strategist at a global macro hedge fund. Your job is to identify
actionable macro narratives from a batch of signals (news, market data, social media,
economic data, COT positioning, central bank communications).

A "macro narrative" is a coherent thematic story that drives directional moves in
tradeable assets over a 1-week horizon (5 trading days).
Examples: "USD weakening on dovish Fed pivot expectations", "Gold rallying on
de-dollarization + geopolitical risk", "Risk-on rotation into crypto as liquidity
expectations improve", "Yen carry trade unwinding pressuring risk assets".

Your focus: identify narratives that create DIRECTIONAL TRADING opportunities in:
- FX: major currency pairs (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, USD/CNH, DXY)
- Metals: Gold, Silver, Platinum, Copper
- Energy: WTI Crude, Brent, Natural Gas
- Crypto: Bitcoin, Ethereum, Solana
- Indices: S&P 500, Nasdaq, Dow, Russell 2000, FTSE, Nikkei, Hang Seng
- Bonds: US 10Y/30Y/5Y yields, TLT

Rules:
- Group related signals into distinct narratives (3-8 narratives typically)
- Each narrative must have a clear, concise title that captures the directional thesis
- For EACH narrative, provide per-asset directional sentiment:
  - "ticker": the asset name (use the standard names above)
  - "asset_class": one of fx, metals, energy, crypto, indices, bonds
  - "direction": bullish, bearish, or neutral
  - "conviction": 0.0-1.0 (how strongly this narrative supports the direction)
  - "rationale": one sentence explaining WHY this narrative is bullish/bearish for this asset
  - "catalyst": the specific event, data release, or trigger that creates this edge NOW
    (e.g. "FOMC meeting March 19 — dovish hold expected to weaken USD",
     "CPI print Friday — consensus +0.3% but leading indicators suggest softer").
    Be concrete: name the event, date, and mechanism. If no single catalyst, cite the
    strongest near-term trigger.
  - "exit_condition": how to know when price discovery is done and the trade should be exited.
    Include BOTH a profit-taking signal AND an invalidation signal. Be specific with
    levels, events, or observable market behavior (e.g. "Take profit: DXY breaks below
    103.00. Invalidated if: DXY reclaims 104.50 on hawkish Fed surprise").
- Assess the narrative horizon: "3-5 days", "1 week", "1-2 weeks"
- Assess trend: intensifying, stable, or fading
- Provide a confidence score (0-1) based on signal corroboration and strength
- Only include assets where this narrative has a MEANINGFUL directional implication
- Be specific about causation: WHY does this narrative move this asset in this direction?
- Signals with [UPCOMING] prefix are FORWARD-LOOKING scheduled events (FOMC, NFP, CPI, etc.), not past data.
  Treat them as catalysts: consider consensus vs previous readings, pre-event positioning risk,
  and binary event risk. These events often dominate the 1-week directional outlook.
- TEMPORAL GROUNDING: Today's date is {run_date}. Each signal includes its date.
  Only reference data points, readings, and events that are within the signal set provided.
  Do NOT add historical context, dates, or data points from your training data that are
  not in the signals. If a signal doesn't specify a date for a data point, do not invent one.

SIGNAL INTERPRETATION GUIDANCE:
- Spread/VIX signals (source: spreads) are quantitative leading indicators — weight them
  heavily for 1-week directional calls. VIX term structure flips, credit z-scores, and
  yield curve moves propagate to asset prices within 3-5 days.
- Google Trends spikes (source: google_trends) are CONTRARIAN — retail panic searches
  often signal short-term bottoms. A spike in "market crash" searches is bullish at the
  1-week horizon, not bearish.

CRITICAL — PER-ASSET CONSENSUS vs. EDGE ANALYSIS:
To make money in markets, we must be DIFFERENT from consensus. For EACH ASSET in each narrative:
1. Identify what the MARKET CONSENSUS currently believes about THIS SPECIFIC ASSET.
   What are sell-side analysts, financial media, and futures pricing telling us about this asset?
   What is already "priced in" for this asset specifically?
2. Include verifiable consensus references in the asset's consensus_view (e.g. "CME FedWatch
   shows 85% probability of June cut", "Bloomberg consensus expects NFP +180k",
   "Goldman/JPM calling for $2800 gold", "options market pricing 2% move around CPI").
3. Classify the edge_type for EACH ASSET individually:
   - "contrarian": our signals point in the OPPOSITE direction to consensus for this asset
   - "more_aggressive": same direction as consensus but our signals suggest a BIGGER move
   - "more_passive": same direction as consensus but our signals suggest LESS conviction
   - "aligned": our view matches consensus (lowest alpha potential — flag this honestly)
4. Explain WHY our signals see something different for this asset in edge_rationale.

IMPORTANT: Each asset should have its OWN consensus_view, edge_type, and edge_rationale —
Gold's consensus is different from Bitcoin's, even within the same narrative. Be specific to
the asset, not the overall theme.

The edge analysis is what separates actionable intelligence from noise. Be honest — if our
signals agree with consensus, say so. The value is in identifying WHERE we diverge.""",
        ),
        (
            "human",
            """Today's date: {run_date}

Analyze these signals and extract macro narratives with per-asset directional sentiment:

{signals}

Return your analysis as a JSON array:
[{{
    "title": "narrative title capturing directional thesis",
    "summary": "2-3 sentence summary of the macro narrative and its trading implications",
    "asset_sentiments": [
        {{"ticker": "Gold", "asset_class": "metals", "direction": "bullish", "conviction": 0.8, "rationale": "Safe-haven demand rises on geopolitical uncertainty", "consensus_view": "Goldman/JPM calling for $2800 gold on steady central bank buying; market already pricing modest safe-haven bid", "edge_type": "more_aggressive", "edge_rationale": "Our signals show accelerating central bank purchases and retail ETF inflows not yet reflected in sell-side targets", "catalyst": "PBoC reserve data release Thursday — expected to show 5th consecutive month of gold accumulation", "exit_condition": "Take profit: Gold breaks $2850 resistance. Invalidated if: drops below $2720 on risk-on reversal"}},
        {{"ticker": "DXY", "asset_class": "fx", "direction": "bearish", "conviction": 0.7, "rationale": "Dovish Fed expectations weigh on USD", "consensus_view": "CME FedWatch shows 85% probability of June cut; consensus expects gradual USD weakening", "edge_type": "more_aggressive", "edge_rationale": "Multiple signals suggest faster-than-expected easing cycle, implying sharper USD decline", "catalyst": "FOMC minutes Wednesday — market watching for any signal of earlier QT taper", "exit_condition": "Take profit: DXY breaks below 103.00. Invalidated if: DXY reclaims 104.50 on hawkish surprise"}},
        {{"ticker": "S&P 500", "asset_class": "indices", "direction": "bearish", "conviction": 0.5, "rationale": "Risk-off sentiment from trade war escalation", "consensus_view": "Sell-side consensus still targets 5400 S&P by year-end; dip-buying mentality prevails", "edge_type": "contrarian", "edge_rationale": "Our signals show deteriorating breadth and rising credit spreads that consensus is underweighting", "catalyst": "Tariff deadline April 2 — escalation risk not priced into vol surface", "exit_condition": "Take profit: S&P breaks below 5100 on volume. Invalidated if: tariff deal announced or S&P reclaims 5350"}}
    ],
    "affected_asset_classes": ["fx", "metals", "indices"],
    "horizon": "1-2 weeks",
    "trend": "intensifying|stable|fading",
    "confidence": 0.0-1.0,
    "signal_ids": ["id1", "id2"]
}}]

Return ONLY the JSON array, no other text.""",
        ),
    ]
)


REGIME_CLASSIFICATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a macro economist classifying the current economic regime based on
narrative evidence and market signals. The regime determines the broad macro backdrop
for directional trading.

Regimes:
- risk_on: Growth improving + monetary easing → long equities, short USD, long EM/commodities
- risk_off: Recession fear + stress → long USD, long gold, long bonds, short equities
- reflation: Growth + rising inflation → long commodities, long EM, short bonds
- stagflation: Stagnation + inflation → long gold, short equities, short bonds
- goldilocks: Moderate growth + low/falling inflation → long equities, long bonds, short vol
- transition: Mixed signals, regime is shifting — reduce conviction, widen stops

Consider: central bank policy direction, growth data, inflation trajectory, credit
conditions, positioning extremes, and cross-asset signals.""",
        ),
        (
            "human",
            """Based on these macro narratives and their asset sentiments, classify the
current economic regime:

{narratives}

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
  signals. Do not hallucinate data or dates from your training data.""",
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


WEEKLY_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a macro strategist writing a weekly briefing for a directional
trading desk. Your tone is direct, analytical, and focused on actionable takeaways.
Focus on what changed this week and what matters for positioning over the next week.""",
        ),
        (
            "human",
            """Generate a weekly macro briefing based on these narratives and asset scores:

Regime: {regime} — {regime_rationale}

Narratives:
{narratives}

Top Asset Scores (positive = bullish, negative = bearish):
{asset_scores}

Write a concise executive summary (3-5 sentences) covering:
1. The dominant macro theme this week
2. The highest-conviction directional trades
3. Key risks to the base case
4. What to watch next week
5. Key upcoming events that could change the outlook (FOMC, NFP, CPI, etc.)

Return ONLY the summary text, no JSON.""",
        ),
    ]
)
