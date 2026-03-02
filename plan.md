# Plan: Tighten Crypto Recommendations for Real-Money Spot Trading

## Context

We're putting real money on crypto positions (BTC, ETH, SOL spot). The current system treats crypto identically to equities — generic narrative prompts, no crypto-native data sources, a 0.25% price validation threshold that's meaningless for crypto's 3-10% weekly moves, and equity-tuned technical thresholds. The existing 5 crypto transmission mechanisms (`crypto_leverage_liquidation`, `stablecoin_contagion`, etc.) are well-designed but **starved of data** — no collector feeds them funding rates, open interest, or stablecoin supply. The result: vague exit conditions like "BTC < $60k", no risk/reward ratios, and the LLM has nothing crypto-specific to cite.

**Goal**: Make crypto narratives trade-grade — specific entries, % targets, intermediate exits, R:R ratios, backed by funding rate + on-chain data.

---

## Step 1: Add `FUNDING_RATES` and `ONCHAIN` to SignalSource enum

**File**: `models/schemas.py`

Add two new enum values after `SPREADS` (line 34):
```python
FUNDING_RATES = "funding_rates"
ONCHAIN = "onchain"
```

---

## Step 2: Create `collectors/funding_rates.py`

**New file**. Follows `FearGreedCollector` pattern (inherits `BaseCollector`).

- **Primary API**: CoinGlass public endpoints (no key): `/public/v2/funding`, `/public/v2/open_interest`
- **Fallback**: Binance FAPI (`/fapi/v1/fundingRate`, `/fapi/v1/openInterest`) — also free, no key
- **Symbols**: BTC, ETH, SOL
- **Signals emitted per symbol**:
  - Funding rate signal: current rate, 7-day average, interpretation (crowded longs >0.03% = bearish, crowded shorts <-0.01% = bullish)
  - Open interest signal: current OI in USD, 24h change %, interpretation (rising OI + rising price = trend confirmation, rising OI + falling price = bear pressure)
  - Leverage alert (conditional): when funding >0.05% or <-0.03%, emit high-priority alert signal that feeds `crypto_leverage_liquidation` mechanism
- **Metadata keys**: `symbol`, `funding_rate`, `funding_7d_avg`, `open_interest_usd`, `oi_24h_change_pct`, `signal_type`

---

## Step 3: Create `collectors/onchain.py`

**New file**. Same `BaseCollector` pattern.

- **API**: DeFi Llama stablecoins endpoint (free, no key): `https://stablecoins.llama.fi/stablecoins?includePrices=true`
- **Signals emitted**:
  - Total stablecoin supply + 7-day change %: growing = bullish (dry powder), shrinking = bearish (capital leaving)
  - USDT vs USDC market cap trend: USDT growing faster = offshore demand signal
  - Alert if any major stablecoin (USDT, USDC, DAI) 7-day market cap drops >1% — feeds `stablecoin_contagion` mechanism
- **Metadata keys**: `total_supply_usd`, `supply_7d_change_pct`, `usdt_supply`, `usdc_supply`, `signal_type`

---

## Step 4: Register new collectors + config

**File**: `run_weekly.py`
- Add imports for `FundingRatesCollector` and `OnChainCollector`
- Add `"funding_rates": FundingRatesCollector` and `"onchain": OnChainCollector` to the collectors dict (line 34-46)
- Add `"funding_rates"` and `"onchain"` to `--sources` argparse choices (line 254)

**File**: `config/sources.yaml`
- Add config section:
  ```yaml
  funding_rates:
    symbols: [BTC, ETH, SOL]
    extreme_long_threshold: 0.05
    extreme_short_threshold: -0.03

  onchain:
    stablecoin_decline_alert_pct: -1.0
  ```

**File**: `dashboard/actionable_view.py`
- Add to `SOURCE_LABELS` dict (line 34-45):
  ```python
  SignalSource.FUNDING_RATES: "Funding",
  SignalSource.ONCHAIN: "On-Chain",
  ```

---

## Step 5: Crypto-specific prompt engineering

**File**: `ai/prompts/templates.py`

### 5a. Add crypto signal interpretation block

Insert after the Google Trends guidance (line 64) in `NARRATIVE_EXTRACTION_PROMPT`:

```
CRYPTO-SPECIFIC SIGNAL INTERPRETATION:
- Funding rate signals (source: funding_rates) are CRITICAL for crypto:
  * Rate >0.03%: leveraged longs crowded — BEARISH contrarian signal.
    Above 0.05% = high liquidation risk within 1-3 days.
  * Rate <-0.01%: leveraged shorts crowded — BULLISH (short squeeze setup).
    Below -0.03% = strong short squeeze potential.
  * Open interest rising + price rising = new longs (trend confirmation).
  * Open interest rising + price falling = new shorts (bear pressure).
  * Open interest dropping >20% in 24h = leverage flush, often marks local bottom.
  You MUST cite funding rate and OI levels when making crypto directional calls.

- On-chain/stablecoin signals (source: onchain) indicate crypto liquidity:
  * Stablecoin supply growing = dry powder entering = bullish.
  * Stablecoin supply shrinking = capital leaving = bearish.
  * Stablecoin market cap drop >1% in 7 days = potential contagion risk.
  Cite stablecoin supply trends when making crypto calls.

- Fear & Greed (source: fear_greed): below 20 = CONTRARIAN bullish (1-week).
  Above 80 = CONTRARIAN bearish. Between 35-65 = low signal value.

- Crypto weekly moves are 5-15x equity volatility. A 2% BTC move is noise.
  Calibrate conviction and exit conditions accordingly.
```

### 5b. Tighten crypto exit conditions

Append to the existing `exit_condition` guidance (after line 44):

```
  For CRYPTO assets (Bitcoin, Ethereum, Solana) specifically:
    - Express targets as PERCENTAGE moves from current price, not just dollar levels.
      Example: "Take profit at +8% ($72,500). Intermediate: +4% ($69,500)."
    - Include an INTERMEDIATE profit target (partial take-profit level).
    - Include a RISK/REWARD ratio. Example: "Risk: -5% ($63,300). Reward: +8%. R:R = 1.6x"
    - Reference observable exit triggers: funding rate normalization, OI collapse,
      Fear & Greed regime change, or stablecoin flow reversal — not just price levels.
```

### 5c. Add crypto guidance to mechanism matching prompt

In `MECHANISM_MATCHING_PROMPT`, add to system message rules (after line 189):

```
- For crypto mechanisms (crypto_leverage_liquidation, stablecoin_contagion,
  crypto_liquidity_proxy): funding rate signals are PRIMARY evidence for
  crypto_leverage_liquidation — do NOT activate without citing funding rate levels.
  Stablecoin supply signals are PRIMARY evidence for stablecoin_contagion —
  do NOT activate without citing stablecoin market cap data.
```

---

## Step 6: Fix price validation threshold for crypto

**File**: `analysis/price_validator.py`

Add a helper function and modify `validate_predictions`:

```python
def _direction_threshold(asset_class: AssetClass) -> float:
    """Minimum weekly return % to count as directional."""
    if asset_class == AssetClass.CRYPTO:
        return 2.0   # crypto needs >2% to be directional
    return 0.25       # traditional assets
```

Replace the hardcoded 0.25 comparisons (lines 33-38) with:
```python
threshold = _direction_threshold(score.asset_class)
if actual_pct > threshold:
    actual_dir = SentimentDirection.BULLISH
elif actual_pct < -threshold:
    actual_dir = SentimentDirection.BEARISH
```

Import `AssetClass` (already imported at top of file).

---

## Step 7: Expand Google Trends keywords

**File**: `config/sources.yaml` — add under `google_trends.keywords` (after line 92):
```yaml
    - ethereum crash
    - solana crash
    - crypto crash
    - crypto regulation
    - bitcoin ETF
    - crypto winter
```

**File**: `collectors/google_trends.py` — add same 6 keywords to `_DEFAULT_KEYWORDS` fallback list (line 24-31).

---

## Step 8: Source-aware stale signal filtering

**File**: `run_weekly.py`

Replace the single 10-day cutoff (lines 83-98) with source-aware filtering:

```python
CRYPTO_SOURCES = {"fear_greed", "funding_rates", "onchain"}
CRYPTO_MAX_AGE = 5
DEFAULT_MAX_AGE = 10

crypto_cutoff = run_date - timedelta(days=CRYPTO_MAX_AGE)
default_cutoff = run_date - timedelta(days=DEFAULT_MAX_AGE)

before = len(signals)
filtered = []
for s in signals:
    if s.metadata.get("is_forward_looking"):
        filtered.append(s)
    elif s.source.value in CRYPTO_SOURCES or s.metadata.get("asset_class") == "crypto":
        if s.timestamp.replace(tzinfo=None) >= crypto_cutoff:
            filtered.append(s)
    else:
        if s.timestamp.replace(tzinfo=None) >= default_cutoff:
            filtered.append(s)
signals = filtered
```

---

## Step 9: Crypto-aware technical indicator thresholds

**File**: `analysis/technicals.py`

### 9a. `_overall_bias` — add `is_crypto` parameter

Change signature to `_overall_bias(rsi, macd_hist, sma_dist, is_crypto=False)`.
Use RSI thresholds 25/80 for crypto (instead of 30/70).

### 9b. `_sma_distance` — add `is_crypto` parameter

Use 8% "extended" threshold for crypto (instead of 3%).

### 9c. `compute_technicals` — pass `is_crypto` through

Detect crypto by checking `yf_sym in {"BTC-USD", "ETH-USD", "SOL-USD"}`.
Pass `is_crypto=True` to `_overall_bias` and `_sma_distance`.
Use 80/25 thresholds for RSI label (instead of 70/30).

---

## Step 10: Tests

**File**: `tests/test_collectors.py`
- Add `FundingRatesCollector` and `OnChainCollector` to base-class inheritance test
- Add basic attribute tests (symbols list, URL constants)

**New file**: `tests/test_price_validator.py`
- Test crypto threshold: BTC with 1.5% actual return → neutral (not bullish)
- Test equity threshold: S&P 500 with 1.5% actual return → bullish
- Test BTC with 3.0% return → bullish

**File**: `tests/test_schemas.py`
- Verify `SignalSource.FUNDING_RATES` and `SignalSource.ONCHAIN` exist

---

## Implementation Order

| # | Step | Files | Depends On |
|---|------|-------|------------|
| 1 | SignalSource enum | `models/schemas.py` | — |
| 2 | Funding rates collector | `collectors/funding_rates.py` (new) | Step 1 |
| 3 | On-chain collector | `collectors/onchain.py` (new) | Step 1 |
| 4 | Register + config | `run_weekly.py`, `config/sources.yaml`, `dashboard/actionable_view.py` | Steps 2, 3 |
| 5 | Prompt engineering | `ai/prompts/templates.py` | Steps 2, 3 (so prompts reference existing sources) |
| 6 | Price validation fix | `analysis/price_validator.py` | — |
| 7 | Google Trends keywords | `config/sources.yaml`, `collectors/google_trends.py` | — |
| 8 | Stale signal filtering | `run_weekly.py` | Step 1 |
| 9 | Technical thresholds | `analysis/technicals.py` | — |
| 10 | Tests | `tests/` | All above |

Steps 6, 7, 9 are independent and can be done in any order / parallel.

---

## Verification

1. **Unit tests**: `poetry run pytest tests/` — all pass
2. **Collector smoke test**: `poetry run python run_weekly.py --collect-only --sources funding_rates onchain` — verify signals in JSON output with correct source enum and metadata
3. **Full pipeline run**: `poetry run python run_weekly.py` — compare crypto narrative section against baseline report:
   - Exit conditions should include % targets, intermediate levels, R:R ratios
   - Narratives should cite funding rate levels and stablecoin supply
   - `crypto_leverage_liquidation` mechanism should activate/deactivate based on actual funding rate data
4. **Price validation check**: Verify crypto assets with 1.5% weekly move are classified as neutral
5. **Dashboard check**: `poetry run streamlit run app.py` — verify crypto cards show RSI "Overbought" only above 80, source chips include "Funding" and "On-Chain"
