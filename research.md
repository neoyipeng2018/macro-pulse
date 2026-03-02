# MACRO-PULSE: Complete Workflow & Idea Generation Analysis

## Date: March 2, 2026

---

## 1. System Overview

**macro-pulse** is a weekly macro narrative extraction and directional trading idea generation system. It ingests raw signals from 11 diverse data sources, synthesizes them through an LLM pipeline (Claude Sonnet 4 primary, Cerebras fallback), and outputs actionable 1-week directional trading ideas across 31 assets in 6 asset classes.

The system's key innovation: it constrains LLM analysis within a framework of 18 known transmission mechanisms while simultaneously extracting free-form narratives, then deterministically aggregates both into per-asset directional scores. This dual approach (structured mechanisms + unstructured narratives) ensures both rigor and flexibility.

**Entry Points:**
- CLI: `poetry run python run_weekly.py`
- Dashboard: `poetry run streamlit run app.py` (with "RUN WEEKLY PIPELINE" sidebar button)
- CLI flags: `--collect-only` (signals only), `--sources news market_data` (selective collection)

---

## 2. The 7-Step Pipeline (Detailed Walkthrough)

### Step 1: Signal Collection (11 Collectors)

The pipeline begins by instantiating and running 11 collectors, each returning a list of `Signal` objects. Each signal has: `id`, `source` (enum), `title`, `content`, `url`, `timestamp`, and `metadata` (dict).

#### 1.1 RSS News (`RSSNewsCollector`)
- **Sources**: 14 RSS feeds across 3 categories:
  - **Macro News** (8 feeds): Reuters Business, Reuters Top, BBC Business, CNBC Top, MarketWatch, NYT Business, CNBC World Markets, CNBC Economy
  - **FX/Commodities** (2 feeds): ForexLive, FXStreet
  - **Crypto** (2 feeds): CoinTelegraph, CoinDesk
- **Per feed**: Parses up to 20 entries via `feedparser`
- **Signal content**: Article title + summary/description
- **Typical yield**: ~200-280 signals per run
- **Signal quality**: Medium — provides thematic context and breaking news, but noisy

#### 1.2 Central Bank (`CentralBankCollector`)
- **Sources**: 3 RSS feed categories:
  - Fed speeches (`federalreserve.gov/feeds/speeches.xml`)
  - Fed press releases (`federalreserve.gov/feeds/press_all.xml`)
  - ECB press releases (`ecb.europa.eu/rss/press.html`)
- **Per feed**: Up to 15 entries
- **Signal quality**: High — direct policy communication, strongest weight for monetary narratives
- **Typical yield**: 15-45 signals

#### 1.3 Economic Data (`EconomicDataCollector`)
- **Source**: FRED API (requires `FRED_API_KEY`)
- **11 Series tracked**:
  | Series ID | Name | Significance |
  |-----------|------|--------------|
  | DFF | Federal Funds Rate | Current policy rate level |
  | T10Y2Y | 10Y-2Y Spread | Classic recession indicator |
  | T10YIE | 10Y Breakeven Inflation | Market inflation expectations |
  | DTWEXBGS | Trade-Weighted USD | Broad dollar strength |
  | ICSA | Initial Jobless Claims | Labor market stress |
  | UMCSENT | Michigan Consumer Sentiment | Consumer confidence |
  | VIXCLS | CBOE VIX | Market fear gauge |
  | BAMLH0A0HYM2 | HY OAS Spread | Credit stress |
  | SOFR | Secured Overnight Financing Rate | Money market conditions |
  | T10Y3M | 10Y-3M Spread | Yield curve shape |
  | STLFSI2 | St. Louis Fed Financial Stress | Systemic stress composite |
- **Per series**: Latest value, change from prior reading, percentage change
- **Typical yield**: 11 signals (one per series)

#### 1.4 Market Data (`MarketDataCollector`)
- **Source**: yfinance, 1-month period
- **31 Tickers** across 6 asset classes:
  - **FX (8)**: DX-Y.NYB, EURUSD=X, GBPUSD=X, USDJPY=X, AUDUSD=X, USDCAD=X, USDCHF=X, USDCNH=X
  - **Metals (4)**: GC=F, SI=F, PL=F, HG=F
  - **Energy (3)**: CL=F, BZ=F, NG=F
  - **Crypto (3)**: BTC-USD, ETH-USD, SOL-USD
  - **Indices (8)**: ^GSPC, ^IXIC, ^DJI, ^RUT, ^VIX, ^FTSE, ^N225, ^HSI
  - **Bonds (4)**: ^TNX, ^TYX, ^FVX, TLT
- **Per ticker**: Weekly return (5-day), monthly return (20-day), current price
- **Typical yield**: 31 signals (one per ticker)
- **Purpose**: Provides price context backdrop — "is the asset already moving?"

#### 1.5 COT Reports (`COTCollector`)
- **Source**: CFTC `deafut.txt` (Commitment of Traders)
- **15 Contracts tracked**: EUR, GBP, JPY, AUD, CAD, CHF, Gold, Silver, Crude Oil, Natural Gas, Copper, S&P 500, Nasdaq 100, US 10Y Note, Bitcoin
- **Per contract**: Non-commercial net position, weekly change, long/short breakdown
- **Signal content**: Net positioning (net long/short), weekly change direction
- **Typical yield**: 15 signals
- **Key insight**: Extreme positioning flags crowded trades; weekly changes signal institutional sentiment shifts

#### 1.6 Fear & Greed (`FearGreedCollector`)
- **Source**: alternative.me Crypto Fear & Greed API
- **Data**: 7-day history of the index (0-100 scale)
- **Classification**: Extreme Fear (<25), Fear (25-45), Neutral (45-55), Greed (55-75), Extreme Greed (>75)
- **Typical yield**: 7 signals (one per day)
- **Key insight**: Extreme fear = potential buying opportunity; extreme greed = potential overheating

#### 1.7 Economic Calendar (`EconomicCalendarCollector`)
- **Primary source**: ForexFactory free calendar API (`ff_calendar_thisweek.json`)
- **Fallback**: Hardcoded FOMC dates (2025-2026, 16 dates total)
- **Lookahead**: 21 days into the future
- **Impact filter**: High and medium impact events only
- **Country filter**: US, EU, GB, JP, CN, AU, CA
- **Critical detail**: Signals marked with `is_forward_looking=True` in metadata, which exempts them from the stale signal filter in Step 1b
- **Signal title prefix**: `[UPCOMING]` — tells the LLM these are scheduled future events, not past data
- **Typical yield**: 10-30 signals depending on calendar density
- **Current FOMC dates within range**: 2026-03-18 (16 days away)

#### 1.8 Prediction Markets (`PredictionMarketCollector`)
- **Kalshi**: Fetches events via `api.elections.kalshi.com`, filtered to macro-relevant categories only (Economics, Financials, Politics, World — excluding Sports, Entertainment). Gets markets for each event, sorts by volume, takes top 50.
  - Signal includes: probability (midpoint of yes_bid/yes_ask), volume, ticker
- **Polymarket**: Fetches from `gamma-api.polymarket.com`, top 50 by volume
  - Signal includes: probability (from outcomePrices JSON), volume, liquidity
- **Typical yield**: 50-100 signals
- **Key insight**: Real-money probabilities reveal crowd intelligence on macro events

#### 1.9 Spreads (`SpreadsCollector`)
- **Source**: yfinance, 3-month period, 11 tickers
- **5 Derived Indicators**:

  **a) VIX Term Structure** (VIX spot vs VIX3M):
  - Ratio > 1.05 → backwardation = near-term fear, bearish equities
  - Ratio > 1.15 → "significant" backwardation
  - Ratio < 0.85 → deep contango = complacency, potential vol spike
  - VIX > 25 → elevated stress
  - VIX > 30 → contrarian bullish for equities (mean reversion within 5-10 days)
  - Also emits 20-day average ratio for context

  **b) VIX/VVIX Ratio** (vol-of-vol leading indicator):
  - VVIX > 120 + VIX < 20 → divergence = vol breakout imminent (3-7 days)
  - VVIX 3-day spike > 15% → institutional hedging spike, leading VIX expansion

  **c) Credit Spreads** (HYG/LQD ratio, 10-day z-score):
  - z < -1.5 → widening spreads = risk-off, bearish equities (propagates 3-5 days)
  - z < -2.5 → "sharply" widening
  - z > 1.5 → tightening = risk-on, bullish equities

  **d) Yield Curve** (10Y-3M spread):
  - Current < 0 → inverted = recession risk, bearish equities, bullish bonds/gold
  - Current < 0.5% → near flat = slowing growth
  - 5-day move > |0.15%| → rapid steepening/flattening = strong directional signal for bonds/FX

  **e) Copper/Gold Ratio** (20-day z-score):
  - z < -1.5 → declining = risk-off, bearish equities/EM, bullish gold/USD
  - z > 1.5 → rising = risk-on, bullish equities/commodities/EM

- **Typical yield**: 2-6 signals (conditional — only fires when thresholds are hit)
- **Signal quality**: Highest — quantitative leading indicators weighted heavily by the LLM

#### 1.10 Google Trends (`GoogleTrendsCollector`)
- **Source**: pytrends API, US-only, 30-day daily data
- **16 Keywords** in 3 categories:
  - **Stress** (6): recession, market crash, bank run, layoffs, margin call, sell stocks
  - **Assets** (5): gold price, bitcoin crash, oil price, dollar collapse, safe haven
  - **Policy** (5): rate cut, inflation, tariff, trade war, sanctions
- **Processed in batches of 5** (Google API limit)
- **Spike detection** (tuned for 1-week horizon):
  - Strong spike: interest >= 70 AND ratio vs 7-day avg >= 1.5x
  - Rapid acceleration: interest >= 50 AND ratio vs 7-day avg >= 2.0x
- **Key insight**: Treated as CONTRARIAN signals — retail panic searches correlate with short-term bottoms
- **Typical yield**: 0-5 signals (conditional on spike detection)

#### 1.11 Reddit (`RedditCollector`)
- **Source**: Reddit public JSON API (`/r/{sub}/hot.json`)
- **10 Subreddits**: wallstreetbets, investing, economics, stocks, Forex, CryptoCurrency, CryptoMarkets, Gold, commodities, bonds
- **Per subreddit**: Up to 25 hot posts (excludes stickied)
- **Per post**: Title, selftext (first 500 chars), score, comment count, upvote ratio
- **Typical yield**: ~150-250 signals
- **Signal quality**: Low — tracks retail sentiment, useful for contrarian positioning

### Step 1b: Relevance Filter

After collection, signals older than **10 days** are dropped — UNLESS the signal has `metadata.is_forward_looking == True` (economic calendar events survive). This ensures the LLM only processes recent, actionable intelligence.

- Typical: ~500-700 signals collected → ~200-400 after filtering (depending on source freshness)
- Filtered signals are logged with count

### Raw Signal Snapshot

All signals are serialized to `data/raw/signals_{timestamp}.json` for audit trail and reproducibility.

---

### Step 2: Narrative Extraction (LLM)

**Model**: Claude Sonnet 4 (`claude-sonnet-4-20250514`) at temperature 0.2, max tokens 4096. Falls back to Cerebras `gpt-oss-120b` if Anthropic fails.

**Input**: All filtered signals formatted as:
```
[signal_id] (source, date) Title
Content (first 400 chars)
```

**Prompt engineering** (NARRATIVE_EXTRACTION_PROMPT):

The system prompt instructs the LLM to act as a **macro strategist at a global macro hedge fund** with specific mandates:

1. **Group signals into 3-8 macro narratives** — each a coherent directional thesis
2. **Per-asset directional sentiment** with:
   - `ticker`: Standard asset name
   - `asset_class`: fx/metals/energy/crypto/indices/bonds
   - `direction`: bullish/bearish/neutral
   - `conviction`: 0.0-1.0 strength
   - `rationale`: One sentence on WHY
   - `catalyst`: Specific event/date creating the opportunity NOW (must name event, date, and mechanism)
   - `exit_condition`: Both profit-take AND invalidation signals with specific levels
3. **Consensus vs. Edge Analysis** (per-asset, not per-narrative):
   - `consensus_view`: What sell-side/media/futures are pricing for THIS asset
   - `edge_type`: contrarian / more_aggressive / more_passive / aligned
   - `edge_rationale`: WHY our signals see something different
4. **Signal interpretation rules**:
   - Spread/VIX signals weighted heavily (quantitative leading indicators)
   - Google Trends spikes treated as CONTRARIAN (retail panic = bottoms)
   - `[UPCOMING]` prefix events treated as catalysts (consider consensus vs. prior, pre-positioning risk)
5. **Temporal grounding**: Strictly grounded to today's date and provided signal data — no hallucinated historical context

**Output parsing**: JSON array of narratives. Handles markdown-wrapped JSON (```json blocks). Each narrative is converted to a `Narrative` Pydantic model.

**Signal backfill**: After LLM extraction, the system checks each asset sentiment and ensures the corresponding market_data signal is attached (the LLM sometimes omits signal_ids for market data signals it referenced).

**Typical output**: 4-8 narratives, each with 5-15 asset sentiments.

---

### Step 2b: Transmission Mechanism Matching (LLM)

**Purpose**: Match signals to 18 known causal chains from the mechanism catalog. This constrains the LLM to established macro relationships rather than allowing it to hallucinate novel mechanisms.

**Mechanism Catalog** (`mechanisms.yaml`, 87.5KB, 18 mechanisms):

| Category | Mechanism | ID |
|----------|-----------|-----|
| Monetary Policy | Fed Dovish Pivot | `fed_dovish_pivot` |
| Monetary Policy | Fed Hawkish Surprise | `fed_hawkish_surprise` |
| Monetary Policy | Global Liquidity Expansion | `liquidity_expansion` |
| Risk Sentiment | Risk-Off Flight to Safety | `risk_off_flight` |
| Risk Sentiment | Risk-On Rotation | `risk_on_rotation` |
| Risk Sentiment | VIX Mean Reversion | `vix_mean_reversion` |
| Growth/Inflation | Stagflation Pressure | `stagflation_pressure` |
| Growth/Inflation | Reflation Trade | `reflation_trade` |
| Growth/Inflation | Recession Signal | `recession_signal` |
| Geopolitical | Trade War Escalation | `trade_war_escalation` |
| Geopolitical | Geopolitical Shock | `geopolitical_shock` |
| FX | Yen Carry Trade Unwind | `yen_carry_unwind` |
| FX | Dollar Wrecking Ball | `dollar_wrecking_ball` |
| Commodities | Energy Supply Shock | `energy_supply_shock` |
| Commodities | Gold Central Bank Accumulation | `gold_cb_accumulation` |
| Crypto | Crypto as Liquidity Proxy | `crypto_liquidity_proxy` |
| Crypto | Crypto Regulatory Shock | `crypto_regulatory_shock` |
| Bonds | Term Premium Repricing | `term_premium_repricing` |

Each mechanism defines:
- **Trigger sources**: Which signal sources can activate it
- **Trigger keywords**: Terms that suggest activation
- **Chain steps**: Sequential causal steps with observables and lag windows (e.g., "Fed signals dovish shift" → "Rate expectations reprice" → "Real yields decline" → "Risk assets rally")
- **Asset impacts**: Per-ticker direction, sensitivity (low/medium/high), and lag
- **Confirmation criteria**: What would confirm the mechanism is playing out
- **Invalidation criteria**: What would break the thesis

**LLM Prompt** (MECHANISM_MATCHING_PROMPT):
- Only activate mechanisms with concrete signal evidence
- Probability 0.2-0.95 (minimum 0.2 to include)
- Typically 2-6 mechanisms active
- Per-mechanism: chain step progress (not_started/emerging/confirmed/invalidated), current stage (early/mid/late/complete), magnitude (minor/moderate/major)
- Per-asset impacts: direction, magnitude (0-1), conviction (0-1), rationale
- Watch items: what would confirm or invalidate
- Temporal grounding enforced

**Output**: List of `ActiveScenario` objects.

---

### Step 3: Regime Classification (LLM)

**Purpose**: Classify the overall macro backdrop into one of 6 regimes.

**Regimes and their asset implications**:

| Regime | Conditions | Asset Playbook |
|--------|-----------|---------------|
| `risk_on` | Growth improving + easing | Long equities, short USD, long EM/commodities |
| `risk_off` | Recession fear + stress | Long USD, long gold, long bonds, short equities |
| `reflation` | Growth + rising inflation | Long commodities, long EM, short bonds |
| `stagflation` | Stagnation + inflation | Long gold, short equities, short bonds |
| `goldilocks` | Moderate growth + low inflation | Long equities, long bonds, short vol |
| `transition` | Mixed signals, regime shifting | Reduce conviction, widen stops |

**Input**: Narrative titles, summaries, confidence, trend, and per-asset sentiment votes.
**Output**: Regime enum, rationale (2-3 sentences), confidence (0-1).

---

### Step 4: Deterministic Sentiment Aggregation

**No LLM here** — this is a pure mathematical aggregation for transparency and reproducibility.

**Formula per asset**:
```
For each narrative N that mentions asset A:
  weight = A.conviction × N.confidence × trend_multiplier(N.trend)
  vote = direction_value(A.direction) × weight

score(A) = sum(votes) / sum(weights)
```

**Trend multipliers**: intensifying=1.5, stable=1.0, fading=0.5

**Direction values**: bullish=+1, bearish=-1, neutral=0

**Direction thresholds**: score > 0.1 → bullish, score < -0.1 → bearish, else neutral

**Output per asset**: `WeeklyAssetScore` with:
- `ticker`, `asset_class`
- `direction`: bullish/bearish/neutral
- `score`: -1.0 to +1.0
- `conviction`: average conviction across all votes
- `narrative_count`: how many narratives reference this asset
- `top_narrative`: title of highest-weight narrative

**Sorted by**: absolute score descending (strongest convictions first)

**Scenario Aggregation** (parallel): Active scenarios are also aggregated per-asset:
- Net score = sum(probability × magnitude × direction_sign)
- Conflict detection: if scenarios with prob >= 0.2 disagree on direction, `conflict_flag = True`

---

### Step 5: Price Validation

**Purpose**: Compare this week's directional predictions against actual weekly returns to measure accuracy over time.

**Process**:
1. Fetch fresh weekly returns via `MarketDataCollector.get_weekly_returns()` (yfinance)
2. For each scored asset, compare predicted direction vs. actual return
3. **Hit threshold**: actual return > +0.25% = bullish; < -0.25% = bearish; else neutral
4. **Hit** = predicted direction matches actual direction
5. Compute overall hit rate + hit rate by asset class

**Example output from latest run**:
```
Price validation: X/Y hits (Z%)
```

---

### Step 6: Weekly Summary (LLM)

**Input**: Regime + rationale, narrative titles/summaries, top 15 asset scores.

**Output**: 3-5 sentence executive briefing covering:
1. Dominant macro theme this week
2. Highest-conviction directional trades
3. Key risks to the base case
4. What to watch next week
5. Key upcoming events (FOMC, NFP, CPI, etc.)

---

### Step 7: Report Assembly & Storage

**WeeklyReport** object constructed with all components:
- `id`: 12-char hex
- `week_start`/`week_end`: Monday-Sunday bracket
- `regime`, `regime_rationale`
- `narratives` (full list with signals)
- `asset_scores` (sorted by absolute score)
- `price_validations`
- `active_scenarios`, `scenario_views`
- `signal_count`, `summary`

**Persistence**:
1. **SQLite** (`macro_pulse.db`): 8 tables with full relational structure
2. **JSON snapshot**: `data/reports/report_{timestamp}.json`
3. **Google Sheets** (optional): 4 worksheets (Summary, Asset Scores, Scenarios, Validations)

---

## 3. Latest Report Analysis (March 1, 2026)

The most recent run produced a **risk_off** regime classification driven by:

### Dominant Narratives

**1. Middle East Conflict Risk-Off** (confidence: 0.85, trend: intensifying)
- **Trigger**: US-Israel strikes on Iran (Feb 28, 2026) + Ayatollah Khamenei death
- **Mechanism**: Strait of Hormuz closure risk → oil supply shock → risk-off cascade
- **Highest-conviction calls**:
  - WTI Crude bullish (0.88 conviction) — supply shock not priced in
  - Gold bullish (0.85 conviction) — safe-haven demand exceeds consensus
  - S&P 500 bearish (0.75 conviction) — contrarian to consensus year-end targets
  - Nasdaq bearish (0.78 conviction) — credit-spread widening signals deeper pullback
- **Edge type**: Contrarian on equities, more_aggressive on metals/energy

**2. Credit-Spread Widening & Flat Yield Curve** (quantitative signal narrative)
- **Evidence**: HYG/LQD z-score at -1.6 (widening), 10Y-3M at 0.38% (near-flat)
- **Implication**: Deteriorating risk appetite propagating to equities within 3-5 days
- **Edge**: Contrarian on equities — spread widening not yet reflected in equity forecasts

### Key Market Data Context (Week of Feb 23 - Mar 1, 2026)

| Asset | Weekly Return | Monthly Return | Price |
|-------|-------------|---------------|-------|
| Gold | +0.83% | +13.53% | $5,247.90 |
| Silver | +7.82% | +21.51% | $93.29 |
| Platinum | +10.58% | +13.37% | $2,373.50 |
| WTI Crude | +1.07% | +7.85% | $67.02 |
| S&P 500 | +0.60% | -1.42% | 6,878.88 |
| Nasdaq | +0.18% | -4.98% | 22,668.21 |
| US 10Y | -1.66% | -6.18% | 3.96% |
| EUR/USD | -0.27% | -0.62% | 1.1803 |

### Spread Signals Detected
- Credit spreads notably widening (HYG/LQD z: -1.6) — bearish equities
- Yield curve near flat (10Y-3M: 0.38%, 5d change: -0.06%) — slowing growth

---

## 4. Idea Generation Architecture: How Ideas Are Born

### The Idea Pipeline (from raw signal to actionable trade)

```
Raw Signal (e.g., "Tanker hit off Iran coast")
    ↓
Grouped with corroborating signals (CNBC oil analysis, spread widening, COT data)
    ↓
LLM extracts coherent NARRATIVE ("Middle East Conflict Risk-Off")
    ↓
LLM assigns per-ASSET directional sentiment:
  - Gold: bullish, conviction 0.85, catalyst "PBoC reserves Thursday"
  - S&P: bearish, conviction 0.75, catalyst "Iran conflict shock"
    ↓
LLM matches to MECHANISM ("Geopolitical Shock" + "Energy Supply Shock")
    ↓
Mechanism provides structured asset impacts + chain progress
    ↓
DETERMINISTIC AGGREGATION weights all votes:
  score = Σ(direction × conviction × narrative_confidence × trend_mult) / Σ(weights)
    ↓
TECHNICAL OVERLAY at dashboard render:
  RSI(14), MACD(12,26,9), SMA(20) → ALIGNED or DIVERGENT badge
    ↓
FINAL IDEA:
  "Gold +0.85 score, bullish, 0.85 conviction, contrarian edge,
   catalyst: PBoC data Thursday, exit: >$5,350 or <$5,050"
```

### What Makes an Idea "Actionable"

Each idea includes:
1. **Direction**: bullish or bearish
2. **Conviction**: 0-1 scale, weighted across all supporting narratives
3. **Score**: -1 to +1, the net directional weight
4. **Edge type**: How it differs from consensus (contrarian = highest alpha)
5. **Catalyst**: Specific named event with a date
6. **Exit conditions**: Both profit target AND invalidation level
7. **Technical alignment**: Whether RSI/MACD/SMA agree with the macro call
8. **Scenario support**: Whether a transmission mechanism matches with probability
9. **Conflict flag**: Whether competing mechanisms disagree

### Signal Interpretation Guidance (Prompt-Level)

The prompt gives **explicit weighting or interpretation guidance for only two sources**. All other sources are passed to the LLM in a flat, unweighted list — the LLM decides their relative importance based on its own judgment and the signal content.

| Source | Explicit Prompt Guidance |
|--------|------------------------|
| Spreads | **"Weight them heavily"** — explicitly called out as "quantitative leading indicators" for 1-week directional calls |
| Google Trends | **Contrarian interpretation** — explicitly instructed that retail panic spikes signal short-term bottoms, not continuation |
| Economic Calendar | **`[UPCOMING]` prefix** — LLM is told these are forward-looking scheduled events, to consider consensus vs. prior readings and pre-event positioning risk |
| All other sources | **No explicit weighting** — Central Bank, Economic Data, COT, Market Data, Prediction Markets, Fear & Greed, News, and Reddit are all presented equally in the signal block. The LLM implicitly weighs them based on content quality and relevance. |

**Important**: There is no numeric weighting of signals by source in the aggregation formula either. The deterministic aggregation in Step 4 only weights by `conviction × confidence × trend_multiplier` — all of which are LLM-assigned per-narrative, not per-source.

---

## 5. Dashboard Presentation Layer

### Streamlit UI Architecture

**Sidebar controls**:
- RUN WEEKLY PIPELINE button
- Asset class multiselect (all 6 classes)
- Direction filter (All/Bullish/Bearish)
- Min probability slider (0-100%)

**Main view** (`actionable_view.py`):

1. **Regime Banner**: Colored badge (green=risk_on, red=risk_off, orange=reflation, teal=goldilocks, etc.) with rationale and LLM executive summary

2. **Asset Cards** (split into BULLISH and BEARISH sections):
   - Ticker header with asset class badge and direction arrow
   - **Narrative view**: Conviction bar (visual), horizon, trend, rationale, catalyst, exit condition
   - **Scenario view**: When mechanisms matched — probability badge, mechanism name, category, chain stage, chain step progress visualization, rationale
   - **Consensus vs. Edge Block**: Edge badge (CONTRARIAN/MORE_AGGRESSIVE/MORE_PASSIVE/ALIGNED), consensus text, edge rationale
   - **Technical Indicators** (collapsible expander): RSI(14), MACD(12,26,9), SMA-20 distance, ALIGNED/DIVERGENT badge compared to macro call
   - **Source Attribution**: Chips by source type (News, Market Data, Social, etc.), expandable signal details with title/url/snippet
   - **Conflict Badge**: Orange warning when scenarios disagree on direction

3. **Technical computation** happens at render time (not pipeline time) via `compute_technicals()` — fetches 3-month yfinance data and computes RSI, MACD, SMA distance fresh each page load

### CSS Theme
- Dark monospace terminal aesthetic (#0a0e14 background)
- Color scheme: #00d4aa (teal accent), #00E676 (bullish green), #FF1744 (bearish red), #FFEA00 (neutral yellow)
- Animated pulse dot on title
- Card-based layout with gradient borders

---

## 6. Technical Infrastructure Details

### LLM Configuration
- **Primary**: Claude Sonnet 4 (`claude-sonnet-4-20250514`)
- **Fallback**: Cerebras `gpt-oss-120b`
- **Temperature**: 0.2 (near-deterministic)
- **Max tokens**: 4096
- **Fallback mechanism**: `_LLMWithFallback` wrapper tries providers in order, catches errors, continues to next
- **Framework**: LangChain (ChatPromptTemplate → BaseChatModel pipe)

### Storage Schema
- **8 SQLite tables**: weekly_reports, narratives, signals, narrative_signals, weekly_asset_scores, price_validations, active_scenarios, scenario_asset_views
- **WAL mode** for concurrent reads
- **Graceful migration**: Adds consensus/edge columns to existing databases

### Data Flow
```
[11 Collectors] → [Signal JSON snapshot]
                      ↓
              [10-day relevance filter]
                      ↓
         [LLM Narrative Extraction]
                      ↓
    [Per-Asset Sentiment + Narratives]
                      ↓
    [LLM Mechanism Matcher] → [Active Scenarios]
                      ↓
         [Deterministic Aggregation]
                      ↓
    [WeeklyAssetScore] + [ScenarioAssetView]
                      ↓
     [LLM Regime Classifier]
                      ↓
     [Price Validation vs. actual returns]
                      ↓
     [LLM Weekly Summary]
                      ↓
          [WeeklyReport]
           ↙         ↓         ↘
    [SQLite DB] [JSON file] [Google Sheets]
```

---

## 7. Edge Cases & Design Decisions

### Temporal Grounding
- LLM is explicitly told today's date and instructed NOT to hallucinate historical data
- Each signal includes its date in the prompt formatting
- Stale signals (>10 days) are filtered pre-LLM

### Contrarian Signal Treatment
- Google Trends spikes: Explicitly instructed as CONTRARIAN (retail panic = bottoms)
- VIX > 30: Mean reversion signal (contrarian bullish equities)
- Extreme Fear/Greed: Values < 25 = buying opportunity; > 75 = overheating

### Forward-Looking Events
- Economic calendar events marked `is_forward_looking=True` survive the stale filter
- FOMC dates hardcoded through 2026 as fallback when API doesn't cover beyond this week

### Signal Backfill
- After LLM narrative extraction, system automatically attaches market_data signals for each asset mentioned (LLM sometimes omits these from signal_ids)
- Matching by ticker name or partial name matching

### Mechanism Constraints
- LLM is told NOT to invent new mechanisms — only match from the catalog
- Novel patterns are handled by the unconstrained narrative pipeline
- This dual approach prevents hallucination while allowing flexibility

### Conflict Detection
- Scenario aggregator detects when mechanisms with probability >= 0.2 disagree on asset direction
- Dashboard renders orange conflict badge to warn trader

---

## 8. Historical Report Inventory

The system has generated **15 reports** between Feb 28 and Mar 1, 2026, with increasing sophistication (file sizes grew from ~36KB to ~174KB as more collectors and features were added during development).

Signal snapshots range from ~600 bytes (single-source test runs) to ~361KB (full 11-source collections), typically containing 200-700 signals per full run.

---

## 9. Key Findings & Observations

### Strengths
1. **Multi-source triangulation**: 11 independent data sources reduce single-source bias
2. **Quantitative + qualitative fusion**: Spread z-scores and FRED data anchor the LLM's qualitative narrative extraction
3. **Transparent aggregation**: Final scores are deterministic, auditable, and reproducible
4. **Per-asset consensus analysis**: Edge identification is done asset-by-asset, not just narrative-level
5. **Mechanism catalog constraints**: Prevents LLM from hallucinating novel causal chains
6. **Exit conditions**: Every idea includes both profit-take and invalidation criteria
7. **Price validation**: Historical hit rate tracking enables performance measurement
8. **Technical overlay**: Independent RSI/MACD/SMA check at render time provides real-time divergence detection

### Current State (Week of March 2, 2026)
- **Regime**: Risk-off
- **Dominant narrative**: Middle East conflict (US-Israel strikes on Iran, Feb 28)
- **Highest-conviction trades**: Long gold, long oil, short Nasdaq
- **Key spread signals**: Credit widening (HYG/LQD z: -1.6), flat yield curve (10Y-3M: 0.38%)
- **Upcoming catalyst**: FOMC Rate Decision (March 18, 2026 — 16 days away)

### Potential Areas for Improvement
1. **Signal deduplication**: RSS feeds may produce overlapping articles from syndicated sources
2. **COT data lag**: CFTC data is typically 3 days delayed; the system doesn't explicitly account for this
3. **Google Trends rate limiting**: pytrends is fragile and may fail silently
4. **Reddit API changes**: Using public JSON API which may have rate limits or require auth
5. **Prediction market filtering**: Polymarket may include many non-macro markets in top 50 by volume
6. **Price validation timing**: Compares "this week's" predictions against "this week's" returns rather than validating last week's predictions against this week's actual
7. **No inter-week narrative tracking**: Narratives are not linked across weeks to track evolution (first_seen/last_updated are set at creation time but never updated from prior weeks)

---

## 10. Complete File Inventory

### Python Modules (27 files)
| Path | Purpose | Lines |
|------|---------|-------|
| `app.py` | Streamlit dashboard entry point | 117 |
| `run_weekly.py` | CLI pipeline orchestrator | 263 |
| `config/settings.py` | Pydantic settings, YAML loaders | 51 |
| `config/mechanisms.py` | YAML loader for mechanisms | ~20 |
| `models/schemas.py` | 20+ Pydantic models | 250 |
| `collectors/base.py` | Abstract base collector | ~15 |
| `collectors/rss_news.py` | RSS feed collector | 67 |
| `collectors/central_bank.py` | Fed/ECB collector | 66 |
| `collectors/economic_data.py` | FRED API collector | 77 |
| `collectors/market_data.py` | yfinance OHLCV collector | 135 |
| `collectors/cot_reports.py` | CFTC COT collector | 120 |
| `collectors/fear_greed.py` | Crypto Fear & Greed | 60 |
| `collectors/economic_calendar.py` | ForexFactory + FOMC | 183 |
| `collectors/prediction_markets.py` | Kalshi + Polymarket | 214 |
| `collectors/spreads.py` | VIX/credit/yield/Cu-Au | 457 |
| `collectors/google_trends.py` | Contrarian search trends | 162 |
| `collectors/reddit.py` | Reddit hot posts | 76 |
| `ai/llm.py` | LLM factory with fallback | 88 |
| `ai/prompts/templates.py` | 4 prompt templates | 266 |
| `ai/chains/narrative_extractor.py` | Signal → narrative extraction | 151 |
| `ai/chains/mechanism_matcher.py` | Signal → mechanism matching | 155 |
| `ai/chains/regime_classifier.py` | Narrative → regime + summary | 90 |
| `analysis/sentiment_aggregator.py` | Deterministic score aggregation | 90 |
| `analysis/scenario_aggregator.py` | Scenario-based aggregation | 117 |
| `analysis/price_validator.py` | Prediction vs actual returns | 88 |
| `analysis/technicals.py` | RSI/MACD/SMA computation | 265 |
| `dashboard/actionable_view.py` | Streamlit rendering | ~600 |
| `dashboard/styles.py` | Dark terminal CSS | ~100 |
| `storage/store.py` | SQLite CRUD (8 tables) | 590 |
| `exports/sheets.py` | Google Sheets export | 143 |

### Configuration Files
| File | Content |
|------|---------|
| `config/assets.yaml` | 31 tickers across 6 asset classes |
| `config/sources.yaml` | RSS feeds, subreddits, FRED series, Google Trends keywords |
| `config/mechanisms.yaml` | 18 transmission mechanisms (87.5KB) |
| `.env` | API keys (Anthropic, Cerebras, FRED, Reddit, Google Sheets) |
| `pyproject.toml` | Poetry dependencies |

### Data Files
| Directory | Content |
|-----------|---------|
| `data/raw/` | Signal JSON snapshots (30+ files) |
| `data/reports/` | Report JSON snapshots (15 files) |
| `macro_pulse.db` | SQLite database |

---

## 11. Summary

macro-pulse is a sophisticated end-to-end macro intelligence system that transforms raw multi-source signals into actionable directional trading ideas. The workflow progresses through signal collection (11 sources, ~500-700 signals), LLM-powered narrative extraction (3-8 themes), transmission mechanism matching (18 known causal chains), deterministic score aggregation, price validation, and executive summary generation — all presented through a dark-themed Streamlit dashboard with per-asset cards showing direction, conviction, catalyst, exit conditions, consensus edge analysis, and technical indicator alignment.

The current live output (March 1, 2026) identifies a **risk-off regime** driven by the US-Israel strikes on Iran, with highest-conviction ideas being **long gold** (0.85 conviction, edge: more_aggressive vs. consensus), **long crude oil** (0.88 conviction, supply shock), and **short Nasdaq** (0.78 conviction, contrarian to year-end targets), all supported by quantitative spread signals (credit widening, flat yield curve) and forward-looking catalysts (FOMC March 18).
