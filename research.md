# Macro-Pulse Data Retrieval — Deep Research Report

## 1. Project Overview

Macro-Pulse is a weekly macro non-consensus discovery system. It collects signals from 16 different data sources, computes a quantitative consensus picture, then uses an LLM to find non-consensus (alpha) views — places where the data disagrees with what the market has priced in.

The pipeline runs in **two phases** (formerly three, simplified in commit `347645e`):

- **Phase 1 — Consensus Computation**: "What does the market think?"
- **Phase 2 — Non-Consensus Discovery**: "Where is the market wrong?"

The output is a `WeeklyReport` stored in SQLite and optionally exported to Google Sheets, displayed in a Streamlit dashboard.

---

## 2. Architecture: How Phases Work

### 2.1 Pipeline Entry Point (`run_weekly.py`)

The main function `run_pipeline()` calls:
1. `run_phase_1(sources)` → returns consensus signals, quant scores, consensus views, and the LLM instance
2. `run_phase_2(phase1, sources)` → returns alpha signals, non-consensus views, active scenarios, regime, and summary
3. `build_report(phase1, phase2)` → assembles the `WeeklyReport`
4. Saves to SQLite via `storage/store.py`, exports JSON, and optionally syncs to Google Sheets

A legacy monolithic pipeline (`run_pipeline_legacy`) still exists but is only invoked with `--legacy` flag.

### 2.2 Source Classification (`config/signal_roles.py`)

Sources are classified into two roles that determine which phase uses them:

**Positioning Sources** (quantitative, how money is deployed):
- `options` — Deribit options data
- `derivatives_consensus` — Binance/Bybit/OKX derivatives
- `etf_flows` — BTC/ETH spot ETF flows
- `funding_rates` — Crypto perpetual funding rates
- `market_data` — yfinance price/return data
- `cot_reports` — CFTC Commitment of Traders

**Narrative Consensus Sources** (qualitative, what people believe):
- `news` — RSS financial news feeds
- `reddit` — Subreddit posts
- `fear_greed` — Crypto Fear & Greed Index
- `prediction_markets` — Kalshi + Polymarket
- `central_bank` — Fed/ECB RSS feeds
- `economic_calendar` — ForexFactory + hardcoded FOMC dates

**Alpha Sources** (may contain information not yet priced in):
- `news`, `reddit`, `spreads`, `google_trends`, `onchain`, `economic_data`, `central_bank`, `economic_calendar`

Note: Some sources are dual-role (e.g. `news` feeds both consensus and alpha).

**All positioning + narrative sources = CONSENSUS_SOURCES** (used in Phase 1)
**ALPHA_SOURCES** are used in Phase 2.

### 2.3 Currently Enabled Collectors (`config/sources.yaml`)

Not all collectors are active. The current `enabled_collectors` list is:
- `news` (crypto RSS only: CoinTelegraph, CoinDesk)
- `reddit` (CryptoCurrency, CryptoMarkets subreddits only)
- `fear_greed`
- `market_data`
- `spreads`
- `google_trends`
- `funding_rates`
- `onchain`

**Disabled** (commented out): `central_bank`, `economic_data`, `cot`, `economic_calendar`, `prediction_markets`

The enabled set is crypto-focused — most traditional macro/FX collectors are disabled.

---

## 3. Phase 1: Consensus Computation — Detailed Data Flow

### Step 1.1: Collect Consensus Signals

`collect_signals_by_role("consensus")` is called. This:
1. Collects from standard collectors whose names appear in `CONSENSUS_SOURCES` (minus the three dedicated consensus collectors)
2. Also calls `collect_consensus_signals()` which runs the three dedicated collectors: `OptionsConsensusCollector`, `DerivativesConsensusCollector`, `ETFFlowsCollector`

All signals are `Signal` objects (Pydantic models) with: `id`, `source` (enum), `title`, `content`, `url`, `timestamp`, `metadata` (dict).

### Step 1.2: Compute Quantitative Consensus

Signals are filtered to `POSITIONING_SOURCES` only, then passed to `compute_consensus_scores()` in `analysis/consensus_scorer.py`.

This function:
1. Groups signals by symbol (BTC, ETH only)
2. Extracts raw values from signal metadata (options skew, funding rate, top trader L/S ratio, ETF flows, put/call ratio, OI change)
3. Normalizes each component to [-1, +1] using static default ranges
4. Computes an **equal-weighted average** of all available components
5. Classifies direction: >+0.15 = bullish, <-0.15 = bearish, else neutral
6. Returns `ConsensusScore` objects per asset

### Step 1.3: Synthesize Consensus (LLM)

The `synthesize_consensus()` function in `ai/chains/consensus_synthesizer.py`:
1. Formats quant scores, positioning signals, narrative signals, and market data into text blocks
2. Sends them to the LLM via `CONSENSUS_SYNTHESIS_PROMPT`
3. Parses the JSON response into `ConsensusView` objects

Each `ConsensusView` contains:
- Quant score and direction
- Positioning consensus (text summary of how money is positioned)
- Narrative consensus (text summary of what people are saying)
- Market narrative (price action context)
- Consensus coherence: do positioning and narrative agree?
- Key levels, what's priced in vs. not priced in
- Consensus direction + confidence

---

## 4. Phase 2: Non-Consensus Discovery — Detailed Data Flow

### Step 2.1: Collect Alpha Signals

`collect_signals_by_role("alpha")` collects from `ALPHA_SOURCES`: news, reddit, spreads, google_trends, onchain, economic_data, central_bank, economic_calendar.

### Step 2.2: Filter Stale Signals

`filter_stale_signals()` removes old data:
- Crypto sources (fear_greed, funding_rates, onchain, options, derivatives_consensus, etf_flows): max 5 days old
- All other sources: max 10 days old
- Forward-looking signals (e.g. scheduled events) are never filtered

### Step 2.3: Match Transmission Mechanisms

`match_mechanisms()` takes all signals (consensus + alpha combined) and the mechanism catalog (`config/mechanisms.yaml`), sends them to the LLM to identify which known macro causal chains are currently active.

The mechanism catalog defines 12+ mechanisms across categories (crypto, monetary_policy, risk_sentiment, etc.) with:
- Trigger sources and keywords
- Chain steps (causal progression with observables and lag days)
- Asset impacts (which tickers, what direction, what sensitivity)
- Confirmation and invalidation criteria

Currently enabled categories: `crypto`, `monetary_policy`, `risk_sentiment`.

### Step 2.4: Classify Regime

`classify_regime_from_consensus()` uses consensus views + active scenarios to classify the macro regime into one of: `risk_on`, `risk_off`, `reflation`, `stagflation`, `goldilocks`, `transition`.

### Step 2.5: Discover Non-Consensus Views (LLM)

`discover_non_consensus()` is the core alpha-generation step:
1. Formats established consensus views and alpha signals into text
2. Sends to LLM via `NON_CONSENSUS_DISCOVERY_PROMPT`
3. The LLM finds where alpha signals **disagree** with consensus
4. Parses output into `NonConsensusView` objects
5. Filters: requires at least 2 independent sources to be valid
6. Sorts by validity_score

Each `NonConsensusView` contains:
- Consensus vs. our direction
- Thesis text
- Edge type (contrarian, more_aggressive, more_passive)
- Evidence list with signal IDs and strength
- Testable mechanism flag, timing edge flag, catalyst
- Invalidation criteria
- Validity score

### Step 2.6: Enrich NC Views

`enrich_nc_views()` adds context:
- Links NC views to supporting transmission mechanisms
- Adds mechanism stage (early/mid/late)
- Adds quant consensus score
- Adds consensus coherence
- Adds regime context

### Step 2.7: Generate Weekly Summary (LLM)

`generate_summary_from_consensus()` creates a human-readable summary of consensus views, non-consensus discoveries, active mechanisms, regime, and rationale.

---

## 5. Collector-by-Collector Deep Dive

### 5.1 Market Data Collector (`collectors/market_data.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.MARKET_DATA` |
| **API** | yfinance (`yf.download`) |
| **Auth required** | No |
| **Phase role** | Positioning (consensus) |
| **Data fetched** | 1 month OHLCV for all assets in `config/assets.yaml` |

**How it works:**
- Reads the full asset universe from `config/assets.yaml` (33 tickers across FX, metals, energy, crypto, indices, bonds)
- Downloads 1 month of data in a single batch `yf.download(all_tickers, period="1mo")`
- Computes weekly return (last 5 trading days) and monthly return
- Emits one `Signal` per asset with price, weekly/monthly return, and asset class in metadata
- Also provides a `get_weekly_returns()` method used by the technicals module

**Signal metadata keys:** `ticker`, `asset_class`, `weekly_return_pct`, `monthly_return_pct`, `price`

### 5.2 RSS News Collector (`collectors/rss_news.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.NEWS` |
| **API** | feedparser (RSS) |
| **Auth required** | No |
| **Phase role** | Consensus (narrative) + Alpha |
| **Currently active feeds** | CoinTelegraph, CoinDesk (crypto only) |

**How it works:**
- Iterates over RSS feed URLs from `config/sources.yaml` under `rss_feeds`
- Parses each feed, takes top 20 entries per feed
- Extracts title, summary/description, link, and published date
- Traditional macro feeds (Reuters, BBC, CNBC, etc.) are configured but commented out

### 5.3 Reddit Collector (`collectors/reddit.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.SOCIAL` |
| **API** | Reddit public JSON API (`/r/{sub}/hot.json`) |
| **Auth required** | No (uses User-Agent header) |
| **Phase role** | Consensus (narrative) + Alpha |
| **Currently active subreddits** | CryptoCurrency, CryptoMarkets |

**How it works:**
- Fetches hot posts from each subreddit (25 per sub by default)
- Uses `urllib.request` with User-Agent `macro-pulse/0.1`
- Skips stickied posts
- Extracts title, selftext (truncated to 500 chars), permalink, score, comment count, upvote ratio
- Traditional finance subreddits (wallstreetbets, investing, Forex, Gold, etc.) are configured but commented out

**Note:** Uses `SignalSource.SOCIAL` not a dedicated Reddit enum, even though `signal_roles.py` references source value `"reddit"`. This is a potential mismatch — the collector's signals use `SOCIAL` but filtering logic checks for `"reddit"`.

### 5.4 Central Bank Collector (`collectors/central_bank.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.CENTRAL_BANK` |
| **API** | feedparser (RSS) |
| **Auth required** | No |
| **Phase role** | Consensus (narrative) + Alpha |
| **Currently enabled** | **No** (commented out in sources.yaml) |

**How it works:**
- Fetches RSS feeds from Fed speeches, Fed press releases, and ECB
- Takes top 15 entries per feed
- Prefixes titles with `[Central Bank]`
- Feed URLs: federalreserve.gov/feeds/speeches.xml, press_all.xml, ecb.europa.eu/rss/press.html

### 5.5 FRED Economic Data Collector (`collectors/economic_data.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.ECONOMIC_DATA` |
| **API** | fredapi (FRED API) |
| **Auth required** | Yes (`FRED_API_KEY`) |
| **Phase role** | Alpha |
| **Currently enabled** | **No** (commented out in sources.yaml) |

**How it works:**
- Fetches latest reading for each configured FRED series
- Computes change from prior reading and percentage change
- Configured series (11 total): Federal Funds Rate, 10Y-2Y spread, breakeven inflation, trade-weighted USD, jobless claims, Michigan sentiment, VIX, HY OAS spread, SOFR, 10Y-3M spread, St. Louis financial stress index

### 5.6 COT Reports Collector (`collectors/cot_reports.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.COT` |
| **API** | CFTC direct CSV download (httpx) |
| **Auth required** | No |
| **Phase role** | Positioning (consensus) |
| **Currently enabled** | **No** (commented out in sources.yaml) |

**How it works:**
- Downloads the full CFTC "new COT" file from `cftc.gov/dea/newcot/deafut.txt`
- Parses comma-delimited data
- Matches rows to 15 tracked contracts by CFTC code: EUR, GBP, JPY, AUD, CAD, CHF, Gold, Silver, Crude Oil, Natural Gas, Copper, S&P 500, Nasdaq 100, US 10Y Note, Bitcoin
- Extracts non-commercial (speculative) long/short positions and weekly changes
- Computes net speculative positioning

**Signal metadata keys:** `contract`, `net_speculative`, `net_change`, `long_spec`, `short_spec`

### 5.7 Fear & Greed Collector (`collectors/fear_greed.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.FEAR_GREED` |
| **API** | alternative.me Fear & Greed API |
| **Auth required** | No |
| **Phase role** | Consensus (narrative) |
| **Currently enabled** | Yes |

**How it works:**
- Fetches last 7 days of Crypto Fear & Greed Index
- Each entry: value (0-100), classification (Extreme Fear to Extreme Greed), timestamp
- One signal per day (7 total)

### 5.8 Economic Calendar Collector (`collectors/economic_calendar.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.ECONOMIC_DATA` |
| **API** | ForexFactory JSON feed (nfs.faireconomy.media) + hardcoded FOMC dates |
| **Auth required** | No |
| **Phase role** | Consensus (narrative) + Alpha |
| **Currently enabled** | **No** (commented out in sources.yaml) |

**How it works:**
- Fetches this week's calendar events from ForexFactory free feed
- Filters by impact level (high/medium) and country (US, EU, GB, JP, CN, AU, CA)
- Only keeps **future** events (not past)
- Also maintains a hardcoded list of FOMC meeting dates through 2026
- Creates signals for upcoming meetings within `lookforward_days` (21 days)
- Forward-looking signals have `is_forward_looking: True` in metadata (exempt from staleness filtering)

**Important:** Uses `SignalSource.ECONOMIC_DATA` (same as FRED), not a separate enum value, even though it's configured as `"economic_calendar"` in signal_roles.

### 5.9 Prediction Markets Collector (`collectors/prediction_markets.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.PREDICTION_MARKET` |
| **API** | Kalshi REST API + Polymarket Gamma API (httpx) |
| **Auth required** | No |
| **Phase role** | Consensus (narrative) |
| **Currently enabled** | **No** (commented out in sources.yaml) |

**How it works:**

*Kalshi:*
- Fetches events from the elections API (`api.elections.kalshi.com`)
- Filters to macro-relevant categories: Economics, Financials, Politics, World
- For each macro event, fetches individual markets
- Sorts by volume, takes top 50
- Computes probability from yes_bid/yes_ask

*Polymarket:*
- Fetches active markets from gamma-api.polymarket.com
- Parses outcome prices to derive probability
- Sorts by volume, takes top 50

### 5.10 Spreads Collector (`collectors/spreads.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.SPREADS` |
| **API** | yfinance |
| **Auth required** | No |
| **Phase role** | Alpha |
| **Currently enabled** | Yes |

Downloads 3 months of data for 11 spread-related tickers: ^VIX, ^VIX3M, ^VVIX, ^TNX, ^FVX, ^TYX, ^IRX, HYG, LQD, GC=F, HG=F.

**Five sub-signals computed:**

1. **VIX Term Structure** — VIX spot / VIX3M ratio. Backwardation (>1.05) = near-term fear. Deep contango (<0.85) = complacency. Also emits VIX level signal if VIX >25 (with contrarian bullish note if >30).

2. **VIX/VVIX Ratio** — VVIX >120 with VIX <20 = vol breakout imminent. Also detects VVIX 3-day spikes >15%.

3. **Credit Spread (HYG/LQD)** — 10-day z-score of HYG/LQD ratio. Z < -1.5 = widening (risk-off). Z > 1.5 = tightening (risk-on).

4. **Yield Curve (10Y-3M)** — Inverted = recession risk. Also detects rapid moves (>0.15% in 5 days).

5. **Copper/Gold Ratio** — 20-day z-score. Falling = risk-off. Rising = risk-on.

**Key design choice:** Signals are only emitted when thresholds are breached (not always). If markets are calm, the spreads collector may return zero signals.

### 5.11 Google Trends Collector (`collectors/google_trends.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.GOOGLE_TRENDS` |
| **API** | pytrends (Google Trends unofficial API) |
| **Auth required** | No |
| **Phase role** | Alpha |
| **Currently enabled** | Yes |

**How it works:**
- Queries Google Trends for configured keywords in batches of 5 (API limit)
- Timeframe: "today 1-m" (30-day daily data)
- Computes 7-day average ratio (current vs. 7-day mean)
- Two signal types:
  - **Strong spike**: interest >= 70 AND ratio >= 1.5x -> contrarian signal
  - **Rapid acceleration**: interest >= 50 AND ratio >= 2.0x -> emerging narrative

**Currently tracked keywords:** margin call, bitcoin crash, ethereum crash, solana crash, crypto crash, crypto regulation, bitcoin ETF, crypto winter

**Philosophy:** Retail search spikes are treated as **contrarian** indicators — peak public anxiety often coincides with short-term market bottoms.

### 5.12 Funding Rates Collector (`collectors/funding_rates.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.FUNDING_RATES` |
| **API** | CoinGlass public API (primary), Binance FAPI (fallback) |
| **Auth required** | No |
| **Phase role** | Positioning (consensus) |
| **Currently enabled** | Yes |

**How it works:**
- Primary: CoinGlass `/public/v2/funding` and `/public/v2/open_interest`
- Fallback: Binance FAPI endpoints (fundingRate, openInterest, ticker/price)
- Tracks BTC, ETH, SOL

**Signals per symbol:**
1. **Funding rate** — current rate + 7-day average + crowd interpretation
2. **Open interest** — current OI in USD + 24h change %
3. **Leverage alert** (conditional) — extreme funding triggers liquidation risk signal

**Thresholds:**
- Extreme long: funding >0.05% -> high liquidation risk
- Crowded long: >0.03% -> bearish contrarian
- Crowded short: <-0.01% -> bullish short squeeze
- Extreme short: <-0.03% -> strong short squeeze potential

### 5.13 On-Chain Collector (`collectors/onchain.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.ONCHAIN` |
| **API** | DeFi Llama stablecoins API |
| **Auth required** | No |
| **Phase role** | Alpha |
| **Currently enabled** | Yes |

**How it works:**
- Fetches total stablecoin market cap from `stablecoins.llama.fi`
- Iterates over all pegged assets, sums circulating supply across chains
- Computes 7-day change for total supply and individual major stablecoins (USDT, USDC, DAI)

**Signals emitted:**
1. **Total stablecoin supply** — growing = bullish (dry powder entering), shrinking = bearish
2. **USDT vs USDC comparison** — USDT growing faster = offshore/EM demand; USDC growing faster = US institutional demand
3. **Decline alerts** — if any major stablecoin drops >1% in 7 days

### 5.14 Options Consensus Collector (`collectors/options_consensus.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.OPTIONS` |
| **API** | Deribit public API (no auth) |
| **Auth required** | No |
| **Phase role** | Positioning (consensus) — dedicated consensus collector |
| **Currently enabled** | Yes (always, via `collect_consensus_signals()`) |

**The most complex collector.** Fetches 5 distinct metrics per symbol (BTC, ETH):

1. **25-delta risk reversal (skew)** — Compares IV of 25-delta calls vs puts. Positive = bullish consensus. Uses actual delta from Greeks if available, falls back to moneyness approximation (~8% OTM).

2. **Put/Call OI ratio** — Total put OI / call OI at the target weekly expiry. <0.7 = bullish. >1.0 = bearish.

3. **Max pain** — Strike where total option holder loss is maximized. Computed by iterating all strikes and summing intrinsic value * OI. Price tends to gravitate toward max pain near expiry.

4. **DVOL (Deribit Volatility Index)** — 30-day expected annualized IV. Fetched via `get_volatility_index_data` endpoint. >80 = extreme fear, <40 = complacency.

5. **IV term structure slope** — (far_term_ATM_IV - near_term_ATM_IV) / near_term_IV. Negative (backwardation) = market expects move this week. Positive (contango) = calm.

**Plus a composite signal** that bundles all raw values in metadata for machine consumption by the consensus scorer.

**Expiry selection:** Targets the nearest weekly expiry between 12 hours and 9 days from now.

### 5.15 Derivatives Consensus Collector (`collectors/derivatives_consensus.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.DERIVATIVES_CONSENSUS` |
| **API** | Binance FAPI (httpx) + ccxt (Binance, Bybit, OKX) |
| **Auth required** | No |
| **Phase role** | Positioning (consensus) — dedicated consensus collector |
| **Currently enabled** | Yes (always, via `collect_consensus_signals()`) |

**Data sources per symbol (BTC, ETH):**

1. **Global L/S ratio** — Binance `globalLongShortAccountRatio`. >1.2 = crowded long (bearish contrarian). <0.8 = crowded short (bullish contrarian). Also fetches 7-day average.

2. **Top trader L/S ratio** — Binance `topLongShortPositionRatio`. >1.3 = smart money strongly long. <0.7 = smart money strongly short.

3. **OI-weighted funding rate** — Aggregates funding from Binance + Bybit + OKX via ccxt (or Binance-only fallback). Weights by each exchange's OI share.

4. **7-day accumulated funding** — Sums 21 funding rate entries (7 days x 3 settlements/day). Persistent positive = bullish consensus. Computes annualized rate.

5. **OI change (24h and 7d)** — From Binance `openInterestHist` endpoint. Rising OI + rising price = trend confirmation. Collapsed OI >20% = leverage flush.

6. **Composite summary signal** — Tallies bullish vs bearish indicators, produces overall consensus label.

### 5.16 ETF Flows Collector (`collectors/etf_flows.py`)

| Attribute | Value |
|-----------|-------|
| **Source enum** | `SignalSource.ETF_FLOWS` |
| **API** | SoSoValue API (primary), neutral stubs (fallback) |
| **Auth required** | No |
| **Phase role** | Positioning (consensus) — dedicated consensus collector |
| **Currently enabled** | Yes (always, via `collect_consensus_signals()`) |

**How it works:**
- Tries two SoSoValue base URLs (api.sosovalue.com, api.sosovalue.xyz)
- Flexible field extraction — tries multiple key names to handle API schema changes
- If SoSoValue is unavailable, returns neutral zero-flow stub signals with `data_available: False` so the consensus scorer can down-weight

**Signals:**
- BTC daily net flow + 5-day rolling net flow + IBIT (BlackRock) specific flow
- ETH daily net flow + 5-day rolling net flow
- Extreme flow alert if daily flow >$500M

---

## 6. Consensus Scoring Deep Dive (`analysis/consensus_scorer.py`)

The consensus scorer takes signals from the three dedicated consensus collectors (options, derivatives, ETF flows) and produces a single `ConsensusScore` per asset (BTC, ETH only).

**Six normalized components (each -1 to +1):**

| Component | Raw Input | Normalization Range | Interpretation |
|-----------|-----------|---------------------|----------------|
| `options_skew` | 25-delta risk reversal | [-0.05, +0.05] | Positive = bullish |
| `funding_7d` | 7d accumulated funding | [-0.10, +0.10] | Positive = bullish |
| `top_trader_ls` | Top trader L/S ratio | [0.7, 1.3] | >1.0 = bullish |
| `etf_flows` | 5-day rolling ETF flow | [-500, +500] $M | Positive = bullish |
| `put_call_ratio` | PCR (inverted) | [0.5, 1.5] | Low PCR = bullish |
| `oi_momentum` | 7-day OI change % | [-15%, +15%] | Positive = bullish |

**Equal-weighted average** of available components. Direction thresholds: +/-0.15.

**Design note:** Weights are intentionally equal because there isn't enough outcome data yet to determine which components are most predictive. The plan is to shift weights after 8-12 weeks of tracked outcomes.

---

## 7. LLM Integration

### Provider Setup (`ai/llm.py`)
- Primary: Anthropic Claude (`claude-sonnet-4-20250514`)
- Fallback: Cerebras (`gpt-oss-120b`)
- Temperature: 0.2 (low, for consistency)
- Max tokens: 4096
- Uses LangChain (`langchain_anthropic`, `langchain_cerebras`)
- Automatic fallback: tries Anthropic first, if it fails, tries Cerebras

### LLM Calls in the Pipeline
1. **Consensus synthesis** (`consensus_synthesizer.py`) — takes quant scores + positioning signals + narrative signals + market data -> produces `ConsensusView` JSON
2. **Mechanism matching** (`mechanism_matcher.py`) — takes all signals + mechanism catalog -> identifies active scenarios
3. **Regime classification** (`regime_classifier.py`) — takes consensus views + scenarios -> classifies macro regime
4. **Non-consensus discovery** (`non_consensus_discoverer.py`) — takes consensus views + alpha signals -> finds disagreements
5. **Summary generation** (`regime_classifier.py`) — takes everything -> produces human-readable weekly summary

---

## 8. Data Flow Diagram

```
                    +----------------------------------+
                    |         config/sources.yaml       |
                    |         config/assets.yaml        |
                    +----------------+-----------------+
                                     |
                    +----------------v-----------------+
                    |      PHASE 1: CONSENSUS          |
                    +----------------------------------+
                    |                                   |
                    |  Standard Consensus Collectors:   |
                    |    - market_data (yfinance)       |
                    |    - news (RSS)                   |
                    |    - reddit (JSON API)            |
                    |    - fear_greed (alternative.me)  |
                    |    - funding_rates (CoinGlass)    |
                    |                                   |
                    |  Dedicated Consensus Collectors:  |
                    |    - options (Deribit)             |
                    |    - derivatives (Binance+ccxt)   |
                    |    - etf_flows (SoSoValue)        |
                    |                                   |
                    +----------------+-----------------+
                                     |
                         +-----------v-----------+
                         | consensus_scorer.py   |
                         | (quant: 6 components) |
                         +-----------+-----------+
                                     |
                         +-----------v-----------+
                         | consensus_synthesizer |
                         | (LLM: positioning +   |
                         |  narrative -> views)  |
                         +-----------+-----------+
                                     |
                              ConsensusViews
                                     |
                    +----------------v-----------------+
                    |      PHASE 2: NON-CONSENSUS      |
                    +----------------------------------+
                    |                                   |
                    |  Alpha Collectors:                |
                    |    - news (RSS, same feeds)       |
                    |    - reddit (same subs)           |
                    |    - spreads (yfinance)           |
                    |    - google_trends (pytrends)     |
                    |    - onchain (DeFi Llama)         |
                    |                                   |
                    |  + filter_stale_signals()         |
                    |                                   |
                    +----------------+-----------------+
                                     |
                         +-----------v-----------+
                         | mechanism_matcher     |
                         | (LLM: signals ->      |
                         |  active scenarios)    |
                         +-----------+-----------+
                                     |
                         +-----------v-----------+
                         | regime_classifier     |
                         | (LLM: regime label)   |
                         +-----------+-----------+
                                     |
                         +-----------v-----------+
                         | non_consensus_disc.   |
                         | (LLM: consensus vs    |
                         |  alpha -> NC views)   |
                         +-----------+-----------+
                                     |
                         +-----------v-----------+
                         | nc_enricher           |
                         | (mechanisms + regime) |
                         +-----------+-----------+
                                     |
                              NonConsensusViews
                                     |
                    +----------------v-----------------+
                    |         WeeklyReport              |
                    |  - SQLite (macro_pulse.db)        |
                    |  - JSON (data/reports/)           |
                    |  - Google Sheets (optional)       |
                    |  - Streamlit dashboard (app.py)   |
                    +----------------------------------+
```

---

## 9. API Dependencies Summary

| Collector | API / Source | Auth | Rate Limits | Reliability |
|-----------|-------------|------|-------------|-------------|
| market_data | yfinance | None | Informal limits | High |
| rss_news | feedparser (RSS) | None | N/A | High |
| reddit | Reddit JSON API | None (User-Agent) | Tight (rate limited) | Medium |
| central_bank | feedparser (RSS) | None | N/A | High |
| economic_data | FRED API | API Key | 120/min | High |
| cot_reports | CFTC CSV | None | N/A | High |
| fear_greed | alternative.me | None | Unknown | Medium |
| economic_calendar | ForexFactory JSON | None | Unknown | Medium |
| prediction_markets | Kalshi + Polymarket | None | Unknown | Medium |
| spreads | yfinance | None | Informal limits | High |
| google_trends | pytrends | None | Very aggressive limits | Low |
| funding_rates | CoinGlass / Binance | None | Unknown / generous | Medium-High |
| onchain | DeFi Llama | None | Generous | High |
| options | Deribit public API | None | Moderate | High |
| derivatives | Binance + ccxt | None | Moderate | High |
| etf_flows | SoSoValue | None | Unknown | Low |

---

## 10. Notable Design Decisions & Specificities

### 10.1 Dual Collection in Phase 2
Alpha sources that overlap with consensus sources (news, reddit, central_bank, economic_calendar) are collected **twice** — once in Phase 1 for consensus, once in Phase 2 for alpha. The same raw data is re-examined through a different analytical lens.

### 10.2 Signal ID Generation
All collectors use MD5 hashing with date-based or content-based seeds to generate deterministic 12-character signal IDs. This prevents duplicate signals on re-runs within the same day.

### 10.3 Fallback Patterns
- `FundingRatesCollector`: CoinGlass -> Binance FAPI
- `DerivativesConsensusCollector`: ccxt (multi-exchange) -> httpx Binance-only
- `ETFFlowsCollector`: SoSoValue -> neutral stubs
- `OptionsConsensusCollector`: weekly expiry -> nearest any expiry
- `LLM`: Anthropic -> Cerebras

### 10.4 Staleness Filtering
Crypto sources get a tighter 5-day window vs. 10 days for macro sources. Forward-looking signals (scheduled events) are never filtered.

### 10.5 Threshold-Based Emission
The `SpreadsCollector` only emits signals when thresholds are breached. In calm markets, it may return zero signals. This contrasts with other collectors that always emit data.

### 10.6 Crypto Focus
Despite the broad asset universe in `assets.yaml` (33 tickers), the consensus scoring only produces scores for **BTC and ETH**. The mechanism catalog is filtered to `crypto`, `monetary_policy`, and `risk_sentiment` categories. Most non-crypto collectors are disabled. The system is currently tuned as a crypto-focused tool that uses macro context.

### 10.7 Source Enum Mismatches
- `RedditCollector` uses `SignalSource.SOCIAL` but `signal_roles.py` checks for `"reddit"` — this means Reddit signals may not be correctly classified in the role-based filtering
- `EconomicCalendarCollector` uses `SignalSource.ECONOMIC_DATA` but is listed as `"economic_calendar"` in signal_roles — similar mismatch issue

### 10.8 Equal-Weight Consensus Scoring
The consensus scorer deliberately uses equal weights across all 6 components. This is a principled choice — without outcome data to validate which components are most predictive, equal weighting avoids premature optimization. The code comments indicate weights should be shifted after 8-12 weeks of tracked outcomes.

### 10.9 Non-Consensus Validation
NC views require at least 2 independent sources to pass validation. Views backed by a single source are dropped with a log message. This prevents noise and false signals.

### 10.10 Transmission Mechanisms
The mechanism catalog (`mechanisms.yaml`) defines known macro causal chains with explicit chain steps, observables, lag days, asset impacts, and confirmation/invalidation criteria. The LLM matches incoming signals to these pre-defined chains rather than inventing new causal explanations — this constrains hallucination and keeps the system grounded in established macro theory.
