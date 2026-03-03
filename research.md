# How Macro-Pulse Finds Non-Consensus, Correct Opportunities

> "Being non-consensus and right is the only way to make above-average returns."
> — Howard Marks

---

## The Core Problem

Markets are mostly efficient. Consensus views are already priced in. The only way to generate alpha is to:

1. **Disagree with the market** (non-consensus)
2. **Be correct** about that disagreement

Macro-Pulse attempts both. Here's how.

---

## Part 0: How Consensus Is Determined

This is the critical question: before we can be non-consensus, we need to know what consensus IS. Here's how the system handles it.

### 0.1 Consensus Is LLM-Generated, Not Computed

**There is no deterministic consensus calculation.** The system does not aggregate signals into a "market consensus score." Instead, the LLM is instructed to identify consensus as part of narrative extraction.

From the prompt (`ai/prompts/templates.py:96-116`):

```
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
   - "more_aggressive": same direction but our signals suggest a BIGGER move
   - "more_passive": same direction but our signals suggest LESS conviction
   - "aligned": our view matches consensus (lowest alpha potential — flag this honestly)
4. Explain WHY our signals see something different for this asset in edge_rationale.
```

So the LLM must fill `consensus_view` as a free-text string for each `AssetSentiment` — describing what the market believes, citing specific sources like CME FedWatch, sell-side targets, or options pricing. Then it classifies `edge_type` based on how our signals diverge from that stated consensus.

### 0.2 What Signals Partially Capture Consensus

While there's no explicit "consensus score," several of the 13 data sources carry embedded consensus information:

| Source | What It Tells Us About Consensus | How It Gets Used |
|---|---|---|
| **Prediction Markets** (Kalshi + Polymarket) | Real-money probability estimates for macro events. If Kalshi prices "Fed rate cut by June" at 85%, that IS consensus. | Fed into LLM as signals; LLM cites these probabilities in `consensus_view` |
| **Economic Calendar** | Consensus forecasts for upcoming data releases (e.g., "NFP consensus: +180k"). The "consensus" column is literally the market's expected number. | LLM sees consensus vs. previous readings; can identify where our signals suggest a miss |
| **COT Positioning** | Net speculative positioning in futures. If specs are max-long EUR, that's consensus-bullish EUR. | LLM interprets crowded positioning as consensus; extreme positioning becomes a contrarian signal |
| **Funding Rates** | Leveraged positioning in crypto perpetuals. High positive funding = market consensus is long. | LLM interprets funding >0.03% as consensus-bullish but our view is contrarian-bearish |
| **Fear & Greed Index** | Composite crowd sentiment (0-100). High greed = consensus-bullish; extreme fear = consensus-bearish. | LLM interprets extremes as contrarian opportunities |
| **RSS News / Reddit** | Media narrative reflects what the market is talking about and broadly believes. Dominant headlines approximate consensus. | LLM reads the tone of news coverage to infer consensus; a flood of bearish headlines = bearish consensus |
| **Market Data** (yfinance) | Price action IS the market's revealed preference. Prices already reflect consensus. | Technical indicators (RSI, MACD, SMA) measure where price is relative to trend — indirectly capturing consensus positioning |

### 0.3 The Consensus Determination Process

In practice, consensus gets established through a two-step process:

**Step 1 — Implicit consensus from signals**: The raw signals carry market positioning, pricing, sentiment, and news narrative. These collectively represent what the market currently believes and how it's positioned.

**Step 2 — LLM articulation**: Claude Sonnet reads all ~350 signals and, for each asset in each narrative, writes a `consensus_view` string. It's asked to be specific — citing FedWatch probabilities, sell-side targets, options pricing — not just saying "consensus is bullish."

Example output:
```json
{
  "ticker": "Gold",
  "consensus_view": "Goldman/JPM calling for $2800 gold on steady central bank buying;
                      market already pricing modest safe-haven bid",
  "edge_type": "more_aggressive",
  "edge_rationale": "Our signals show accelerating central bank purchases and
                     retail ETF inflows not yet reflected in sell-side targets"
}
```

### 0.4 The Weakness: LLM Consensus Is Not Grounded

This is the system's most significant vulnerability. The consensus view relies on:

1. **The LLM's training data** — Claude knows what Goldman and JPM said as of its training cutoff, but not what they said yesterday. It may cite stale sell-side targets.

2. **Signals that implicitly carry consensus** — Prediction market probabilities and funding rates reflect real positioning, but they're just a few data points in a 350-signal batch. The LLM decides how much weight to give them.

3. **No dedicated consensus data source** — There's no Bloomberg Terminal feed, no options-implied probability surface, no aggregated sell-side survey. The system approximates consensus from fragments.

**What this means**: The system's "non-consensus" label is only as good as its consensus estimate. If the LLM misjudges what the market believes (e.g., says consensus is bearish Gold when it's actually neutral), the resulting "contrarian bullish" call isn't truly contrarian — it's just based on a wrong consensus read.

### 0.5 How Edge Type Flows Through the Pipeline

Once the LLM assigns `edge_type` per asset, it flows downstream:

```
LLM assigns edge_type per asset in narrative extraction
    ↓
run_weekly.py extracts the dominant edge_type per ticker
(highest-conviction narrative's edge_type wins)
    ↓
composite_scorer.py applies the nudge:
    contrarian  → +0.10
    aligned     → -0.05
    other       →  0.00
    ↓
Final composite_score includes this nudge, clamped to [-1.0, +1.0]
```

The edge_type is a **single string per asset** — not a probability or a spectrum. An asset is either contrarian or it isn't. There's no "60% contrarian" — it's a discrete label set by the LLM.

---

## Part 1: How We Disagree (Non-Consensus)

### 1.1 Explicit Consensus vs. Edge Labeling

Every asset in every narrative gets three fields the LLM must fill:

| Field | Purpose |
|---|---|
| `consensus_view` | What the market currently believes about this asset |
| `edge_type` | How our view differs: `contrarian`, `more_aggressive`, `more_passive`, `aligned` |
| `edge_rationale` | Specific reasoning for why we see something different |

This forces the system to **articulate its disagreement**. It can't just say "bullish on Gold" — it must say "consensus expects sideways Gold because of strong DXY, but our signals show real yields declining faster than priced, creating a contrarian long."

### 1.2 Scoring Incentive Structure

The composite score formula actively penalizes consensus-following:

```
composite = 0.50 × narrative + 0.25 × technical + 0.25 × scenario + nudge

where nudge:
  +0.10  if edge_type == contrarian
  -0.05  if edge_type == aligned
   0.00  otherwise
```

Contrarian views get a 10-point bonus. Aligned views get penalized. The system is structurally biased toward non-consensus calls.

### 1.3 Contrarian Signal Interpretation

Certain data sources are interpreted **opposite to their face value**:

| Signal | Naive Reading | Our Interpretation | Why |
|---|---|---|---|
| Google Trends spike for "recession" | Bearish — people worried | **Bullish** — retail panic marks short-term bottoms | By the time retail searches, institutions have already positioned |
| Crypto Fear & Greed < 20 | Danger — extreme fear | **Buying opportunity** — capitulation = bottom | Crowds panic-sell at lows, not highs |
| Crypto Fear & Greed > 80 | Good times — greed | **Sell signal** — euphoria = top | Crowds FOMO-buy at highs |
| Funding rate > 0.03% | Longs are confident | **Bearish** — crowded longs = liquidation cascade risk | Leveraged positioning creates fragility |
| Funding rate < -0.01% | Shorts are confident | **Bullish** — crowded shorts = short squeeze potential | Same fragility, opposite direction |

These aren't arbitrary flips. They're based on a structural observation: **crowded positioning creates the fuel for its own reversal**.

### 1.4 Transmission Mechanism Timing

The system matches signals against 28 known causal chains (e.g., "Fed Dovish Pivot", "Risk-Off Flight to Safety"), of which 11 are currently enabled. Each mechanism defines:

- **Chain steps** with expected lags (0-14 days)
- **Current stage** (early / mid / late / complete)

This creates timing edge. Example:

```
Fed signals dovish hold (Day 0, confirmed)
  → Rate expectations reprice (Day 0-3, emerging)
    → Real yields decline (Day 1-5, not started yet)
      → DXY weakens, Gold rallies, Bitcoin rallies (Day 2-7, not started)
```

If we're at the "emerging" stage for rate repricing, the asset-level moves haven't happened yet. We're positioning **before the market fully prices the chain**.

This is how you disagree with the market: you see the same signal, but you trace its implications further and faster than the crowd.

---

## Part 2: How We Try to Be Correct

### 2.1 Multi-Source Signal Collection (350-500 signals/week)

The system pulls from 13 independent sources:

| Category | Sources | Signal Type |
|---|---|---|
| **News & Narrative** | RSS feeds (10 outlets), Central bank speeches, Reddit (10 subreddits) | Qualitative — what's being discussed |
| **Hard Data** | FRED (11 macro series), Market data (31 tickers), COT positioning (15 contracts) | Quantitative — what's actually happening |
| **Sentiment & Positioning** | Fear & Greed, Google Trends, Funding rates, Prediction markets | Behavioral — what people believe and bet on |
| **Structural** | Intermarket spreads (5), On-chain stablecoin flows, Economic calendar | Mechanical — structural pressures and upcoming catalysts |

Correctness comes from **triangulation**. A single source can mislead. When news narratives, hard data, positioning data, and structural signals all point the same direction, the probability of being correct goes up.

### 2.2 LLM Narrative Extraction (Non-Consensus Interpretation)

~350 raw signals get compressed into 3-8 coherent narratives by Claude Sonnet. The prompt instructs the LLM to:

1. Identify **thematic clusters** across sources (not just echo one source)
2. Assign **per-asset direction + conviction** grounded in specific signals
3. Specify a **catalyst** (dated event) and **exit conditions** (take-profit + invalidation)
4. Explicitly state consensus vs. edge for every asset

The LLM's role is **interpretation, not prediction**. It connects dots across disparate signals that a human scanning 350 headlines would miss.

### 2.3 Transmission Mechanism Matching (Causal Discipline)

Rather than letting the LLM invent arbitrary causal stories, it must match signals to a **fixed catalog of 28 known mechanisms** (11 currently enabled across 3 categories):

| Category | Mechanisms |
|---|---|
| Monetary Policy | Fed Dovish Pivot, Fed Hawkish Surprise |
| Liquidity | Global Liquidity Expansion, Liquidity Squeeze |
| Risk Sentiment | Risk-Off Flight to Safety, Risk-On Rotation, VIX Mean Reversion |
| Crypto-Specific | Crypto Leverage Flush, Stablecoin Liquidity Shift, Crypto Narrative Momentum |
| Growth/Inflation | Stagflation Pressure, Reflation Trade, Recession Signal |
| Geopolitical | Trade War Escalation, Geopolitical Shock |
| FX-Specific | Yen Carry Unwind, Dollar Wrecking Ball |
| Commodity | Energy Supply Shock, Gold Central Bank Accumulation, Commodity Supercycle |
| Bonds | Term Premium Repricing |
| Credit | Credit Cycle EBP, Banking Stress Contagion |
| China/EM | China Credit Impulse, EM Sudden Stop |
| Fiscal | Fiscal Dominance, CB Policy Divergence |
| *(last 7 categories disabled — only crypto, monetary_policy, risk_sentiment active)* | |

Each mechanism defines **confirmation and invalidation criteria**. The system can't just assert "Fed is dovish" — it must show which chain steps have evidence and which don't.

This constrains the LLM's creativity to **known, testable causal chains**. If the chain steps don't have evidence, the mechanism gets low probability. 28 mechanisms exist in the catalog; 11 are active (crypto: 5, monetary_policy: 3, risk_sentiment: 3). The remaining 17 across 7 categories are defined but disabled.

### 2.4 Three Independent Scoring Pillars

The composite score combines three independent assessments:

```
┌─────────────────────────────┐
│  NARRATIVE SCORE (50%)      │  LLM-derived direction × conviction
│  from sentiment_aggregator  │  across all narratives mentioning this asset
├─────────────────────────────┤
│  TECHNICAL SCORE (25%)      │  RSI(14) + MACD(12,26,9) + SMA(20) distance
│  from technicals.py         │  pure price-action, no opinion
├─────────────────────────────┤
│  SCENARIO SCORE (25%)       │  Σ(mechanism_probability × magnitude × direction)
│  from scenario_aggregator   │  causal chain weighted by probability
├─────────────────────────────┤
│  CONTRARIAN NUDGE           │  +0.10 contrarian / -0.05 aligned
│  from composite_scorer      │  structural bias toward non-consensus
└─────────────────────────────┘
```

**Why this helps correctness**: If narrative says bullish but technicals say overbought (RSI > 70) and scenarios are conflicting, the composite dampens the signal. The system flags this as a **conflict** — reducing false confidence.

Conversely, when all three pillars agree and the view is contrarian, that's the highest-conviction setup: non-consensus AND multi-factor confirmed.

### 2.5 Conflict Detection

The system explicitly flags when:

- Scenarios disagree on direction for the same asset (`conflict_flag = True`)
- Technical bias contradicts narrative direction
- Multiple narratives point different directions for the same ticker

Conflicts reduce composite score magnitude and signal caution. This prevents the system from being confidently wrong when evidence is mixed.

### 2.6 Economic Regime Classification

Before scoring individual assets, the system classifies the macro regime:

| Regime | Characteristics | Implications |
|---|---|---|
| RISK_ON | Growth + easing | Long equities, short USD, long crypto |
| RISK_OFF | Recession + stress | Long USD, long gold, long bonds |
| REFLATION | Growth + inflation | Long commodities, short bonds |
| STAGFLATION | Stagnation + inflation | Long gold, short equities |
| GOLDILOCKS | Moderate growth, low inflation | Long everything, short vol |
| TRANSITION | Mixed signals | Reduce conviction across the board |

The regime acts as a **sanity check**. A bullish crypto call during a RISK_OFF regime should have lower conviction than during RISK_ON.

---

## Part 3: The Full Pipeline (How It Comes Together)

```
Week N:

1. COLLECT    350-500 signals from 13 sources
                 ↓
2. FILTER     Drop signals older than 5-10 days (keep forward-looking events)
                 ↓
3. NARRATE    LLM extracts 3-8 macro narratives with per-asset consensus vs. edge
                 ↓
4. MATCH      LLM matches signals to 18 transmission mechanisms with probabilities
                 ↓
5. CLASSIFY   LLM determines economic regime (risk-on, risk-off, etc.)
                 ↓
6. SCORE      Deterministic aggregation:
              • Narrative scores (weighted vote across narratives)
              • Technical scores (RSI, MACD, SMA — pure price action)
              • Scenario scores (probability-weighted mechanism impacts)
              • Composite = 50% narrative + 25% technical + 25% scenario + nudge
                 ↓
7. RANK       Assets sorted by |composite_score| descending
              Top assets = highest conviction, non-consensus calls
                 ↓
8. PRESENT    Streamlit dashboard with full breakdown:
              direction, score components, narratives, mechanisms,
              catalyst, exit conditions, source signals
```

---

## Part 4: Where the Edge Actually Is

### The Strongest Edge Cases

The system is most likely to be **non-consensus AND correct** when:

1. **Crowded positioning + catalyst**: Funding rates extreme AND upcoming event (FOMC, CPI) that could trigger unwind. The crowd is levered one way, and a catalyst is approaching that consensus hasn't fully priced.

2. **Mechanism early-stage + technical confirmation**: A transmission mechanism is in early stage (e.g., Fed just signaled dovish), technicals already turning (MACD crossover), but asset price hasn't moved yet. We're ahead of the chain.

3. **Cross-source convergence on contrarian view**: News is bearish (everyone scared), but hard data improving (FRED series), positioning already capitulated (COT extremes), and on-chain flows are bullish (stablecoin inflows). The narrative hasn't caught up to reality.

4. **Prediction market divergence**: Prediction markets price an event at 30% but our signal set suggests higher probability. Real-money probabilities are useful but can be wrong on low-liquidity markets.

### The Weakest Edge Cases

The system is most likely to be **wrong** when:

1. **Aligned trades with high scores**: If we agree with consensus and the score is high, we're probably late. The nudge penalty helps but doesn't eliminate this.

2. **Single-source narratives**: When a narrative is driven by one noisy source (Reddit, single RSS article), the LLM may overweight it.

3. **TRANSITION regime**: When the regime classifier says "mixed signals," the system's directional calls are less reliable.

4. **Low scenario probability**: When mechanism probabilities are all below 0.4, the causal chains are uncertain. Directional calls based on weak mechanisms are speculative.

---

## Part 5: What's Missing (Honest Assessment)

### Can't Yet Validate "Correct"

The system has **no backtesting or performance tracking**. We can articulate non-consensus views, but we don't yet measure whether they were correct after the fact. Without realized P&L tracking, the "correct" half of the equation is an assumption.

### Limited Mechanism Coverage

Only 3 of 10 mechanism categories are active (crypto, monetary_policy, risk_sentiment), enabling 11 of 28 mechanisms. The system is blind to:
- Geopolitical transmission (tariffs, sanctions, elections)
- China/EM-specific chains
- Commodity supply shocks
- Fiscal policy mechanisms
- Credit cycle dynamics

### No Position Sizing or Risk Management

The system says "bullish Bitcoin, score +0.7" but doesn't say how much to buy or when to cut. Position sizing, stop losses, and portfolio-level risk (concentration, correlation, max drawdown) are left to the user.

### LLM Reliability

The narrative extraction and mechanism matching are LLM-dependent. Claude is good but:
- Can hallucinate causal links not supported by signals
- May anchor on recent, salient events over slow-moving structural shifts
- Consistency across runs is not guaranteed (same signals may produce slightly different narratives)

### No Source Quality Weighting

A Reuters headline and a Reddit shitpost are treated with equal weight in the signal set. The LLM implicitly weights them, but there's no explicit source reliability scoring.

---

## Summary

**How Macro-Pulse finds non-consensus opportunities:**

| Component | How It Creates Non-Consensus |
|---|---|
| Contrarian signal interpretation | Inverts retail panic, crowded positioning, extreme sentiment |
| Explicit consensus vs. edge labeling | Forces every call to articulate how it differs from the market |
| Scoring nudge (+0.10/-0.05) | Structurally rewards contrarian, penalizes aligned |
| Transmission mechanism timing | Positions ahead of slower market participants in causal chains |
| Multi-source triangulation | Sees convergence across sources the market processes in silos |

**How Macro-Pulse tries to be correct:**

| Component | How It Increases Correctness |
|---|---|
| 350-500 signals from 13 sources | Broad evidence base, hard to fool all sources simultaneously |
| Three independent scoring pillars | Narrative + Technical + Scenario must agree for high conviction |
| Conflict detection | Explicitly flags when evidence is contradictory |
| Mechanism confirmation criteria | Each causal chain has testable steps — not vibes |
| Exit conditions | Every trade has invalidation criteria — wrong is defined upfront |

**The gap:** We can articulate the non-consensus view. We cannot yet prove we're correct more often than we're wrong. That requires performance tracking, backtesting, and iteration — which don't exist yet.
