"""Compute 1-week consensus price range from options + positioning."""

from __future__ import annotations

import math

from models.schemas import ConsensusScore, Signal


def compute_consensus_range(
    spot_price: float,
    atm_iv: float,
    max_pain: float,
    consensus_score: float,
    horizon_days: int = 7,
) -> dict[str, float]:
    """Compute 1-week consensus price range from options + positioning.

    Parameters
    ----------
    spot_price : current price
    atm_iv : annualized implied volatility (e.g. 0.60 for 60%)
    max_pain : max pain strike price
    consensus_score : -1 to +1 from ConsensusScore
    horizon_days : forecast horizon (default 7)
    """
    sigma_1w = spot_price * atm_iv * math.sqrt(horizon_days / 365)

    max_pain_weight = 0.3
    adjusted_mid = spot_price * (1 - max_pain_weight) + max_pain * max_pain_weight

    bias_shift = consensus_score * 0.5 * sigma_1w
    final_mid = adjusted_mid + bias_shift

    consensus_low = round(final_mid - sigma_1w, 2)
    consensus_high = round(final_mid + sigma_1w, 2)

    return {
        "spot": spot_price,
        "consensus_mid": round(final_mid, 2),
        "consensus_low": consensus_low,
        "consensus_high": consensus_high,
        "sigma_1w_usd": round(sigma_1w, 2),
        "max_pain": max_pain,
        "iv_annualized": atm_iv,
        "positioning_bias": round(bias_shift, 2),
    }


def extract_options_data(
    signals: list[Signal], ticker: str
) -> tuple[float, float, float]:
    """Extract ATM IV, max pain, and spot from options signals.

    Returns (atm_iv, max_pain, spot_price). Returns (0,0,0) if not found.
    """
    atm_iv = 0.0
    max_pain = 0.0
    spot_price = 0.0

    symbol = "BTC" if ticker == "Bitcoin" else "ETH" if ticker == "Ethereum" else ""

    for s in signals:
        if s.source.value == "options" and s.metadata.get("symbol") == symbol:
            metric = s.metadata.get("metric", "")
            if metric == "dvol":
                atm_iv = s.metadata.get("dvol", 0.0) / 100.0
            elif metric == "max_pain":
                max_pain = s.metadata.get("max_pain_strike", 0.0)
                spot_price = s.metadata.get("current_price", 0.0)

        if s.source.value == "market_data" and not spot_price:
            yf_symbol = "BTC-USD" if ticker == "Bitcoin" else "ETH-USD" if ticker == "Ethereum" else ""
            if s.metadata.get("ticker") == yf_symbol:
                spot_price = s.metadata.get("price", 0.0)

    return atm_iv, max_pain, spot_price


def compute_ranges_for_assets(
    signals: list[Signal],
    quant_scores: list[ConsensusScore],
) -> dict[str, dict[str, float]]:
    """Compute 1-week ranges for BTC and ETH."""
    score_map = {qs.ticker: qs.consensus_score for qs in quant_scores}
    ranges: dict[str, dict[str, float]] = {}

    for ticker in ["Bitcoin", "Ethereum"]:
        atm_iv, max_pain, spot = extract_options_data(signals, ticker)
        cs = score_map.get(ticker, 0.0)

        if spot > 0 and atm_iv > 0 and max_pain > 0:
            ranges[ticker] = compute_consensus_range(spot, atm_iv, max_pain, cs)
        elif spot > 0:
            default_iv = 0.60 if ticker == "Bitcoin" else 0.70
            ranges[ticker] = compute_consensus_range(
                spot, default_iv, spot, cs
            )

    return ranges
