"""Prediction market signal collector (Kalshi + Polymarket)."""

import hashlib
import json
import logging
from datetime import datetime

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

_USER_AGENT = "macro-pulse/0.1"


class PredictionMarketCollector(BaseCollector):
    """Collect signals from Kalshi and Polymarket prediction markets."""

    source_name = "prediction_markets"

    KALSHI_EVENTS_URL = (
        "https://api.elections.kalshi.com/trade-api/v2/events"
        "?limit=100&status=open"
    )
    KALSHI_MARKETS_URL = (
        "https://api.elections.kalshi.com/trade-api/v2/markets"
        "?limit=50&status=open&event_ticker={event_ticker}"
    )
    POLYMARKET_URL = (
        "https://gamma-api.polymarket.com/markets"
        "?limit=200&active=true&closed=false"
    )

    # Only fetch macro-relevant categories (skip Sports, Entertainment, etc.)
    KALSHI_MACRO_CATEGORIES = {"Economics", "Financials", "Politics", "World"}

    def __init__(self, limit: int = 50):
        self.limit = limit

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []
        signals.extend(self._fetch_kalshi())
        signals.extend(self._fetch_polymarket())
        logger.info("Prediction markets: %d signals total", len(signals))
        return signals

    def _fetch_kalshi(self) -> list[Signal]:
        """Fetch macro-relevant markets from Kalshi via events API."""
        signals: list[Signal] = []

        # Step 1: Get events filtered to macro categories
        try:
            resp = httpx.get(
                self.KALSHI_EVENTS_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
        except Exception as e:
            logger.warning("Error fetching Kalshi events: %s", e)
            return signals

        macro_events = [
            e for e in events
            if e.get("category", "") in self.KALSHI_MACRO_CATEGORIES
        ]

        # Step 2: Fetch markets for each macro event
        all_markets: list[tuple[dict, str]] = []  # (market, category)
        for event in macro_events:
            event_ticker = event.get("event_ticker", "")
            category = event.get("category", "")
            try:
                resp = httpx.get(
                    self.KALSHI_MARKETS_URL.format(event_ticker=event_ticker),
                    headers={"User-Agent": _USER_AGENT},
                    timeout=10,
                )
                resp.raise_for_status()
                for m in resp.json().get("markets", []):
                    all_markets.append((m, category))
            except Exception:
                continue

        # Sort by volume, take top N
        all_markets.sort(key=lambda x: x[0].get("volume", 0), reverse=True)
        all_markets = all_markets[: self.limit]

        for m, category in all_markets:
            title = m.get("title", "")
            ticker = m.get("ticker", "")
            yes_bid = m.get("yes_bid", 0)
            yes_ask = m.get("yes_ask", 0)
            volume = m.get("volume", 0)

            prob = (yes_bid + yes_ask) / 200 if (yes_bid + yes_ask) else 0

            sig_id = hashlib.md5(f"kalshi:{ticker}".encode()).hexdigest()[:12]

            content = (
                f"Prediction market: {title}\n"
                f"Probability: {prob:.0%} | Volume: {volume:,} contracts\n"
                f"Platform: Kalshi | Category: {category}"
            )

            signals.append(
                Signal(
                    id=sig_id,
                    source=SignalSource.PREDICTION_MARKET,
                    title=title,
                    content=content,
                    url=f"https://kalshi.com/markets/{ticker}",
                    timestamp=datetime.utcnow(),
                    metadata={
                        "platform": "kalshi",
                        "probability": round(prob, 4),
                        "volume": volume,
                        "ticker": ticker,
                        "category": category,
                    },
                )
            )

        return signals

    def _fetch_polymarket(self) -> list[Signal]:
        """Fetch active markets from Polymarket's public API."""
        signals: list[Signal] = []
        try:
            resp = httpx.get(
                self.POLYMARKET_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Error fetching Polymarket markets: %s", e)
            return signals

        markets = (
            data
            if isinstance(data, list)
            else data.get("markets", data.get("data", []))
        )

        for m in markets:
            try:
                m["_vol"] = float(m.get("volume", 0) or 0)
            except (ValueError, TypeError):
                m["_vol"] = 0
        markets.sort(key=lambda m: m["_vol"], reverse=True)
        markets = markets[: self.limit]

        for m in markets:
            question = m.get("question", "") or m.get("title", "")
            condition_id = m.get("conditionId", "") or m.get("id", "")
            slug = m.get("slug", "")
            volume = m["_vol"]
            liquidity = float(m.get("liquidity", 0) or 0)

            # Parse outcome prices
            outcome_prices = m.get("outcomePrices", "")
            prob = 0.0
            if isinstance(outcome_prices, str) and outcome_prices:
                try:
                    prices = json.loads(outcome_prices)
                    if prices:
                        prob = float(prices[0])
                except (json.JSONDecodeError, ValueError, IndexError):
                    pass
            elif isinstance(outcome_prices, list) and outcome_prices:
                try:
                    prob = float(outcome_prices[0])
                except (ValueError, IndexError):
                    pass

            sig_id = hashlib.md5(
                f"polymarket:{condition_id}".encode()
            ).hexdigest()[:12]

            content = (
                f"Prediction market: {question}\n"
                f"Probability: {prob:.0%} | Volume: ${volume:,.0f} | "
                f"Liquidity: ${liquidity:,.0f}\n"
                f"Platform: Polymarket"
            )

            market_url = f"https://polymarket.com/event/{slug}" if slug else ""

            signals.append(
                Signal(
                    id=sig_id,
                    source=SignalSource.PREDICTION_MARKET,
                    title=question,
                    content=content,
                    url=market_url,
                    timestamp=datetime.utcnow(),
                    metadata={
                        "platform": "polymarket",
                        "probability": round(prob, 4),
                        "volume": volume,
                        "liquidity": liquidity,
                        "condition_id": condition_id,
                    },
                )
            )

        return signals
