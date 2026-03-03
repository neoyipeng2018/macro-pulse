"""Consensus score aggregator: combine individual consensus signals into a single score per asset.

Takes raw consensus data from options, derivatives, and ETF flow collectors
and produces a single ConsensusScore per asset (BTC, ETH).

Equal-weighted by design — we don't know which components are most predictive yet.
After 8-12 weeks of outcome data, weights can be shifted toward better predictors.

Each component is normalized to [-1, +1] against a 30-day rolling window.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from models.schemas import ConsensusScore, Signal

logger = logging.getLogger(__name__)

# Ticker mapping from collector symbols to display names
_SYMBOL_TO_TICKER = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
}

# Static normalization ranges (used until we have 30 days of history)
# These represent typical ranges for each metric
_DEFAULT_RANGES = {
    "options_skew": (-0.05, 0.05),       # 25-delta risk reversal
    "funding_7d": (-0.10, 0.10),          # 7-day accumulated funding %
    "top_trader_ls": (0.7, 1.3),          # top trader L/S ratio (centered on 1.0)
    "etf_flow_5d": (-500.0, 500.0),       # USD millions, 5-day rolling
    "put_call_ratio": (0.5, 1.5),         # raw PCR
    "oi_change_7d": (-15.0, 15.0),        # % OI change over 7 days
}

# Consensus direction thresholds
_BULLISH_THRESHOLD = 0.15
_BEARISH_THRESHOLD = -0.15


def _normalize(value: float, range_min: float, range_max: float) -> float:
    """Normalize a value to [-1, +1] within a given range."""
    if range_max == range_min:
        return 0.0
    mid = (range_min + range_max) / 2.0
    half_range = (range_max - range_min) / 2.0
    normalized = (value - mid) / half_range
    return max(-1.0, min(1.0, normalized))


def _safe_get(metadata: dict, key: str, default: float = 0.0) -> float:
    """Safely extract a float from metadata."""
    val = metadata.get(key, default)
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def compute_consensus_scores(
    signals: list[Signal],
    historical_scores: list[ConsensusScore] | None = None,
) -> list[ConsensusScore]:
    """Compute consensus scores for BTC and ETH from collected signals.

    Parameters
    ----------
    signals : list[Signal]
        All collected signals (filtered to options, derivatives_consensus, etf_flows).
    historical_scores : list[ConsensusScore] | None
        Previous consensus scores for dynamic normalization (future use).

    Returns
    -------
    list[ConsensusScore]
        One per asset (BTC, ETH).
    """
    # Group relevant signals by symbol
    symbol_data: dict[str, dict] = {
        "BTC": {},
        "ETH": {},
    }

    for signal in signals:
        source = signal.source.value
        if source not in ("options", "derivatives_consensus", "etf_flows"):
            continue

        meta = signal.metadata
        symbol = meta.get("symbol", "")

        # Handle composite/summary signals that aggregate all metrics
        signal_type = meta.get("signal_type", "")

        if source == "options" and signal_type == "options_composite":
            if symbol in symbol_data:
                sd = symbol_data[symbol]
                sd["options_skew"] = _safe_get(meta, "options_skew_25d")
                sd["put_call_ratio"] = _safe_get(meta, "put_call_ratio")
                sd["max_pain"] = _safe_get(meta, "max_pain")
                sd["max_pain_distance_pct"] = _safe_get(meta, "max_pain_distance_pct")
                sd["dvol"] = _safe_get(meta, "dvol")
                sd["iv_term_slope"] = _safe_get(meta, "iv_term_slope")

        elif source == "derivatives_consensus" and signal_type == "derivatives_composite":
            if symbol in symbol_data:
                sd = symbol_data[symbol]
                sd["top_ls_ratio"] = _safe_get(meta, "top_ls_ratio", 1.0)
                sd["ls_ratio"] = _safe_get(meta, "ls_ratio", 1.0)
                sd["funding_rate"] = _safe_get(meta, "funding_rate")
                sd["funding_7d_accumulated"] = _safe_get(meta, "funding_7d_accumulated")
                sd["oi_24h_change_pct"] = _safe_get(meta, "oi_24h_change_pct")
                sd["oi_7d_change_pct"] = _safe_get(meta, "oi_7d_change_pct")

        elif source == "etf_flows":
            # ETF flow signals use asset name in metadata
            if "btc" in signal_type or symbol == "BTC" or "Bitcoin" in signal.title:
                sd = symbol_data["BTC"]
                sd["etf_daily_flow"] = _safe_get(meta, "btc_daily_flow_usd")
                sd["etf_5d_flow"] = _safe_get(meta, "btc_5d_rolling_flow_usd")
                sd["ibit_flow"] = _safe_get(meta, "ibit_daily_flow_usd")
                sd["etf_data_available"] = meta.get("data_available", False)
            elif "eth" in signal_type or symbol == "ETH" or "Ethereum" in signal.title:
                sd = symbol_data["ETH"]
                sd["etf_daily_flow"] = _safe_get(meta, "eth_daily_flow_usd")
                sd["etf_5d_flow"] = _safe_get(meta, "eth_5d_rolling_flow_usd")
                sd["etf_data_available"] = meta.get("data_available", False)

        # Also pick up individual signal types
        if source == "options":
            if symbol in symbol_data:
                sd = symbol_data[symbol]
                if signal_type == "options_skew" and "options_skew" not in sd:
                    sd["options_skew"] = _safe_get(meta, "options_skew_25d")
                elif signal_type == "put_call_ratio" and "put_call_ratio" not in sd:
                    sd["put_call_ratio"] = _safe_get(meta, "put_call_ratio")
                elif signal_type == "max_pain" and "max_pain" not in sd:
                    sd["max_pain"] = _safe_get(meta, "max_pain")
                    sd["max_pain_distance_pct"] = _safe_get(meta, "max_pain_distance_pct")

        if source == "derivatives_consensus":
            if symbol in symbol_data:
                sd = symbol_data[symbol]
                if signal_type == "top_trader_ls" and "top_ls_ratio" not in sd:
                    sd["top_ls_ratio"] = _safe_get(meta, "top_ls_ratio", 1.0)
                elif signal_type == "funding_oi_weighted" and "funding_rate" not in sd:
                    sd["funding_rate"] = _safe_get(meta, "funding_rate")
                elif signal_type == "funding_7d" and "funding_7d_accumulated" not in sd:
                    sd["funding_7d_accumulated"] = _safe_get(meta, "funding_7d_accumulated")
                elif signal_type == "oi_change" and "oi_7d_change_pct" not in sd:
                    sd["oi_7d_change_pct"] = _safe_get(meta, "oi_7d_change_pct")

    results = []
    for symbol, data in symbol_data.items():
        ticker = _SYMBOL_TO_TICKER.get(symbol, symbol)
        score = _compute_single_score(ticker, symbol, data)
        if score is not None:
            results.append(score)

    logger.info(
        "Consensus scores: %s",
        ", ".join(f"{s.ticker}={s.consensus_score:+.3f} ({s.consensus_direction})" for s in results),
    )
    return results


def _compute_single_score(ticker: str, symbol: str, data: dict) -> ConsensusScore | None:
    """Compute consensus score for a single asset from collected data."""
    components: dict[str, float] = {}
    component_count = 0

    # 1. Options skew signal
    if "options_skew" in data:
        skew = data["options_skew"]
        skew_signal = _normalize(skew, *_DEFAULT_RANGES["options_skew"])
        components["options_skew"] = round(skew_signal, 4)
        component_count += 1

    # 2. Funding rate signal (7-day accumulated preferred, else current)
    funding_7d = data.get("funding_7d_accumulated", data.get("funding_rate", None))
    if funding_7d is not None:
        funding_signal = _normalize(funding_7d, *_DEFAULT_RANGES["funding_7d"])
        components["funding_7d"] = round(funding_signal, 4)
        component_count += 1

    # 3. Top trader L/S signal
    if "top_ls_ratio" in data:
        ratio = data["top_ls_ratio"]
        ls_signal = _normalize(ratio, *_DEFAULT_RANGES["top_trader_ls"])
        components["top_trader_ls"] = round(ls_signal, 4)
        component_count += 1

    # 4. ETF flow signal
    etf_flow = data.get("etf_5d_flow", data.get("etf_daily_flow", None))
    etf_available = data.get("etf_data_available", False)
    if etf_flow is not None and etf_available:
        etf_signal = _normalize(etf_flow, *_DEFAULT_RANGES["etf_flow_5d"])
        components["etf_flows"] = round(etf_signal, 4)
        component_count += 1

    # 5. Put/call ratio signal (inverted: low PCR = bullish)
    if "put_call_ratio" in data:
        pcr = data["put_call_ratio"]
        # Invert: low PCR (0.5) = bullish (+1), high PCR (1.5) = bearish (-1)
        pcr_signal = _normalize(1.0 - pcr, -0.5, 0.5)
        components["put_call_ratio"] = round(pcr_signal, 4)
        component_count += 1

    # 6. OI momentum signal
    oi_7d = data.get("oi_7d_change_pct")
    if oi_7d is not None:
        oi_signal = _normalize(oi_7d, *_DEFAULT_RANGES["oi_change_7d"])
        components["oi_momentum"] = round(oi_signal, 4)
        component_count += 1

    if component_count == 0:
        logger.warning("No consensus data available for %s", ticker)
        return None

    # Equal-weighted average of available components
    consensus_score = sum(components.values()) / component_count
    consensus_score = max(-1.0, min(1.0, round(consensus_score, 4)))

    # Direction classification
    if consensus_score > _BULLISH_THRESHOLD:
        direction = "bullish"
    elif consensus_score < _BEARISH_THRESHOLD:
        direction = "bearish"
    else:
        direction = "neutral"

    return ConsensusScore(
        ticker=ticker,
        consensus_score=consensus_score,
        consensus_direction=direction,
        components=components,
        options_skew=round(data.get("options_skew", 0.0), 6),
        funding_rate_7d=round(data.get("funding_7d_accumulated", data.get("funding_rate", 0.0)), 6),
        top_trader_ls_ratio=round(data.get("top_ls_ratio", 0.0), 4),
        etf_flow_5d=round(data.get("etf_5d_flow", 0.0), 2),
        put_call_ratio=round(data.get("put_call_ratio", 0.0), 4),
        max_pain_distance_pct=round(data.get("max_pain_distance_pct", 0.0), 4),
        oi_change_7d_pct=round(data.get("oi_7d_change_pct", 0.0), 2),
        data_timestamp=datetime.utcnow(),
    )


def compute_divergence(
    consensus_scores: list[ConsensusScore],
    composite_scores_map: dict[str, float],
) -> dict[str, dict]:
    """Compute divergence between our view and market consensus.

    Parameters
    ----------
    consensus_scores : list[ConsensusScore]
        Computed consensus scores per asset.
    composite_scores_map : dict[str, float]
        Our composite scores keyed by ticker.

    Returns
    -------
    dict[str, dict]
        Per-ticker divergence data with keys: consensus_score, our_score, divergence,
        abs_divergence, divergence_label, consensus_direction, our_direction.
    """
    from models.schemas import DivergenceMetrics

    results = {}
    for cs in consensus_scores:
        our_score = composite_scores_map.get(cs.ticker, 0.0)
        divergence = our_score - cs.consensus_score
        abs_div = abs(divergence)

        if abs_div > 1.0:
            label = "strongly_contrarian"
        elif abs_div > 0.5:
            label = "contrarian"
        elif abs_div > 0.2:
            label = "mildly_non_consensus"
        else:
            label = "aligned"

        # Our direction
        if our_score > 0.1:
            our_dir = "bullish"
        elif our_score < -0.1:
            our_dir = "bearish"
        else:
            our_dir = "neutral"

        metrics = DivergenceMetrics(
            ticker=cs.ticker,
            consensus_score=cs.consensus_score,
            our_score=our_score,
            divergence=round(divergence, 4),
            abs_divergence=round(abs_div, 4),
            divergence_label=label,
            consensus_direction=cs.consensus_direction,
            our_direction=our_dir,
        )

        results[cs.ticker] = metrics.model_dump()

    logger.info(
        "Divergence: %s",
        ", ".join(
            f"{t}={d['divergence']:+.3f} ({d['divergence_label']})"
            for t, d in results.items()
        ),
    )
    return results
