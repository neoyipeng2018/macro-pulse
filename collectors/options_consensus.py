"""Options consensus collector — Deribit public API.

Fetches options market data from Deribit's public (no-auth) API for BTC and ETH
to derive quantitative consensus signals:

1. 25-delta risk reversal (skew): calls vs puts pricing imbalance
2. Put/Call OI ratio: aggregate positioning bias
3. Max pain (nearest weekly expiry): expected settlement price
4. DVOL (Deribit Volatility Index): implied vol regime
5. IV term structure slope: near-term vs far-term vol expectations

All metrics are stored as raw values in signal metadata for downstream
consensus scoring. Signals use SignalSource.OPTIONS.
"""

import hashlib
import logging
import math
import re
from datetime import datetime, timezone

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.deribit.com/api/v2/public"

_SYMBOLS = ["BTC", "ETH"]

# Deribit instrument naming: e.g. "BTC-28MAR25-90000-C"
# Pattern: CURRENCY-DDMMMYY-STRIKE-TYPE
_INSTRUMENT_RE = re.compile(
    r"^(BTC|ETH)-(\d{1,2}[A-Z]{3}\d{2})-(\d+)-(C|P)$"
)

# How many milliseconds in a day
_MS_PER_DAY = 86_400_000

# Thresholds for interpreting signals
_PCR_BULLISH = 0.7
_PCR_BEARISH = 1.0

# HTTP client config
_TIMEOUT = 20
_MAX_RETRIES = 2


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _parse_expiry_date(date_str: str) -> datetime | None:
    """Parse Deribit expiry string like '28MAR25' to datetime."""
    try:
        return datetime.strptime(date_str, "%d%b%y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_price(price: float) -> str:
    """Format price with appropriate precision and comma separators."""
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:,.2f}"
    return f"${price:.4f}"


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if val is None:
        return default
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


class OptionsConsensusCollector(BaseCollector):
    """Collect options consensus data from Deribit public API."""

    source_name = "options"

    def __init__(self):
        self.symbols = list(_SYMBOLS)
        self._client = httpx.Client(timeout=_TIMEOUT)

    def collect(self) -> list[Signal]:
        """Fetch options data for BTC and ETH, derive consensus signals."""
        all_signals: list[Signal] = []

        for symbol in self.symbols:
            try:
                signals = self._collect_symbol(symbol)
                all_signals.extend(signals)
            except Exception as e:
                logger.warning("Options collector failed for %s: %s", symbol, e)

        try:
            self._client.close()
        except Exception:
            pass

        return all_signals

    def _collect_symbol(self, symbol: str) -> list[Signal]:
        """Collect all options metrics for a single symbol."""
        signals: list[Signal] = []

        # Step 1: Get book summaries for all options on this currency.
        # This gives us OI, mark price, mark IV, and delta for each instrument.
        book_summaries = self._fetch_book_summaries(symbol)
        if not book_summaries:
            logger.warning("No book summaries returned for %s options", symbol)
            return signals

        # Step 2: Get available instruments to find the nearest weekly expiry.
        instruments = self._fetch_instruments(symbol)
        if not instruments:
            logger.warning("No instruments returned for %s", symbol)
            return signals

        # Step 3: Identify nearest weekly expiry (within 2-9 days).
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        weekly_expiry_ms = self._find_nearest_weekly_expiry(instruments, now_ms)
        if weekly_expiry_ms is None:
            logger.warning("No suitable weekly expiry found for %s", symbol)
            # Fall back: use the nearest expiry beyond 12 hours from now
            weekly_expiry_ms = self._find_nearest_any_expiry(instruments, now_ms)
            if weekly_expiry_ms is None:
                return signals

        expiry_dt = datetime.fromtimestamp(weekly_expiry_ms / 1000, tz=timezone.utc)
        expiry_label = expiry_dt.strftime("%d%b%y").upper()
        days_to_expiry = (weekly_expiry_ms - now_ms) / _MS_PER_DAY

        # Step 4: Get current underlying price from the index.
        underlying_price = self._get_underlying_price(symbol, book_summaries)
        if underlying_price <= 0:
            logger.warning("Could not determine underlying price for %s", symbol)
            return signals

        # Step 5: Filter book summaries to the target expiry.
        expiry_books = self._filter_to_expiry(book_summaries, expiry_label)
        if not expiry_books:
            logger.warning(
                "No book summaries found for %s expiry %s", symbol, expiry_label
            )
            return signals

        # Step 6: Compute each metric.

        # 6a: 25-delta risk reversal (skew)
        skew = self._compute_25d_skew(expiry_books, symbol)
        if skew is not None:
            signals.append(self._build_skew_signal(symbol, skew, expiry_label))

        # 6b: Put/Call OI ratio
        pcr = self._compute_put_call_ratio(expiry_books)
        if pcr is not None:
            signals.append(
                self._build_pcr_signal(symbol, pcr, expiry_label)
            )

        # 6c: Max pain
        max_pain = self._compute_max_pain(expiry_books)
        if max_pain is not None and underlying_price > 0:
            signals.append(
                self._build_max_pain_signal(
                    symbol, max_pain, underlying_price, expiry_label
                )
            )

        # 6d: DVOL
        dvol = self._fetch_dvol(symbol)
        if dvol is not None:
            signals.append(self._build_dvol_signal(symbol, dvol))

        # 6e: IV term structure slope
        iv_slope = self._compute_iv_term_structure(book_summaries, symbol, now_ms)
        if iv_slope is not None:
            signals.append(
                self._build_iv_slope_signal(symbol, iv_slope, days_to_expiry)
            )

        # 6f: Composite summary signal with all metadata for consensus scorer
        signals.append(
            self._build_composite_signal(
                symbol=symbol,
                skew=skew,
                pcr=pcr,
                max_pain=max_pain,
                underlying_price=underlying_price,
                dvol=dvol,
                iv_slope=iv_slope,
                expiry_label=expiry_label,
                days_to_expiry=days_to_expiry,
            )
        )

        return signals

    # ── API fetch methods ──────────────────────────────────────────────

    def _api_get(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Make a GET request to Deribit public API with retry logic."""
        url = f"{_BASE_URL}/{endpoint}"
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._client.get(url, params=params or {})
                resp.raise_for_status()
                data = resp.json()
                # Deribit wraps results in {"jsonrpc": "2.0", "result": ...}
                if "result" in data:
                    return data["result"]
                # Some endpoints return data directly
                return data
            except httpx.HTTPStatusError as e:
                logger.debug(
                    "Deribit API HTTP error (attempt %d): %s %s",
                    attempt + 1, e.response.status_code, endpoint,
                )
                if attempt == _MAX_RETRIES:
                    raise
            except httpx.RequestError as e:
                logger.debug(
                    "Deribit API request error (attempt %d): %s", attempt + 1, e
                )
                if attempt == _MAX_RETRIES:
                    raise
        return None

    def _fetch_book_summaries(self, symbol: str) -> list[dict]:
        """Fetch book summaries for all options on a currency."""
        try:
            result = self._api_get(
                "get_book_summary_by_currency",
                {"currency": symbol, "kind": "option"},
            )
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.warning("Failed to fetch book summaries for %s: %s", symbol, e)
            return []

    def _fetch_instruments(self, symbol: str) -> list[dict]:
        """Fetch available option instruments for a currency."""
        try:
            result = self._api_get(
                "get_instruments",
                {"currency": symbol, "kind": "option", "expired": "false"},
            )
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.warning("Failed to fetch instruments for %s: %s", symbol, e)
            return []

    def _fetch_dvol(self, symbol: str) -> float | None:
        """Fetch the DVOL (Deribit Volatility Index) for a symbol.

        Uses the volatility index data endpoint, requesting a short recent window
        and extracting the latest close value.
        """
        index_name = f"{symbol.lower()}_vol"  # e.g. "btc_vol" or "eth_vol"
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # Request last 2 hours of data with 1-hour resolution
        start_ms = now_ms - 2 * 3_600_000

        try:
            result = self._api_get(
                "get_volatility_index_data",
                {
                    "currency": symbol,
                    "start_timestamp": start_ms,
                    "end_timestamp": now_ms,
                    "resolution": "3600",  # 1 hour candles
                },
            )
            if not result:
                return None

            # Result may be a dict with "data" key or a list directly
            data = result
            if isinstance(result, dict):
                data = result.get("data", [])
                if not data:
                    # Try "continuation" key format
                    data = result.get("continuation", [])

            if not data:
                return None

            # Each entry: [timestamp, open, high, low, close]
            # Take the most recent close value
            if isinstance(data, list) and len(data) > 0:
                last_entry = data[-1]
                if isinstance(last_entry, list) and len(last_entry) >= 5:
                    return _safe_float(last_entry[4])
                elif isinstance(last_entry, dict):
                    return _safe_float(last_entry.get("close"))

            return None
        except Exception as e:
            logger.debug("DVOL fetch failed for %s: %s", symbol, e)
            return None

    # ── Expiry selection ───────────────────────────────────────────────

    def _find_nearest_weekly_expiry(
        self, instruments: list[dict], now_ms: int
    ) -> int | None:
        """Find the nearest weekly expiry between 12 hours and 9 days from now.

        Deribit has daily, weekly, monthly, and quarterly expiries.
        We target the nearest one that falls within our 1-week horizon window.
        """
        min_ms = now_ms + 12 * 3_600_000  # at least 12 hours out
        max_ms = now_ms + 9 * _MS_PER_DAY  # at most 9 days out

        expiries = set()
        for inst in instruments:
            exp_ts = inst.get("expiration_timestamp")
            if exp_ts and min_ms <= exp_ts <= max_ms:
                expiries.add(exp_ts)

        if not expiries:
            return None

        # Return the nearest one
        return min(expiries)

    def _find_nearest_any_expiry(
        self, instruments: list[dict], now_ms: int
    ) -> int | None:
        """Fallback: find the nearest expiry beyond 12 hours."""
        min_ms = now_ms + 12 * 3_600_000
        expiries = set()
        for inst in instruments:
            exp_ts = inst.get("expiration_timestamp")
            if exp_ts and exp_ts > min_ms:
                expiries.add(exp_ts)

        if not expiries:
            return None
        return min(expiries)

    # ── Data filtering & extraction ────────────────────────────────────

    def _filter_to_expiry(
        self, book_summaries: list[dict], expiry_label: str
    ) -> list[dict]:
        """Filter book summaries to a specific expiry date string."""
        filtered = []
        for book in book_summaries:
            inst_name = book.get("instrument_name", "")
            match = _INSTRUMENT_RE.match(inst_name)
            if match and match.group(2) == expiry_label:
                filtered.append(book)
        return filtered

    def _get_underlying_price(
        self, symbol: str, book_summaries: list[dict]
    ) -> float:
        """Extract the underlying price from book summary data.

        Deribit book summaries include 'underlying_price' field.
        We take the median of available values to be robust against outliers.
        """
        prices = []
        for book in book_summaries:
            up = book.get("underlying_price")
            if up is not None:
                p = _safe_float(up)
                if p > 0:
                    prices.append(p)

        if not prices:
            return 0.0

        prices.sort()
        mid = len(prices) // 2
        return prices[mid]

    # ── Metric computations ────────────────────────────────────────────

    def _compute_25d_skew(
        self, expiry_books: list[dict], symbol: str
    ) -> float | None:
        """Compute 25-delta risk reversal: IV(25d call) - IV(25d put).

        Positive skew = calls more expensive = bullish consensus.
        Negative skew = puts more expensive = bearish consensus.

        Strategy: find the options closest to 25-delta on each side,
        then compare their implied volatilities.
        """
        calls = []
        puts = []

        for book in expiry_books:
            inst_name = book.get("instrument_name", "")
            match = _INSTRUMENT_RE.match(inst_name)
            if not match:
                continue

            option_type = match.group(4)
            mark_iv = book.get("mark_iv")
            if mark_iv is None:
                # Some entries may use 'interest_rate' or lack IV data
                continue

            iv = _safe_float(mark_iv)
            if iv <= 0:
                continue

            # Deribit provides Greeks in book summaries under 'greeks'
            greeks = book.get("greeks", {})
            delta = _safe_float(greeks.get("delta")) if greeks else None

            # Also try 'mid_price' and compute approximate moneyness
            strike = _safe_float(match.group(3))
            underlying = _safe_float(book.get("underlying_price"))
            oi = _safe_float(book.get("open_interest"))

            entry = {
                "instrument": inst_name,
                "iv": iv,
                "delta": delta,
                "strike": strike,
                "underlying": underlying,
                "oi": oi,
            }

            if option_type == "C":
                calls.append(entry)
            else:
                puts.append(entry)

        if not calls or not puts:
            return None

        # Strategy 1: Use actual delta values if available
        call_25d = self._find_nearest_delta(calls, target=0.25)
        put_25d = self._find_nearest_delta(puts, target=-0.25)

        if call_25d is not None and put_25d is not None:
            return call_25d["iv"] - put_25d["iv"]

        # Strategy 2: Approximate using moneyness (OTM ~25 delta is roughly
        # 5-10% OTM for weeklies depending on IV). Use strikes that are
        # moderately OTM on each side.
        call_25d_approx = self._find_25d_by_moneyness(calls, is_call=True)
        put_25d_approx = self._find_25d_by_moneyness(puts, is_call=False)

        if call_25d_approx is not None and put_25d_approx is not None:
            return call_25d_approx["iv"] - put_25d_approx["iv"]

        return None

    def _find_nearest_delta(
        self, options: list[dict], target: float
    ) -> dict | None:
        """Find the option nearest to a target delta value."""
        candidates = [o for o in options if o["delta"] is not None]
        if not candidates:
            return None

        return min(candidates, key=lambda o: abs(o["delta"] - target))

    def _find_25d_by_moneyness(
        self, options: list[dict], is_call: bool
    ) -> dict | None:
        """Approximate 25-delta option by moneyness (~5-15% OTM).

        For calls: strike > underlying by 5-15%.
        For puts: strike < underlying by 5-15%.
        """
        candidates = []
        for o in options:
            if o["strike"] <= 0 or o["underlying"] <= 0:
                continue
            moneyness = (o["strike"] - o["underlying"]) / o["underlying"]
            if is_call:
                # OTM call: strike above spot
                if 0.03 <= moneyness <= 0.20:
                    candidates.append((abs(moneyness - 0.08), o))
            else:
                # OTM put: strike below spot
                if -0.20 <= moneyness <= -0.03:
                    candidates.append((abs(moneyness + 0.08), o))

        if not candidates:
            return None

        # Pick the one closest to ~8% OTM (typical ~25 delta for weeklies)
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _compute_put_call_ratio(self, expiry_books: list[dict]) -> float | None:
        """Compute put/call open interest ratio at the target expiry.

        PCR < 0.7 = call-dominated = bullish consensus.
        PCR > 1.0 = put-dominated = bearish consensus.
        """
        call_oi = 0.0
        put_oi = 0.0

        for book in expiry_books:
            inst_name = book.get("instrument_name", "")
            match = _INSTRUMENT_RE.match(inst_name)
            if not match:
                continue

            option_type = match.group(4)
            oi = _safe_float(book.get("open_interest"))

            if option_type == "C":
                call_oi += oi
            else:
                put_oi += oi

        if call_oi <= 0:
            return None

        return put_oi / call_oi

    def _compute_max_pain(self, expiry_books: list[dict]) -> float | None:
        """Compute max pain: the strike where total option holder loss is maximized.

        At max pain, the sum of (in-the-money value * OI) across all options is
        minimized. This is the price where option writers collectively keep
        the most premium.
        """
        # Collect OI by strike and type
        strike_data: dict[float, dict[str, float]] = {}

        for book in expiry_books:
            inst_name = book.get("instrument_name", "")
            match = _INSTRUMENT_RE.match(inst_name)
            if not match:
                continue

            strike = _safe_float(match.group(3))
            option_type = match.group(4)
            oi = _safe_float(book.get("open_interest"))

            if strike <= 0 or oi <= 0:
                continue

            if strike not in strike_data:
                strike_data[strike] = {"call_oi": 0.0, "put_oi": 0.0}

            if option_type == "C":
                strike_data[strike]["call_oi"] += oi
            else:
                strike_data[strike]["put_oi"] += oi

        if len(strike_data) < 3:
            return None

        strikes = sorted(strike_data.keys())

        # For each candidate settlement price, compute total intrinsic value
        # that option holders would receive. Max pain is where this is minimized.
        min_pain = float("inf")
        max_pain_strike = strikes[0]

        for settlement in strikes:
            total_pain = 0.0
            for strike, data in strike_data.items():
                # Call holders' gain: max(0, settlement - strike) * call_oi
                if settlement > strike:
                    total_pain += (settlement - strike) * data["call_oi"]
                # Put holders' gain: max(0, strike - settlement) * put_oi
                if settlement < strike:
                    total_pain += (strike - settlement) * data["put_oi"]

            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = settlement

        return max_pain_strike

    def _compute_iv_term_structure(
        self, book_summaries: list[dict], symbol: str, now_ms: int
    ) -> float | None:
        """Compute IV term structure slope: near-term ATM IV vs far-term ATM IV.

        A negative slope (backwardation) means near-term IV > far-term IV,
        indicating the market expects a significant move THIS week.
        A positive slope (contango) means the market is calm near-term.

        Returns: (far_term_iv - near_term_iv) / near_term_iv
        Negative = backwardation (expects move), Positive = contango (calm).
        """
        # Group ATM options by expiry
        expiry_ivs: dict[int, list[float]] = {}

        for book in book_summaries:
            inst_name = book.get("instrument_name", "")
            match = _INSTRUMENT_RE.match(inst_name)
            if not match:
                continue

            strike = _safe_float(match.group(3))
            underlying = _safe_float(book.get("underlying_price"))
            mark_iv = _safe_float(book.get("mark_iv"))

            if strike <= 0 or underlying <= 0 or mark_iv <= 0:
                continue

            # Consider "ATM" as within 3% of underlying
            moneyness = abs(strike - underlying) / underlying
            if moneyness > 0.03:
                continue

            # Find this instrument's expiry timestamp
            expiry_str = match.group(2)
            exp_dt = _parse_expiry_date(expiry_str)
            if exp_dt is None:
                continue
            exp_ms = int(exp_dt.timestamp() * 1000)

            if exp_ms <= now_ms:
                continue

            if exp_ms not in expiry_ivs:
                expiry_ivs[exp_ms] = []
            expiry_ivs[exp_ms].append(mark_iv)

        if len(expiry_ivs) < 2:
            return None

        # Sort expiries by time
        sorted_expiries = sorted(expiry_ivs.keys())

        # Near-term: closest expiry at least 12 hours out
        min_near = now_ms + 12 * 3_600_000
        near_expiries = [e for e in sorted_expiries if e >= min_near]
        if not near_expiries:
            return None

        near_exp = near_expiries[0]

        # Far-term: expiry at least 14 days out
        min_far = now_ms + 14 * _MS_PER_DAY
        far_expiries = [e for e in sorted_expiries if e >= min_far]
        if not far_expiries:
            # If no expiry 14+ days out, use the furthest available
            if sorted_expiries[-1] != near_exp:
                far_exp = sorted_expiries[-1]
            else:
                return None
        else:
            far_exp = far_expiries[0]

        near_iv = sum(expiry_ivs[near_exp]) / len(expiry_ivs[near_exp])
        far_iv = sum(expiry_ivs[far_exp]) / len(expiry_ivs[far_exp])

        if near_iv <= 0:
            return None

        return (far_iv - near_iv) / near_iv

    # ── Signal builders ────────────────────────────────────────────────

    def _build_skew_signal(
        self, symbol: str, skew: float, expiry: str
    ) -> Signal:
        """Build signal for 25-delta risk reversal (skew)."""
        if skew > 2.0:
            interpretation = "calls favored — bullish consensus"
        elif skew > 0:
            interpretation = "slight call premium — mildly bullish"
        elif skew > -2.0:
            interpretation = "slight put premium — mildly bearish"
        else:
            interpretation = "puts favored — bearish consensus"

        return Signal(
            id=_make_id("options_skew", symbol),
            source=SignalSource.OPTIONS,
            url=f"https://www.deribit.com/options/{symbol}",
            title=f"{symbol} options skew: {skew:+.2f} ({interpretation} at {expiry} expiry)",
            content=(
                f"{symbol} 25-delta risk reversal is {skew:+.2f}% at the "
                f"{expiry} weekly expiry. {interpretation}. "
                f"Positive skew = calls more expensive than puts = bullish consensus. "
                f"Negative skew = puts more expensive = bearish consensus. "
                f"The 25-delta risk reversal is the single best options-derived "
                f"consensus thermometer."
            ),
            metadata={
                "symbol": symbol,
                "options_skew_25d": round(skew, 4),
                "expiry": expiry,
                "signal_type": "options_skew",
                "asset_class": "crypto",
            },
        )

    def _build_pcr_signal(
        self, symbol: str, pcr: float, expiry: str
    ) -> Signal:
        """Build signal for put/call OI ratio."""
        if pcr < _PCR_BULLISH:
            interpretation = "call-dominated — bullish positioning"
        elif pcr > _PCR_BEARISH:
            interpretation = "put-dominated — bearish positioning"
        else:
            interpretation = "balanced — neutral positioning"

        return Signal(
            id=_make_id("options_pcr", symbol),
            source=SignalSource.OPTIONS,
            url=f"https://www.deribit.com/options/{symbol}",
            title=f"{symbol} put/call OI ratio: {pcr:.2f} ({interpretation})",
            content=(
                f"{symbol} put/call open interest ratio is {pcr:.2f} at the "
                f"{expiry} weekly expiry. {interpretation}. "
                f"PCR below 0.7 = call-dominated = bullish consensus. "
                f"PCR above 1.0 = put-dominated = bearish consensus."
            ),
            metadata={
                "symbol": symbol,
                "put_call_ratio": round(pcr, 4),
                "expiry": expiry,
                "signal_type": "put_call_ratio",
                "asset_class": "crypto",
            },
        )

    def _build_max_pain_signal(
        self, symbol: str, max_pain: float, current_price: float, expiry: str
    ) -> Signal:
        """Build signal for max pain level."""
        distance_pct = (current_price - max_pain) / max_pain * 100

        if distance_pct > 3:
            interpretation = f"current price {distance_pct:.1f}% above max pain — gravitational pull downward"
        elif distance_pct < -3:
            interpretation = f"current price {abs(distance_pct):.1f}% below max pain — gravitational pull upward"
        else:
            interpretation = f"current price near max pain — neutral magnet effect"

        return Signal(
            id=_make_id("options_maxpain", symbol),
            source=SignalSource.OPTIONS,
            url=f"https://www.deribit.com/options/{symbol}",
            title=f"{symbol} max pain: {_format_price(max_pain)} (current price {distance_pct:+.1f}% away)",
            content=(
                f"{symbol} max pain for {expiry} expiry is {_format_price(max_pain)}. "
                f"Current price: {_format_price(current_price)}. "
                f"{interpretation}. "
                f"Max pain is the strike where option writers keep the most premium. "
                f"Price tends to gravitate toward max pain as expiry approaches."
            ),
            metadata={
                "symbol": symbol,
                "max_pain": round(max_pain, 2),
                "underlying_price": round(current_price, 2),
                "max_pain_distance_pct": round(distance_pct, 4),
                "expiry": expiry,
                "signal_type": "max_pain",
                "asset_class": "crypto",
            },
        )

    def _build_dvol_signal(self, symbol: str, dvol: float) -> Signal:
        """Build signal for DVOL (Deribit Volatility Index)."""
        if dvol > 80:
            interpretation = "very high — extreme uncertainty / fear"
        elif dvol > 60:
            interpretation = "elevated — significant uncertainty"
        elif dvol > 40:
            interpretation = "moderate — normal market conditions"
        else:
            interpretation = "low — complacency / calm market"

        return Signal(
            id=_make_id("options_dvol", symbol),
            source=SignalSource.OPTIONS,
            url=f"https://www.deribit.com/options/{symbol}",
            title=f"{symbol} DVOL: {dvol:.1f} ({interpretation})",
            content=(
                f"{symbol} Deribit Volatility Index (DVOL) is {dvol:.1f}. "
                f"{interpretation}. "
                f"DVOL measures 30-day expected annualized volatility from options prices. "
                f"High DVOL alone is not directional, but DVOL spike combined with "
                f"negative skew = bearish consensus with conviction. "
                f"DVOL spike with positive skew = bullish consensus with conviction."
            ),
            metadata={
                "symbol": symbol,
                "dvol": round(dvol, 2),
                "signal_type": "dvol",
                "asset_class": "crypto",
            },
        )

    def _build_iv_slope_signal(
        self, symbol: str, slope: float, days_to_expiry: float
    ) -> Signal:
        """Build signal for IV term structure slope."""
        if slope < -0.05:
            structure = "backwardation"
            interpretation = "near-term IV elevated — market expects move this week"
        elif slope > 0.05:
            structure = "contango"
            interpretation = "far-term IV higher — calm near-term consensus"
        else:
            structure = "flat"
            interpretation = "term structure flat — no strong timing signal"

        slope_pct = slope * 100

        return Signal(
            id=_make_id("options_iv_slope", symbol),
            source=SignalSource.OPTIONS,
            url=f"https://www.deribit.com/options/{symbol}",
            title=f"{symbol} IV term structure: {structure} ({slope_pct:+.1f}%)",
            content=(
                f"{symbol} IV term structure slope is {slope_pct:+.1f}% "
                f"(far-term ATM IV vs near-term ATM IV). "
                f"Structure: {structure}. {interpretation}. "
                f"Weekly expiry in {days_to_expiry:.1f} days. "
                f"Backwardation (negative slope) = market pricing a near-term event. "
                f"Contango (positive slope) = market expects calm week."
            ),
            metadata={
                "symbol": symbol,
                "iv_term_slope": round(slope, 6),
                "iv_structure": structure,
                "days_to_expiry": round(days_to_expiry, 2),
                "signal_type": "iv_term_structure",
                "asset_class": "crypto",
            },
        )

    def _build_composite_signal(
        self,
        symbol: str,
        skew: float | None,
        pcr: float | None,
        max_pain: float | None,
        underlying_price: float,
        dvol: float | None,
        iv_slope: float | None,
        expiry_label: str,
        days_to_expiry: float,
    ) -> Signal:
        """Build a composite summary signal with all raw values in metadata.

        This signal aggregates all options metrics for consumption by the
        consensus scorer. The individual signals above provide human-readable
        narratives; this one stores machine-readable values.
        """
        # Derive an overall options consensus interpretation
        bullish_factors = []
        bearish_factors = []

        if skew is not None:
            if skew > 1.0:
                bullish_factors.append(f"positive skew ({skew:+.2f})")
            elif skew < -1.0:
                bearish_factors.append(f"negative skew ({skew:+.2f})")

        if pcr is not None:
            if pcr < _PCR_BULLISH:
                bullish_factors.append(f"low PCR ({pcr:.2f})")
            elif pcr > _PCR_BEARISH:
                bearish_factors.append(f"high PCR ({pcr:.2f})")

        if max_pain is not None and underlying_price > 0:
            dist = (underlying_price - max_pain) / max_pain * 100
            if dist < -3:
                bullish_factors.append(f"below max pain ({dist:+.1f}%)")
            elif dist > 3:
                bearish_factors.append(f"above max pain ({dist:+.1f}%)")

        n_bull = len(bullish_factors)
        n_bear = len(bearish_factors)

        if n_bull > n_bear:
            overall = "bullish consensus"
        elif n_bear > n_bull:
            overall = "bearish consensus"
        else:
            overall = "mixed/neutral consensus"

        factors_desc = []
        if bullish_factors:
            factors_desc.append(f"Bullish: {', '.join(bullish_factors)}")
        if bearish_factors:
            factors_desc.append(f"Bearish: {', '.join(bearish_factors)}")
        factors_str = ". ".join(factors_desc) if factors_desc else "Insufficient data"

        # Compute max pain distance for metadata
        max_pain_dist_pct = 0.0
        if max_pain is not None and max_pain > 0:
            max_pain_dist_pct = (underlying_price - max_pain) / max_pain * 100

        # Build content string with conditional metric details
        content_parts = [
            f"{symbol} options market composite for {expiry_label} expiry "
            f"({days_to_expiry:.1f} days out): {overall}. "
            f"{factors_str}.",
        ]
        if skew is not None:
            content_parts.append(f"Skew: {skew:+.2f}.")
        if pcr is not None:
            content_parts.append(f"PCR: {pcr:.2f}.")
        if max_pain is not None:
            content_parts.append(f"Max pain: {_format_price(max_pain)}.")
        if dvol is not None:
            content_parts.append(f"DVOL: {dvol:.1f}.")

        return Signal(
            id=_make_id("options_composite", symbol),
            source=SignalSource.OPTIONS,
            url=f"https://www.deribit.com/options/{symbol}",
            title=f"{symbol} options consensus: {overall} ({expiry_label} expiry)",
            content=" ".join(content_parts),
            metadata={
                "symbol": symbol,
                "signal_type": "options_composite",
                "asset_class": "crypto",
                "expiry": expiry_label,
                "days_to_expiry": round(days_to_expiry, 2),
                "underlying_price": round(underlying_price, 2),
                # Raw consensus component values for the consensus scorer
                "options_skew_25d": round(skew, 4) if skew is not None else None,
                "put_call_ratio": round(pcr, 4) if pcr is not None else None,
                "max_pain": round(max_pain, 2) if max_pain is not None else None,
                "max_pain_distance_pct": round(max_pain_dist_pct, 4),
                "dvol": round(dvol, 2) if dvol is not None else None,
                "iv_term_slope": round(iv_slope, 6) if iv_slope is not None else None,
                # Derived interpretation
                "overall_consensus": overall,
                "bullish_factor_count": n_bull,
                "bearish_factor_count": n_bear,
            },
        )
