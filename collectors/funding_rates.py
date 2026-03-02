"""Funding rates & open interest collector for crypto perpetual futures.

Fetches funding rates and open interest from CoinGlass (primary) or
Binance FAPI (fallback). Both are free, no API key required.

Signals emitted per symbol (BTC, ETH, SOL):
  - Funding rate: current rate, 7-day average, crowd interpretation
  - Open interest: current OI in USD, 24h change %
  - Leverage alert (conditional): extreme funding triggers liquidation risk signal
"""

import hashlib
import logging
from datetime import datetime

import httpx
import yaml

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

_SYMBOLS = ["BTC", "ETH", "SOL"]

# CoinGlass public endpoints (no key)
_COINGLASS_FUNDING_URL = "https://open-api.coinglass.com/public/v2/funding"
_COINGLASS_OI_URL = "https://open-api.coinglass.com/public/v2/open_interest"

# Binance FAPI fallback (no key)
_BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
_BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"

# Thresholds
_EXTREME_LONG_THRESHOLD = 0.05   # funding >0.05% = high liquidation risk
_EXTREME_SHORT_THRESHOLD = -0.03  # funding <-0.03% = strong short squeeze
_CROWDED_LONG_THRESHOLD = 0.03   # funding >0.03% = longs crowded
_CROWDED_SHORT_THRESHOLD = -0.01  # funding <-0.01% = shorts crowded

_BINANCE_SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _interpret_funding(rate: float) -> str:
    """Interpret funding rate for directional bias."""
    if rate >= _EXTREME_LONG_THRESHOLD:
        return "EXTREME crowded longs — high liquidation risk within 1-3 days"
    if rate >= _CROWDED_LONG_THRESHOLD:
        return "Leveraged longs crowded — BEARISH contrarian signal"
    if rate <= _EXTREME_SHORT_THRESHOLD:
        return "EXTREME crowded shorts — strong short squeeze potential"
    if rate <= _CROWDED_SHORT_THRESHOLD:
        return "Leveraged shorts crowded — BULLISH short squeeze setup"
    return "Neutral — no extreme positioning"


def _interpret_oi(oi_change_pct: float, price_trend: str) -> str:
    """Interpret OI change combined with price direction."""
    if oi_change_pct > 5:
        if price_trend == "rising":
            return "Rising OI + rising price = new longs entering (trend confirmation)"
        return "Rising OI + falling price = new shorts entering (bear pressure)"
    if oi_change_pct < -20:
        return "OI collapsed >20% — leverage flush, often marks local bottom"
    if oi_change_pct < -5:
        return "Declining OI — deleveraging in progress"
    return "OI stable — no strong positioning signal"


class FundingRatesCollector(BaseCollector):
    """Collect crypto funding rates and open interest data."""

    source_name = "funding_rates"

    def __init__(self):
        self.symbols = list(_SYMBOLS)
        self.extreme_long_threshold = _EXTREME_LONG_THRESHOLD
        self.extreme_short_threshold = _EXTREME_SHORT_THRESHOLD
        self._load_config()

    def _load_config(self) -> None:
        try:
            with open("config/sources.yaml") as f:
                cfg = yaml.safe_load(f)
            fr_cfg = cfg.get("funding_rates", {})
            if fr_cfg.get("symbols"):
                self.symbols = fr_cfg["symbols"]
            if fr_cfg.get("extreme_long_threshold") is not None:
                self.extreme_long_threshold = fr_cfg["extreme_long_threshold"]
            if fr_cfg.get("extreme_short_threshold") is not None:
                self.extreme_short_threshold = fr_cfg["extreme_short_threshold"]
        except Exception:
            pass

    def collect(self) -> list[Signal]:
        signals = self._collect_coinglass()
        if not signals:
            logger.info("CoinGlass unavailable, falling back to Binance FAPI")
            signals = self._collect_binance()
        return signals

    def _collect_coinglass(self) -> list[Signal]:
        """Try CoinGlass public API."""
        signals: list[Signal] = []
        try:
            resp = httpx.get(
                _COINGLASS_FUNDING_URL,
                params={"time_type": "all"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "0" or not data.get("data"):
                return []

            # Build lookup by symbol
            funding_lookup = {}
            for item in data["data"]:
                sym = item.get("symbol", "").upper()
                if sym in self.symbols:
                    funding_lookup[sym] = item

            for symbol in self.symbols:
                item = funding_lookup.get(symbol)
                if not item:
                    continue

                rate = float(item.get("uMarginList", [{}])[0].get("rate", 0))
                signals.extend(self._build_funding_signals(symbol, rate))

        except Exception as e:
            logger.debug("CoinGlass funding fetch failed: %s", e)

        # Open interest
        try:
            resp = httpx.get(
                _COINGLASS_OI_URL,
                params={"time_type": "all"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == "0" and data.get("data"):
                for item in data["data"]:
                    sym = item.get("symbol", "").upper()
                    if sym in self.symbols:
                        oi_usd = float(item.get("openInterest", 0))
                        oi_change = float(item.get("h24Change", 0))
                        signals.extend(
                            self._build_oi_signals(sym, oi_usd, oi_change)
                        )
        except Exception as e:
            logger.debug("CoinGlass OI fetch failed: %s", e)

        return signals

    def _collect_binance(self) -> list[Signal]:
        """Fallback to Binance FAPI (free, no key)."""
        signals: list[Signal] = []

        for symbol in self.symbols:
            binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
            if not binance_sym:
                continue

            # Funding rate
            try:
                resp = httpx.get(
                    _BINANCE_FUNDING_URL,
                    params={"symbol": binance_sym, "limit": 8},
                    timeout=15,
                )
                resp.raise_for_status()
                entries = resp.json()

                if entries:
                    current_rate = float(entries[-1].get("fundingRate", 0)) * 100
                    rates = [float(e["fundingRate"]) * 100 for e in entries]
                    avg_7d = sum(rates) / len(rates) if rates else current_rate

                    signals.extend(
                        self._build_funding_signals(
                            symbol, current_rate, avg_7d=avg_7d
                        )
                    )
            except Exception as e:
                logger.debug("Binance funding fetch for %s failed: %s", symbol, e)

            # Open interest (Binance returns OI in coin units, convert to USD)
            try:
                resp = httpx.get(
                    _BINANCE_OI_URL,
                    params={"symbol": binance_sym},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                oi_coins = float(data.get("openInterest", 0))
                # Get mark price to convert OI to USD
                price_resp = httpx.get(
                    "https://fapi.binance.com/fapi/v1/ticker/price",
                    params={"symbol": binance_sym},
                    timeout=10,
                )
                price_resp.raise_for_status()
                mark_price = float(price_resp.json().get("price", 0))
                oi_usd = oi_coins * mark_price
                # Binance single-call doesn't provide 24h change; set 0
                signals.extend(self._build_oi_signals(symbol, oi_usd, 0.0))
            except Exception as e:
                logger.debug("Binance OI fetch for %s failed: %s", symbol, e)

        return signals

    def _build_funding_signals(
        self, symbol: str, rate: float, avg_7d: float | None = None
    ) -> list[Signal]:
        """Build funding rate signal and optional leverage alert."""
        if avg_7d is None:
            avg_7d = rate

        interpretation = _interpret_funding(rate)
        signals = [
            Signal(
                id=_make_id("funding", symbol),
                source=SignalSource.FUNDING_RATES,
                title=f"{symbol} funding rate: {rate:+.4f}% ({interpretation.split(' — ')[0]})",
                content=(
                    f"{symbol} perpetual futures funding rate is {rate:+.4f}% "
                    f"(8-hour), 7-day average {avg_7d:+.4f}%. "
                    f"Interpretation: {interpretation}. "
                    f"Funding rate >0.03% means leveraged longs are crowded (bearish contrarian). "
                    f"Funding rate <-0.01% means shorts are crowded (bullish, short squeeze setup)."
                ),
                metadata={
                    "symbol": symbol,
                    "funding_rate": round(rate, 6),
                    "funding_7d_avg": round(avg_7d, 6),
                    "signal_type": "funding_rate",
                    "asset_class": "crypto",
                },
            )
        ]

        # Conditional leverage alert for extreme readings
        if rate >= self.extreme_long_threshold or rate <= self.extreme_short_threshold:
            direction = "LONG" if rate > 0 else "SHORT"
            signals.append(
                Signal(
                    id=_make_id("leverage_alert", symbol),
                    source=SignalSource.FUNDING_RATES,
                    title=f"LEVERAGE ALERT: {symbol} extreme {direction} funding {rate:+.4f}%",
                    content=(
                        f"HIGH PRIORITY: {symbol} funding rate at {rate:+.4f}% is in "
                        f"extreme territory. {interpretation}. "
                        f"This level historically precedes liquidation cascades within 1-3 days. "
                        f"Feeds crypto_leverage_liquidation mechanism."
                    ),
                    metadata={
                        "symbol": symbol,
                        "funding_rate": round(rate, 6),
                        "signal_type": "leverage_alert",
                        "asset_class": "crypto",
                        "priority": "high",
                    },
                )
            )

        return signals

    def _build_oi_signals(
        self, symbol: str, oi_usd: float, oi_change_pct: float
    ) -> list[Signal]:
        """Build open interest signal."""
        # Infer price trend from OI change sign as a rough proxy
        price_trend = "rising" if oi_change_pct > 0 else "falling"
        interpretation = _interpret_oi(oi_change_pct, price_trend)

        return [
            Signal(
                id=_make_id("oi", symbol),
                source=SignalSource.FUNDING_RATES,
                title=f"{symbol} open interest: ${oi_usd / 1e9:.1f}B ({oi_change_pct:+.1f}% 24h)",
                content=(
                    f"{symbol} total open interest is ${oi_usd / 1e9:.2f}B, "
                    f"24h change {oi_change_pct:+.1f}%. "
                    f"Interpretation: {interpretation}. "
                    f"Rising OI + rising price = trend confirmation. "
                    f"Rising OI + falling price = bear pressure. "
                    f"OI collapse >20% in 24h = leverage flush (often marks local bottom)."
                ),
                metadata={
                    "symbol": symbol,
                    "open_interest_usd": round(oi_usd, 2),
                    "oi_24h_change_pct": round(oi_change_pct, 2),
                    "signal_type": "open_interest",
                    "asset_class": "crypto",
                },
            )
        ]
