# Plan: Capture Real Consensus, Measure True Non-Consensus, Profit on 1-Week BTC/ETH Trades

## The Problem

Right now, "consensus" is whatever Claude decides to write in a free-text `consensus_view` field. It cites things like "Goldman calling for $2800 gold" or "CME FedWatch shows 85%" — but these references come from the LLM's training data, not from live market data. The system has no actual measurement of what the market believes about BTC and ETH over the next week.

This means:
- We don't actually know what consensus is
- We can't measure how far our view diverges from it
- We can't tell if our "contrarian" label means anything
- We can't track whether non-consensus views were correct after the fact

## The Goal

Build a system that:
1. **Computes a quantitative consensus score** for BTC and ETH from real market data (what does the market actually believe about direction this week?)
2. **Computes our directional view** from the existing signal pipeline (what do our signals say?)
3. **Measures the divergence** between consensus and our view (how non-consensus are we, exactly?)
4. **Tracks 1-week outcomes** to validate whether non-consensus calls were correct
5. **Focus**: BTC and ETH only. Everything else is secondary.

---

## Phase 1: Build the Consensus Score (New Collectors)

The consensus score is a single number per asset: **-1.0 (max bearish consensus) to +1.0 (max bullish consensus)**. It's computed from hard market data, not LLM interpretation.

### 1A. Options Consensus Collector (`collectors/options_consensus.py`)

**Source**: Deribit public API (free, no auth)

**Data to collect for BTC and ETH**:

| Metric | API Endpoint | What It Tells Us |
|---|---|---|
| 25-delta risk reversal (skew) | Compute from `public/get_book_summary_by_currency` | Positive = calls expensive = bullish consensus. Negative = puts expensive = bearish consensus. **This is the single best consensus thermometer.** |
| Put/Call OI ratio | `public/get_book_summary_by_currency?kind=option` | Below 0.7 = bullish consensus. Above 1.0 = bearish. |
| Max pain (weekly expiry) | Compute from OI by strike | The price the market "expects" at weekly expiry. If current price is far above max pain, consensus is stretched bullish. |
| DVOL (Deribit Volatility Index) | `public/get_volatility_index_data` | High DVOL = uncertainty, not directional. But DVOL spike + negative skew = bearish consensus with conviction. |
| IV term structure slope | Compare near-term vs. far-term ATM IV | Backwardation (near > far) = market expects move THIS week. Contango = quiet consensus. |

**Consensus signal derivation**:
```
skew_signal = normalize(risk_reversal_25d, historical_range)  # -1 to +1
pcr_signal  = normalize(1.0 - put_call_ratio, [0.5, 1.5])    # inverted: low PCR = bullish
maxpain_signal = sign(max_pain - current_price) * magnitude   # above max pain = bearish drift expected
```

**Implementation notes**:
- Filter to the nearest weekly expiry options only (1-week horizon alignment)
- Compute 25-delta skew by interpolating IV across strikes at the weekly expiry
- Cache results — Deribit data doesn't change fast enough to need real-time polling
- Store raw values AND the derived consensus signal

### 1B. Multi-Exchange Derivatives Collector (`collectors/derivatives_consensus.py`)

**Source**: Binance, Bybit, OKX public APIs via `ccxt` library (free)

**Data to collect for BTC and ETH**:

| Metric | Source | What It Tells Us |
|---|---|---|
| Long/short ratio (global) | Binance `futures/data/globalLongShortAccountRatio` | Retail directional consensus |
| Long/short ratio (top traders) | Binance `futures/data/topLongShortPositionRatio` | Smart money directional consensus |
| Aggregated funding rate | Binance + Bybit + OKX via ccxt | OI-weighted average. Persistently positive = bullish consensus. |
| 7-day accumulated funding | Compute from historical rates | Total cost longs paid shorts over the week. High = strong bullish consensus. |
| OI change (24h, 7d) | Multiple exchanges | Rising OI + rising price = consensus strengthening. Rising OI + falling price = new shorts entering. |
| OI-weighted funding | Weight each exchange's rate by its OI share | True consensus rate, not skewed by low-liquidity exchanges |

**Consensus signal derivation**:
```
ls_signal       = normalize(long_short_ratio - 1.0, [-0.5, 0.5])  # >1 = bullish consensus
top_ls_signal   = normalize(top_trader_ratio - 1.0, [-0.5, 0.5])  # smart money consensus
funding_signal  = normalize(accumulated_7d_funding, [-0.1%, 0.1%]) # persistent direction
oi_signal       = sign(oi_7d_change) * sign(price_7d_change)       # +1 if OI and price agree
```

**Why multi-exchange matters**: Single-exchange funding can be misleading (arbitrage, exchange-specific flows). OI-weighted average across 3+ exchanges is the true market rate.

### 1C. ETF Flow Collector (`collectors/etf_flows.py`)

**Source**: SoSoValue API (free limited), with fallback to scraping free dashboards (BitBO, CoinMarketCap). No paid APIs until the full signal is validated.

**Data to collect**:

| Metric | What It Tells Us |
|---|---|
| Daily net BTC ETF flows (total across all funds) | Institutional buying/selling pressure |
| 5-day rolling net flow | Smoothed institutional consensus |
| IBIT (BlackRock) specific flow | The single most important ETF — BlackRock is the institutional bellwether |
| Daily net ETH ETF flows | Same for ETH (lower volume, more volatile signal) |

**Consensus signal derivation**:
```
etf_signal = normalize(rolling_5d_net_flow, 30d_rolling_range)  # persistent inflows = bullish consensus
```

**Why this matters**: ETF flows represent TradFi institutional consensus. This is a completely different population than crypto-native traders (who show up in funding rates). When both agree, consensus is strong. When they diverge, interesting things happen.

**Cost approach**: Start free. SoSoValue has a free API tier. If it's unreliable, fall back to scraping the free web dashboards (SoSoValue, BitBO, CoinMarketCap all publish daily flows). Only consider CoinGlass ($29/mo) after we've validated that ETF flows actually improve our consensus accuracy over 4+ weeks of outcome data.

### 1D. Consensus Score Aggregator (`analysis/consensus_scorer.py`)

Combine the individual consensus signals into a single score per asset:

```
consensus_score = equal_weight_average(
    options_skew_signal,       # what are sophisticated traders paying for?
    funding_signal,            # leveraged trader consensus
    top_trader_ls_signal,      # smart money directional bet
    etf_flow_signal,           # institutional consensus
    pcr_signal,                # put/call ratio
    oi_momentum_signal         # conviction behind consensus
)
# = (1/6) × each component
```

**Equal-weighted by design.** We don't know which components are most predictive yet. Equal weights are the honest starting point. Once we have 8-12 weeks of outcome data (Phase 4), we can shift weights toward whichever components best predicted actual 1-week moves.

**Normalization**: Each component is normalized to [-1, +1] against a **30-day rolling window**. Why 30 days:
- 90 days includes too many regime changes — an options skew of +2% means something different in a post-halving euphoria vs. a range-bound market. A 90-day window would wash that out.
- 7-14 days is too noisy — not enough history to establish what "normal" looks like.
- 30 days captures the current volatility regime without being stale. If we're in a high-vol period, "normal" funding rates are higher, and only extremes relative to the current regime register as strong consensus signals.
- For the 1-week forecast horizon, we want to know "is this consensus reading extreme *for the current environment*?" — 30 days is the tightest window that answers that reliably.

**Output**: `ConsensusScore` model per asset:
```python
class ConsensusScore(BaseModel):
    ticker: str                          # "Bitcoin" or "Ethereum"
    consensus_score: float               # -1.0 to +1.0
    consensus_direction: str             # bullish / bearish / neutral (threshold ±0.15)
    components: dict[str, float]         # breakdown by source (each -1 to +1)
    options_skew: float                  # raw 25-delta risk reversal
    funding_rate_7d: float               # 7-day accumulated funding
    top_trader_ls_ratio: float           # raw ratio
    etf_flow_5d: float                   # USD millions, 5-day rolling
    put_call_ratio: float                # raw PCR
    max_pain_distance_pct: float         # (current_price - max_pain) / current_price
    oi_change_7d_pct: float              # % OI change over 7 days
    data_timestamp: datetime             # when this was computed
```

---

## Phase 2: Compute the Divergence (Non-Consensus Measurement)

### 2A. Replace LLM Consensus with Computed Consensus

Currently, the LLM fills `consensus_view` and `edge_type` as free text. Change this:

**Before** (LLM-generated):
```json
{
  "consensus_view": "Goldman calling for $100K BTC, CME FedWatch shows 85% June cut",
  "edge_type": "contrarian",
  "edge_rationale": "Our signals suggest bearish pressure from crowded longs"
}
```

**After** (computed + LLM-enriched):
```json
{
  "consensus_score": 0.62,
  "consensus_direction": "bullish",
  "consensus_components": {
    "options_skew": 0.45,
    "funding_7d": 0.78,
    "top_trader_ls": 0.55,
    "etf_flows": 0.71,
    "put_call_ratio": 0.40,
    "oi_momentum": 0.65
  },
  "consensus_summary": "Market is moderately bullish BTC: positive funding (0.78), steady ETF inflows ($340M 5-day), calls favored in options (skew +0.45). Top traders 55% long.",
  "our_score": -0.35,
  "our_direction": "bearish",
  "divergence": -0.97,
  "divergence_label": "strongly contrarian",
  "edge_rationale": "Despite bullish consensus, crowded long funding rates historically precede 5-8% corrections within 1 week when >0.05% sustained for 3+ days"
}
```

**The divergence is now a number**: `our_score - consensus_score`. This replaces the discrete `edge_type` label with a continuous measurement.

### 2B. Divergence Classification

```
divergence = our_score - consensus_score

|divergence| > 1.0   → "strongly contrarian" (maximum non-consensus)
|divergence| > 0.5   → "contrarian"
|divergence| > 0.2   → "mildly non-consensus"
|divergence| <= 0.2  → "aligned" (no edge)
```

### 2C. Update the Composite Scorer

Replace the flat +0.10/-0.05 nudge with a **divergence-scaled bonus**:

```
# Old: flat nudge
nudge = +0.10 if contrarian else -0.05 if aligned else 0.0

# New: scaled by divergence magnitude
divergence = our_score - consensus_score
abs_div = abs(divergence)

if abs_div > 0.5:
    nudge = 0.15 * sign(our_score)   # strong conviction bonus for high divergence
elif abs_div > 0.2:
    nudge = 0.08 * sign(our_score)   # moderate bonus
else:
    nudge = -0.05 * sign(our_score)  # penalty for consensus-following
```

This makes the bonus proportional to how non-consensus we are, rather than a binary label.

### 2D. Feed Consensus Data into the LLM Prompt

Add the computed consensus score to the narrative extraction prompt so the LLM knows what consensus actually is (instead of guessing):

```
CONSENSUS DATA (computed from market positioning, not estimated):
Bitcoin: consensus_score = +0.62 (bullish)
  - Options skew: +0.45 (calls favored at weekly expiry)
  - 7-day accumulated funding: +0.078% (longs paying)
  - Top trader L/S: 1.22 (55% long)
  - ETF flows 5-day: +$340M (steady inflows)
  - Put/Call ratio: 0.52 (call-dominated)
  - Max pain: $94,000 (current price $97,500 — 3.7% above)
  - OI 7d change: +8.2% (new money entering, directionally aligned)

Ethereum: consensus_score = +0.38 (mildly bullish)
  - Options skew: +0.20 (slight call preference)
  - 7-day accumulated funding: +0.042% (moderate)
  - Top trader L/S: 1.08 (52% long)
  - ETF flows 5-day: +$45M (modest inflows)
  ...
```

Now the LLM doesn't have to guess consensus — it's given the numbers. Its job becomes: **"Given this consensus, what do our 350 signals tell us that the market is missing?"**

---

## Phase 3: Improve the "Our View" Signal (Be More Correct)

Being non-consensus only matters if we're right. These changes improve signal quality for the 1-week BTC/ETH horizon.

### 3A. Crypto-Specific Technical Indicators

Current technicals (RSI, MACD, SMA) are generic. Add crypto-specific indicators that are actually predictive at the 1-week horizon:

| Indicator | Why It Matters for 1-Week Crypto |
|---|---|
| **Funding rate mean reversion** | When funding >0.05% for 3+ days, historically reverts (and price corrects) within 3-7 days. This is a timing signal, not just a level signal. |
| **OI vs. price divergence** | Rising OI + flat/falling price = shorts building. Falling OI + rising price = short squeeze exhaustion. Both are 1-3 day leading indicators. |
| **Liquidation level proximity** | How close is current price to major liquidation clusters? Proximity = magnetic pull. If $2B in long liquidations sit 5% below, there's a structural risk. |
| **Max pain gravity** | Price tends to converge toward max pain as weekly options expire (Friday 8:00 UTC on Deribit). Distance from max pain on Monday gives a directional pull for the week. |
| **ETF flow momentum** | 3 consecutive days of outflows historically precede further downside in the following 3-5 days. Conversely for inflows. |

### 3B. Add Exchange Flow Data (On-Chain Edge)

Current on-chain collector only tracks stablecoin supply. Add exchange flow signals:

**Source**: CryptoQuant free dashboard data or their API ($29/mo)

| Signal | Meaning |
|---|---|
| BTC exchange netflow positive (5d) | Coins moving to exchanges = selling intent = bearish |
| BTC exchange netflow negative (5d) | Coins leaving exchanges = accumulation = bullish |
| Exchange whale ratio > 85% | Top 10 transactions dominate inflows = whale dump incoming |

These are on-chain signals that derivatives traders don't see directly. When exchange flows disagree with funding rate consensus, we have a genuine informational edge.

### 3C. Tighten the 1-Week Exit Framework

Current exit conditions are LLM-generated text ("Take profit at $X, invalidated at $Y"). Make them structured and trackable:

```python
class TradeThesis(BaseModel):
    ticker: str
    direction: str                       # bullish / bearish
    entry_price: float                   # price at signal generation
    entry_date: datetime

    # Structured exits
    take_profit_pct: float               # e.g., +6%
    stop_loss_pct: float                 # e.g., -3%
    risk_reward_ratio: float             # computed: TP / SL
    max_holding_days: int = 7            # hard 1-week cap

    # Consensus context
    consensus_score_at_entry: float
    our_score_at_entry: float
    divergence_at_entry: float

    # For outcome tracking
    exit_price: float | None = None
    exit_date: datetime | None = None
    exit_reason: str | None = None       # "tp_hit", "sl_hit", "time_expired", "invalidated"
    pnl_pct: float | None = None
```

**Key rule**: Every trade must have a risk/reward ratio >= 1.5. If the LLM can't identify a setup with 1.5:1 R:R, the trade doesn't qualify.

---

## Phase 4: Track Outcomes (Prove We're Correct)

This is the missing piece. Without outcome tracking, we can't know if our non-consensus views are actually correct.

### 4A. How Outcome Tracking Actually Runs

**The problem**: Streamlit apps are stateless — they only execute when someone opens the page. Streamlit Community Cloud won't run background cron jobs. So we need a trigger mechanism.

**The solution**: Outcome scoring runs as **Step 7 of the existing pipeline** — every time `run_weekly.py` executes (whether manually from the dashboard button or from a cron/scheduler), it scores the PREVIOUS week's trades before generating new ones.

**Concrete timeline for a single trade cycle**:

```
SUNDAY WEEK 1 (pipeline runs):
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: Score previous week's trades (if any exist)            │
│   → Fetch BTC/ETH prices from yfinance for 7 days ago         │
│   → For each trade from last week:                             │
│     - Did price hit TP or SL during the week? (check daily     │
│       high/low from yfinance against TP/SL levels)             │
│     - If neither hit, use 7-day closing price (time expiry)    │
│     - Compute P&L %, record exit reason                        │
│   → Write results to "Outcomes" worksheet in Google Sheets     │
│   → Update SQLite trade_outcomes table                         │
│                                                                │
│ Steps 1-6: Generate THIS week's signals, consensus, trades     │
│   → New trade theses written to "Trades" worksheet             │
└─────────────────────────────────────────────────────────────────┘

DURING WEEK 1 (no action needed):
  Trades are live. No monitoring system needed — we're not
  auto-executing. The sheet just records what was called.

SUNDAY WEEK 2 (pipeline runs again):
  Step 7 scores Week 1's trades against actual prices.
  Steps 1-6 generate Week 2's trades.
  ...and so on.
```

**What gets written to Google Sheets**:

**"Trades" worksheet** (written at generation time — Step 6):

| Week | Ticker | Direction | Entry Price | TP % | SL % | R:R | Consensus Score | Our Score | Divergence | Divergence Label | Composite Score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-08 | Bitcoin | bearish | $97,500 | -6% | +3% | 2.0 | +0.62 | -0.35 | -0.97 | strongly contrarian | -0.68 |
| 2026-03-08 | Ethereum | bullish | $3,200 | +8% | -4% | 2.0 | +0.38 | +0.72 | +0.34 | mildly non-consensus | +0.55 |

**"Outcomes" worksheet** (written when NEXT week's pipeline runs — Step 7):

| Week | Ticker | Direction | Entry Price | Exit Price | Exit Reason | P&L % | Direction Correct? | Consensus Score | Our Score | Divergence | Days Held |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-08 | Bitcoin | bearish | $97,500 | $93,600 | tp_hit | +4.0% | Yes | +0.62 | -0.35 | -0.97 | 4 |
| 2026-03-08 | Ethereum | bullish | $3,200 | $3,072 | sl_hit | -4.0% | No | +0.38 | +0.72 | +0.34 | 3 |

**Exit reason logic** (checked in order):
1. **`tp_hit`**: During the 7-day window, did the daily high (for bullish) or daily low (for bearish) reach the TP level? Use intraday high/low from yfinance daily data.
2. **`sl_hit`**: Same check against SL level. If both TP and SL were hit in the same week, the one that was hit first (by date) wins.
3. **`time_expired`**: Neither TP nor SL hit within 7 days. P&L = closing price on day 7 vs entry price.

**Outcome validation is opportunistic, not scheduled.** It doesn't wait for Sunday — it checks ALL unvalidated trades every time the app loads or the pipeline runs, and scores any that can be resolved.

**How it works**:

```python
def validate_pending_trades():
    """Called on every dashboard load AND every pipeline run.
    Scans all trades with exit_price == None and checks if they can be resolved."""

    pending = db.get_trades_without_outcomes()  # all unvalidated trades

    for trade in pending:
        days_elapsed = (now - trade.entry_date).days

        # Fetch daily OHLC from entry_date to now (or entry_date + 7d, whichever is less)
        check_end = min(now, trade.entry_date + timedelta(days=7))
        daily_bars = yfinance.download(trade.ticker, start=trade.entry_date, end=check_end)

        # Check each day in order: did TP or SL get hit?
        for day in daily_bars:
            if trade.direction == "bullish":
                if day.high >= tp_price:   → record tp_hit on this date, break
                if day.low <= sl_price:    → record sl_hit on this date, break
            else:  # bearish
                if day.low <= tp_price:    → record tp_hit on this date, break
                if day.high >= sl_price:   → record sl_hit on this date, break

        # If 7 days have passed and neither TP nor SL hit:
        if days_elapsed >= 7 and no exit recorded:
            → record time_expired, P&L = day-7 close vs entry price

        # If < 7 days and neither hit yet:
        #   → skip, trade is still live. Will check again next time.
```

**Key behavior**:
- A trade entered on Wednesday can be validated as early as Thursday (if TP/SL hit on day 1)
- No need to wait for Sunday — every dashboard load checks for resolvable trades
- Trades that are still live (< 7 days, no TP/SL hit) are skipped and re-checked next time
- Results written to both SQLite and Google Sheets "Outcomes" worksheet immediately upon resolution

**In-app background scheduler** (runs while Streamlit is live):

```python
# In app.py — start a background thread on app load
import threading, time

def background_validator():
    """Runs every 6 hours while the app is alive.
    Checks for trades that can be validated and scores them."""
    while True:
        try:
            validate_pending_trades()
            sync_outcomes_to_sheets()  # push any new outcomes to Google Sheets
        except Exception as e:
            logger.error(f"Background validation failed: {e}")
        time.sleep(6 * 3600)  # check every 6 hours

# Start once per Streamlit session (guarded by session_state to avoid duplicates)
if "validator_started" not in st.session_state:
    thread = threading.Thread(target=background_validator, daemon=True)
    thread.start()
    st.session_state.validator_started = True
```

**What this gives you**:
- Open the dashboard on any day → pending trades get checked and validated if resolvable
- Leave the dashboard open → background thread checks every 6 hours
- Close the dashboard → no validation happens (but nothing is lost — next time you open it, all pending trades get scanned)
- No external cron needed unless you want validation to happen when the app is closed (GitHub Actions can handle that later)

**Trade lifecycle**:

```
Day 0 (Sunday): Pipeline runs → trade generated → status: LIVE
Day 1-6: Each dashboard load checks if TP/SL hit → if yes: RESOLVED
Day 7: Trade auto-expires if still live → status: RESOLVED (time_expired)
Day 8+: Trade is in the outcomes log, contributes to performance metrics
```

### 4B. Edge Validation Dashboard

Track these metrics over time (displayed in a new "Performance" tab in the Streamlit dashboard):

| Metric | What It Tells Us |
|---|---|
| **Hit rate by divergence bucket** | Are high-divergence (strongly contrarian) calls correct more often? |
| **Average P&L by edge type** | Do contrarian trades make more money on average? |
| **Consensus accuracy** | How often does consensus direction match actual 1-week move? (Baseline to beat) |
| **Signal source attribution** | Which consensus components were most predictive of 1-week moves? |
| **Composite score calibration** | Is a +0.8 composite actually more correct than a +0.4? |

These metrics only become meaningful after 4+ weeks (8+ trades minimum for BTC+ETH). Until then, the dashboard shows the raw outcome log.

### 4C. Feedback Loop (Later — after 8-12 weeks of data)

Once we have enough outcome data:
- Shift consensus component weights from equal toward whichever components best predicted outcomes
- Recalibrate composite score weights based on which pillar (narrative/technical/scenario) was most correct
- Identify systematic biases (e.g., are we always too bullish ETH? always wrong on funding rate signals?)
- This is NOT automated — it's a manual review of the outcome data + a config change to the weights

---

## Phase 5: Pipeline Integration

### 5A. Updated `run_weekly.py` Pipeline

```
Step 1:   Collect signals (existing 8 enabled collectors)
Step 1b:  NEW — Collect consensus data (options, derivatives, ETF flows)
Step 1c:  NEW — Compute consensus scores for BTC and ETH
Step 2:   Extract narratives (LLM) — NOW with consensus data in prompt
Step 2b:  Match transmission mechanisms (LLM)
Step 3:   Classify regime (LLM)
Step 4:   Aggregate asset scores (deterministic)
Step 4b:  Compute technicals (existing + new crypto indicators)
Step 4c:  Aggregate scenarios (deterministic)
Step 4d:  Composite scoring — NOW with divergence-scaled nudge
Step 4e:  NEW — Generate structured trade theses (entry, TP, SL, R:R)
Step 5:   Generate summary (LLM)
Step 6:   Save report + trade theses to DB
Step 7:   NEW — Score previous week's trades against actual outcomes
```

### 5B. Updated Dashboard

Add to the asset card:
- **Consensus meter**: Visual bar showing consensus_score (-1 to +1) with our_score overlaid
- **Divergence badge**: "STRONGLY CONTRARIAN" / "CONTRARIAN" / "MILDLY NON-CONSENSUS" / "ALIGNED"
- **Consensus breakdown**: Expandable section showing each component (options skew, funding, L/S, ETF flows)
- **Trade thesis**: Structured entry/TP/SL/R:R (not just LLM text)
- **Historical accuracy**: After 4+ weeks, show hit rate for similar setups

### 5C. Updated Schemas

New models to add to `models/schemas.py`:
- `ConsensusScore` — per-asset consensus measurement
- `TradeThesis` — structured trade with entry/exit/R:R
- `TradeOutcome` — realized P&L and exit reason
- `DivergenceMetrics` — our_score vs consensus_score with classification

New DB tables in `storage/store.py`:
- `consensus_scores` — weekly consensus snapshots
- `trade_theses` — all generated trades
- `trade_outcomes` — realized results

---

## Implementation Order

### Sprint 1: Consensus Data Collection (the foundation)
1. `collectors/options_consensus.py` — Deribit options API integration
2. `collectors/derivatives_consensus.py` — Multi-exchange funding/L-S/OI via ccxt
3. `collectors/etf_flows.py` — ETF flow data (SoSoValue or CoinGlass)
4. `analysis/consensus_scorer.py` — Aggregate into single consensus score
5. New schemas + DB tables for consensus data

### Sprint 2: Divergence Measurement + Prompt Update
6. Feed consensus scores into narrative extraction prompt
7. Compute divergence (our_score - consensus_score) per asset
8. Replace flat contrarian nudge with divergence-scaled bonus in composite scorer
9. Update dashboard to show consensus meter + divergence

### Sprint 3: Structured Trades + Outcome Tracking
10. `TradeThesis` generation with structured TP/SL/R:R
11. `analysis/outcome_tracker.py` — weekly P&L recording
12. Edge validation metrics + dashboard section
13. Google Sheets export update with consensus + outcomes

### Sprint 4: Signal Quality Improvements
14. Add crypto-specific technical indicators (funding mean reversion, OI divergence, max pain gravity)
15. Add exchange flow collector (CryptoQuant or equivalent)
16. Calibrate weights based on initial outcome data

---

## What This Changes

**Before**: "We think we're contrarian because the LLM said so."

**After**: "Consensus is +0.62 bullish (options skew +0.45, funding accumulated +0.078%, ETF inflows $340M/5d). Our signals say -0.35 bearish. Divergence = -0.97. Last 8 times divergence was this negative, 6 were correct within 1 week, average P&L +4.2%."

That's the difference between storytelling and a system.

---

## Cost

| Item | Cost | Priority |
|---|---|---|
| Deribit API | Free | Sprint 1 |
| ccxt (Binance/Bybit/OKX) | Free | Sprint 1 |
| SoSoValue ETF API | Free (limited) | Sprint 1 |
| CoinGlass API | $29/mo (if SoSoValue insufficient) | Sprint 1 fallback |
| CryptoQuant API | $29/mo (for exchange flows) | Sprint 4 |
| Total minimum | $0/mo | |
| Total recommended | $29-58/mo | |

---

## Resolved Decisions

1. **Consensus component weights**: Equal-weighted (1/6 each). Let outcome data guide rebalancing after 8-12 weeks.

2. **Normalization window**: 30-day rolling. Captures current vol regime without being too noisy or too stale for 7-day forecasting.

3. **ETF flow data source**: Start free (SoSoValue API + free dashboard fallbacks). No paid APIs until the full consensus signal is validated over 4+ weeks of outcome data.

4. **Outcome tracking**: Runs as Step 7 of the existing `run_weekly.py` pipeline — scores last week's trades every time the pipeline runs. Results written to a new "Outcomes" worksheet in Google Sheets. Triggered manually via the dashboard button for now, with GitHub Actions cron as a later automation option. See Phase 4A for full details.