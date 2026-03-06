"""BTC and ETH spot-ETF flow collector.

Primary source: SoSoValue API (free tier).
Fallback: neutral stub signals so the consensus scorer can handle missing data
gracefully.

Signals emitted:
  - BTC daily net ETF flow (total across all funds)
  - BTC 5-day rolling net flow
  - IBIT (BlackRock) daily flow — institutional bellwether
  - ETH daily net ETF flow
  - ETH 5-day rolling net flow
"""

import hashlib
import logging
from datetime import datetime

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

# SoSoValue base URLs — try both known domains
_SOSOVALUE_BASES = [
    "https://api.sosovalue.com",
    "https://api.sosovalue.xyz",
]

# Endpoint paths (best-effort; may change without notice)
_BTC_FLOWS_PATH = "/api/v1/etf/bitcoin/fund-flows"
_ETH_FLOWS_PATH = "/api/v1/etf/ethereum/fund-flows"

_REQUEST_TIMEOUT = 15  # seconds


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _interpret_flow(daily_flow: float, rolling_5d: float) -> str:
    """Produce a human-readable interpretation of ETF flow data."""
    if daily_flow > 200:
        daily_label = "STRONG inflows"
    elif daily_flow > 50:
        daily_label = "Moderate inflows"
    elif daily_flow > 0:
        daily_label = "Mild inflows"
    elif daily_flow > -50:
        daily_label = "Mild outflows"
    elif daily_flow > -200:
        daily_label = "Moderate outflows"
    else:
        daily_label = "STRONG outflows"

    if rolling_5d > 500:
        trend = "sustained buying pressure — bullish"
    elif rolling_5d > 0:
        trend = "net positive over 5 days — mildly bullish"
    elif rolling_5d > -500:
        trend = "net negative over 5 days — mildly bearish"
    else:
        trend = "sustained selling pressure — bearish"

    return f"{daily_label} today; 5-day rolling {trend}"


def _interpret_ibit(ibit_flow: float) -> str:
    """Interpret IBIT-specific flow as an institutional signal."""
    if ibit_flow > 100:
        return "Strong IBIT inflows — institutional demand accelerating"
    if ibit_flow > 0:
        return "Positive IBIT flow — steady institutional accumulation"
    if ibit_flow > -50:
        return "Flat/mild IBIT outflows — institutional demand pausing"
    return "Significant IBIT outflows — institutional selling pressure"


class ETFFlowsCollector(BaseCollector):
    """Collect BTC and ETH spot-ETF flow data."""

    source_name = "etf_flows"

    def collect(self) -> list[Signal]:
        signals = self._collect_sosovalue()
        if not signals:
            logger.info(
                "SoSoValue API unavailable, returning neutral ETF flow stubs"
            )
            signals = self._fallback_neutral()
        return signals

    # ------------------------------------------------------------------
    # Primary: SoSoValue API
    # ------------------------------------------------------------------

    def _collect_sosovalue(self) -> list[Signal]:
        """Try SoSoValue API across known base URLs."""
        btc_data = self._fetch_sosovalue(_BTC_FLOWS_PATH)
        eth_data = self._fetch_sosovalue(_ETH_FLOWS_PATH)

        if btc_data is None and eth_data is None:
            return []

        signals: list[Signal] = []

        if btc_data is not None:
            signals.extend(self._parse_btc_flows(btc_data))

        if eth_data is not None:
            signals.extend(self._parse_eth_flows(eth_data))

        return signals

    def _fetch_sosovalue(self, path: str) -> dict | None:
        """Attempt to fetch from SoSoValue, trying each base URL."""
        for base in _SOSOVALUE_BASES:
            url = f"{base}{path}"
            try:
                resp = httpx.get(url, timeout=_REQUEST_TIMEOUT, follow_redirects=True)
                resp.raise_for_status()
                data = resp.json()
                # Accept any response that looks like valid JSON with data
                if isinstance(data, dict) and data.get("data") is not None:
                    logger.debug("SoSoValue responded from %s", base)
                    return data
                if isinstance(data, list) and len(data) > 0:
                    return {"data": data}
            except httpx.HTTPStatusError as e:
                logger.debug(
                    "SoSoValue %s returned HTTP %s", url, e.response.status_code
                )
            except Exception as e:
                logger.debug("SoSoValue fetch %s failed: %s", url, e)
        return None

    # ------------------------------------------------------------------
    # Parsers — adapt to whatever shape SoSoValue returns
    # ------------------------------------------------------------------

    def _parse_btc_flows(self, raw: dict) -> list[Signal]:
        """Parse BTC ETF flow data from SoSoValue response."""
        signals: list[Signal] = []
        data = raw.get("data", raw)

        try:
            # Attempt to extract aggregate daily flow
            daily_flow = self._extract_field(data, [
                "totalNetFlow", "netFlow", "daily_net_flow", "total_flow",
            ])
            rolling_5d = self._extract_field(data, [
                "fiveDayNetFlow", "rolling5d", "5d_net_flow", "weekly_flow",
            ])
            ibit_flow = self._extract_ibit_flow(data)

            if daily_flow is None:
                daily_flow = 0.0
            if rolling_5d is None:
                rolling_5d = 0.0
            if ibit_flow is None:
                ibit_flow = 0.0

            interpretation = _interpret_flow(daily_flow, rolling_5d)
            ibit_interpretation = _interpret_ibit(ibit_flow)

            # Main BTC ETF flow signal
            signals.append(
                Signal(
                    id=_make_id("etf_btc_flow"),
                    source=SignalSource.ETF_FLOWS,
                    url="https://sosovalue.com/assets/etf/us-btc-spot",
                    title=(
                        f"BTC ETF flows: ${daily_flow:+.1f}M daily, "
                        f"${rolling_5d:+.1f}M 5-day rolling"
                    ),
                    content=(
                        f"BTC spot-ETF net daily flow: ${daily_flow:+.1f}M. "
                        f"5-day rolling net flow: ${rolling_5d:+.1f}M. "
                        f"IBIT (BlackRock) daily flow: ${ibit_flow:+.1f}M. "
                        f"Interpretation: {interpretation}. "
                        f"IBIT: {ibit_interpretation}. "
                        f"Sustained ETF inflows signal institutional demand — bullish. "
                        f"Persistent outflows signal institutional distribution — bearish."
                    ),
                    metadata={
                        "btc_daily_flow_usd": round(daily_flow, 2),
                        "btc_5d_rolling_flow_usd": round(rolling_5d, 2),
                        "ibit_daily_flow_usd": round(ibit_flow, 2),
                        "data_available": True,
                        "signal_type": "btc_etf_flow",
                        "asset_class": "crypto",
                    },
                )
            )

            # Conditional alert for extreme BTC ETF flows
            if abs(daily_flow) > 500:
                direction = "INFLOW" if daily_flow > 0 else "OUTFLOW"
                signals.append(
                    Signal(
                        id=_make_id("etf_btc_alert"),
                        source=SignalSource.ETF_FLOWS,
                        url="https://sosovalue.com/assets/etf/us-btc-spot",
                        title=(
                            f"ETF ALERT: BTC extreme {direction} "
                            f"${abs(daily_flow):.0f}M"
                        ),
                        content=(
                            f"HIGH PRIORITY: BTC ETF daily net flow of "
                            f"${daily_flow:+.1f}M is extreme (>$500M). "
                            f"This level of {direction.lower()} historically "
                            f"precedes significant price moves within 1-3 days."
                        ),
                        metadata={
                            "btc_daily_flow_usd": round(daily_flow, 2),
                            "signal_type": "btc_etf_extreme_alert",
                            "asset_class": "crypto",
                            "priority": "high",
                        },
                    )
                )

        except Exception as e:
            logger.warning("Failed to parse BTC ETF flow data: %s", e)

        return signals

    def _parse_eth_flows(self, raw: dict) -> list[Signal]:
        """Parse ETH ETF flow data from SoSoValue response."""
        signals: list[Signal] = []
        data = raw.get("data", raw)

        try:
            daily_flow = self._extract_field(data, [
                "totalNetFlow", "netFlow", "daily_net_flow", "total_flow",
            ])
            rolling_5d = self._extract_field(data, [
                "fiveDayNetFlow", "rolling5d", "5d_net_flow", "weekly_flow",
            ])

            if daily_flow is None:
                daily_flow = 0.0
            if rolling_5d is None:
                rolling_5d = 0.0

            interpretation = _interpret_flow(daily_flow, rolling_5d)

            signals.append(
                Signal(
                    id=_make_id("etf_eth_flow"),
                    source=SignalSource.ETF_FLOWS,
                    url="https://sosovalue.com/assets/etf/us-btc-spot",
                    title=(
                        f"ETH ETF flows: ${daily_flow:+.1f}M daily, "
                        f"${rolling_5d:+.1f}M 5-day rolling"
                    ),
                    content=(
                        f"ETH spot-ETF net daily flow: ${daily_flow:+.1f}M. "
                        f"5-day rolling net flow: ${rolling_5d:+.1f}M. "
                        f"Interpretation: {interpretation}. "
                        f"ETH ETF flows trail BTC in magnitude but confirm "
                        f"institutional appetite for the broader crypto complex."
                    ),
                    metadata={
                        "eth_daily_flow_usd": round(daily_flow, 2),
                        "eth_5d_rolling_flow_usd": round(rolling_5d, 2),
                        "data_available": True,
                        "signal_type": "eth_etf_flow",
                        "asset_class": "crypto",
                    },
                )
            )

        except Exception as e:
            logger.warning("Failed to parse ETH ETF flow data: %s", e)

        return signals

    # ------------------------------------------------------------------
    # Helpers for flexible field extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_field(data: dict | list, candidate_keys: list[str]) -> float | None:
        """Try multiple key names to find a numeric value in the data.

        Handles both flat dicts and lists-of-dicts (takes the most recent
        entry from a list).
        """
        target = data
        if isinstance(data, list) and data:
            target = data[-1]  # most recent entry
        if not isinstance(target, dict):
            return None
        for key in candidate_keys:
            val = target.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _extract_ibit_flow(data: dict | list) -> float | None:
        """Try to find IBIT-specific flow data in the response."""
        # Case 1: dedicated field
        if isinstance(data, dict):
            for key in ("ibitFlow", "ibit_flow", "IBIT", "ibit"):
                val = data.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        continue

            # Case 2: nested fund-level breakdown
            funds = data.get("funds", data.get("fundFlows", []))
            if isinstance(funds, list):
                for fund in funds:
                    if not isinstance(fund, dict):
                        continue
                    name = str(fund.get("name", "") or fund.get("ticker", ""))
                    if "IBIT" in name.upper():
                        for key in ("netFlow", "flow", "dailyFlow", "net_flow"):
                            val = fund.get(key)
                            if val is not None:
                                try:
                                    return float(val)
                                except (ValueError, TypeError):
                                    continue
        return None

    # ------------------------------------------------------------------
    # Fallback: neutral stubs when API is unavailable
    # ------------------------------------------------------------------

    def _fallback_neutral(self) -> list[Signal]:
        """Return neutral/zero-flow signals when no ETF flow data is available."""
        now = datetime.utcnow()
        return [
            Signal(
                id=_make_id("etf_btc_stub"),
                source=SignalSource.ETF_FLOWS,
                url="https://sosovalue.com/assets/etf/us-btc-spot",
                title="BTC ETF flows: data unavailable — neutral stub",
                content=(
                    "BTC spot-ETF flow data could not be retrieved from "
                    "SoSoValue. Returning neutral zero-flow values. "
                    "The consensus scorer will down-weight this component. "
                    "Check SoSoValue manually for latest figures."
                ),
                timestamp=now,
                metadata={
                    "btc_daily_flow_usd": 0.0,
                    "btc_5d_rolling_flow_usd": 0.0,
                    "ibit_daily_flow_usd": 0.0,
                    "data_available": False,
                    "signal_type": "btc_etf_flow",
                    "asset_class": "crypto",
                },
            ),
            Signal(
                id=_make_id("etf_eth_stub"),
                source=SignalSource.ETF_FLOWS,
                url="https://sosovalue.com/assets/etf/us-btc-spot",
                title="ETH ETF flows: data unavailable — neutral stub",
                content=(
                    "ETH spot-ETF flow data could not be retrieved from "
                    "SoSoValue. Returning neutral zero-flow values. "
                    "The consensus scorer will down-weight this component. "
                    "Check SoSoValue manually for latest figures."
                ),
                timestamp=now,
                metadata={
                    "eth_daily_flow_usd": 0.0,
                    "eth_5d_rolling_flow_usd": 0.0,
                    "data_available": False,
                    "signal_type": "eth_etf_flow",
                    "asset_class": "crypto",
                },
            ),
        ]
