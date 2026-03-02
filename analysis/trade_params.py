"""Parse LLM exit conditions into structured trade parameters.

Extracts stop-loss %, take-profit %, R:R ratio, and horizon from the
prose exit_condition strings produced by the narrative extractor.
Also fetches current spot prices from yfinance as entry references.
"""

from __future__ import annotations

import logging
import re

import yfinance as yf

from analysis.technicals import TICKER_TO_YF
from models.schemas import (
    CompositeAssetScore,
    SentimentDirection,
    TradeParams,
)

logger = logging.getLogger(__name__)

# Default trade parameters when parsing fails
DEFAULTS = {
    "stop_loss_pct": -5.0,
    "take_profit_pct": 8.0,
    "risk_reward": 1.6,
    "horizon_days": 7,
}


def _parse_percentage(text: str, pattern: str) -> float | None:
    """Extract a percentage value from text using a regex pattern."""
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        val = float(match.group(1))
        return val
    return None


def _parse_rr(text: str) -> float | None:
    """Extract R:R ratio from text."""
    patterns = [
        r"R[:/]R\s*[=:]\s*([\d.]+)",
        r"risk[/-]reward\s*[=:]\s*([\d.]+)",
        r"([\d.]+)\s*[xX]\s*R[:/]R",
        r"([\d.]+)\s*[xX]\s*risk[/-]reward",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _parse_horizon(text: str) -> int | None:
    """Extract horizon in days from text."""
    patterns = [
        (r"(\d+)\s*day", 1),
        (r"(\d+)\s*week", 7),
        (r"(\d+)\s*-\s*(\d+)\s*week", 7),  # "1-2 weeks" → use first number
    ]
    for pat, mult in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return int(match.group(1)) * mult
    return None


def _parse_invalidation_triggers(text: str) -> list[str]:
    """Extract non-price invalidation triggers."""
    triggers = []
    # Look for "invalidated if ..." or "invalid if ..." clauses
    inv_match = re.search(
        r"(?:invalidat(?:ed|ion)|invalid)\s+if\s+(.+?)(?:\.\s|$)",
        text,
        re.IGNORECASE,
    )
    if inv_match:
        clause = inv_match.group(1).strip()
        # Split on "or" / "," to get individual triggers
        parts = re.split(r"\s+or\s+|,\s*", clause)
        triggers.extend(p.strip() for p in parts if p.strip())
    return triggers


def fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current spot prices for a list of tickers.

    Returns a dict of ticker → price. Tickers with no data are omitted.
    """
    if not tickers:
        return {}

    yf_symbols = []
    yf_to_orig: dict[str, str] = {}
    for t in tickers:
        yf_sym = TICKER_TO_YF.get(t, t)
        yf_symbols.append(yf_sym)
        yf_to_orig[yf_sym] = t

    prices: dict[str, float] = {}
    try:
        data = yf.download(yf_symbols, period="5d", progress=False, threads=True)
        if data.empty:
            return {}

        import pandas as pd

        for yf_sym in yf_symbols:
            orig = yf_to_orig[yf_sym]
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    close = data["Close"][yf_sym].dropna()
                else:
                    close = data["Close"].dropna()

                if len(close) > 0:
                    prices[orig] = float(close.iloc[-1])
            except (KeyError, IndexError):
                continue
    except Exception:
        logger.exception("Failed to fetch prices")

    return prices


def parse_trade_params(
    composite_scores: list[CompositeAssetScore],
    exit_conditions: dict[str, str],
    current_prices: dict[str, float],
    horizons: dict[str, str] | None = None,
) -> list[TradeParams]:
    """Parse LLM exit conditions into structured TradeParams.

    Parameters
    ----------
    composite_scores : list[CompositeAssetScore]
        Scored assets with direction.
    exit_conditions : dict[str, str]
        Per-ticker exit condition text from narratives.
    current_prices : dict[str, float]
        Current spot prices by ticker.
    horizons : dict[str, str] | None
        Per-ticker horizon text from narratives (e.g., "1-2 weeks").

    Returns
    -------
    list[TradeParams]
        Structured parameters for each tradeable asset.
    """
    results: list[TradeParams] = []

    for score in composite_scores:
        if score.direction == SentimentDirection.NEUTRAL:
            continue

        ticker = score.ticker
        text = exit_conditions.get(ticker, "")
        entry = current_prices.get(ticker, 0.0)

        direction = "long" if score.direction == SentimentDirection.BULLISH else "short"

        # Parse take-profit %
        tp_pct = _parse_percentage(
            text,
            r"(?:take\s*profit|TP|target)\s*(?:at\s*)?\+?([\d.]+)\s*%",
        )
        if tp_pct is None:
            tp_pct = DEFAULTS["take_profit_pct"]

        # Parse stop-loss %
        sl_pct = _parse_percentage(
            text,
            r"(?:stop[\s-]*loss|SL|stop)\s*(?:at\s*)?-?([\d.]+)\s*%",
        )
        if sl_pct is None:
            sl_pct = abs(DEFAULTS["stop_loss_pct"])
        sl_pct = -abs(sl_pct)  # always negative

        # Parse intermediate take-profit
        itp_pct = _parse_percentage(
            text,
            r"(?:intermediate|partial|first\s*target)\s*(?:TP\s*)?(?:at\s*)?\+?([\d.]+)\s*%",
        )

        # Parse R:R
        rr = _parse_rr(text)
        if rr is None:
            rr = tp_pct / abs(sl_pct) if sl_pct != 0 else DEFAULTS["risk_reward"]

        # Parse horizon
        horizon_text = (horizons or {}).get(ticker, text)
        horizon_days = _parse_horizon(horizon_text)
        if horizon_days is None:
            horizon_days = DEFAULTS["horizon_days"]

        # Parse invalidation triggers
        triggers = _parse_invalidation_triggers(text)

        results.append(
            TradeParams(
                ticker=ticker,
                direction=direction,
                entry_price=entry,
                stop_loss_pct=round(sl_pct, 2),
                take_profit_pct=round(tp_pct, 2),
                intermediate_tp_pct=round(itp_pct, 2) if itp_pct else None,
                risk_reward=round(rr, 2),
                invalidation_triggers=triggers,
                horizon_days=horizon_days,
            )
        )

    logger.info("Parsed trade params for %d assets", len(results))
    return results
