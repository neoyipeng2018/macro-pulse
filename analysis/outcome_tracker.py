"""Outcome tracker: validate pending trades against actual price data.

Checks all unresolved trades and scores any that can be resolved:
- TP hit: daily high/low reached take-profit level
- SL hit: daily high/low reached stop-loss level
- Time expired: 7 days passed, neither TP nor SL hit

Called on every dashboard load and every pipeline run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import yfinance as yf

from models.schemas import TradeThesis, TradeOutcome

logger = logging.getLogger(__name__)

# Ticker to yfinance symbol mapping
_TICKER_TO_YF = {
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
    "Solana": "SOL-USD",
}


def validate_pending_trades(pending_trades: list[dict]) -> list[TradeOutcome]:
    """Check all pending trades and resolve any that can be scored.

    Parameters
    ----------
    pending_trades : list[dict]
        Trades from DB with exit_price == None. Each dict has keys matching TradeThesis fields.

    Returns
    -------
    list[TradeOutcome]
        Resolved trade outcomes ready to be saved.
    """
    outcomes = []
    now = datetime.utcnow()

    for trade_dict in pending_trades:
        try:
            outcome = _check_single_trade(trade_dict, now)
            if outcome is not None:
                outcomes.append(outcome)
        except Exception as e:
            ticker = trade_dict.get("ticker", "unknown")
            logger.error("Error validating trade for %s: %s", ticker, e)

    if outcomes:
        logger.info("Validated %d trades: %s", len(outcomes),
                     ", ".join(f"{o.ticker} ({o.exit_reason}: {o.pnl_pct:+.1f}%)" for o in outcomes))
    return outcomes


def _check_single_trade(trade_dict: dict, now: datetime) -> TradeOutcome | None:
    """Check a single trade against actual price data."""
    ticker = trade_dict["ticker"]
    direction = trade_dict["direction"]
    entry_price = float(trade_dict["entry_price"])
    entry_date_raw = trade_dict["entry_date"]
    tp_pct = float(trade_dict["take_profit_pct"])
    sl_pct = float(trade_dict["stop_loss_pct"])

    if isinstance(entry_date_raw, str):
        entry_date = datetime.fromisoformat(entry_date_raw)
    else:
        entry_date = entry_date_raw

    days_elapsed = (now - entry_date).days

    # Skip trades less than 1 day old (need at least 1 day of data)
    if days_elapsed < 1:
        return None

    # Compute TP/SL price levels
    if direction == "bullish":
        tp_price = entry_price * (1 + tp_pct / 100.0)
        sl_price = entry_price * (1 - abs(sl_pct) / 100.0)
    else:  # bearish
        tp_price = entry_price * (1 - abs(tp_pct) / 100.0)
        sl_price = entry_price * (1 + abs(sl_pct) / 100.0)

    # Fetch daily OHLC from entry_date to now (or entry_date + 7d, whichever is less)
    check_end = min(now, entry_date + timedelta(days=8))  # +8 to include day 7
    yf_symbol = _TICKER_TO_YF.get(ticker, f"{ticker}")

    try:
        df = yf.download(
            yf_symbol,
            start=entry_date.strftime("%Y-%m-%d"),
            end=check_end.strftime("%Y-%m-%d"),
            progress=False,
        )
    except Exception as e:
        logger.warning("Failed to fetch price data for %s: %s", ticker, e)
        return None

    if df.empty:
        return None

    # Check each day in order for TP/SL hits
    exit_price = None
    exit_date = None
    exit_reason = None

    for idx, row in df.iterrows():
        day_high = float(row["High"].iloc[0]) if hasattr(row["High"], "iloc") else float(row["High"])
        day_low = float(row["Low"].iloc[0]) if hasattr(row["Low"], "iloc") else float(row["Low"])
        day_close = float(row["Close"].iloc[0]) if hasattr(row["Close"], "iloc") else float(row["Close"])
        day_date = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx

        if direction == "bullish":
            # Check TP: did high reach TP level?
            if day_high >= tp_price:
                exit_price = tp_price
                exit_date = day_date
                exit_reason = "tp_hit"
                break
            # Check SL: did low reach SL level?
            if day_low <= sl_price:
                exit_price = sl_price
                exit_date = day_date
                exit_reason = "sl_hit"
                break
        else:  # bearish
            # Check TP: did low reach TP level?
            if day_low <= tp_price:
                exit_price = tp_price
                exit_date = day_date
                exit_reason = "tp_hit"
                break
            # Check SL: did high reach SL level?
            if day_high >= sl_price:
                exit_price = sl_price
                exit_date = day_date
                exit_reason = "sl_hit"
                break

    # If neither TP nor SL hit and 7+ days have passed: time_expired
    if exit_reason is None and days_elapsed >= 7:
        last_row = df.iloc[-1]
        exit_price_val = last_row["Close"]
        exit_price = float(exit_price_val.iloc[0]) if hasattr(exit_price_val, "iloc") else float(exit_price_val)
        exit_date = df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1]
        exit_reason = "time_expired"

    # If still no resolution (trade is live, < 7 days, no TP/SL): skip
    if exit_reason is None:
        return None

    # Compute P&L
    if direction == "bullish":
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
    else:
        pnl_pct = ((entry_price - exit_price) / entry_price) * 100.0

    # Was direction correct?
    if direction == "bullish":
        direction_correct = exit_price > entry_price
    else:
        direction_correct = exit_price < entry_price

    days_held = (exit_date - entry_date).days if exit_date else days_elapsed

    week = trade_dict.get("week", entry_date.strftime("%Y-%m-%d"))

    return TradeOutcome(
        ticker=ticker,
        week=week,
        direction=direction,
        entry_price=entry_price,
        entry_date=entry_date,
        exit_price=exit_price,
        exit_date=exit_date,
        exit_reason=exit_reason,
        pnl_pct=round(pnl_pct, 2),
        direction_correct=direction_correct,
        consensus_score=float(trade_dict.get("consensus_score_at_entry", 0.0)),
        our_score=float(trade_dict.get("our_score_at_entry", 0.0)),
        divergence=float(trade_dict.get("divergence_at_entry", 0.0)),
        divergence_label=trade_dict.get("divergence_label", "aligned"),
        days_held=days_held,
    )


def generate_trade_theses(
    composite_scores: list,
    consensus_scores: list,
    divergence_data: dict[str, dict],
    market_data: dict[str, float] | None = None,
) -> list[TradeThesis]:
    """Generate structured trade theses for BTC and ETH.

    Only generates trades for assets where:
    1. We have both a composite score and consensus score
    2. Risk/reward ratio >= 1.5

    Parameters
    ----------
    composite_scores : list[CompositeAssetScore]
        Our pipeline's composite scores.
    consensus_scores : list[ConsensusScore]
        Computed market consensus scores.
    divergence_data : dict[str, dict]
        Divergence metrics keyed by ticker.
    market_data : dict[str, float] | None
        Current prices keyed by ticker (fetched from yfinance if not provided).

    Returns
    -------
    list[TradeThesis]
        Structured trade theses with TP/SL/R:R.
    """
    consensus_map = {cs.ticker: cs for cs in consensus_scores}
    crypto_tickers = {"Bitcoin", "Ethereum"}

    # Fetch current prices if not provided
    if market_data is None:
        market_data = _fetch_current_prices(list(crypto_tickers))

    theses = []
    now = datetime.utcnow()

    for cs in composite_scores:
        if cs.ticker not in crypto_tickers:
            continue

        consensus = consensus_map.get(cs.ticker)
        div_data = divergence_data.get(cs.ticker, {})
        current_price = market_data.get(cs.ticker, 0.0)

        if current_price <= 0:
            logger.warning("No price data for %s, skipping trade thesis", cs.ticker)
            continue

        # Determine direction from composite score
        if cs.composite_score > 0.15:
            direction = "bullish"
        elif cs.composite_score < -0.15:
            direction = "bearish"
        else:
            continue  # No trade for neutral

        # Scale TP/SL by conviction (abs composite score)
        abs_score = abs(cs.composite_score)
        abs_div = div_data.get("abs_divergence", 0.0)

        # Base TP: 4-8% scaled by conviction and divergence
        base_tp = 4.0 + abs_score * 4.0 + abs_div * 2.0
        tp_pct = round(min(base_tp, 12.0), 1)  # cap at 12%

        # SL: TP / target_rr, minimum 2%
        target_rr = 2.0 if abs_div > 0.5 else 1.5
        sl_pct = round(max(tp_pct / target_rr, 2.0), 1)

        # Actual R:R
        rr = round(tp_pct / sl_pct, 2) if sl_pct > 0 else 0.0

        # Must meet minimum R:R of 1.5
        if rr < 1.5:
            logger.info("Skipping %s trade: R:R %.2f < 1.5", cs.ticker, rr)
            continue

        consensus_score_val = consensus.consensus_score if consensus else 0.0
        divergence_val = div_data.get("divergence", 0.0)
        div_label = div_data.get("divergence_label", "aligned")

        thesis = TradeThesis(
            ticker=cs.ticker,
            direction=direction,
            entry_price=current_price,
            entry_date=now,
            take_profit_pct=tp_pct,
            stop_loss_pct=sl_pct,
            risk_reward_ratio=rr,
            max_holding_days=7,
            consensus_score_at_entry=consensus_score_val,
            our_score_at_entry=cs.composite_score,
            divergence_at_entry=divergence_val,
            divergence_label=div_label,
            composite_score=cs.composite_score,
            rationale=(
                f"Composite score {cs.composite_score:+.2f} ({direction}). "
                f"Consensus: {consensus_score_val:+.2f}. "
                f"Divergence: {divergence_val:+.2f} ({div_label}). "
                f"Entry: ${current_price:,.0f}. TP: {tp_pct:+.1f}%. SL: -{sl_pct:.1f}%. R:R: {rr:.1f}x."
            ),
        )
        theses.append(thesis)

    logger.info("Generated %d trade theses", len(theses))
    return theses


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current prices from yfinance."""
    prices = {}
    for ticker in tickers:
        yf_symbol = _TICKER_TO_YF.get(ticker)
        if not yf_symbol:
            continue
        try:
            t = yf.Ticker(yf_symbol)
            info = t.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            if price:
                prices[ticker] = float(price)
        except Exception as e:
            logger.warning("Failed to fetch price for %s: %s", ticker, e)
    return prices
