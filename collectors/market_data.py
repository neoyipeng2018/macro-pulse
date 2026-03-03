"""Market data collector — weekly OHLCV and price returns via yfinance."""

import hashlib
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import AssetClass, Signal, SignalSource

logger = logging.getLogger(__name__)


class MarketDataCollector(BaseCollector):
    """Collect weekly OHLCV data and compute price returns for the asset universe."""

    source_name = "market_data"

    def __init__(self):
        self.assets = settings.assets

    def _get_all_tickers(self) -> list[tuple[str, str, str]]:
        """Return (ticker, name, asset_class) tuples."""
        result = []
        for asset_class, items in self.assets.items():
            for item in items:
                result.append((item["ticker"], item["name"], asset_class))
        return result

    def collect(self) -> list[Signal]:
        """Fetch weekly data and generate signals for notable moves."""
        tickers_info = self._get_all_tickers()
        all_tickers = [t[0] for t in tickers_info]
        ticker_names = {t[0]: t[1] for t in tickers_info}
        ticker_classes = {t[0]: t[2] for t in tickers_info}

        signals: list[Signal] = []

        try:
            data = yf.download(
                all_tickers, period="1mo", group_by="ticker", progress=False
            )
        except Exception as e:
            logger.warning("Error downloading market data: %s", e)
            return signals

        for ticker in all_tickers:
            try:
                if len(all_tickers) == 1:
                    close = data["Close"].dropna()
                elif ticker in data.columns.get_level_values(0):
                    close = data[ticker]["Close"].dropna()
                else:
                    continue

                if len(close) < 5:
                    continue

                # Weekly return (last 5 trading days)
                weekly_return = (close.iloc[-1] / close.iloc[-5] - 1) * 100
                # Monthly return
                monthly_return = (close.iloc[-1] / close.iloc[0] - 1) * 100
                current_price = close.iloc[-1]

                name = ticker_names.get(ticker, ticker)
                ac = ticker_classes.get(ticker, "indices")

                # Generate signal for all assets (the LLM needs the price context)
                direction = "up" if weekly_return > 0 else "down"
                sig_id = hashlib.md5(
                    f"mkt_{ticker}_{datetime.utcnow().date()}".encode()
                ).hexdigest()[:12]

                signals.append(
                    Signal(
                        id=sig_id,
                        source=SignalSource.MARKET_DATA,
                        title=f"{name} ({ticker}): {weekly_return:+.2f}% weekly, {monthly_return:+.2f}% monthly",
                        content=(
                            f"{name} is {direction} {abs(weekly_return):.2f}% this week "
                            f"and {abs(monthly_return):.2f}% this month. "
                            f"Current price: {current_price:.2f}. "
                            f"Asset class: {ac}."
                        ),
                        timestamp=datetime.utcnow(),
                        metadata={
                            "ticker": ticker,
                            "asset_class": ac,
                            "weekly_return_pct": round(weekly_return, 4),
                            "monthly_return_pct": round(monthly_return, 4),
                            "price": round(float(current_price), 4),
                        },
                    )
                )
            except Exception as e:
                logger.warning("Error processing %s: %s", ticker, e)

        return signals

    def get_weekly_returns(self) -> dict[str, float]:
        """Get weekly returns for all assets."""
        tickers_info = self._get_all_tickers()
        all_tickers = [t[0] for t in tickers_info]
        ticker_names = {t[0]: t[1] for t in tickers_info}
        returns = {}

        try:
            data = yf.download(
                all_tickers, period="1mo", group_by="ticker", progress=False
            )
        except Exception:
            return returns

        for ticker in all_tickers:
            try:
                if len(all_tickers) == 1:
                    close = data["Close"].dropna()
                elif ticker in data.columns.get_level_values(0):
                    close = data[ticker]["Close"].dropna()
                else:
                    continue
                if len(close) < 5:
                    continue
                weekly_return = (close.iloc[-1] / close.iloc[-5] - 1) * 100
                name = ticker_names.get(ticker, ticker)
                returns[name] = round(weekly_return, 4)
                returns[ticker] = round(weekly_return, 4)
            except Exception:
                continue

        return returns
