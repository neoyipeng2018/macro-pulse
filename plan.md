# Plan: Simplify Pipeline — Stop at Phase 2, Make It the Whole Product

## The Problem

The three-phase pipeline has a structural contradiction:

- **Phase 1** builds a rigorous consensus picture (quant scoring + LLM synthesis)
- **Phase 2** discovers validated non-consensus views with evidence quality gates
- **Phase 3** re-scores everything through a composite formula that _actively fights contrarian trades_ (technicals vote for consensus trend), _leaks in consensus-aligned assets_ (via aligned narratives), and _ranks NC trades below consensus trades_ (because the composite formula rewards pillar agreement)

Phase 3 is noise. The NC views from Phase 2 already have direction, conviction, validity, evidence, and invalidation. Re-running them through sentiment aggregation → composite scoring → trade thesis generation adds complexity without adding signal.

## The Goal

**Stop at Phase 2. Make Phase 2 the whole product.**

The dashboard should show:
1. What the market believes (Phase 1 consensus) — as context
2. Where we disagree and why (Phase 2 non-consensus views) — as the product
3. What causal chains are driving these views (transmission mechanisms) — as depth
4. Full drill-down into evidence, sources, and signals — as transparency

No composite scores. No sentiment aggregation. No narrative extraction. No trade thesis generation. The NC view IS the trade.

## What Gets Removed

### Files to delete or gut:
- `analysis/sentiment_aggregator.py` — no longer needed (was bridge between narratives and composite)
- `analysis/composite_scorer.py` — no longer needed (composite scoring is the problem)
- `ai/chains/narrative_extractor.py` — remove `extract_narratives_from_nc_views()` (keep `extract_narratives()` for legacy pipeline if desired)

### Models to deprecate:
- `WeeklyAssetScore` — product of sentiment aggregation, no longer computed
- `CompositeAssetScore` — the composite formula is gone
- `DivergenceMetrics` — divergence was composite_score - consensus_score; without composite, this is meaningless
- `Narrative` — no longer extracted in the three-phase pipeline
- `AssetSentiment` — sub-object of Narrative

### Pipeline steps to remove from `run_weekly.py`:
- Phase 3 step 3.1 (narrative extraction from NC views)
- Phase 3 step 3.3 (regime classification) — move to Phase 1 or Phase 2
- Phase 3 step 3.4 (sentiment aggregation)
- Phase 3 step 3.4 continued (composite scoring)
- Phase 3 step 3.5 (divergence computation)
- Phase 3 step 3.6 (trade thesis generation)
- Phase 3 step 3.7 (weekly summary)

### Dashboard sections to remove:
- Asset cards (scenario-based and legacy)
- Consensus meters (divergence display)
- Trade thesis cards
- The entire BULLISH/BEARISH/NEUTRAL grouping

## What Gets Kept

- **Phase 1** (consensus): `run_phase_1()` stays exactly as is
- **Phase 2** (non-consensus): `run_phase_2()` stays, gets expanded
- **Transmission mechanisms**: moved from Phase 3 into Phase 2
- **Regime classification**: moved from Phase 3 into Phase 2
- **ConsensusScore**, **ConsensusView**, **NonConsensusView**, **ActiveScenario** models stay
- **Storage**: consensus_scores, consensus_views, non_consensus_views, active_scenarios tables stay
- **Sheets export**: Consensus, Consensus Views, Non-Consensus Views worksheets stay

## What Gets Added/Expanded

### 1. Mechanism matching moves into Phase 2

Currently in Phase 3. Move it to Phase 2 so NC views can reference which transmission mechanisms support them.

### 2. NC views get enriched with mechanism links

Each `NonConsensusView` should reference the active scenarios that support its thesis. This connects "what we disagree on" with "why, causally."

### 3. The dashboard becomes a deep-dive into NC views

Instead of asset cards with composite scores, the dashboard shows rich NC view cards with full drill-down capability.

## Implementation Steps

### Step 1: Expand the NonConsensusView schema

Add mechanism links and the raw signal data that supports the view.

```python
# models/schemas.py — changes to NonConsensusView

class NonConsensusView(BaseModel):
    """A specific disagreement with market consensus, with evidence."""

    ticker: str
    asset_class: AssetClass
    consensus_direction: SentimentDirection
    consensus_narrative: str = ""
    our_direction: SentimentDirection
    our_conviction: float = 0.0
    thesis: str = ""
    edge_type: str = "contrarian"
    evidence: list[EvidenceSource] = Field(default_factory=list)
    independent_source_count: int = 0
    has_testable_mechanism: bool = False
    has_timing_edge: bool = False
    has_catalyst: str = ""
    invalidation: str = ""
    validity_score: float = 0.0
    signal_ids: list[str] = Field(default_factory=list)
    # --- NEW FIELDS ---
    supporting_mechanisms: list[str] = Field(default_factory=list)  # mechanism_ids
    mechanism_stage: str = ""           # earliest active stage: early/mid/late
    regime_context: str = ""            # how the macro regime relates to this view
    consensus_quant_score: float = 0.0  # from Phase 1 ConsensusScore
    consensus_coherence: str = ""       # from Phase 1 ConsensusView — aligned/fractured
```

### Step 2: Restructure the pipeline — merge Phase 2 + Phase 3

`run_weekly.py` becomes a two-phase pipeline:

```python
# run_weekly.py — new structure

def run_pipeline(sources: list[str] | None = None) -> None:
    """Two-phase pipeline: consensus → non-consensus."""
    phase1 = run_phase_1(sources)
    phase2 = run_phase_2(phase1, sources)
    report = build_report(phase1, phase2)
    save_report(report)
    export_to_sheets(report)


def run_phase_1(sources: list[str] | None = None) -> dict:
    """Phase 1: Build the consensus picture. (UNCHANGED)"""
    # ... exactly as today ...
    return {
        "consensus_signals": consensus_signals,
        "quant_scores": quant_scores,
        "consensus_views": consensus_views,
        "llm": llm,
    }


def run_phase_2(phase1: dict, sources: list[str] | None = None) -> dict:
    """Phase 2: Discover non-consensus views + match mechanisms + classify regime."""
    from ai.chains.non_consensus_discoverer import discover_non_consensus
    from config.mechanisms import load_mechanisms
    from ai.chains.mechanism_matcher import match_mechanisms
    from ai.chains.regime_classifier import classify_regime

    llm = phase1["llm"]

    # 2.1: Collect and filter alpha signals (unchanged)
    alpha_signals = collect_signals_by_role("alpha", sources)
    alpha_signals = filter_stale_signals(alpha_signals)

    all_signals = phase1["consensus_signals"] + alpha_signals

    # 2.2: Match transmission mechanisms (moved from Phase 3)
    mechanisms = load_mechanisms()
    active_scenarios = []
    if mechanisms:
        active_scenarios = match_mechanisms(all_signals, mechanisms, llm)

    # 2.3: Classify regime (moved from Phase 3)
    # Regime now classified from consensus views + active scenarios,
    # not from narratives (which no longer exist)
    regime, regime_rationale, regime_confidence = classify_regime_from_consensus(
        phase1["consensus_views"], active_scenarios, llm
    )

    # 2.4: Discover non-consensus views (unchanged core, but gets mechanism context)
    non_consensus_views = discover_non_consensus(
        consensus_views=phase1["consensus_views"],
        alpha_signals=alpha_signals,
        llm=llm,
    )

    # 2.5: Enrich NC views with mechanism links and consensus data
    non_consensus_views = enrich_nc_views(
        non_consensus_views,
        active_scenarios,
        phase1["quant_scores"],
        phase1["consensus_views"],
        regime,
    )

    return {
        "alpha_signals": alpha_signals,
        "all_signals": all_signals,
        "non_consensus_views": non_consensus_views,
        "active_scenarios": active_scenarios,
        "regime": regime,
        "regime_rationale": regime_rationale,
    }
```

### Step 3: Implement NC view enrichment

Link NC views to supporting mechanisms and consensus context:

```python
# run_weekly.py (or new file: analysis/nc_enricher.py)

def enrich_nc_views(
    nc_views: list[NonConsensusView],
    active_scenarios: list[ActiveScenario],
    quant_scores: list[ConsensusScore],
    consensus_views: list[ConsensusView],
    regime: EconomicRegime,
) -> list[NonConsensusView]:
    """Enrich NC views with mechanism links, quant scores, and regime context."""

    quant_by_ticker = {cs.ticker: cs for cs in quant_scores}
    cv_by_ticker = {cv.ticker: cv for cv in consensus_views}

    for ncv in nc_views:
        # Link supporting mechanisms
        supporting = []
        earliest_stage = "complete"
        stage_order = {"early": 0, "mid": 1, "late": 2, "complete": 3}

        for scenario in active_scenarios:
            # Does this mechanism impact this ticker in the NC direction?
            for impact in scenario.asset_impacts:
                if impact.ticker == ncv.ticker and impact.direction == ncv.our_direction:
                    supporting.append(scenario.mechanism_id)
                    if stage_order.get(scenario.current_stage, 3) < stage_order.get(earliest_stage, 3):
                        earliest_stage = scenario.current_stage
                    break

        ncv.supporting_mechanisms = supporting
        ncv.mechanism_stage = earliest_stage if supporting else ""

        # Attach quant consensus score
        qs = quant_by_ticker.get(ncv.ticker)
        if qs:
            ncv.consensus_quant_score = qs.consensus_score

        # Attach coherence from consensus view
        cv = cv_by_ticker.get(ncv.ticker)
        if cv:
            ncv.consensus_coherence = cv.consensus_coherence

        # Regime context
        ncv.regime_context = regime.value

    return nc_views
```

### Step 4: Adapt regime classification

Currently regime is classified from narratives (which won't exist anymore). Change to classify from consensus views + active scenarios:

```python
# ai/chains/regime_classifier.py — new function

def classify_regime_from_consensus(
    consensus_views: list[ConsensusView],
    active_scenarios: list[ActiveScenario],
    llm: BaseChatModel,
) -> tuple[EconomicRegime, str, float]:
    """Classify regime from consensus picture and active mechanisms."""
    # Build context text from consensus views
    consensus_text = "\n".join(
        f"{cv.ticker}: {cv.consensus_direction.value} "
        f"(quant={cv.quant_score:+.2f}, coherence={cv.consensus_coherence})\n"
        f"  Positioning: {cv.positioning_summary}\n"
        f"  Narrative: {cv.market_narrative[:200]}"
        for cv in consensus_views
    )

    # Active scenarios as context
    scenario_text = "\n".join(
        f"[{s.mechanism_name}] ({s.category}, prob={s.probability:.0%}, "
        f"stage={s.current_stage}): {s.trigger_evidence[:200]}"
        for s in active_scenarios
    ) if active_scenarios else "No active transmission mechanisms."

    # Use existing REGIME_CLASSIFICATION_PROMPT with adapted input
    # (or create a new prompt that takes consensus + scenarios instead of narratives)
    chain = REGIME_FROM_CONSENSUS_PROMPT | llm
    response = chain.invoke({
        "consensus_views": consensus_text,
        "active_scenarios": scenario_text,
    })

    # ... parse response same as today ...
```

### Step 5: Simplify the WeeklyReport model

```python
# models/schemas.py — simplified WeeklyReport

class WeeklyReport(BaseModel):
    """Complete weekly macro-pulse report."""

    id: str = Field(default_factory=lambda: "")
    week_start: datetime
    week_end: datetime
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    regime: EconomicRegime = EconomicRegime.TRANSITION
    regime_rationale: str = ""
    signal_count: int = 0
    summary: str = ""
    # Phase 1: Consensus
    consensus_scores: list[ConsensusScore] = Field(default_factory=list)
    consensus_views: list[ConsensusView] = Field(default_factory=list)
    # Phase 2: Non-Consensus + Mechanisms
    non_consensus_views: list[NonConsensusView] = Field(default_factory=list)
    active_scenarios: list[ActiveScenario] = Field(default_factory=list)
    # --- REMOVED ---
    # narratives, asset_scores, scenario_views, composite_scores,
    # divergence_metrics, trade_theses
```

Keep the old fields as Optional with defaults for backwards compatibility when loading historical reports from the database. But new reports won't populate them.

### Step 6: Rebuild the dashboard

The dashboard becomes two sections:

**Section A: Consensus Context** (Phase 1 — existing, minor tweaks)
- Consensus cards per asset (unchanged)
- Consensus meter showing quant score breakdown (simplified — no "our score" marker)

**Section B: Non-Consensus Views** (Phase 2 — the product, majorly expanded)

Each NC view becomes a rich, expandable card:

```python
# dashboard/actionable_view.py — new NC card structure

def _render_nc_view_card(
    ncv: NonConsensusView,
    consensus_view: ConsensusView | None,
    consensus_score: ConsensusScore | None,
    active_scenarios: list[ActiveScenario],
    signals: list[Signal],  # for drill-down
) -> None:
    """Render a single non-consensus view as a rich card."""

    # --- Header: ticker, direction arrow, edge badge, validity ---
    # Bitcoin   CONSENSUS: BULLISH → OUR VIEW: BEARISH   [CONTRARIAN]   validity: 78%

    # --- Thesis block ---
    # The core disagreement in 2-3 sentences

    # --- Consensus context (collapsible) ---
    # What the market believes:
    #   Positioning: funding +0.04%, top traders 62% long, ETF inflows +$200M
    #   Narrative: institutional adoption, post-halving supply dynamics
    #   Coherence: ALIGNED (positioning and narrative agree)
    #   Priced in: continued ETF inflows, stable macro
    #   Not priced in: tariff escalation, FOMC surprise
    #   Quant score: +0.45 breakdown [options_skew: +0.3] [funding_7d: +0.8] ...

    # --- Evidence block (always visible) ---
    # Each evidence source with:
    #   ✓ [onchain] Stablecoin supply down 2.1% — capital leaving crypto ecosystem
    #     └─ Signal: [sig_123] "USDT market cap declined from $108.2B to $105.9B..."
    #        Source: onchain | Date: 2026-03-04 | Strength: 0.8
    #   ✓ [spreads] HYG/LQD credit spread z-score at -1.5
    #     └─ Signal: [sig_456] "Credit spreads widened to..."
    #        Source: spreads | Date: 2026-03-05 | Strength: 0.6

    # --- Transmission mechanisms (collapsible) ---
    # Supporting mechanisms:
    #   [Crypto Leverage Flush] prob: 65%, stage: EARLY
    #     Chain: ① Funding extreme (confirmed) → ② Liquidation cascade (emerging)
    #            → ③ Price capitulation (not started) → ④ Bounce (not started)
    #     Watch: funding rate trajectory, OI collapse >20%
    #
    #   [Risk-Off Flight to Safety] prob: 45%, stage: MID
    #     Chain: ① Credit stress (confirmed) → ② Risk repricing (emerging)
    #            → ③ Safe haven bid (not started)
    #     Watch: VIX term structure, TLT flows

    # --- Trade parameters ---
    # Catalyst: FOMC meeting March 19 — hawkish surprise risk
    # Invalidation: stablecoin supply stabilizes AND credit spreads normalize
    # Conviction: 0.70 | Validity: 0.78 | Independent sources: 3

    # --- Quality flags ---
    # ✓ Testable mechanism  ✓ Timing edge  ✓ Has catalyst
    # Consensus coherence: ALIGNED (strong consensus — needs stronger evidence)
```

### Step 7: Signal drill-down

Store signal references so the dashboard can show the actual signal content behind each evidence citation.

The NC view already has `signal_ids`. We need to make the raw signals available to the dashboard. Options:

**Option A: Store signals in the report** (simple, increases report size)
```python
class WeeklyReport(BaseModel):
    # ... existing fields ...
    signals: list[Signal] = Field(default_factory=list)  # all collected signals
```

**Option B: Load signals from DB on demand** (more complex, better for large signal sets)
```python
# storage/store.py — already stores signals in the signals table
# Dashboard calls load_signals_for_report(report_id) when user expands a card
```

Recommendation: **Option A** for simplicity. 300-500 signals × ~500 bytes each = ~250KB. Negligible.

### Step 8: Update storage layer

```python
# storage/store.py — changes to save_report() and load_latest_report()

# save_report():
#   - Stop writing to: narratives, narrative_signals, weekly_asset_scores,
#     composite_scores, divergence_metrics, trade_theses tables
#   - Keep writing to: weekly_reports, signals, consensus_scores,
#     consensus_views, non_consensus_views, active_scenarios
#   - Add: new NC view fields (supporting_mechanisms, mechanism_stage, etc.)

# load_latest_report():
#   - Stop loading: narratives, weekly_asset_scores, composite_scores,
#     divergence_metrics, trade_theses
#   - Keep loading: consensus_scores, consensus_views, non_consensus_views,
#     active_scenarios, signals
#   - Handle backwards compat: old reports in DB will have composite_scores
#     and narratives — load them into Optional fields if present
```

The `non_consensus_views` table needs new columns:

```sql
ALTER TABLE non_consensus_views ADD COLUMN supporting_mechanisms TEXT DEFAULT '[]';
ALTER TABLE non_consensus_views ADD COLUMN mechanism_stage TEXT DEFAULT '';
ALTER TABLE non_consensus_views ADD COLUMN regime_context TEXT DEFAULT '';
ALTER TABLE non_consensus_views ADD COLUMN consensus_quant_score REAL DEFAULT 0.0;
ALTER TABLE non_consensus_views ADD COLUMN consensus_coherence TEXT DEFAULT '';
```

### Step 9: Update Sheets export

```python
# exports/sheets.py — simplify

# Keep worksheets:
#   Summary (week, regime, signal count, summary)
#   Consensus (quant scores with component breakdown)
#   Consensus Views (Phase 1 positioning + narrative + coherence)
#   Non-Consensus Views (expanded: thesis, evidence, mechanisms, quality flags)
#   Active Mechanisms (chain progress, asset impacts, watch items)

# Remove worksheets:
#   Asset Scores (was composite scores — gone)
#   Scenarios (replaced by Active Mechanisms with richer detail)
#   Trades (no more trade thesis generation)
```

### Step 10: Update app.py

```python
# app.py — simplify sidebar

# Remove:
#   - Direction filter (BULLISH/BEARISH/ALL) — NC views are shown as-is
#   - MIN PROBABILITY slider — not applicable
#   - Asset class multiselect — keep but simplify (just filter NC view cards)

# Keep:
#   - RUN WEEKLY PIPELINE button
#   - SYNC TO SHEETS button
#   - Asset class filter (simplified)

# Add:
#   - "Show consensus detail" toggle (expand/collapse Phase 1 section)
```

### Step 11: Handle the "zero NC views" case

When Phase 2 finds no valid non-consensus views (all filtered by ≥2 source requirement), the dashboard should clearly say so:

```
"No valid non-consensus views this week.

Our alpha signals agree with market consensus across all assets. This means
either consensus is correct (no edge) or our signal coverage is insufficient
to identify a disagreement.

Active consensus: [summary of Phase 1 consensus views]
Active mechanisms: [list of transmission mechanisms, which are informational
even without NC views]"
```

This is the honest answer. If we can't find a validated disagreement, we shouldn't manufacture one. No trade is a valid position.

## File Change Summary

| File | Action |
|---|---|
| `models/schemas.py` | Add fields to NonConsensusView, simplify WeeklyReport |
| `run_weekly.py` | Merge Phase 2+3 into Phase 2, remove Phase 3 |
| `analysis/nc_enricher.py` | **NEW** — enrich NC views with mechanism/consensus links |
| `ai/chains/regime_classifier.py` | Add `classify_regime_from_consensus()` |
| `ai/prompts/templates.py` | Add `REGIME_FROM_CONSENSUS_PROMPT` |
| `dashboard/actionable_view.py` | Rewrite — NC-centric view with drill-down |
| `dashboard/styles.py` | Update CSS for new card structure |
| `storage/store.py` | Update save/load, add new NC columns |
| `exports/sheets.py` | Simplify to 5 worksheets |
| `app.py` | Simplify sidebar, update render call |
| `analysis/sentiment_aggregator.py` | Dead code (keep for legacy pipeline) |
| `analysis/composite_scorer.py` | Dead code (keep for legacy pipeline) |
| `ai/chains/narrative_extractor.py` | Remove `extract_narratives_from_nc_views()` |

## Migration Notes

- Old reports in the database should still load. Keep deprecated fields as Optional in the WeeklyReport model with default empty lists.
- The legacy pipeline (`run_pipeline_legacy()`) can stay for backwards compatibility but should not be the default.
- The `non_consensus_views` table needs ALTER TABLE for new columns; SQLite handles this gracefully with defaults.
- Trade outcome tracking (background validator in app.py) becomes dead code since we no longer generate trade theses. Remove the background thread.

## What This Achieves

**Before (3-phase):**
```
350 signals → consensus → NC discovery → narratives → scoring → trades → dashboard
             (good)       (good)         (noise)      (fights NC)  (diluted)  (confusing)
```

**After (2-phase):**
```
350 signals → consensus → NC discovery + mechanisms → dashboard
             (context)    (the product)                (clear, deep)
```

The NC view becomes the atomic unit of output. Each one is a complete, self-contained trade thesis with:
- What the market believes (consensus context)
- Why we disagree (thesis + evidence + citations)
- The causal mechanism (transmission chain + stage)
- When we're wrong (invalidation)
- How confident we are (conviction × validity)

No re-scoring. No dilution. No backward-looking technicals fighting the thesis. The signal IS the trade.

---

## Detailed TODO List

### Milestone 1: Schema & Model Changes

These are foundational — everything else depends on the models being right.

- [x] **1.1** Add new fields to `NonConsensusView` in `models/schemas.py`
  - `supporting_mechanisms: list[str]` (mechanism IDs)
  - `mechanism_stage: str` (earliest active stage)
  - `regime_context: str`
  - `consensus_quant_score: float`
  - `consensus_coherence: str`

- [x] **1.2** Simplify `WeeklyReport` in `models/schemas.py`
  - Make `narratives`, `asset_scores`, `composite_scores`, `divergence_metrics`, `trade_theses`, `scenario_views` Optional with default `None` (backwards compat for loading old reports)
  - New reports won't populate these fields
  - Keep `consensus_scores`, `consensus_views`, `non_consensus_views`, `active_scenarios` as required

- [x] **1.3** Remove `TradeThesis` from the report flow
  - Keep the model class (needed to load old reports from DB)
  - It's just no longer produced by the pipeline

---

### Milestone 2: Pipeline Restructure (`run_weekly.py`)

Merge Phase 3 into Phase 2, delete the scoring/narrative chain.

- [x] **2.1** Move mechanism matching from `run_phase_3()` into `run_phase_2()`
  - Import `load_mechanisms` and `match_mechanisms` in Phase 2
  - Call after alpha signal collection, before NC discovery
  - Pass `all_signals` (consensus + alpha) to `match_mechanisms()`

- [x] **2.2** Move regime classification from `run_phase_3()` into `run_phase_2()`
  - Create new `classify_regime_from_consensus()` function (see Milestone 3)
  - Call after mechanism matching
  - Input: consensus_views + active_scenarios (not narratives)

- [x] **2.3** Create `enrich_nc_views()` function
  - New file `analysis/nc_enricher.py`
  - For each NC view: find active scenarios where an asset impact matches the NC ticker + direction
  - Attach mechanism IDs, earliest mechanism stage
  - Attach consensus quant score and coherence from Phase 1

- [x] **2.4** Call `enrich_nc_views()` at end of Phase 2
  - After NC discovery, after mechanism matching
  - Before returning Phase 2 results

- [x] **2.5** Create new `build_report()` function
  - Replaces the report-building logic in `run_phase_3()`
  - Assembles `WeeklyReport` from Phase 1 + Phase 2 outputs only
  - No narratives, no composite scores, no trade theses
  - Generate summary from consensus views + NC views (simple LLM call or template)

- [x] **2.6** Update `run_pipeline()` to call Phase 1 → Phase 2 → `build_report()` → save → export
  - Delete `run_phase_3()` entirely
  - Keep `run_pipeline_legacy()` as-is for backwards compat (optional — could also delete)

- [x] **2.7** Remove dead imports from `run_weekly.py`
  - `extract_narratives_from_nc_views`
  - `aggregate_asset_scores`
  - `compute_composite_scores`
  - `compute_divergence`
  - `generate_trade_theses`

---

### Milestone 3: Regime Classification Rework

- [x] **3.1** Create `REGIME_FROM_CONSENSUS_PROMPT` in `ai/prompts/templates.py`
  - System prompt: classify regime from consensus positioning/narrative + active transmission mechanisms
  - Human prompt: takes consensus_views_text + active_scenarios_text
  - Same output schema as current (regime, rationale, confidence, key_indicators)

- [x] **3.2** Create `classify_regime_from_consensus()` in `ai/chains/regime_classifier.py`
  - Formats consensus views into text (direction, quant score, positioning summary, narrative)
  - Formats active scenarios into text (mechanism name, category, probability, stage, trigger evidence)
  - Calls LLM with `REGIME_FROM_CONSENSUS_PROMPT`
  - Returns `(EconomicRegime, str, float)` same as current `classify_regime()`

- [x] **3.3** Generate weekly summary from consensus + NC views
  - New `SUMMARY_FROM_NC_VIEWS_PROMPT` or adapt `WEEKLY_SUMMARY_PROMPT`
  - Input: regime, consensus views, NC views, active mechanisms
  - Output: 3-5 sentence executive summary

---

### Milestone 4: Storage Layer Updates

- [x] **4.1** Add new columns to `non_consensus_views` table in `init_db()`
  - `supporting_mechanisms TEXT DEFAULT '[]'`
  - `mechanism_stage TEXT DEFAULT ''`
  - `regime_context TEXT DEFAULT ''`
  - `consensus_quant_score REAL DEFAULT 0.0`
  - `consensus_coherence TEXT DEFAULT ''`
  - Use `ALTER TABLE ... ADD COLUMN` with try/except for existing DBs

- [x] **4.2** Update `save_report()` in `store.py`
  - Write new NC view fields to DB
  - Stop writing to: `narratives`, `narrative_signals`, `weekly_asset_scores`, `composite_scores`, `trade_theses` tables (skip these inserts when the report doesn't have them)
  - Keep writing: `weekly_reports`, `signals`, `consensus_scores`, `consensus_views`, `non_consensus_views`, `active_scenarios`

- [x] **4.3** Update `load_latest_report()` in `store.py`
  - Load new NC view fields from DB
  - Make loading of narratives, composite_scores, divergence_metrics, trade_theses conditional (only if tables have data for this report — backwards compat)
  - Stop recomputing divergence metrics on the fly (no longer needed)

- [x] **4.4** Optionally store full signal list with report
  - Add signals to `WeeklyReport` model (for dashboard drill-down)
  - Or: add `load_signals_for_report(report_id)` function to `store.py`
  - Decision: store on report for simplicity (signals table already exists, just need to load them)

---

### Milestone 5: Dashboard Rewrite

This is the biggest milestone — the entire dashboard UX changes.

#### 5a: Remove old sections

- [x] **5a.1** Remove `_render_scenario_view()` function
- [x] **5a.2** Remove `_render_legacy_view()` function
- [x] **5a.3** Remove `_consensus_meter_html()` function (or simplify — see 5b.2)
- [x] **5a.4** Remove `_trade_thesis_html()` function
- [x] **5a.5** Remove all asset card rendering (BULLISH/BEARISH/NEUTRAL grouping, composite score display, NC badge, score breakdown)
- [x] **5a.6** Remove the PERFORMANCE tab (was for trade outcomes — no longer relevant)

#### 5b: Simplify consensus section

- [x] **5b.1** Keep `_render_consensus_section()` mostly as-is
  - Consensus cards with direction, quant score, coherence, positioning, narrative, priced-in, not-priced-in
  - Make it collapsible (default collapsed — it's context, not the product)

- [x] **5b.2** Simplify consensus meter
  - Show only the consensus position (teal marker), remove "our score" marker
  - Show component breakdown (options_skew, funding_7d, etc.)
  - Remove divergence badge (no divergence concept without composite scores)

#### 5c: Build new NC view cards

- [x] **5c.1** Create `_render_nc_view_card()` function — the main card
  - Header: ticker, direction arrow (consensus → ours), edge type badge, validity %
  - Thesis: the core disagreement (always visible, 2-3 sentences)
  - Conviction bar + validity bar side by side
  - Quality flags row: ✓/✗ for testable mechanism, timing edge, has catalyst

- [x] **5c.2** Create evidence drill-down section within NC card
  - Each `EvidenceSource` rendered with:
    - Source badge, summary, strength indicator
    - Expandable: full signal content, signal ID, signal date, signal URL (if any)
  - Requires signals to be available (from report or loaded from DB)

- [x] **5c.3** Create mechanism drill-down section within NC card
  - For each supporting mechanism:
    - Mechanism name, category, probability, stage badge (EARLY/MID/LATE)
    - Chain progress: numbered steps with status icons (confirmed ✓ / emerging ◐ / not started ○ / invalidated ✗)
    - Each step shows evidence text if available
    - Watch items list
    - Confirmation status + invalidation risk
  - Collapsible, default collapsed

- [x] **5c.4** Create consensus context section within NC card
  - Shows the Phase 1 consensus view for this specific ticker
  - Quant score with component breakdown
  - Positioning summary + narrative summary
  - Coherence badge
  - Priced-in / not-priced-in chips
  - Collapsible, default collapsed

- [x] **5c.5** Create trade parameters section within NC card
  - Catalyst (with date if available)
  - Invalidation condition
  - Conviction, validity score, independent source count
  - Always visible (bottom of card)

#### 5d: Assemble the new dashboard layout

- [x] **5d.1** Update `render_actionable_view()` entry point
  - Render regime banner (unchanged)
  - Single tab (remove PERFORMANCE tab) or keep tabs as VIEWS | CONSENSUS DETAIL
  - Render consensus section (collapsible context)
  - Render NC views section (the product)
  - Render active mechanisms summary (informational — even if no NC views reference them)
  - Handle "zero NC views" case with honest messaging

- [x] **5d.2** Handle zero NC views gracefully
  - Show message: "No valid non-consensus views this week"
  - Still show consensus section and active mechanisms as informational context

- [x] **5d.3** Add asset class filter support to NC view rendering
  - Filter NC view cards by selected asset classes (from sidebar)

---

### Milestone 6: CSS / Styling

- [x] **6.1** Add CSS for new NC card structure in `dashboard/styles.py`
  - NC card container (border-left colored by edge type)
  - Evidence item rows with strength indicators
  - Mechanism chain progress (step indicators with status colors)
  - Conviction/validity bars (horizontal, colored)
  - Quality flag chips (green checkmark / red X)
  - Collapsible section styling

- [x] **6.2** Remove CSS for deprecated components
  - Asset cards (composite score display)
  - BULLISH/BEARISH/NEUTRAL section headers
  - Trade thesis cards
  - NC badge (no longer needed — everything is NC)

---

### Milestone 7: Sheets Export Update

- [x] **7.1** Update `export_report()` in `exports/sheets.py`
  - Keep: Summary, Consensus, Consensus Views worksheets
  - Expand: Non-Consensus Views worksheet (add mechanism links, quality flags, consensus quant score)
  - Add: Active Mechanisms worksheet (mechanism name, category, probability, stage, chain progress, asset impacts, watch items)
  - Remove: Asset Scores, Scenarios, Trades worksheets

- [x] **7.2** Remove `sync_trades_to_sheets()` function
  - No longer generating trades, so nothing to sync

---

### Milestone 8: App.py Cleanup

- [x] **8.1** Remove background trade validator thread
  - Delete `_background_validator()` function
  - Delete the `if "validator_started" not in st.session_state` block

- [x] **8.2** Simplify sidebar
  - Keep: RUN WEEKLY PIPELINE button, SYNC TO SHEETS button, asset class filter
  - Remove: direction filter radio (BULLISH/BEARISH/ALL)
  - Remove: MIN PROBABILITY slider
  - Add: "Show consensus detail" toggle (optional — controls whether consensus section is expanded)

- [x] **8.3** Update `render_actionable_view()` call signature
  - Remove `direction_filter` and `min_threshold` parameters
  - Keep `selected_assets` for asset class filtering

---

### Milestone 9: Cleanup Dead Code

- [x] **9.1** Mark `analysis/sentiment_aggregator.py` as legacy
  - Add docstring: "Legacy — only used by run_pipeline_legacy()"
  - Or delete if legacy pipeline is also removed

- [x] **9.2** Mark `analysis/composite_scorer.py` as legacy
  - Same treatment as sentiment_aggregator

- [x] **9.3** Remove `extract_narratives_from_nc_views()` from `ai/chains/narrative_extractor.py`
  - Keep `extract_narratives()` (used by legacy pipeline)
  - Remove the NC-specific variant

- [x] **9.4** Clean up `models/schemas.py`
  - Add `# LEGACY` comment to deprecated models (WeeklyAssetScore, CompositeAssetScore, DivergenceMetrics)
  - Do NOT delete them — needed for loading old reports from DB

- [x] **9.5** Remove the `NARRATIVE_FROM_NC_VIEWS_PROMPT` from `ai/prompts/templates.py`
  - No longer used

---

### Milestone 10: Testing & Validation

- [x] **10.1** Run Phase 1 → Phase 2 pipeline end-to-end
  - Verify consensus scores, consensus views produced correctly
  - Verify NC discovery still works
  - Verify mechanism matching runs in Phase 2
  - Verify regime classification works from consensus + scenarios

- [x] **10.2** Verify NC enrichment
  - Check that supporting_mechanisms are correctly linked
  - Check that consensus_quant_score and consensus_coherence populate

- [x] **10.3** Verify storage round-trip
  - `save_report()` writes new NC fields
  - `load_latest_report()` reads them back correctly
  - Old reports in DB still load without errors (backwards compat)

- [x] **10.4** Verify dashboard renders
  - Consensus section renders (with/without quant scores)
  - NC view cards render with evidence, mechanisms, consensus context
  - Zero NC views case shows honest messaging
  - Asset class filter works
  - Collapsible sections expand/collapse

- [x] **10.5** Verify Sheets export
  - All worksheets write correctly
  - NC Views worksheet has expanded columns
  - Active Mechanisms worksheet is new and correct

- [x] **10.6** Run on Streamlit locally
  - `streamlit run app.py`
  - Full visual check of the new dashboard
  - Click through all expandable sections

---

### Execution Order

The milestones should be executed roughly in this order, though some can be parallelized:

```
Milestone 1 (schemas)          ← everything depends on this
    ↓
Milestone 2 (pipeline)         ← core restructure
Milestone 3 (regime rework)    ← can run in parallel with M2
    ↓
Milestone 4 (storage)          ← depends on M1 + M2
    ↓
Milestone 5 (dashboard)        ← depends on M1 + M4
Milestone 6 (CSS)              ← runs in parallel with M5
    ↓
Milestone 7 (sheets)           ← depends on M1
Milestone 8 (app.py)           ← depends on M5
Milestone 9 (cleanup)          ← last, after everything works
    ↓
Milestone 10 (testing)         ← final validation
```

Total: ~50 individual tasks across 10 milestones.
