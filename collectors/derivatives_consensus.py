"""Multi-exchange derivatives consensus collector for BTC and ETH.

Fetches derivatives data from Binance, Bybit, and OKX to derive consensus
signals. Uses ccxt for exchange APIs (funding rates, open interest) and
httpx for Binance-specific endpoints (long/short ratios).

Signals emitted per symbol (BTC, ETH):
  - Global long/short ratio (Binance retail positioning)
  - Top trader long/short ratio (Binance smart money positioning)
  - OI-weighted aggregated funding rate (cross-exchange)
  - 7-day accumulated funding (total cost longs paid shorts)
  - OI change 24h and 7d (multi-exchange)
  - OI-weighted funding rate (true consensus rate)

All computed values are stored in signal metadata for the consensus scorer.
"""

import hashlib
import logging
from datetime import datetime, timedelta

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

# Binance-specific REST endpoints (not covered by ccxt)
_BINANCE_GLOBAL_LS_URL = (
    "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
)
_BINANCE_TOP_LS_URL = (
    "https://fapi.binance.com/futures/data/topLongShortPositionRatio"
)

_SYMBOLS = ["BTC", "ETH"]

_BINANCE_SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
_CCXT_SYMBOL_MAP = {"BTC": "BTC/USDT:USDT", "ETH": "ETH/USDT:USDT"}

# Exchanges to query via ccxt for funding rates and OI
_EXCHANGES = ["binance", "bybit", "okx"]

_HTTP_TIMEOUT = 15


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class DerivativesConsensusCollector(BaseCollector):
    """Collect multi-exchange derivatives data for BTC/ETH consensus signals."""

    source_name = "derivatives_consensus"

    def __init__(self):
        self._ccxt_available = False
        self._exchanges: dict = {}
        self._init_ccxt()

    def _init_ccxt(self) -> None:
        """Initialize ccxt exchange connections. Falls back gracefully if unavailable."""
        try:
            import ccxt

            self._ccxt_available = True
            for name in _EXCHANGES:
                try:
                    exchange_class = getattr(ccxt, name)
                    exchange = exchange_class({"options": {"defaultType": "swap"}})
                    exchange.load_markets()
                    self._exchanges[name] = exchange
                    logger.info("ccxt: initialized %s", name)
                except Exception as e:
                    logger.warning("ccxt: failed to initialize %s: %s", name, e)
        except ImportError:
            logger.warning(
                "ccxt not installed — falling back to httpx-only Binance data"
            )

    def collect(self) -> list[Signal]:
        """Collect all derivatives consensus signals for BTC and ETH."""
        signals: list[Signal] = []

        for symbol in _SYMBOLS:
            symbol_signals = self._collect_symbol(symbol)
            signals.extend(symbol_signals)

        return signals

    def _collect_symbol(self, symbol: str) -> list[Signal]:
        """Collect all derivatives data for a single symbol."""
        signals: list[Signal] = []

        # 1. Long/short ratios from Binance (httpx)
        ls_data = self._fetch_long_short_ratios(symbol)

        # 2. Funding rates and OI from exchanges (ccxt or httpx fallback)
        funding_oi_data = self._fetch_funding_and_oi(symbol)

        # 3. Historical funding for 7-day accumulation
        funding_history = self._fetch_funding_history(symbol)

        # Build composite metadata
        metadata = self._build_metadata(symbol, ls_data, funding_oi_data, funding_history)

        # Emit signals
        signals.extend(self._build_signals(symbol, metadata))

        return signals

    # ── Binance long/short ratios (httpx) ──────────────────────────────

    def _fetch_long_short_ratios(self, symbol: str) -> dict:
        """Fetch global and top-trader long/short ratios from Binance."""
        binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
        if not binance_sym:
            return {}

        data: dict = {}

        # Global long/short ratio
        try:
            resp = httpx.get(
                _BINANCE_GLOBAL_LS_URL,
                params={"symbol": binance_sym, "period": "1d", "limit": 7},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            entries = resp.json()
            if entries and isinstance(entries, list):
                latest = entries[-1]
                data["global_ls_ratio"] = _safe_float(
                    latest.get("longShortRatio"), 1.0
                )
                data["global_long_account"] = _safe_float(
                    latest.get("longAccount"), 0.5
                )
                data["global_short_account"] = _safe_float(
                    latest.get("shortAccount"), 0.5
                )
                # 7-day average
                ratios = [_safe_float(e.get("longShortRatio"), 1.0) for e in entries]
                data["global_ls_ratio_7d_avg"] = sum(ratios) / len(ratios)
                logger.debug(
                    "%s global L/S ratio: %.4f (7d avg: %.4f)",
                    symbol,
                    data["global_ls_ratio"],
                    data["global_ls_ratio_7d_avg"],
                )
        except Exception as e:
            logger.warning("Binance global L/S ratio fetch failed for %s: %s", symbol, e)

        # Top trader long/short ratio
        try:
            resp = httpx.get(
                _BINANCE_TOP_LS_URL,
                params={"symbol": binance_sym, "period": "1d", "limit": 7},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            entries = resp.json()
            if entries and isinstance(entries, list):
                latest = entries[-1]
                data["top_ls_ratio"] = _safe_float(
                    latest.get("longShortRatio"), 1.0
                )
                data["top_long_account"] = _safe_float(
                    latest.get("longAccount"), 0.5
                )
                data["top_short_account"] = _safe_float(
                    latest.get("shortAccount"), 0.5
                )
                ratios = [_safe_float(e.get("longShortRatio"), 1.0) for e in entries]
                data["top_ls_ratio_7d_avg"] = sum(ratios) / len(ratios)
                logger.debug(
                    "%s top trader L/S ratio: %.4f (7d avg: %.4f)",
                    symbol,
                    data["top_ls_ratio"],
                    data["top_ls_ratio_7d_avg"],
                )
        except Exception as e:
            logger.warning("Binance top trader L/S ratio fetch failed for %s: %s", symbol, e)

        return data

    # ── Funding rates and OI (ccxt or httpx fallback) ──────────────────

    def _fetch_funding_and_oi(self, symbol: str) -> dict:
        """Fetch current funding rates and open interest from multiple exchanges.

        Uses ccxt if available, otherwise falls back to Binance httpx.
        Returns per-exchange data for OI-weighted aggregation.
        """
        ccxt_symbol = _CCXT_SYMBOL_MAP.get(symbol)
        if not ccxt_symbol:
            return {}

        exchange_data: dict[str, dict] = {}

        if self._ccxt_available and self._exchanges:
            for name, exchange in self._exchanges.items():
                try:
                    ex_data: dict = {}

                    # Funding rate
                    try:
                        funding = exchange.fetch_funding_rate(ccxt_symbol)
                        ex_data["funding_rate"] = _safe_float(
                            funding.get("fundingRate")
                        )
                        ex_data["funding_timestamp"] = funding.get(
                            "fundingTimestamp"
                        ) or funding.get("timestamp")
                        ex_data["next_funding_timestamp"] = funding.get(
                            "nextFundingTimestamp"
                        )
                    except Exception as e:
                        logger.debug(
                            "ccxt %s funding rate failed for %s: %s", name, symbol, e
                        )

                    # Open interest
                    try:
                        oi = exchange.fetch_open_interest(ccxt_symbol)
                        ex_data["open_interest"] = _safe_float(
                            oi.get("openInterestAmount")
                            or oi.get("openInterest")
                        )
                        # Try to get OI in USD value
                        oi_value = oi.get("openInterestValue") or oi.get("info", {}).get(
                            "openInterestValue"
                        )
                        if oi_value:
                            ex_data["open_interest_usd"] = _safe_float(oi_value)
                        else:
                            # Approximate USD value using mark price if available
                            mark = _safe_float(
                                oi.get("markPrice")
                                or oi.get("info", {}).get("markPrice"),
                                0.0,
                            )
                            if mark > 0 and ex_data["open_interest"] > 0:
                                ex_data["open_interest_usd"] = (
                                    ex_data["open_interest"] * mark
                                )
                    except Exception as e:
                        logger.debug(
                            "ccxt %s OI failed for %s: %s", name, symbol, e
                        )

                    if ex_data:
                        exchange_data[name] = ex_data

                except Exception as e:
                    logger.warning(
                        "ccxt %s completely failed for %s: %s", name, symbol, e
                    )
        else:
            # httpx fallback: Binance only
            exchange_data = self._fetch_binance_funding_oi_httpx(symbol)

        # Compute OI-weighted funding rate
        result = self._compute_oi_weighted_funding(exchange_data)
        result["exchange_data"] = exchange_data
        return result

    def _fetch_binance_funding_oi_httpx(self, symbol: str) -> dict[str, dict]:
        """Fallback: fetch funding rate and OI from Binance via httpx."""
        binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
        if not binance_sym:
            return {}

        exchange_data: dict[str, dict] = {}
        ex_data: dict = {}

        # Funding rate
        try:
            resp = httpx.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": binance_sym, "limit": 1},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            entries = resp.json()
            if entries:
                ex_data["funding_rate"] = _safe_float(
                    entries[-1].get("fundingRate")
                )
        except Exception as e:
            logger.warning("Binance httpx funding rate failed for %s: %s", symbol, e)

        # Open interest
        try:
            resp = httpx.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": binance_sym},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            oi_coins = _safe_float(data.get("openInterest"))

            # Get mark price to convert to USD
            price_resp = httpx.get(
                "https://fapi.binance.com/fapi/v1/ticker/price",
                params={"symbol": binance_sym},
                timeout=_HTTP_TIMEOUT,
            )
            price_resp.raise_for_status()
            mark_price = _safe_float(price_resp.json().get("price"))
            if oi_coins > 0 and mark_price > 0:
                ex_data["open_interest"] = oi_coins
                ex_data["open_interest_usd"] = oi_coins * mark_price
        except Exception as e:
            logger.warning("Binance httpx OI failed for %s: %s", symbol, e)

        if ex_data:
            exchange_data["binance"] = ex_data

        return exchange_data

    def _compute_oi_weighted_funding(self, exchange_data: dict[str, dict]) -> dict:
        """Compute OI-weighted average funding rate across exchanges."""
        total_oi = 0.0
        weighted_funding_sum = 0.0
        simple_funding_rates: list[float] = []
        oi_values: dict[str, float] = {}

        for name, ex_data in exchange_data.items():
            funding = ex_data.get("funding_rate")
            oi_usd = ex_data.get("open_interest_usd", 0.0)

            if funding is not None:
                simple_funding_rates.append(funding)

            if funding is not None and oi_usd > 0:
                total_oi += oi_usd
                weighted_funding_sum += funding * oi_usd
                oi_values[name] = oi_usd

        result: dict = {}

        # OI-weighted funding rate
        if total_oi > 0:
            result["oi_weighted_funding"] = weighted_funding_sum / total_oi
            result["total_oi_usd"] = total_oi
            result["oi_shares"] = {
                name: oi / total_oi for name, oi in oi_values.items()
            }
        elif simple_funding_rates:
            # Fallback to simple average if OI data is missing
            result["oi_weighted_funding"] = sum(simple_funding_rates) / len(
                simple_funding_rates
            )
            result["total_oi_usd"] = 0.0
            result["oi_shares"] = {}
            logger.debug(
                "OI data unavailable, using simple average funding rate"
            )

        # Simple average for comparison
        if simple_funding_rates:
            result["simple_avg_funding"] = sum(simple_funding_rates) / len(
                simple_funding_rates
            )
            result["exchange_count"] = len(simple_funding_rates)

        return result

    # ── Historical funding (7-day accumulated) ─────────────────────────

    def _fetch_funding_history(self, symbol: str) -> dict:
        """Fetch 7 days of historical funding rates.

        Binance settles every 8 hours = 3 per day = 21 entries for 7 days.
        """
        ccxt_symbol = _CCXT_SYMBOL_MAP.get(symbol)
        result: dict = {}

        if self._ccxt_available and "binance" in self._exchanges:
            try:
                exchange = self._exchanges["binance"]
                # Fetch last 21 funding rate entries (7 days * 3 settlements/day)
                since_ms = int(
                    (datetime.utcnow() - timedelta(days=7)).timestamp() * 1000
                )
                history = exchange.fetch_funding_rate_history(
                    ccxt_symbol, since=since_ms, limit=21
                )
                if history:
                    rates = [
                        _safe_float(entry.get("fundingRate"))
                        for entry in history
                        if entry.get("fundingRate") is not None
                    ]
                    if rates:
                        result["funding_7d_accumulated"] = sum(rates)
                        result["funding_7d_avg"] = sum(rates) / len(rates)
                        result["funding_7d_count"] = len(rates)
                        result["funding_7d_max"] = max(rates)
                        result["funding_7d_min"] = min(rates)

                        # Annualized rate (for context)
                        # 3 settlements/day * 365 days
                        result["funding_annualized"] = (
                            result["funding_7d_avg"] * 3 * 365
                        )

                        logger.debug(
                            "%s 7d accumulated funding: %.6f%% (%d entries)",
                            symbol,
                            result["funding_7d_accumulated"] * 100,
                            len(rates),
                        )
                        return result
            except Exception as e:
                logger.warning(
                    "ccxt Binance funding history failed for %s: %s", symbol, e
                )

        # httpx fallback for Binance funding history
        result = self._fetch_funding_history_httpx(symbol)
        return result

    def _fetch_funding_history_httpx(self, symbol: str) -> dict:
        """Fallback: fetch funding history from Binance via httpx."""
        binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
        if not binance_sym:
            return {}

        result: dict = {}
        try:
            # Binance fundingRate endpoint returns historical rates with limit
            resp = httpx.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": binance_sym, "limit": 21},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            entries = resp.json()

            if entries:
                rates = [_safe_float(e.get("fundingRate")) for e in entries]
                rates = [r for r in rates if r != 0.0 or len(rates) == len(entries)]

                if rates:
                    result["funding_7d_accumulated"] = sum(rates)
                    result["funding_7d_avg"] = sum(rates) / len(rates)
                    result["funding_7d_count"] = len(rates)
                    result["funding_7d_max"] = max(rates)
                    result["funding_7d_min"] = min(rates)
                    result["funding_annualized"] = (
                        result["funding_7d_avg"] * 3 * 365
                    )
        except Exception as e:
            logger.warning(
                "Binance httpx funding history failed for %s: %s", symbol, e
            )

        return result

    # ── OI change computation ──────────────────────────────────────────

    def _fetch_oi_change(self, symbol: str) -> dict:
        """Fetch OI change over 24h and 7d periods.

        Uses Binance open interest statistics endpoint which provides
        historical OI data.
        """
        binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
        if not binance_sym:
            return {}

        result: dict = {}

        try:
            # Binance open interest statistics (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d)
            # Fetch daily OI for the last 7 days
            resp = httpx.get(
                "https://fapi.binance.com/futures/data/openInterestHist",
                params={"symbol": binance_sym, "period": "1d", "limit": 8},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            entries = resp.json()

            if entries and len(entries) >= 2:
                current_oi = _safe_float(entries[-1].get("sumOpenInterestValue"))
                prev_24h_oi = _safe_float(entries[-2].get("sumOpenInterestValue"))

                if prev_24h_oi > 0:
                    result["oi_24h_change_pct"] = (
                        (current_oi - prev_24h_oi) / prev_24h_oi * 100
                    )

                if len(entries) >= 7:
                    prev_7d_oi = _safe_float(entries[-7].get("sumOpenInterestValue"))
                    if prev_7d_oi > 0:
                        result["oi_7d_change_pct"] = (
                            (current_oi - prev_7d_oi) / prev_7d_oi * 100
                        )

                result["current_oi_usd"] = current_oi

                logger.debug(
                    "%s OI change: 24h=%.2f%%, 7d=%.2f%%",
                    symbol,
                    result.get("oi_24h_change_pct", 0),
                    result.get("oi_7d_change_pct", 0),
                )
        except Exception as e:
            logger.warning("Binance OI history fetch failed for %s: %s", symbol, e)

        return result

    # ── Metadata assembly ──────────────────────────────────────────────

    def _build_metadata(
        self,
        symbol: str,
        ls_data: dict,
        funding_oi_data: dict,
        funding_history: dict,
    ) -> dict:
        """Assemble all collected data into a unified metadata dict."""
        # Fetch OI change separately (uses Binance OI statistics endpoint)
        oi_change = self._fetch_oi_change(symbol)

        metadata: dict = {
            "symbol": symbol,
            "asset_class": "crypto",
            "signal_type": "derivatives_consensus",
            "data_timestamp": datetime.utcnow().isoformat(),
            # Long/short ratios
            "ls_ratio": ls_data.get("global_ls_ratio"),
            "ls_long_pct": ls_data.get("global_long_account"),
            "ls_short_pct": ls_data.get("global_short_account"),
            "ls_ratio_7d_avg": ls_data.get("global_ls_ratio_7d_avg"),
            "top_ls_ratio": ls_data.get("top_ls_ratio"),
            "top_long_pct": ls_data.get("top_long_account"),
            "top_short_pct": ls_data.get("top_short_account"),
            "top_ls_ratio_7d_avg": ls_data.get("top_ls_ratio_7d_avg"),
            # Funding rate (OI-weighted current)
            "funding_rate": funding_oi_data.get("oi_weighted_funding"),
            "funding_rate_simple_avg": funding_oi_data.get("simple_avg_funding"),
            "exchange_count": funding_oi_data.get("exchange_count", 0),
            "total_oi_usd": funding_oi_data.get("total_oi_usd"),
            "oi_shares": funding_oi_data.get("oi_shares", {}),
            # 7-day accumulated funding
            "funding_7d_accumulated": funding_history.get("funding_7d_accumulated"),
            "funding_7d_avg": funding_history.get("funding_7d_avg"),
            "funding_7d_count": funding_history.get("funding_7d_count"),
            "funding_7d_max": funding_history.get("funding_7d_max"),
            "funding_7d_min": funding_history.get("funding_7d_min"),
            "funding_annualized": funding_history.get("funding_annualized"),
            # OI change
            "oi_24h_change_pct": oi_change.get("oi_24h_change_pct"),
            "oi_7d_change_pct": oi_change.get("oi_7d_change_pct"),
            "current_oi_usd": oi_change.get("current_oi_usd"),
        }

        # Clean out None values for cleaner storage
        metadata = {k: v for k, v in metadata.items() if v is not None}

        return metadata

    # ── Signal construction ────────────────────────────────────────────

    def _build_signals(self, symbol: str, metadata: dict) -> list[Signal]:
        """Build Signal objects from collected metadata."""
        signals: list[Signal] = []

        # 1. Long/short ratio signal
        ls_signal = self._build_ls_signal(symbol, metadata)
        if ls_signal:
            signals.append(ls_signal)

        # 2. Top trader long/short signal
        top_ls_signal = self._build_top_ls_signal(symbol, metadata)
        if top_ls_signal:
            signals.append(top_ls_signal)

        # 3. OI-weighted funding rate signal
        funding_signal = self._build_funding_signal(symbol, metadata)
        if funding_signal:
            signals.append(funding_signal)

        # 4. 7-day accumulated funding signal
        acc_funding_signal = self._build_accumulated_funding_signal(symbol, metadata)
        if acc_funding_signal:
            signals.append(acc_funding_signal)

        # 5. OI change signal
        oi_signal = self._build_oi_change_signal(symbol, metadata)
        if oi_signal:
            signals.append(oi_signal)

        # 6. Composite derivatives consensus summary
        summary_signal = self._build_summary_signal(symbol, metadata)
        if summary_signal:
            signals.append(summary_signal)

        return signals

    def _build_ls_signal(self, symbol: str, metadata: dict) -> Signal | None:
        """Build global long/short ratio signal."""
        ratio = metadata.get("ls_ratio")
        if ratio is None:
            return None

        long_pct = metadata.get("ls_long_pct", 0.5)
        short_pct = metadata.get("ls_short_pct", 0.5)

        if ratio > 1.2:
            bias = "CROWDED LONG"
            interpretation = "Retail heavily long — bearish contrarian signal"
        elif ratio > 1.05:
            bias = "MILDLY LONG"
            interpretation = "Retail leaning long — mild bullish consensus"
        elif ratio < 0.8:
            bias = "CROWDED SHORT"
            interpretation = "Retail heavily short — bullish contrarian signal"
        elif ratio < 0.95:
            bias = "MILDLY SHORT"
            interpretation = "Retail leaning short — mild bearish consensus"
        else:
            bias = "NEUTRAL"
            interpretation = "Balanced positioning — no strong retail bias"

        return Signal(
            id=_make_id("deriv_ls", symbol),
            source=SignalSource.DERIVATIVES_CONSENSUS,
            url=f"https://www.binance.com/en/futures/{symbol}USDT",
            title=f"{symbol} global L/S ratio: {ratio:.3f} ({bias})",
            content=(
                f"{symbol} Binance global long/short account ratio: {ratio:.3f} "
                f"(longs {long_pct * 100:.1f}%, shorts {short_pct * 100:.1f}%). "
                f"{interpretation}. "
                f"Ratio >1.2 = crowded longs (bearish contrarian). "
                f"Ratio <0.8 = crowded shorts (bullish contrarian)."
            ),
            metadata=metadata,
        )

    def _build_top_ls_signal(self, symbol: str, metadata: dict) -> Signal | None:
        """Build top trader long/short ratio signal."""
        ratio = metadata.get("top_ls_ratio")
        if ratio is None:
            return None

        long_pct = metadata.get("top_long_pct", 0.5)
        short_pct = metadata.get("top_short_pct", 0.5)

        if ratio > 1.3:
            bias = "STRONGLY LONG"
            interpretation = "Smart money aggressively long — strong bullish consensus"
        elif ratio > 1.1:
            bias = "LONG"
            interpretation = "Smart money leaning long — bullish consensus"
        elif ratio < 0.7:
            bias = "STRONGLY SHORT"
            interpretation = "Smart money aggressively short — strong bearish consensus"
        elif ratio < 0.9:
            bias = "SHORT"
            interpretation = "Smart money leaning short — bearish consensus"
        else:
            bias = "NEUTRAL"
            interpretation = "Smart money balanced — no strong directional view"

        return Signal(
            id=_make_id("deriv_top_ls", symbol),
            source=SignalSource.DERIVATIVES_CONSENSUS,
            url=f"https://www.binance.com/en/futures/{symbol}USDT",
            title=f"{symbol} top trader L/S: {ratio:.3f} ({bias})",
            content=(
                f"{symbol} Binance top trader long/short ratio: {ratio:.3f} "
                f"(longs {long_pct * 100:.1f}%, shorts {short_pct * 100:.1f}%). "
                f"{interpretation}. "
                f"Top trader positioning often diverges from retail — when they disagree, "
                f"top traders tend to be right."
            ),
            metadata=metadata,
        )

    def _build_funding_signal(self, symbol: str, metadata: dict) -> Signal | None:
        """Build OI-weighted funding rate signal."""
        rate = metadata.get("funding_rate")
        if rate is None:
            return None

        rate_pct = rate * 100  # Convert to percentage
        exchange_count = metadata.get("exchange_count", 0)
        total_oi = metadata.get("total_oi_usd", 0)

        if rate_pct > 0.05:
            bias = "EXTREME POSITIVE"
            interpretation = "Extremely crowded longs — high liquidation risk"
        elif rate_pct > 0.03:
            bias = "POSITIVE"
            interpretation = "Longs paying shorts — bullish consensus but crowded"
        elif rate_pct < -0.03:
            bias = "EXTREME NEGATIVE"
            interpretation = "Shorts paying longs — bearish consensus, short squeeze risk"
        elif rate_pct < -0.01:
            bias = "NEGATIVE"
            interpretation = "Shorts slightly crowded — mild short squeeze setup"
        else:
            bias = "NEUTRAL"
            interpretation = "Funding near zero — no strong leveraged consensus"

        oi_str = f"${total_oi / 1e9:.1f}B" if total_oi > 0 else "N/A"

        return Signal(
            id=_make_id("deriv_funding", symbol),
            source=SignalSource.DERIVATIVES_CONSENSUS,
            url=f"https://www.binance.com/en/futures/{symbol}USDT",
            title=f"{symbol} OI-weighted funding: {rate_pct:+.4f}% ({bias})",
            content=(
                f"{symbol} OI-weighted funding rate across {exchange_count} exchanges: "
                f"{rate_pct:+.4f}% (8-hour). "
                f"Total OI: {oi_str}. "
                f"{interpretation}. "
                f"OI-weighted rate removes bias from low-liquidity exchanges "
                f"and reflects the true market-wide consensus rate."
            ),
            metadata=metadata,
        )

    def _build_accumulated_funding_signal(
        self, symbol: str, metadata: dict
    ) -> Signal | None:
        """Build 7-day accumulated funding signal."""
        accumulated = metadata.get("funding_7d_accumulated")
        if accumulated is None:
            return None

        acc_pct = accumulated * 100
        avg_pct = metadata.get("funding_7d_avg", 0) * 100
        count = metadata.get("funding_7d_count", 0)
        annualized = metadata.get("funding_annualized", 0) * 100

        if acc_pct > 0.1:
            bias = "STRONG BULLISH CONSENSUS"
            interpretation = (
                "Longs paid significant premium over 7 days — persistent bullish consensus"
            )
        elif acc_pct > 0.03:
            bias = "MILD BULLISH CONSENSUS"
            interpretation = (
                "Longs paying moderate premium — mild bullish consensus in leveraged markets"
            )
        elif acc_pct < -0.1:
            bias = "STRONG BEARISH CONSENSUS"
            interpretation = (
                "Shorts paid significant premium over 7 days — persistent bearish consensus"
            )
        elif acc_pct < -0.03:
            bias = "MILD BEARISH CONSENSUS"
            interpretation = (
                "Shorts paying moderate premium — mild bearish consensus"
            )
        else:
            bias = "NEUTRAL"
            interpretation = "Funding accumulated near zero — no persistent directional bias"

        return Signal(
            id=_make_id("deriv_funding_7d", symbol),
            source=SignalSource.DERIVATIVES_CONSENSUS,
            url=f"https://www.binance.com/en/futures/{symbol}USDT",
            title=f"{symbol} 7d accumulated funding: {acc_pct:+.4f}% ({bias})",
            content=(
                f"{symbol} accumulated funding over 7 days: {acc_pct:+.4f}% "
                f"({count} settlements, avg {avg_pct:+.4f}% per 8h, "
                f"annualized {annualized:+.1f}%). "
                f"{interpretation}. "
                f"Persistent positive funding means longs have been paying shorts "
                f"consistently — this is the cost of bullish consensus. "
                f"When accumulated funding is extreme, mean reversion typically follows."
            ),
            metadata=metadata,
        )

    def _build_oi_change_signal(self, symbol: str, metadata: dict) -> Signal | None:
        """Build OI change signal (24h + 7d)."""
        oi_24h = metadata.get("oi_24h_change_pct")
        oi_7d = metadata.get("oi_7d_change_pct")

        if oi_24h is None and oi_7d is None:
            return None

        current_oi = metadata.get("current_oi_usd", 0)
        oi_str = f"${current_oi / 1e9:.1f}B" if current_oi > 0 else "N/A"

        parts: list[str] = []
        if oi_24h is not None:
            parts.append(f"24h: {oi_24h:+.1f}%")
        if oi_7d is not None:
            parts.append(f"7d: {oi_7d:+.1f}%")
        change_str = ", ".join(parts)

        # Interpret OI changes
        if oi_7d is not None:
            if oi_7d > 10:
                interpretation = (
                    "Significant new money entering futures — strong conviction, "
                    "watch for direction confirmation"
                )
            elif oi_7d > 3:
                interpretation = (
                    "Moderate OI growth — new positions being built"
                )
            elif oi_7d < -20:
                interpretation = (
                    "OI COLLAPSED — leverage flush/mass liquidation, often marks local bottom"
                )
            elif oi_7d < -5:
                interpretation = "OI declining — deleveraging in progress"
            else:
                interpretation = "OI relatively stable — no major positioning shift"
        elif oi_24h is not None:
            if oi_24h > 5:
                interpretation = "Sharp 24h OI spike — rapid position building"
            elif oi_24h < -10:
                interpretation = "Sharp 24h OI drop — liquidation event"
            else:
                interpretation = "OI stable in last 24h"
        else:
            interpretation = "OI data limited"

        return Signal(
            id=_make_id("deriv_oi_change", symbol),
            source=SignalSource.DERIVATIVES_CONSENSUS,
            url=f"https://www.binance.com/en/futures/{symbol}USDT",
            title=f"{symbol} OI change: {change_str} (OI: {oi_str})",
            content=(
                f"{symbol} open interest change — {change_str}. "
                f"Current OI: {oi_str}. "
                f"{interpretation}. "
                f"Rising OI + rising price = trend confirmation (new longs). "
                f"Rising OI + falling price = bear pressure (new shorts). "
                f"Falling OI = closing positions / deleveraging."
            ),
            metadata=metadata,
        )

    def _build_summary_signal(self, symbol: str, metadata: dict) -> Signal | None:
        """Build composite derivatives consensus summary signal."""
        # Need at least some data to produce a summary
        has_ls = metadata.get("ls_ratio") is not None
        has_funding = metadata.get("funding_rate") is not None
        has_funding_7d = metadata.get("funding_7d_accumulated") is not None
        has_oi = metadata.get("oi_7d_change_pct") is not None

        if not any([has_ls, has_funding, has_funding_7d, has_oi]):
            return None

        # Tally directional signals
        bullish_signals: list[str] = []
        bearish_signals: list[str] = []
        neutral_signals: list[str] = []

        # Global L/S
        ls = metadata.get("ls_ratio")
        if ls is not None:
            if ls > 1.1:
                bullish_signals.append(f"retail long (L/S {ls:.2f})")
            elif ls < 0.9:
                bearish_signals.append(f"retail short (L/S {ls:.2f})")
            else:
                neutral_signals.append(f"retail balanced (L/S {ls:.2f})")

        # Top trader L/S
        top_ls = metadata.get("top_ls_ratio")
        if top_ls is not None:
            if top_ls > 1.1:
                bullish_signals.append(f"top traders long (L/S {top_ls:.2f})")
            elif top_ls < 0.9:
                bearish_signals.append(f"top traders short (L/S {top_ls:.2f})")
            else:
                neutral_signals.append(f"top traders balanced (L/S {top_ls:.2f})")

        # Funding rate
        funding = metadata.get("funding_rate")
        if funding is not None:
            fr_pct = funding * 100
            if fr_pct > 0.01:
                bullish_signals.append(f"positive funding ({fr_pct:+.4f}%)")
            elif fr_pct < -0.01:
                bearish_signals.append(f"negative funding ({fr_pct:+.4f}%)")
            else:
                neutral_signals.append(f"neutral funding ({fr_pct:+.4f}%)")

        # 7-day accumulated funding
        acc = metadata.get("funding_7d_accumulated")
        if acc is not None:
            acc_pct = acc * 100
            if acc_pct > 0.03:
                bullish_signals.append(f"7d funding accumulated positive ({acc_pct:+.4f}%)")
            elif acc_pct < -0.03:
                bearish_signals.append(
                    f"7d funding accumulated negative ({acc_pct:+.4f}%)"
                )

        # Determine overall consensus
        bull_count = len(bullish_signals)
        bear_count = len(bearish_signals)

        if bull_count > bear_count + 1:
            consensus = "BULLISH"
            consensus_detail = "Derivatives markets show bullish consensus"
        elif bear_count > bull_count + 1:
            consensus = "BEARISH"
            consensus_detail = "Derivatives markets show bearish consensus"
        elif bull_count > bear_count:
            consensus = "MILDLY BULLISH"
            consensus_detail = "Derivatives markets lean slightly bullish"
        elif bear_count > bull_count:
            consensus = "MILDLY BEARISH"
            consensus_detail = "Derivatives markets lean slightly bearish"
        else:
            consensus = "MIXED"
            consensus_detail = "Derivatives markets show mixed/neutral positioning"

        # Build detailed content
        signal_parts: list[str] = []
        if bullish_signals:
            signal_parts.append(f"Bullish: {', '.join(bullish_signals)}")
        if bearish_signals:
            signal_parts.append(f"Bearish: {', '.join(bearish_signals)}")
        if neutral_signals:
            signal_parts.append(f"Neutral: {', '.join(neutral_signals)}")
        breakdown = ". ".join(signal_parts)

        return Signal(
            id=_make_id("deriv_consensus", symbol),
            source=SignalSource.DERIVATIVES_CONSENSUS,
            url=f"https://www.binance.com/en/futures/{symbol}USDT",
            title=f"{symbol} derivatives consensus: {consensus}",
            content=(
                f"{symbol} multi-exchange derivatives consensus: {consensus}. "
                f"{consensus_detail}. "
                f"Breakdown — {breakdown}. "
                f"This aggregates Binance L/S ratios, OI-weighted funding from "
                f"{metadata.get('exchange_count', 0)} exchanges, "
                f"and 7-day accumulated funding to measure the leveraged market's "
                f"directional consensus."
            ),
            metadata=metadata,
        )
