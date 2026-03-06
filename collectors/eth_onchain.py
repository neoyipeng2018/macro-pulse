"""ETH-specific on-chain data: gas price, DeFi TVL."""

import hashlib
import logging
from datetime import datetime

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


class EthOnChainCollector(BaseCollector):
    source_name = "eth_onchain"

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []
        client = httpx.Client(timeout=15)

        try:
            signals.extend(self._collect_gas_price(client))
        except Exception as e:
            logger.warning("ETH gas price failed: %s", e)

        try:
            signals.extend(self._collect_tvl(client))
        except Exception as e:
            logger.warning("ETH TVL failed: %s", e)

        client.close()
        return signals

    def _collect_gas_price(self, client: httpx.Client) -> list[Signal]:
        resp = client.post(
            "https://eth.llamarpc.com",
            json={"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1},
        )
        data = resp.json()
        gas_gwei = int(data["result"], 16) / 1e9
        return [Signal(
            id=self._make_id("eth_gas"),
            source=SignalSource.ETH_ONCHAIN,
            title=f"ETH Gas: {gas_gwei:.1f} gwei",
            content=(
                f"Current gas price: {gas_gwei:.1f} gwei. "
                f"{'High gas = strong on-chain demand.' if gas_gwei > 30 else 'Low gas = subdued activity.'}"
            ),
            url="https://etherscan.io/gastracker",
            timestamp=datetime.utcnow(),
            metadata={
                "metric": "gas_price",
                "gas_gwei": gas_gwei,
                "asset_class": "crypto",
                "symbol": "ETH",
            },
        )]

    def _collect_tvl(self, client: httpx.Client) -> list[Signal]:
        resp = client.get("https://api.llama.fi/v2/historicalChainTvl/Ethereum")
        data = resp.json()
        if len(data) < 7:
            return []
        current_tvl = data[-1]["tvl"]
        week_ago_tvl = data[-7]["tvl"]
        tvl_change = (current_tvl - week_ago_tvl) / week_ago_tvl if week_ago_tvl else 0

        return [Signal(
            id=self._make_id("eth_tvl"),
            source=SignalSource.ETH_ONCHAIN,
            title=f"ETH DeFi TVL: ${current_tvl / 1e9:.1f}B ({tvl_change:+.1%} WoW)",
            content=(
                f"Ethereum DeFi TVL: ${current_tvl / 1e9:.1f}B. "
                f"7-day change: {tvl_change:+.2%}. "
                f"{'TVL growing = capital inflow.' if tvl_change > 0 else 'TVL shrinking = capital outflow.'}"
            ),
            url="https://defillama.com/chain/Ethereum",
            timestamp=datetime.utcnow(),
            metadata={
                "metric": "defi_tvl",
                "tvl_usd": current_tvl,
                "tvl_change_7d_pct": tvl_change * 100,
                "asset_class": "crypto",
                "symbol": "ETH",
            },
        )]

    @staticmethod
    def _make_id(key: str) -> str:
        return hashlib.md5(f"eth_{key}_{datetime.utcnow().strftime('%Y%m%d')}".encode()).hexdigest()[:12]
