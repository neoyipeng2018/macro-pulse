# How Macro-Pulse Finds Non-Consensus, Correct Opportunities

> "Being non-consensus and right is the only way to make above-average returns."
> — Howard Marks

---

## The Core Problem

Markets are mostly efficient. Consensus views are already priced in. The only way to generate alpha is to:

1. **Disagree with the market** (non-consensus)
2. **Be correct** about that disagreement

Macro-Pulse attempts both through a structured three-phase pipeline. Here's how.

---

## Architecture Overview: The Three-Phase Pipeline

The system operates in three sequential phases, orchestrated by `run_weekly.py:run_pipeline()`:

```
Phase 1 — CONSENSUS:    What does the market believe?
Phase 2 — NON-CONSENSUS: Where do our signals disagree?
Phase 3 — SCORE & PRESENT: Combine everything into actionable output.
```

Each phase has distinct data sources, processing logic, and outputs. A legacy monolithic pipeline (`run_pipeline_legacy()`) still exists but bypasses the three-phase structure.

---

## Part 0: Signal Source Classification

**File:** `config/signal_roles.py`

Before any analysis, signals are classified by role:

### Positioning Sources (Quantitative — how money is deployed)
```python
{"options", "derivatives_consensus", "etf_flows", "funding_rates", "market_data", "cot_reports"}
```

### Narrative Consensus Sources (Qualitative — what people believe)
```python
{"news", "reddit", "fear_greed", "prediction_markets", "central_bank", "economic_calendar"}
```

### Consensus Sources (Union of both)
Used in Phase 1 to build the full consensus picture.

### Alpha Sources (May contain information not yet priced in)
```python
{"news", "reddit", "spreads", "google_trends", "onchain", "economic_data", "central_bank", "economic_calendar"}
```

Note the overlap: `news`, `reddit`, `central_bank`, and `economic_calendar` appear in both consensus and alpha sets. They're used in Phase 1 to establish consensus AND re-examined in Phase 2 through an "alpha lens" — same data, different question.

---

## Part 1: Phase 1 — How Consensus Is Determined

This is the foundational question: before we can be non-consensus, we need to know what consensus IS. The current system uses a **two-layer approach**: quantitative scoring + LLM synthesis.

### 1.1 Quantitative Consensus Scoring

**File:** `analysis/consensus_scorer.py`

`compute_consensus_scores()` processes signals from `options`, `derivatives_consensus`, and `etf_flows` into a `ConsensusScore` per asset (currently BTC and ETH).

**Six components**, each normalized to [-1, +1]:

| Component | Raw Metric | Normalization Range | Logic |
|---|---|---|---|
| `options_skew` | 25-delta risk reversal | (-0.05, 0.05) | Positive skew = calls > puts = bullish |
| `funding_7d` | 7-day accumulated funding % | (-0.10, 0.10) | Positive = longs paying shorts = bullish positioning |
| `top_trader_ls` | Top trader long/short ratio | (0.7, 1.3), centered on 1.0 | Ratio > 1 = more longs = bullish |
| `etf_flows` | 5-day rolling USD millions | (-500, +500) | Positive = inflows = bullish |
| `put_call_ratio` | Raw PCR | Inverted: low PCR = bullish | Inverted so low PCR maps to +1 (complacency = bullish sentiment) |
| `oi_momentum` | 7-day % OI change | (-15, +15) | Rising OI = fresh money entering = momentum |

**Scoring formula:** Equal-weighted average of all available components, clamped to [-1, +1].

**Direction thresholds:**
- Score > **+0.15** → `bullish`
- Score < **-0.15** → `bearish`
- Otherwise → `neutral`

These thresholds were raised from 0.1 to 0.15 to reduce false directional signals.

**Output:** `ConsensusScore` per asset — a single number with direction label plus the raw component breakdown.

### 1.2 LLM Consensus Synthesis

**File:** `ai/chains/consensus_synthesizer.py`
**Prompt:** `ai/prompts/templates.py`, `CONSENSUS_SYNTHESIS_PROMPT` (line ~272)

`synthesize_consensus()` takes the quantitative scores + raw positioning signals + narrative signals + market data signals, then sends everything to the LLM acting as a "market microstructure analyst."

The LLM synthesizes two layers:

1. **Positioning consensus** — where is money actually deployed? How crowded is the trade?
2. **Narrative consensus** — what's the dominant story? What does the market believe is "priced in"?
3. **Consensus coherence** — do positioning and narrative agree?

**Output per asset:** `ConsensusView` (schema in `models/schemas.py`, lines 324-343):

| Field | Type | Purpose |
|---|---|---|
| `quant_score` | float | From the quantitative scorer |
| `quant_direction` | str | bullish/bearish/neutral from quant scorer |
| `positioning_consensus` | str | LLM summary of how money is deployed |
| `positioning_summary` | str | One-line positioning takeaway |
| `narrative_consensus` | str | LLM summary of dominant market beliefs |
| `market_narrative` | str | One-line narrative takeaway |
| `consensus_coherence` | str | `aligned` / `fractured` / `divergent` |
| `key_levels` | list[str] | Important price levels cited by market |
| `priced_in` | list[str] | What the market has already discounted |
| `not_priced_in` | list[str] | What the market hasn't yet discounted |
| `consensus_direction` | str | Overall consensus: bullish/bearish/neutral |
| `consensus_confidence` | float | 0-1 confidence in the consensus read |

### 1.3 Why Two Layers?

The quantitative score grounds the consensus in hard data — options markets, funding rates, and ETF flows don't lie about positioning. The LLM synthesis adds interpretive richness — "what's priced in" and "positioning vs narrative coherence" are judgments no formula can capture.

**Coherence matters.** When positioning is bullish but narrative is bearish (or vice versa), that's a `fractured` consensus — inherently less stable and more prone to sharp reversals. The system explicitly surfaces this.

### 1.4 What Signals Carry Consensus Information

While the quantitative scorer handles derivatives/flow data, several other sources carry embedded consensus:

| Source | What It Tells Us About Consensus |
|---|---|
| **Prediction Markets** (Kalshi + Polymarket) | Real-money probability estimates for macro events. If Kalshi prices "Fed rate cut by June" at 85%, that IS consensus. |
| **Economic Calendar** | Consensus forecasts for upcoming releases (e.g., "NFP consensus: +180k"). The "consensus" column is literally the market's expected number. |
| **COT Positioning** | Net speculative positioning in futures. Max-long EUR specs = consensus-bullish EUR. |
| **Funding Rates** | Leveraged positioning in crypto perpetuals. High positive funding = market consensus is long. |
| **Fear & Greed Index** | Composite crowd sentiment (0-100). High greed = consensus-bullish. |
| **RSS News / Reddit** | Media narrative reflects what the market broadly believes. Dominant headlines approximate consensus. |
| **Market Data** (yfinance) | Price action IS the market's revealed preference. Prices already reflect consensus. |

---

## Part 2: Phase 2 — Non-Consensus Discovery

**File:** `ai/chains/non_consensus_discoverer.py`
**Prompt:** `ai/prompts/templates.py`, `NON_CONSENSUS_DISCOVERY_PROMPT` (line ~367)

Phase 2 takes the Phase 1 consensus views and asks: "Where do our alpha signals disagree?"

### 2.1 Alpha Signal Collection and Filtering

`collect_signals_by_role("alpha")` gathers signals from alpha sources, then `filter_stale_signals()` removes old data:
- **Crypto sources**: 5-day limit
- **Other sources**: 10-day limit
- **Forward-looking signals** (e.g., economic calendar events): never filtered

### 2.2 LLM Non-Consensus Discovery

The LLM acts as a "contrarian research analyst" and searches for **specific disagreements** between alpha signals and established consensus. For each disagreement, it must evaluate:

1. **What consensus believes** — citing the Phase 1 consensus data
2. **What our signals say differently** — citing specific signal IDs from the alpha set
3. **The mechanism** — why consensus could be wrong (not just "vibes")
4. **Independent source count** — how many distinct sources support our view
5. **Invalidation condition** — what would prove our non-consensus view wrong
6. **Timing edge** — whether there's a temporal advantage

### 2.3 Validity Filtering (Hardcoded Rules)

After LLM parsing, a critical quality gate is applied (`non_consensus_discoverer.py`, lines 96-103):

```python
if view.independent_source_count < 2:
    # DROPPED — requires at least 2 independent sources
    continue
```

**This is the single most important filter.** A non-consensus view supported by only one source is noise. Two or more independent sources suggesting the same contrarian conclusion is a signal worth investigating.

Views that pass are sorted by `validity_score` descending.

### 2.4 Non-Consensus View Schema

**File:** `models/schemas.py`, lines 355-373, `NonConsensusView`:

| Field | Type | Purpose |
|---|---|---|
| `ticker` | str | Asset symbol |
| `consensus_direction` | str | What Phase 1 said the market believes |
| `consensus_narrative` | str | Summary of the consensus view |
| `our_direction` | str | Our contrarian direction |
| `our_conviction` | float | 0-1 confidence in our contrarian view |
| `thesis` | str | Why we disagree with consensus |
| `edge_type` | str | `contrarian`, `more_aggressive`, `more_passive`, `aligned` |
| `evidence` | list[EvidenceSource] | Signal citations (signal_id, source, summary, strength) |
| `independent_source_count` | int | Must be ≥ 2 to survive filtering |
| `has_testable_mechanism` | bool | Is the thesis causally grounded? |
| `has_timing_edge` | bool | Do we have a temporal advantage? |
| `has_catalyst` | bool | Is there a specific trigger event? |
| `invalidation` | str | What would prove us wrong |
| `validity_score` | float | 0-1 overall quality score (LLM-assigned) |

### 2.5 Edge Types

The `edge_type` classification captures the nature of the disagreement:

| Edge Type | Meaning |
|---|---|
| `contrarian` | Our signals point in the **opposite direction** to consensus |
| `more_aggressive` | Same direction, but our signals suggest a **bigger move** than consensus expects |
| `more_passive` | Same direction, but our signals suggest **less conviction** than consensus shows |
| `aligned` | Our view matches consensus (lowest alpha potential — flagged honestly) |

---

## Part 3: Phase 3 — Scoring, Trading, and Presentation

### 3.1 Narrative Extraction from Non-Consensus Views

**File:** `ai/chains/narrative_extractor.py`

`extract_narratives_from_nc_views()` takes validated non-consensus views + consensus views + all signals and organizes them into coherent narratives via `NARRATIVE_FROM_NC_VIEWS_PROMPT`.

Key difference from legacy narrative extraction: **directions and edge analysis are already determined by Phase 2.** The LLM is organizing and enriching, not discovering. It may also add 1-2 "aligned" narratives where signals genuinely agree with consensus.

Each `Narrative` contains:
- `title`, `confidence` (0-1), `summary`
- Per-asset `AssetSentiment` objects with: `direction`, `conviction`, `rationale`, `consensus_view`, `edge_type`, `edge_rationale`, `catalyst`, `exit_condition`

### 3.2 Sentiment Aggregation

**File:** `analysis/sentiment_aggregator.py`

`aggregate_asset_scores()` is the bridge between LLM narratives and the deterministic composite scorer. It collapses multiple narrative opinions about the same asset into a single `WeeklyAssetScore`.

**Why it exists:** A single asset (e.g., BTC) may appear in 3-5 different narratives, each with its own direction and conviction. The sentiment aggregator resolves these multiple votes into one number per asset.

**How it works:**

1. **Collect votes**: For each asset across all narratives, extract direction (+1 bullish, -1 bearish, 0 neutral) and compute weight = `conviction × narrative.confidence`.

2. **Weighted average**: `score = Σ(direction_val × weight) / Σ(weight)` — a single float in [-1, +1].

3. **Direction thresholds**: score > +0.15 → bullish, < -0.15 → bearish, else neutral.

4. **Additional metadata**: average conviction, narrative count, and the highest-weight narrative title (`top_narrative`).

**Example:** BTC appears in 3 narratives:
- Narrative A (confidence 0.8): bullish, conviction 0.9 → weight 0.72, vote +1
- Narrative B (confidence 0.7): bullish, conviction 0.7 → weight 0.49, vote +1
- Narrative C (confidence 0.5): bearish, conviction 0.4 → weight 0.20, vote -1

Score = (0.72×1 + 0.49×1 + 0.20×-1) / (0.72 + 0.49 + 0.20) = **+0.716** → bullish

**Output:** `WeeklyAssetScore` per asset, sorted by `abs(score)` descending.

**How it feeds into composite scoring:** The `.score` field from each `WeeklyAssetScore` becomes the **narrative component** (`nar_score`) in the composite scorer, where it receives **50% weight** — the single largest contributor to the final composite score. The list of `WeeklyAssetScore` objects is passed directly as the `asset_scores` parameter to `compute_composite_scores()`.

```
Narratives (3-8, from LLM)
  → each contains AssetSentiment per ticker (direction + conviction)
    → sentiment_aggregator: weighted average across narratives per ticker
      → WeeklyAssetScore.score (one float per asset, [-1, +1])
        → composite_scorer: nar_score = asset.score, weighted at 50%
          → final composite = 0.50 × nar_score + 0.25 × tech + 0.25 × scenario + nudge
```

### 3.3 Composite Scoring

**File:** `analysis/composite_scorer.py`

`compute_composite_scores()` combines the sentiment aggregation output with two other pillars plus a nudge:

```
composite = W_NARRATIVE × nar_score + W_TECHNICAL × tech_score + W_SCENARIO × scen_score + nudge

Where:
  W_NARRATIVE = 0.50  (from sentiment_aggregator — weighted vote across narratives)
  W_TECHNICAL = 0.25  (RSI > 50, MACD histogram > 0, price > SMA20 — each ±1, averaged)
  W_SCENARIO  = 0.25  (from transmission mechanism matching — probability × magnitude × direction)
```

The `asset_scores` parameter (list of `WeeklyAssetScore`) drives both the narrative component values AND the list of tickers to score — if an asset wasn't mentioned in any narrative, it won't get a composite score at all.

### 3.4 The Nudge: Incentivizing Non-Consensus

The nudge is where the system structurally rewards non-consensus thinking. There are two modes:

#### Three-Phase Pipeline: NC Validity-Based Nudge (`_nc_validity_nudge`)

When `non_consensus_views` is provided:

| Condition | Nudge | Rationale |
|---|---|---|
| No NC view for this asset | **-0.05** | Consensus-following gets penalized |
| Has NC view | **+0.05 + validity_score × 0.15** | Range: +0.05 to +0.20, scaled by evidence quality |

This means a well-validated contrarian view (validity_score = 1.0) gets a +0.20 nudge, while an asset with no contrarian thesis gets a -0.05 penalty.

#### Legacy Pipeline: Divergence-Based Nudge (`_divergence_nudge`)

When no NC views exist (legacy mode):

| Divergence | Nudge | Rationale |
|---|---|---|
| \|divergence\| > 0.5 | **±0.15** | Strong disagreement rewarded |
| \|divergence\| > 0.2 | **±0.08** | Moderate disagreement rewarded |
| \|divergence\| ≤ 0.2 | **-0.05** | Consensus-following penalized |

**Final score** = clamp(pre_nudge + nudge, -1.0, +1.0)

### 3.5 Divergence Computation

**File:** `analysis/consensus_scorer.py`, `compute_divergence()`

Computes `our_composite_score - consensus_score` per asset:

| Divergence Magnitude | Label |
|---|---|
| > 1.0 | `strongly_contrarian` |
| > 0.5 | `contrarian` |
| > 0.2 | `mildly_non_consensus` |
| ≤ 0.2 | `aligned` |

### 3.6 Trade Thesis Generation

**File:** `analysis/outcome_tracker.py`

`generate_trade_theses()` creates structured trade entries with:
- Entry price (current market)
- Take-profit % and stop-loss %
- Risk/reward ratio
- Max holding period (7 days)
- `consensus_score_at_entry`, `our_score_at_entry`, `divergence_at_entry`

### 3.7 The Phase 2 → Phase 3 Disconnect: Consensus Assets Leak Through

There is a structural disconnect between Phase 2 (non-consensus discovery) and Phase 3 (scoring). In an ideal world, the whole point of the three-phase pipeline is to identify where we disagree with the market and only trade those disagreements. But that's not what happens — consensus-aligned assets still get scored, presented, and traded alongside non-consensus ones.

**Where the leak happens:**

```
Phase 2 output: NC views for maybe 2-3 assets (e.g., BTC bearish, ETH bearish)
                                    ↓
Phase 3, step 3.1: NARRATIVE_FROM_NC_VIEWS_PROMPT tells the LLM:
  "You may also identify 1-2 ALIGNED narratives where our signals agree
   with consensus — but flag them honestly as aligned"
                                    ↓
LLM produces 3-8 narratives containing assets from NC views AND new
consensus-aligned assets (Gold, DXY, S&P 500, etc.) that Phase 2
never examined or validated
                                    ↓
Step 3.2: sentiment_aggregator scores ALL assets from ALL narratives —
no filtering by whether the asset has an NC view
                                    ↓
Step 3.3: composite_scorer scores ALL assets from the aggregator.
Assets without NC views get a -0.05 nudge penalty, but still get
scored and ranked alongside NC assets
                                    ↓
Dashboard: ALL scored assets are displayed — NC and consensus-aligned
side by side. The only distinction is a small "NC" badge on cards
that have a NonConsensusView.
```

**The specific problems:**

1. **The LLM in step 3.1 has no hard constraint on which assets it can include.** It's told to organize NC views into narratives, but the prompt explicitly allows "1-2 aligned narratives." In practice, the LLM often introduces 5-10+ assets across all narratives — most of which were never part of any NC view. These assets enter the scoring pipeline purely on the LLM's initiative, with no Phase 2 validation, no minimum source requirement, no validity score.

2. **The -0.05 penalty is too weak to matter.** A consensus-aligned asset with a strong narrative score (say +0.7) and strong technicals (+0.33) gets a pre-nudge of ~0.53. After the -0.05 penalty, it's still +0.48 — a high-conviction score that ranks above many NC assets. The penalty is cosmetic, not structural.

3. **Trade theses are generated for ALL composite-scored assets**, not just those with NC views. So the system generates entry/exit/TP/SL for consensus trades it was never designed to find edge in.

4. **The dashboard doesn't clearly separate NC from consensus trades.** Both appear in the same BULLISH/BEARISH/NEUTRAL groupings, sorted by absolute composite score. A user scanning the dashboard sees Gold at +0.48 (aligned) ranked above BTC at +0.35 (contrarian) and might reasonably assume Gold is the higher-conviction trade — even though BTC has a validated non-consensus thesis and Gold doesn't.

**What an ideal pipeline would look like:**

In a pure non-consensus system, Phase 3 would only score assets that survived Phase 2's quality gate:

```
Phase 2 output: NC views for BTC (bearish), ETH (bearish)
                                    ↓
Phase 3: ONLY build narratives around BTC and ETH
         ONLY score BTC and ETH
         ONLY generate trades for BTC and ETH
                                    ↓
Dashboard: Show ONLY the 2 validated non-consensus trades
           Consensus section (Phase 1) provides context, not trades
```

This would mean fewer trades per week (maybe 1-3 instead of 8-15), but each one would have the full Phase 1 consensus → Phase 2 disagreement → Phase 3 scoring chain behind it. No asset would appear in the output without a validated reason to believe we see something the market doesn't.

**Why the current design allows the leak:**

The system was likely designed this way as a pragmatic compromise. If Phase 2 finds no valid NC views (all filtered out by the ≥2 source requirement), the pipeline would produce zero trades. By allowing the LLM to also surface "aligned" narratives, the system always has something to show. The `-0.05` nudge is a nod toward penalizing consensus, but it's a soft nudge, not a hard gate.

There's also a coverage argument: if the system only traded NC assets, it would miss strong trend-following opportunities where consensus happens to be right. But this contradicts the stated philosophy — if the goal is "non-consensus and right," consensus trades dilute the signal.

### 3.8 The Scoring Problem: Composite Score Works Against Non-Consensus

Beyond the leak, there's a deeper issue: **the composite score formula structurally dampens non-consensus trades.** The 50/25/25 weighting was designed for the legacy pipeline where all trades are scored uniformly. In the three-phase pipeline where the goal is contrarian trades, the formula actively fights them.

**Why the math punishes contrarian calls:**

Consider Phase 1 says consensus is bullish BTC (+0.60), and Phase 2 finds a valid bearish contrarian view. In Phase 3:

```
Narrative score (50%):  LLM says bearish from NC view → maybe -0.5
                        But "aligned" narratives dilute this → realistically -0.3 to -0.5

Technical score (25%):  If consensus is bullish, price is trending UP.
                        RSI > 50 (+1), MACD > 0 (+1), price > SMA20 (+1)
                        Tech score = +1.0 (maximum bullish)

Scenario score (25%):   Bullish consensus often aligns with active bullish mechanisms
                        Scenario = +0.3 (say)

NC nudge:               +0.05 + 0.75 × 0.15 = +0.16 (good validity)

Composite:  0.50 × (-0.4) + 0.25 × (+1.0) + 0.25 × (+0.3) + 0.16
          = -0.20 + 0.25 + 0.075 + 0.16
          = +0.285 (BULLISH!)
```

**The contrarian bearish view produces a bullish composite score.** The 25% technical weight is the main culprit — technicals are backward-looking by definition. They measure the trend that consensus already established. When you're contrarian, technicals will almost always vote against you because you're betting on a trend reversal that hasn't started yet.

Even in a best-case scenario where narrative is strongly bearish (-0.7) and scenario is neutral (0.0):

```
0.50 × (-0.7) + 0.25 × (+1.0) + 0.25 × (0.0) + 0.16
= -0.35 + 0.25 + 0.0 + 0.16 = +0.06 (NEUTRAL)
```

The contrarian call can barely reach neutral, let alone bearish. The system would need technicals to also flip bearish (RSI < 50, MACD < 0, price < SMA20) — but if technicals have already flipped, the contrarian view is no longer early; it's consensus.

**The fundamental contradiction:**

The composite scorer rewards trades where all three pillars agree (narrative + technical + scenario). But by definition, a non-consensus trade has at least one pillar disagreeing — usually technicals, because technicals reflect the consensus trend. The scoring system is optimized for trend-following consensus trades, while the three-phase pipeline is designed to find contrarian ones.

**What this means in practice:**

- NC trade scores cluster in the **-0.15 to +0.15 range** (neutral zone), regardless of NC validity
- The absolute composite score is nearly meaningless for NC trades — a +0.10 NC trade may have a stronger thesis than a +0.50 consensus trade
- Ranking by `abs(composite_score)` pushes NC trades to the bottom of the dashboard, below consensus-aligned trades that score higher because all their pillars agree
- The direction label (BULLISH/BEARISH/NEUTRAL) can literally invert the NC view's direction when technicals dominate

**The scoring is arguably redundant for NC trades.** Phase 2 already produces everything needed to evaluate a non-consensus trade:
- `our_direction` — which way to trade
- `our_conviction` — how confident we are (0-1)
- `validity_score` — evidence quality (0-1)
- `independent_source_count` — breadth of evidence
- `has_testable_mechanism`, `has_timing_edge`, `has_catalyst` — quality flags
- `invalidation` — when we're wrong

Re-scoring this through a composite formula that includes backward-looking technicals adds noise, not signal. The NC view's own conviction × validity is a more honest measure of trade quality than a composite that's structurally biased toward consensus direction.

**Possible fixes (not yet implemented):**

1. **Hard gate in composite scorer**: Skip assets without an NC view entirely (or make it configurable).
2. **Separate trade lists**: NC trades (primary, ranked by validity × conviction) and consensus trades (secondary/informational), clearly separated in the dashboard.
3. **Constrain the narrative prompt**: Remove the "1-2 aligned narratives" allowance, or limit asset sentiments to only tickers that appear in `non_consensus_views`.
4. **NC-specific scoring**: For assets with NC views, replace the composite formula entirely — use `conviction × validity_score` as the rank, and use the NC view's `our_direction` directly instead of deriving direction from a composite that technicals will invert.
5. **Drop or downweight technicals for NC trades**: If keeping the composite, reduce technical weight to 0% for assets with NC views (technicals are actively misleading for contrarian trades) and redistribute to narrative + scenario.
6. **Use technicals as confirmation, not score input**: Instead of weighting technicals into the composite, use them as a filter — only flag when technicals start confirming the NC direction (e.g., MACD crossover in the contrarian direction = "technical confirmation emerging"), which would be a signal to increase conviction, not a score component that fights the thesis.

---

## Part 4: Data Storage

**File:** `storage/store.py`

SQLite database (`macro_pulse.db`) with tables:

| Table | Content |
|---|---|
| `weekly_reports` | Regime, summary, signal count |
| `narratives` | Title, asset_sentiments (JSON), edge_type |
| `signals` | Raw signal data |
| `narrative_signals` | Many-to-many link |
| `weekly_asset_scores` | Per-asset direction/score |
| `active_scenarios` | Transmission mechanism matches |
| `scenario_asset_views` | Aggregated scenario outlook per asset |
| `composite_scores` | Full composite breakdown (narrative/technical/scenario/nudge) |
| `consensus_scores` | Quantitative consensus per asset (6 components) |
| `consensus_views` | Phase 1 consensus picture per asset |
| `non_consensus_views` | Phase 2 non-consensus views per asset |
| `trade_theses` | Structured trades with entry/exit levels |
| `trade_outcomes` | Resolved trade results |

`save_report()` persists the entire `WeeklyReport` into all tables. `load_latest_report()` reconstructs the full object.

**Important:** Divergence metrics are **recomputed on the fly** when loading (lines 870-898 in store.py), not stored. This ensures consistency if scoring logic changes.

---

## Part 5: Dashboard Display

**File:** `dashboard/actionable_view.py`

**Entry point:** `render_actionable_view()` (line 1598)

### 5.1 Render Order

1. **Regime Banner** — macro regime classification (risk_on / risk_off / reflation / stagflation / goldilocks / transition) with rationale and summary.

2. **Two Tabs**: "ASSET CALLS" and "PERFORMANCE"

Within the ASSET CALLS tab, three major sections render in order:

### 5.2 Consensus Section (`_render_consensus_section`, line 1466)

Only renders if `report.consensus_views` exists (three-phase pipeline runs).

Displays consensus cards in columns (up to 3 per row). Each card shows:
- **Ticker** and **direction badge** (BULLISH / BEARISH / NEUTRAL)
- **Quant score** from the quantitative scorer
- **Coherence badge** (ALIGNED / FRACTURED / DIVERGENT) — whether positioning and narrative agree
- **Confidence %** — LLM's confidence in its consensus read
- **Positioning summary** — how money is deployed
- **Market narrative** — dominant story
- **Key levels** — important price levels
- **Priced in** — what the market has already discounted
- **Not priced in** — what the market hasn't discounted yet

### 5.3 Non-Consensus Section (`_render_non_consensus_section`, line 1522)

Only renders if `report.consensus_views` exists (gating condition).

Each non-consensus card shows:
- **Ticker** and **edge type badge** (CONTRARIAN / MORE_AGGRESSIVE / etc.)
- **Direction comparison**: `consensus_direction → our_direction`
- **Thesis** — why we disagree
- **Evidence list** — each evidence source with checkmark, source badge, summary
- **Validity bar** (0-100%) — visual quality indicator
- **Catalyst** — specific trigger event (if any)
- **Invalidation** — what would prove us wrong

### 5.4 Consensus Meter (`_consensus_meter_html`, line 1225)

Rendered per asset that has a `ConsensusScore`. A visual bar from BEARISH to BULLISH with:
- **Teal marker** — consensus position on the spectrum
- **Orange marker** — "our" composite score position
- **Divergence badge** (STRONGLY CONTRARIAN / CONTRARIAN / MILDLY NON CONSENSUS / ALIGNED) with color coding
- **Expandable components breakdown** — shows individual component scores (options_skew, funding_7d, etc.)

### 5.5 Asset Cards

Branching logic at line 1643:
- If scenario views exist → **scenario-based cards** (`_render_scenario_view`)
- Otherwise → **legacy narrative-based cards** (`_render_legacy_view`)

Both views:
- **Group assets by direction**: BULLISH section, BEARISH section, NEUTRAL section
- **Sort within each group** by `abs(composite_score)` descending (highest conviction first)
- **Filter** by selected asset classes, direction, and minimum threshold

Each asset card displays:
- Ticker, asset class, direction badge, composite score
- **NC badge** ("NC" checkmark) — shown if the asset has a `NonConsensusView` in `report.non_consensus_views`
- **Composite score breakdown**: NAR / TECH / SCEN / EDGE components
- Rationale, catalyst, exit condition
- Technical indicators (collapsible)
- **Consensus vs. Edge block** — shows edge type badge (CONTRARIAN / MORE_AGGRESSIVE / etc.), consensus view text, "OUR EDGE" rationale text
- Source signal details (collapsible per-source with links)
- Additional narratives (collapsible)

**Direction for grouping** uses `composite_score.direction` when available, falling back to scenario `net_direction`.

### 5.6 Trade Thesis Display (`_trade_thesis_html`, line 1315)

Each trade shows:
- Entry price, take-profit level, stop-loss level
- Risk/reward ratio
- Max holding period
- Resolved outcome (if trade has been scored)

---

## Part 6: Google Sheets Export

**File:** `exports/sheets.py`

Exports to 7 worksheets:

| Worksheet | Content |
|---|---|
| **Summary** | Week, regime, signal count, summary |
| **Asset Scores** | Full composite breakdown per asset |
| **Scenarios** | Matched transmission mechanisms |
| **Trades** | Structured trade theses with entry/exit levels |
| **Consensus** | Quantitative consensus scores with raw component data |
| **Consensus Views** | Phase 1 consensus picture (positioning, narrative, coherence, priced-in/not-priced-in) |
| **Non-Consensus Views** | Phase 2 disagreements (consensus direction, our direction, thesis, evidence, validity score) |

Also has `sync_trades_to_sheets()` for idempotent reconciliation of trades and outcomes.

---

## Part 7: Contrarian Signal Interpretation

Certain data sources are interpreted **opposite to their face value**:

| Signal | Naive Reading | Our Interpretation | Why |
|---|---|---|---|
| Google Trends spike for "recession" | Bearish — people worried | **Bullish** — retail panic marks short-term bottoms | By the time retail searches, institutions have already positioned |
| Crypto Fear & Greed < 20 | Danger — extreme fear | **Buying opportunity** — capitulation = bottom | Crowds panic-sell at lows, not highs |
| Crypto Fear & Greed > 80 | Good times — greed | **Sell signal** — euphoria = top | Crowds FOMO-buy at highs |
| Funding rate > 0.03% | Longs are confident | **Bearish** — crowded longs = liquidation cascade risk | Leveraged positioning creates fragility |
| Funding rate < -0.01% | Shorts are confident | **Bullish** — crowded shorts = short squeeze potential | Same fragility, opposite direction |

These aren't arbitrary flips. They're based on a structural observation: **crowded positioning creates the fuel for its own reversal.**

### 7.1 Deep Dive: Funding Rates as Flipped Signals

Funding rates are the most nuanced "flipped" signal in the system. They appear in **two different roles** and are interpreted differently in each.

#### What Funding Rates Actually Are

In crypto perpetual futures (contracts with no expiry), the funding rate is a periodic payment (every 8 hours) between longs and shorts that keeps the perpetual price anchored to spot. When the perp trades **above** spot, funding is positive — longs pay shorts. When it trades **below** spot, funding is negative — shorts pay longs. The rate reflects the aggregate willingness of leveraged traders to pay a premium to maintain their directional bet.

#### How Funding Rates Are Collected

Two collectors fetch funding data, each with a different purpose:

**`collectors/funding_rates.py`** (FundingRatesCollector) — Broad crypto coverage:
- Fetches from CoinGlass (primary) or Binance FAPI (fallback)
- Covers BTC, ETH, SOL
- Emits the current 8-hour rate, 7-day average, and conditional leverage alerts
- **Interprets at the signal level** with hardcoded thresholds baked into the signal text

**`collectors/derivatives_consensus.py`** (DerivativesConsensusCollector) — Multi-exchange consensus:
- Fetches from Binance, Bybit, and OKX via ccxt (or Binance httpx fallback)
- Covers BTC and ETH only
- Computes **OI-weighted funding rate** across exchanges (larger exchanges count more)
- Fetches 7-day historical funding (21 settlements) and computes accumulated cost
- Also collects long/short ratios, OI changes, and builds a composite summary

#### The "Flip" Logic: Where and How

The contrarian interpretation happens at **three layers**:

**Layer 1 — Signal text (collector level).** The collector bakes the interpretation directly into the signal content string that the LLM reads:

```python
# From funding_rates.py _interpret_funding():
if rate >= 0.05:   # EXTREME_LONG_THRESHOLD
    "EXTREME crowded longs — high liquidation risk within 1-3 days"
if rate >= 0.03:   # CROWDED_LONG_THRESHOLD
    "Leveraged longs crowded — BEARISH contrarian signal"
if rate <= -0.03:  # EXTREME_SHORT_THRESHOLD
    "EXTREME crowded shorts — strong short squeeze potential"
if rate <= -0.01:  # CROWDED_SHORT_THRESHOLD
    "Leveraged shorts crowded — BULLISH short squeeze setup"
```

The signal content explicitly says `"Funding rate >0.03% means leveraged longs are crowded (bearish contrarian). Funding rate <-0.01% means shorts are crowded (bullish, short squeeze setup)."` — so the LLM reads the contrarian framing directly.

Similarly, the derivatives consensus collector interprets L/S ratios in contrarian terms:
```python
# From derivatives_consensus.py _build_ls_signal():
if ratio > 1.2:   "Retail heavily long — bearish contrarian signal"
if ratio < 0.8:   "Retail heavily short — bullish contrarian signal"
```

**Layer 2 — Conditional leverage alerts.** When funding hits extreme levels (>0.05% or <-0.03%), the collector emits an additional **high-priority "LEVERAGE ALERT"** signal with text like: `"This level historically precedes liquidation cascades within 1-3 days."` This separate signal amplifies the contrarian reading because the LLM sees two signals from the same source — the base reading plus the alert.

**Layer 3 — Quantitative consensus score (scorer level).** In `analysis/consensus_scorer.py`, funding enters the 6-component consensus score **without any flip** — it's treated as a **straight consensus indicator**:

```python
# funding_7d normalized to [-1, +1] against range (-0.10, 0.10)
# Positive accumulated funding → positive component → bullish consensus reading
funding_signal = _normalize(funding_7d, -0.10, 0.10)
```

This is the critical distinction: **in the consensus score, positive funding = bullish consensus (the market IS long). In the signal text, positive funding = bearish contrarian (the market is crowded long, therefore vulnerable).** Both are correct — they answer different questions:
- Consensus score asks: "What direction is the market positioned?" → Positive funding = bullish positioning.
- Contrarian signal asks: "Is that positioning a vulnerability?" → Positive funding = yes, longs are crowded.

The flip happens **between layers**: the consensus scorer measures the crowd's direction, then the non-consensus discoverer (Phase 2) reads the signal text that says this very positioning is a vulnerability, and uses it as evidence for a contrarian thesis.

#### Thresholds Summary

| Rate (8h) | Collector Interpretation | Consensus Score Direction | Contrarian Implication |
|---|---|---|---|
| > +0.05% | EXTREME crowded longs | Strongly bullish consensus | **Bearish** — liquidation cascade imminent (1-3 days) |
| > +0.03% | Crowded longs | Bullish consensus | **Bearish** — longs paying unsustainable premium |
| +0.01% to +0.03% | Mild long bias | Mildly bullish | Neutral — normal bull market funding |
| -0.01% to +0.01% | Neutral | Neutral | No signal — balanced market |
| < -0.01% | Crowded shorts | Bearish consensus | **Bullish** — shorts paying premium, squeeze setup |
| < -0.03% | EXTREME crowded shorts | Strongly bearish consensus | **Bullish** — strong short squeeze potential |

#### The Dual Role in Practice

Consider a concrete scenario: BTC 7-day accumulated funding is +0.08%.

1. **Phase 1 (Consensus):** The consensus scorer normalizes +0.08 against range (-0.10, +0.10), producing a `funding_7d` component of **+0.80** (strongly bullish). This contributes to a bullish consensus score — correctly capturing that the market is positioned long.

2. **Phase 2 (Non-Consensus):** The LLM reads the signal text: *"BTC accumulated funding over 7 days: +0.08%. Persistent positive funding means longs have been paying shorts consistently — this is the cost of bullish consensus. When accumulated funding is extreme, mean reversion typically follows."* Combined with other alpha signals (e.g., declining on-chain inflows, rising Google Trends for "Bitcoin"), the LLM may produce a NonConsensusView: *"Consensus is bullish (crowded longs paying 0.08%/week), but our signals suggest the crowded position is fragile. Edge type: contrarian."*

3. **Phase 3 (Scoring):** The composite score weighs the bullish narrative (if any narratives are bullish) against the bearish non-consensus view. The NC validity nudge adds +0.05 to +0.20 depending on evidence quality.

This dual role — funding as consensus thermometer AND as contrarian trigger — is the core mechanism by which the system simultaneously measures what the market believes and identifies where that belief creates vulnerability.

#### Why This Works (The Structural Argument)

Perpetual futures funding creates a **self-reinforcing loop that eventually breaks**:

1. Price rises → perp premium over spot → positive funding → longs pay shorts
2. Despite paying funding, longs stay because price keeps rising → more longs enter → funding increases
3. At some point, the cost of carrying longs becomes prohibitive OR a small price dip triggers margin calls
4. Liquidated longs force-sell → price drops → more liquidations → **cascade**
5. Funding snaps negative → the crowd has flipped

The same mechanism works in reverse for crowded shorts. The key insight is that **the funding rate measures the energy stored in the spring** — the higher the absolute rate, the more potential energy for a reversal. The system captures this by reading high funding as both "the crowd is confident" (consensus) and "the crowd is fragile" (contrarian).

---

## Part 8: Transmission Mechanism Timing

The system matches signals against a catalog of 28 known causal chains, of which 11 are currently enabled across 3 categories:

| Active Category | Mechanisms |
|---|---|
| Monetary Policy (3) | Fed Dovish Pivot, Fed Hawkish Surprise, + 1 more |
| Risk Sentiment (3) | Risk-Off Flight to Safety, Risk-On Rotation, VIX Mean Reversion |
| Crypto-Specific (5) | Crypto Leverage Flush, Stablecoin Liquidity Shift, Crypto Narrative Momentum, + 2 more |

Each mechanism defines **chain steps with expected lags** (0-14 days) and a **current stage** (early / mid / late / complete).

This creates timing edge. Example:

```
Fed signals dovish hold (Day 0, confirmed)
  → Rate expectations reprice (Day 0-3, emerging)
    → Real yields decline (Day 1-5, not started yet)
      → DXY weakens, Gold rallies, Bitcoin rallies (Day 2-7, not started)
```

If we're at the "emerging" stage for rate repricing, the asset-level moves haven't happened yet. We're positioning **before the market fully prices the chain.**

Remaining 17 mechanisms across 7 categories (geopolitical, China/EM, commodity, fiscal, credit, bonds, FX) are defined but disabled.

---

## Part 9: Three Independent Scoring Pillars

```
┌─────────────────────────────────┐
│  NARRATIVE SCORE (50%)          │  LLM-derived direction × conviction
│  from sentiment_aggregator      │  across all narratives mentioning this asset
├─────────────────────────────────┤
│  TECHNICAL SCORE (25%)          │  RSI(14) + MACD(12,26,9) + SMA(20) distance
│  from technicals.py             │  pure price-action, no opinion
├─────────────────────────────────┤
│  SCENARIO SCORE (25%)           │  Σ(mechanism_probability × magnitude × direction)
│  from scenario_aggregator       │  causal chain weighted by probability
├─────────────────────────────────┤
│  NC NUDGE (+0.20 to -0.05)     │  Rewards validated non-consensus views
│  from composite_scorer          │  Penalizes consensus-following
└─────────────────────────────────┘
```

**Why this architecture helps correctness**: If narrative says bullish but technicals say overbought (RSI > 70) and scenarios are conflicting, the composite dampens the signal. The system flags this as a **conflict** — reducing false confidence.

When all three pillars agree AND the view is contrarian with high validity, that's the highest-conviction setup: non-consensus AND multi-factor confirmed.

---

## Part 10: The Full Pipeline (End-to-End)

```
Week N:

┌─── PHASE 1: CONSENSUS ─────────────────────────────────────────────┐
│                                                                     │
│  1. COLLECT consensus signals (positioning + narrative sources)     │
│  2. QUANT SCORE derivatives/flows into ConsensusScore per asset    │
│  3. LLM SYNTHESIZE consensus picture (positioning + narrative +    │
│     coherence + priced-in/not-priced-in) → ConsensusView per asset │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─── PHASE 2: NON-CONSENSUS ─────────────────────────────────────────┐
│                                                                     │
│  4. COLLECT alpha signals (spreads, trends, on-chain, economic)    │
│  5. FILTER stale signals (5-day crypto, 10-day others)             │
│  6. LLM DISCOVER disagreements between alpha signals and Phase 1   │
│     consensus → NonConsensusView per asset                          │
│  7. FILTER views with < 2 independent sources (quality gate)       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─── PHASE 3: SCORE & PRESENT ───────────────────────────────────────┐
│                                                                     │
│  8. NARRATE: LLM organizes NC views into coherent narratives       │
│  9. MATCH: LLM matches signals to transmission mechanisms          │
│  10. CLASSIFY: LLM determines economic regime                      │
│  11. AGGREGATE: Weighted average of narrative votes per asset       │
│  12. COMPOSITE: 50% narrative + 25% technical + 25% scenario       │
│      + NC validity nudge → final score per asset                    │
│  13. DIVERGENCE: our_score - consensus_score per asset              │
│  14. TRADE: Generate structured trade theses with entry/exit       │
│  15. STORE: Persist to SQLite                                       │
│  16. PRESENT: Streamlit dashboard with full breakdown               │
│  17. EXPORT: Google Sheets with 7 worksheets                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 11: Where the Edge Actually Is

### The Strongest Edge Cases

The system is most likely to be **non-consensus AND correct** when:

1. **Crowded positioning + catalyst**: Funding rates extreme AND upcoming event (FOMC, CPI) that could trigger unwind. The crowd is levered one way, and a catalyst is approaching.

2. **Mechanism early-stage + technical confirmation**: A transmission mechanism is in early stage (e.g., Fed just signaled dovish), technicals already turning (MACD crossover), but asset price hasn't moved yet.

3. **Cross-source convergence on contrarian view**: News is bearish (everyone scared), but hard data improving (FRED series), positioning already capitulated (COT extremes), and on-chain flows are bullish (stablecoin inflows). The narrative hasn't caught up to reality.

4. **Fractured consensus coherence**: When Phase 1 shows positioning and narrative disagree (`fractured` coherence), the consensus is unstable and more likely to break one way.

5. **High validity NC views with catalysts**: NonConsensusView with validity_score > 0.7, has_testable_mechanism = true, has_catalyst = true, independent_source_count ≥ 3.

### The Weakest Edge Cases

The system is most likely to be **wrong** when:

1. **No NC views survive filtering**: If no contrarian thesis has 2+ independent sources, the system falls back to consensus-aligned calls with a penalty nudge.

2. **TRANSITION regime**: When the regime classifier says "mixed signals," directional calls are unreliable.

3. **Low validity NC views**: NonConsensusView with validity_score < 0.4 barely clears the quality gate. The nudge is small (+0.05 to +0.11), not enough to meaningfully shift the composite.

4. **Single-narrative dominance**: When one narrative drives most asset scores, a bad LLM interpretation cascades across all assets.

---

## Part 12: What's Missing (Honest Assessment)

### Limited Performance Tracking

The system has trade thesis generation and outcome tracking infrastructure, but historical validation is nascent. Measuring whether non-consensus calls are correct more often than they're wrong requires accumulated data.

### Limited Mechanism Coverage

Only 3 of 10 mechanism categories are active (crypto, monetary_policy, risk_sentiment), enabling 11 of 28 mechanisms. The system is blind to geopolitical transmission, China/EM-specific chains, commodity supply shocks, fiscal policy mechanisms, and credit cycle dynamics.

### Consensus Scoring Limited to BTC/ETH

The quantitative consensus scorer only produces `ConsensusScore` for BTC and ETH. Other assets (Gold, DXY, equities) get consensus views from the LLM only — no quantitative grounding.

### No Source Quality Weighting

A Reuters headline and a Reddit shitpost are treated with equal weight in the signal set. The LLM implicitly weights them, but there's no explicit source reliability scoring.

### LLM Reliability

The narrative extraction, mechanism matching, consensus synthesis, and non-consensus discovery are all LLM-dependent. Claude is good but:
- Can hallucinate causal links not supported by signals
- May anchor on recent, salient events over slow-moving structural shifts
- Consistency across runs is not guaranteed (same signals may produce different narratives)

### No Position Sizing

The system says "bullish Bitcoin, score +0.7" but doesn't say how much to buy. Position sizing, stop losses, and portfolio-level risk are left to the user.

---

## Summary

**How Macro-Pulse determines consensus (Phase 1):**

| Component | Method |
|---|---|
| Quantitative consensus score | 6-component derivatives/flow scorer normalized to [-1, +1] |
| Positioning consensus | LLM synthesis of how money is actually deployed |
| Narrative consensus | LLM synthesis of dominant market beliefs |
| Coherence check | Whether positioning and narrative agree (aligned/fractured/divergent) |
| Priced-in analysis | LLM identifies what is and isn't discounted |

**How Macro-Pulse finds non-consensus (Phase 2):**

| Component | Method |
|---|---|
| Alpha signal collection | Re-examine data through contrarian lens |
| LLM disagreement discovery | Find specific, cited disagreements with Phase 1 consensus |
| Quality gate | ≥ 2 independent sources required |
| Validity scoring | LLM rates evidence quality 0-1 |
| Structural nudge | +0.05 to +0.20 for NC views; -0.05 penalty for consensus-following |

**How Macro-Pulse tries to be correct (Phase 3):**

| Component | Method |
|---|---|
| Three scoring pillars | Narrative (50%) + Technical (25%) + Scenario (25%) must agree |
| Transmission mechanism timing | Positions ahead of causal chain completion |
| Conflict detection | Flags contradictory evidence, dampens false confidence |
| Trade structure | Entry/exit/invalidation defined upfront |
| Regime sanity check | Directional calls must be coherent with macro regime |
