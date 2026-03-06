"""On-chain stablecoin supply collector via DeFi Llama.

Tracks total stablecoin market cap and per-coin trends as crypto liquidity
indicators. Growing stablecoin supply = dry powder entering = bullish.
Shrinking supply = capital leaving = bearish.

API: DeFi Llama stablecoins endpoint (free, no key required).
"""

import hashlib
import logging
from datetime import datetime

import httpx
import yaml

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

_STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
_STABLECOIN_CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

# Major stablecoins to track individually
_MAJOR_STABLECOINS = {"Tether", "USD Coin", "Dai"}
_DECLINE_ALERT_PCT = -1.0  # alert if 7d mcap drops >1%


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class OnChainCollector(BaseCollector):
    """Collect on-chain stablecoin supply data from DeFi Llama."""

    source_name = "onchain"

    def __init__(self):
        self.decline_alert_pct = _DECLINE_ALERT_PCT
        self._load_config()

    def _load_config(self) -> None:
        try:
            with open("config/sources.yaml") as f:
                cfg = yaml.safe_load(f)
            oc_cfg = cfg.get("onchain", {})
            if oc_cfg.get("stablecoin_decline_alert_pct") is not None:
                self.decline_alert_pct = oc_cfg["stablecoin_decline_alert_pct"]
        except Exception:
            pass

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []
        try:
            resp = httpx.get(_STABLECOINS_URL, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("DeFi Llama stablecoins fetch failed: %s", e)
            return signals

        peggedAssets = data.get("peggedAssets", [])
        if not peggedAssets:
            return signals

        total_supply = 0.0
        total_supply_7d_ago = 0.0
        usdt_supply = 0.0
        usdc_supply = 0.0
        coin_details: list[dict] = []

        for coin in peggedAssets:
            name = coin.get("name", "")
            symbol = coin.get("symbol", "")

            # Current circulating supply (pegged to USD)
            chains = coin.get("chainCirculating", {})
            current_mcap = 0.0
            for chain_data in chains.values():
                current_mcap += chain_data.get("current", {}).get("peggedUSD", 0)

            if current_mcap <= 0:
                continue

            total_supply += current_mcap

            # 7-day change from circulating history
            circ = coin.get("circulatingPrevDay", {})
            circ_7d = coin.get("circulatingPrevWeek", {})
            prev_week_mcap = circ_7d.get("peggedUSD", current_mcap)
            total_supply_7d_ago += prev_week_mcap

            change_pct = (
                ((current_mcap - prev_week_mcap) / prev_week_mcap * 100)
                if prev_week_mcap > 0
                else 0
            )

            if name in _MAJOR_STABLECOINS or symbol in {"USDT", "USDC", "DAI"}:
                coin_details.append({
                    "name": name,
                    "symbol": symbol,
                    "mcap": current_mcap,
                    "change_7d_pct": change_pct,
                })

            if symbol == "USDT":
                usdt_supply = current_mcap
            elif symbol == "USDC":
                usdc_supply = current_mcap

        # Total supply signal
        supply_7d_change_pct = (
            ((total_supply - total_supply_7d_ago) / total_supply_7d_ago * 100)
            if total_supply_7d_ago > 0
            else 0
        )

        if supply_7d_change_pct > 0:
            trend = "GROWING"
            interpretation = "Dry powder entering crypto ecosystem — bullish"
        elif supply_7d_change_pct < -0.5:
            trend = "SHRINKING"
            interpretation = "Capital leaving crypto ecosystem — bearish"
        else:
            trend = "STABLE"
            interpretation = "Stablecoin supply flat — neutral liquidity signal"

        signals.append(
            Signal(
                id=_make_id("stablecoin_total"),
                source=SignalSource.ONCHAIN,
                url="https://defillama.com/stablecoins",
                title=f"Stablecoin supply ${total_supply / 1e9:.1f}B ({supply_7d_change_pct:+.2f}% 7d) — {trend}",
                content=(
                    f"Total stablecoin market cap: ${total_supply / 1e9:.2f}B, "
                    f"7-day change: {supply_7d_change_pct:+.2f}%. "
                    f"{interpretation}. "
                    f"USDT: ${usdt_supply / 1e9:.1f}B, USDC: ${usdc_supply / 1e9:.1f}B. "
                    f"Growing stablecoin supply = dry powder entering = bullish. "
                    f"Shrinking supply = capital leaving = bearish."
                ),
                metadata={
                    "total_supply_usd": round(total_supply, 2),
                    "supply_7d_change_pct": round(supply_7d_change_pct, 4),
                    "usdt_supply": round(usdt_supply, 2),
                    "usdc_supply": round(usdc_supply, 2),
                    "signal_type": "stablecoin_supply",
                    "asset_class": "crypto",
                },
            )
        )

        # USDT vs USDC trend comparison
        if usdt_supply > 0 and usdc_supply > 0:
            usdt_detail = next(
                (c for c in coin_details if c["symbol"] == "USDT"), None
            )
            usdc_detail = next(
                (c for c in coin_details if c["symbol"] == "USDC"), None
            )
            if usdt_detail and usdc_detail:
                usdt_chg = usdt_detail["change_7d_pct"]
                usdc_chg = usdc_detail["change_7d_pct"]
                if usdt_chg > usdc_chg + 0.5:
                    demand_signal = (
                        "USDT growing faster than USDC — offshore/EM demand signal"
                    )
                elif usdc_chg > usdt_chg + 0.5:
                    demand_signal = (
                        "USDC growing faster than USDT — US institutional demand signal"
                    )
                else:
                    demand_signal = "USDT/USDC growth balanced — no clear demand skew"

                signals.append(
                    Signal(
                        id=_make_id("stablecoin_comparison"),
                        source=SignalSource.ONCHAIN,
                        url="https://defillama.com/stablecoins",
                        title=f"Stablecoin demand: USDT {usdt_chg:+.2f}% vs USDC {usdc_chg:+.2f}% (7d)",
                        content=(
                            f"USDT 7d change: {usdt_chg:+.2f}% (${usdt_supply / 1e9:.1f}B). "
                            f"USDC 7d change: {usdc_chg:+.2f}% (${usdc_supply / 1e9:.1f}B). "
                            f"{demand_signal}."
                        ),
                        metadata={
                            "usdt_change_7d_pct": round(usdt_chg, 4),
                            "usdc_change_7d_pct": round(usdc_chg, 4),
                            "signal_type": "stablecoin_comparison",
                            "asset_class": "crypto",
                        },
                    )
                )

        # Alert if any major stablecoin declining >1% in 7d
        for coin in coin_details:
            if coin["change_7d_pct"] <= self.decline_alert_pct:
                signals.append(
                    Signal(
                        id=_make_id("stablecoin_alert", coin["symbol"]),
                        source=SignalSource.ONCHAIN,
                        url="https://defillama.com/stablecoins",
                        title=f"STABLECOIN ALERT: {coin['symbol']} mcap down {coin['change_7d_pct']:.1f}% in 7d",
                        content=(
                            f"WARNING: {coin['name']} ({coin['symbol']}) market cap "
                            f"declined {coin['change_7d_pct']:.1f}% over 7 days "
                            f"(current: ${coin['mcap'] / 1e9:.2f}B). "
                            f"A >1% decline in major stablecoin supply signals potential "
                            f"contagion risk. Feeds stablecoin_contagion mechanism."
                        ),
                        metadata={
                            "symbol": coin["symbol"],
                            "mcap_usd": round(coin["mcap"], 2),
                            "change_7d_pct": round(coin["change_7d_pct"], 4),
                            "signal_type": "stablecoin_decline_alert",
                            "asset_class": "crypto",
                            "priority": "high",
                        },
                    )
                )

        return signals
