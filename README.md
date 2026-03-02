# MACRO-PULSE

Weekly macro narrative extraction system for directional trading across FX, metals, energy, crypto, indices, and bonds.

Collects raw signals from 11 data sources, passes them through an LLM pipeline (Claude / Cerebras) to extract coherent macro narratives, matches signals against a catalog of 18 known transmission mechanisms, and presents everything in a Streamlit command-center dashboard targeting a **1-week trading horizon**.

---

## Pipeline Overview

The weekly pipeline (`run_weekly.py`) executes 7 steps:

1. **Collect signals** — runs all 11 collectors, saves raw JSON snapshots
2. **Filter stale signals** — drops signals older than 10 days (except forward-looking events)
3. **Extract narratives** — LLM produces 3-8 coherent macro narratives with per-asset directional sentiment, consensus vs. edge analysis, catalysts, and exit conditions
4. **Match transmission mechanisms** — LLM matches signals to the 18-mechanism catalog, producing active scenarios with chain progress and probability estimates
5. **Classify economic regime** — LLM classifies one of 6 regimes (risk-on, risk-off, reflation, stagflation, goldilocks, transition) with confidence
6. **Aggregate asset scores** — deterministic weighted aggregation (conviction x narrative confidence x trend multiplier)
7. **Price validation** — compares last week's directional predictions vs actual returns from yfinance (hit rate by asset class)

A final LLM call generates a 3-5 sentence executive summary. Reports are persisted to SQLite and JSON.

---

## Data Sources (11 Collectors)

### 1. RSS News Feeds (`collectors/rss_news.py`)

Macro and market news from major financial outlets, parsed via `feedparser`.

| Category | Feeds |
|---|---|
| Macro / General | Reuters (Business, Top News), BBC Business, CNBC (Economy, Markets), MarketWatch Top Stories, NYT Business |
| FX / Commodities | ForexLive, FXStreet |
| Crypto | CoinTelegraph, CoinDesk |

Each article yields a signal with headline, summary snippet, source, and publication timestamp.

### 2. Central Bank Communications (`collectors/central_bank.py`)

Official RSS feeds from the Federal Reserve and ECB:

- **Fed speeches** — `federalreserve.gov/feeds/speeches.xml`
- **Fed press releases** — `federalreserve.gov/feeds/press_all.xml`
- **ECB press releases** — `ecb.europa.eu/rss/press.html`

Captures rate decisions, forward guidance language, QT/QE announcements, and policy committee commentary.

### 3. FRED Economic Data (`collectors/economic_data.py`)

11 macro-economic time series from the Federal Reserve Economic Data API (`fredapi`):

| Series ID | Indicator |
|---|---|
| `DFF` | Federal Funds Rate |
| `T10Y2Y` | 10Y-2Y Treasury Spread |
| `T10Y3M` | 10Y-3M Treasury Spread |
| `T10YIE` | 10Y Breakeven Inflation |
| `DTWEXBGS` | Trade Weighted USD Index |
| `ICSA` | Initial Jobless Claims |
| `UMCSENT` | Michigan Consumer Sentiment |
| `VIXCLS` | CBOE VIX |
| `BAMLH0A0HYM2` | High-Yield OAS Spread |
| `SOFR` | Secured Overnight Financing Rate |
| `STLFSI2` | St. Louis Fed Financial Stress Index |

Signals include current value, week-over-week change, and directional context.

### 4. Market Data (`collectors/market_data.py`)

OHLCV price data from `yfinance` for 31 tickers across 6 asset classes:

| Asset Class | Tickers |
|---|---|
| **FX** (8) | DXY, EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, USD/CNH |
| **Metals** (4) | Gold, Silver, Platinum, Copper |
| **Energy** (3) | WTI Crude, Brent Crude, Natural Gas |
| **Crypto** (3) | Bitcoin, Ethereum, Solana |
| **Indices** (8) | S&P 500, Nasdaq, Dow Jones, Russell 2000, VIX, FTSE 100, Nikkei 225, Hang Seng |
| **Bonds** (4) | US 10Y Yield, 30Y Yield, 5Y Yield, TLT (20+ Year Treasury ETF) |

Provides weekly and monthly return calculations, plus live technical indicators (RSI-14, MACD 12/26/9, 20-day SMA distance).

### 5. CFTC Commitment of Traders (`collectors/cot_reports.py`)

Weekly positioning data downloaded directly from `cftc.gov/dea/newcot/deafut.txt`, tracking net speculative positioning for 15 futures contracts:

- **FX**: EUR, GBP, JPY, AUD, CAD, CHF
- **Metals**: Gold, Silver, Copper
- **Energy**: Crude Oil, Natural Gas
- **Indices**: S&P 500, Nasdaq 100
- **Bonds**: US 10Y Note
- **Crypto**: Bitcoin

Signals include net long/short positioning, week-over-week change, and extreme-positioning flags.

### 6. Crypto Fear & Greed Index (`collectors/fear_greed.py`)

7-day history from `api.alternative.me/fng/`, providing a composite sentiment reading (0 = extreme fear, 100 = extreme greed) based on volatility, momentum, social media, surveys, dominance, and trends.

### 7. Economic Calendar (`collectors/economic_calendar.py`)

Upcoming high- and medium-impact events from ForexFactory-compatible JSON feed (`nfs.faireconomy.media`):

- **Countries**: US, EU, GB, JP, CN, AU, CA
- **Lookforward**: 21 days
- **Impact filter**: high + medium only
- Hardcoded FOMC meeting dates (2025-2026) as fallback for the most critical events

### 8. Prediction Markets (`collectors/prediction_markets.py`)

Real-money probability estimates from two platforms:

- **Kalshi** (`api.elections.kalshi.com`) — Economics, Financials, Politics, World categories
- **Polymarket** (`gamma-api.polymarket.com`) — top 50 markets by volume

Captures contract titles, current probabilities, and volume as market-implied signals for macro outcomes.

### 9. Intermarket Spreads (`collectors/spreads.py`)

Computed spread signals derived from yfinance price data:

| Spread | Calculation | Interpretation |
|---|---|---|
| **VIX Term Structure** | VIX / VIX3M ratio | Backwardation (>1.0) = stress; contango (<1.0) = calm |
| **VIX / VVIX Divergence** | VIX level vs VVIX (vol-of-vol) | Leading indicator of regime shifts |
| **Credit Spread Proxy** | HYG/LQD ratio z-score (10-day) | Widening = risk-off, tightening = risk-on |
| **Yield Curve** | 10Y - 3M Treasury spread | Inversion / steepening / flattening signals |
| **Copper/Gold Ratio** | HG/GC ratio z-score (20-day) | Global growth appetite proxy |

### 10. Google Trends (`collectors/google_trends.py`)

Search interest over the past month (`pytrends`, daily granularity) for 16 keywords across three categories:

- **Stress signals**: recession, market crash, bank run, layoffs, margin call, sell stocks
- **Asset-related**: gold price, bitcoin crash, oil price, dollar collapse, safe haven
- **Policy-related**: rate cut, inflation, tariff, trade war, sanctions

Treated as **contrarian indicators** — spikes in retail panic searches can signal potential bottoms or exhaustion.

### 11. Reddit (`collectors/reddit.py`)

Top and hot posts from 10 finance-related subreddits via public JSON API (no OAuth):

`wallstreetbets` · `investing` · `economics` · `stocks` · `Forex` · `CryptoCurrency` · `CryptoMarkets` · `Gold` · `commodities` · `bonds`

Captures post titles, scores, comment counts, and submission timestamps as retail sentiment signals.

---

## Transmission Mechanism Catalog (18 Mechanisms)

The system matches incoming signals against a predefined catalog of known macro causal chains. Each mechanism defines trigger sources/keywords, a multi-step chain with observable indicators and expected lag, asset impacts with sensitivity levels, and confirmation/invalidation criteria.

| Category | Mechanisms |
|---|---|
| **Monetary Policy** | Fed Dovish Pivot, Fed Hawkish Surprise, Global Liquidity Expansion |
| **Risk Sentiment** | Risk-Off Flight to Safety, Risk-On Rotation, VIX Mean Reversion |
| **Growth / Inflation** | Stagflation Pressure, Reflation Trade, Recession Signal |
| **Geopolitical** | Trade War Escalation, Geopolitical Shock |
| **FX-Specific** | Yen Carry Trade Unwind, Dollar Wrecking Ball |
| **Commodity** | Energy Supply Shock, Gold Central Bank Accumulation |
| **Crypto** | Crypto as Liquidity Proxy, Crypto Regulatory Shock |
| **Bonds** | Term Premium Repricing |

Each active scenario reports: probability estimate, chain stage (early / mid / late / complete), directional asset impacts, rationale, and watch items.

---

## Dashboard

The Streamlit dashboard (`app.py`) presents the pipeline output as a single-page command center with a dark monospace terminal aesthetic.

### Sidebar Controls

- **Run Weekly Pipeline** — triggers the full collect-to-report pipeline from the UI
- **Asset class filter** — multiselect: FX, Metals, Energy, Crypto, Indices, Bonds
- **Direction filter** — All / Bullish / Bearish
- **Min probability slider** — filters scenario-based views by probability threshold (0-100%)

### Regime Banner

Colored badge at the top showing the current macro regime classification:

- **RISK_ON** (green) / **RISK_OFF** (red) / **REFLATION** (orange) / **STAGFLATION** (red) / **GOLDILOCKS** (teal) / **TRANSITION** (yellow)

Includes regime rationale and an LLM-generated executive summary.

### Asset Cards

Each tracked asset gets a card displaying:

**Scenario-based view** (when transmission mechanisms are matched):
- Ticker, asset class, directional badge (bullish/bearish/neutral), net probability-weighted score
- Per-scenario blocks: probability %, mechanism name, category, chain stage, direction, rationale, watch items
- Conflict badge when active scenarios disagree on direction

**Narrative-based view** (fallback):
- Ticker, asset class, direction, conviction bar (visual fill + %)
- Horizon chip (1 week), trend chip (intensifying / stable / fading)
- Primary rationale, catalyst (event + date + mechanism), exit condition (profit-take + invalidation)
- Consensus vs. Edge block — edge badge (CONTRARIAN / MORE AGGRESSIVE / MORE PASSIVE / ALIGNED), consensus view, differentiated rationale

**Technical indicators** (collapsible, on both views):
- RSI(14) with overbought/oversold context
- MACD(12,26,9) histogram with trend
- Price vs 20-day SMA distance (%)
- ALIGNED / DIVERGENT badge relative to the macro directional call

**Source attribution**: source type chips (News, Market Data, Social, Central Bank, Econ Data, COT, Fear/Greed, Predictions, Trends, Spreads) with expandable per-source signal details.

### Layout

Cards are grouped into **BULLISH CALLS** and **BEARISH CALLS** sections with counts. Neutral calls are collapsed by default.

---

## LLM Configuration

| | Provider | Model | Temperature | Max Tokens |
|---|---|---|---|---|
| **Primary** | Anthropic | `claude-sonnet-4-20250514` | 0.2 | 4096 |
| **Fallback** | Cerebras | `gpt-oss-120b` | 0.2 | 4096 |

Automatic selection based on available API keys (tries Anthropic first).

---

## Project Structure

```
macro-pulse/
├── app.py                          # Streamlit dashboard entry point
├── run_weekly.py                   # CLI pipeline orchestrator
├── pyproject.toml                  # Poetry dependencies
├── macro_pulse.db                  # SQLite persistence
│
├── config/
│   ├── settings.py                 # Pydantic settings (env vars + YAML)
│   ├── assets.yaml                 # 31 tickers across 6 asset classes
│   ├── sources.yaml                # RSS feeds, subreddits, FRED series, keywords
│   ├── mechanisms.yaml             # 18 transmission mechanism definitions
│   └── mechanisms.py               # YAML loader
│
├── models/
│   └── schemas.py                  # Pydantic models (Signal, Narrative, Report, etc.)
│
├── collectors/                     # 11 signal collectors (BaseCollector ABC)
│   ├── rss_news.py                 # RSS feeds
│   ├── central_bank.py             # Fed + ECB feeds
│   ├── economic_data.py            # FRED API
│   ├── market_data.py              # yfinance OHLCV + returns
│   ├── cot_reports.py              # CFTC COT positioning
│   ├── fear_greed.py               # Crypto Fear & Greed
│   ├── economic_calendar.py        # ForexFactory calendar
│   ├── prediction_markets.py       # Kalshi + Polymarket
│   ├── spreads.py                  # Intermarket spread signals
│   ├── google_trends.py            # pytrends search interest
│   └── reddit.py                   # Reddit public JSON API
│
├── ai/
│   ├── llm.py                      # LLM factory (Anthropic / Cerebras)
│   ├── prompts/templates.py        # LangChain prompt templates
│   └── chains/
│       ├── narrative_extractor.py  # Signals → narratives
│       ├── regime_classifier.py    # Narratives → regime + summary
│       └── mechanism_matcher.py    # Signals → active scenarios
│
├── analysis/
│   ├── sentiment_aggregator.py     # Weighted score aggregation
│   ├── scenario_aggregator.py      # Probability-weighted scenario scoring
│   ├── price_validator.py          # Prediction vs actual return comparison
│   └── technicals.py              # RSI, MACD, SMA calculations
│
├── dashboard/
│   ├── actionable_view.py          # Dashboard rendering logic
│   └── styles.py                   # Custom CSS (dark terminal theme)
│
├── storage/
│   └── store.py                    # SQLite persistence (7 tables)
│
└── data/
    ├── raw/                        # Signal snapshots (timestamped JSON)
    └── reports/                    # Report snapshots (timestamped JSON)
```

---

## Setup

```bash
# Install dependencies
poetry install

# Configure API keys in .env
cp .env.example .env
# Required: ANTHROPIC_API_KEY or CEREBRAS_API_KEY
# Optional: FRED_API_KEY (for economic data)

# Run the weekly pipeline
poetry run python run_weekly.py

# Or collect signals only (no LLM processing)
poetry run python run_weekly.py --collect-only

# Or collect from specific sources
poetry run python run_weekly.py --sources news market_data fred cot

# Launch the dashboard
poetry run streamlit run app.py
```

---

## Requirements

- Python 3.11+
- API keys: Anthropic (or Cerebras) for LLM, FRED for economic data
- No API key needed for: RSS feeds, Reddit, yfinance, CFTC COT, Fear & Greed, Economic Calendar, Prediction Markets, Google Trends
