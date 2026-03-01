"""Technical indicator computation for asset cards.

Computes RSI(14), MACD(12,26,9), and 20-day SMA distance at dashboard
render time so indicators always reflect the latest prices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Map human-readable asset names from the narrative pipeline to yfinance symbols.
TICKER_TO_YF: dict[str, str] = {
    # FX
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "USD/CHF": "USDCHF=X",
    "USD/CNH": "USDCNH=X",
    "DXY": "DX-Y.NYB",
    # Metals
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Platinum": "PL=F",
    "Copper": "HG=F",
    # Energy
    "WTI Crude": "CL=F",
    "Brent": "BZ=F",
    "Natural Gas": "NG=F",
    # Crypto
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "SOL-USD": "SOL-USD",
    # Indices
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow": "^DJI",
    "Russell 2000": "^RUT",
    "FTSE": "^FTSE",
    "Nikkei": "^N225",
    "Hang Seng": "^HSI",
    # Bonds
    "US 10Y": "^TNX",
    "US 2Y": "^IRX",
}


@dataclass
class TechnicalSnapshot:
    rsi: float  # RSI(14) value 0-100
    rsi_label: str  # "Overbought" / "Oversold" / "Neutral"
    macd_histogram: float  # Current MACD histogram value
    macd_label: str  # "Bullish, accelerating" etc.
    sma_20_dist_pct: float  # % distance from 20d SMA
    sma_20_label: str  # "+2.1% above" etc.
    agrees_with: str | None  # "bullish" / "bearish" / None (mixed)


def _rsi(close: pd.Series, period: int = 14) -> float:
    """Wilder's smoothed RSI."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.iloc[:period].mean()
    avg_loss = loss.iloc[:period].mean()

    for i in range(period, len(close)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(close: pd.Series) -> tuple[float, str]:
    """MACD(12,26,9) histogram value and directional label."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal

    current = histogram.iloc[-1]
    # Determine acceleration from last 3 bars
    recent = histogram.iloc[-3:].values
    if len(recent) >= 3:
        accelerating = abs(recent[-1]) > abs(recent[-2]) and abs(recent[-2]) > abs(recent[-3])
        decelerating = abs(recent[-1]) < abs(recent[-2])
    else:
        accelerating = False
        decelerating = False

    if current > 0:
        direction = "Bullish"
        momentum = "accelerating" if accelerating else ("decelerating" if decelerating else "steady")
    else:
        direction = "Bearish"
        momentum = "accelerating" if accelerating else ("decelerating" if decelerating else "steady")

    return float(current), f"{direction}, {momentum}"


def _sma_distance(close: pd.Series, period: int = 20) -> tuple[float, str]:
    """Percentage distance from SMA and descriptive label."""
    sma = close.rolling(window=period).mean()
    current_price = close.iloc[-1]
    current_sma = sma.iloc[-1]

    if pd.isna(current_sma) or current_sma == 0:
        return 0.0, "Insufficient data"

    dist_pct = ((current_price - current_sma) / current_sma) * 100

    if dist_pct > 0:
        qualifier = "extended" if abs(dist_pct) > 3 else "near"
        label = f"+{dist_pct:.1f}% above — {qualifier}"
    elif dist_pct < 0:
        qualifier = "extended" if abs(dist_pct) > 3 else "near"
        label = f"{dist_pct:.1f}% below — {qualifier}"
    else:
        label = "At SMA"

    return float(dist_pct), label


def _overall_bias(rsi: float, macd_hist: float, sma_dist: float) -> str | None:
    """If 2+ of 3 indicators lean the same direction, return that direction."""
    bullish = 0
    bearish = 0

    # RSI
    if rsi < 30:
        bullish += 1  # Oversold = contrarian bullish
    elif rsi > 70:
        bearish += 1  # Overbought = contrarian bearish
    elif rsi > 50:
        bullish += 1
    else:
        bearish += 1

    # MACD histogram
    if macd_hist > 0:
        bullish += 1
    else:
        bearish += 1

    # SMA distance
    if sma_dist > 0:
        bullish += 1
    else:
        bearish += 1

    if bullish >= 2:
        return "bullish"
    if bearish >= 2:
        return "bearish"
    return None


def compute_technicals(tickers: list[str]) -> dict[str, TechnicalSnapshot]:
    """Fetch 3 months of price data and compute technicals for each ticker.

    *tickers* are human-readable names from the narrative pipeline (e.g.
    "Gold", "EUR/USD").  Returns a dict keyed by these same names.
    Tickers with no yfinance mapping or insufficient data are silently skipped.
    """
    if not tickers:
        return {}

    # Build mapping: yf_symbol -> original ticker name
    yf_to_orig: dict[str, str] = {}
    yf_symbols: list[str] = []
    for t in tickers:
        yf_sym = TICKER_TO_YF.get(t)
        if yf_sym:
            yf_to_orig[yf_sym] = t
            yf_symbols.append(yf_sym)
        else:
            logger.debug("No yfinance mapping for ticker %s", t)

    if not yf_symbols:
        return {}

    try:
        df = yf.download(yf_symbols, period="3mo", progress=False, threads=True)
    except Exception:
        logger.exception("yfinance download failed")
        return {}

    if df.empty:
        return {}

    results: dict[str, TechnicalSnapshot] = {}

    for yf_sym in yf_symbols:
        orig = yf_to_orig[yf_sym]
        try:
            # yf.download returns multi-level columns for multiple tickers,
            # single-level for a single ticker
            if len(yf_symbols) == 1:
                close = df["Close"].dropna()
            else:
                close = df["Close"][yf_sym].dropna()

            if len(close) < 30:
                continue

            # RSI
            rsi_val = _rsi(close)
            if rsi_val > 70:
                rsi_label = "Overbought"
            elif rsi_val < 30:
                rsi_label = "Oversold"
            else:
                rsi_label = "Neutral"

            # MACD
            macd_hist, macd_label = _macd(close)

            # SMA distance
            sma_dist, sma_label = _sma_distance(close)

            # Overall bias
            agrees = _overall_bias(rsi_val, macd_hist, sma_dist)

            results[orig] = TechnicalSnapshot(
                rsi=round(rsi_val, 1),
                rsi_label=rsi_label,
                macd_histogram=round(macd_hist, 4),
                macd_label=macd_label,
                sma_20_dist_pct=round(sma_dist, 2),
                sma_20_label=sma_label,
                agrees_with=agrees,
            )
        except Exception:
            logger.debug("Skipping technicals for %s (%s)", orig, yf_sym, exc_info=True)
            continue

    return results
