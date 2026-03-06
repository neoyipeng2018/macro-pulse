"""Bitcoin on-chain data from mempool.space (free, no auth)."""

import hashlib
import logging
from datetime import datetime

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

MEMPOOL_BASE = "https://mempool.space/api/v1"


class MempoolCollector(BaseCollector):
    source_name = "mempool"

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []
        client = httpx.Client(timeout=15)

        try:
            signals.extend(self._collect_difficulty(client))
        except Exception as e:
            logger.warning("mempool difficulty failed: %s", e)

        try:
            signals.extend(self._collect_hashrate(client))
        except Exception as e:
            logger.warning("mempool hashrate failed: %s", e)

        try:
            signals.extend(self._collect_fees(client))
        except Exception as e:
            logger.warning("mempool fees failed: %s", e)

        try:
            signals.extend(self._collect_mining_pools(client))
        except Exception as e:
            logger.warning("mempool mining pools failed: %s", e)

        client.close()
        return signals

    def _collect_difficulty(self, client: httpx.Client) -> list[Signal]:
        resp = client.get(f"{MEMPOOL_BASE}/difficulty-adjustment")
        data = resp.json()
        return [Signal(
            id=self._make_id("difficulty_adjustment"),
            source=SignalSource.MEMPOOL,
            title=f"BTC Difficulty Adjustment: {data['difficultyChange']:+.2f}%",
            content=(
                f"Progress: {data['progressPercent']:.1f}% through epoch. "
                f"Estimated adjustment: {data['difficultyChange']:+.2f}%. "
                f"Remaining blocks: {data['remainingBlocks']}. "
                f"Time ahead/behind: {data['timeAvg'] / 600000 - 1:.1%}."
            ),
            url="https://mempool.space/graphs/mining/hashrate-difficulty",
            timestamp=datetime.utcnow(),
            metadata={
                "metric": "difficulty_adjustment",
                "difficulty_change_pct": data["difficultyChange"],
                "progress_pct": data["progressPercent"],
                "remaining_blocks": data["remainingBlocks"],
                "asset_class": "crypto",
                "symbol": "BTC",
            },
        )]

    def _collect_hashrate(self, client: httpx.Client) -> list[Signal]:
        resp = client.get(f"{MEMPOOL_BASE}/mining/hashrate/1w")
        data = resp.json()
        if not data.get("hashrates") or len(data["hashrates"]) < 2:
            return []
        latest = data["hashrates"][-1]
        prev = data["hashrates"][-2]
        hr_change = (latest["avgHashrate"] - prev["avgHashrate"]) / prev["avgHashrate"] if prev["avgHashrate"] else 0

        return [Signal(
            id=self._make_id("hashrate_weekly"),
            source=SignalSource.MEMPOOL,
            title=f"BTC Hashrate: {latest['avgHashrate'] / 1e18:.1f} EH/s ({hr_change:+.1%} WoW)",
            content=(
                f"Weekly average hashrate: {latest['avgHashrate'] / 1e18:.1f} EH/s. "
                f"Change: {hr_change:+.2%} week-over-week. "
                f"{'Rising hashrate = miner confidence.' if hr_change > 0 else 'Falling hashrate = potential miner capitulation.'}"
            ),
            url="https://mempool.space/graphs/mining/hashrate-difficulty",
            timestamp=datetime.utcnow(),
            metadata={
                "metric": "hashrate",
                "hashrate_eh": latest["avgHashrate"] / 1e18,
                "hashrate_change_pct": hr_change * 100,
                "asset_class": "crypto",
                "symbol": "BTC",
            },
        )]

    def _collect_fees(self, client: httpx.Client) -> list[Signal]:
        resp = client.get(f"{MEMPOOL_BASE}/fees/recommended")
        data = resp.json()
        return [Signal(
            id=self._make_id("fees_recommended"),
            source=SignalSource.MEMPOOL,
            title=f"BTC Fees: {data['fastestFee']} sat/vB (fast), {data['hourFee']} sat/vB (hour)",
            content=(
                f"Fastest: {data['fastestFee']} sat/vB. "
                f"Half-hour: {data['halfHourFee']} sat/vB. "
                f"Hour: {data['hourFee']} sat/vB. "
                f"Economy: {data['economyFee']} sat/vB. "
                f"{'High fees = high demand for block space.' if data['fastestFee'] > 50 else 'Low fees = subdued on-chain activity.'}"
            ),
            url="https://mempool.space",
            timestamp=datetime.utcnow(),
            metadata={
                "metric": "fees",
                "fastest_fee": data["fastestFee"],
                "half_hour_fee": data["halfHourFee"],
                "hour_fee": data["hourFee"],
                "economy_fee": data["economyFee"],
                "asset_class": "crypto",
                "symbol": "BTC",
            },
        )]

    def _collect_mining_pools(self, client: httpx.Client) -> list[Signal]:
        resp = client.get(f"{MEMPOOL_BASE}/mining/pools/1w")
        data = resp.json()
        if not data.get("pools"):
            return []
        top3 = sorted(data["pools"], key=lambda p: p["blockCount"], reverse=True)[:3]
        total_blocks = sum(p["blockCount"] for p in data["pools"])
        if total_blocks == 0:
            return []
        top3_share = sum(p["blockCount"] for p in top3) / total_blocks

        pool_details = ", ".join(
            f"{p['name']} ({p['blockCount'] / total_blocks:.0%})" for p in top3
        )
        return [Signal(
            id=self._make_id("mining_pools"),
            source=SignalSource.MEMPOOL,
            title=f"BTC Mining: Top 3 pools control {top3_share:.0%} of hashrate",
            content=f"Top 3 pools: {pool_details}. Total blocks this week: {total_blocks}.",
            url="https://mempool.space/graphs/mining/pools",
            timestamp=datetime.utcnow(),
            metadata={
                "metric": "mining_pools",
                "top3_share_pct": top3_share * 100,
                "total_blocks": total_blocks,
                "asset_class": "crypto",
                "symbol": "BTC",
            },
        )]

    @staticmethod
    def _make_id(key: str) -> str:
        return hashlib.md5(f"mempool_{key}_{datetime.utcnow().strftime('%Y%m%d')}".encode()).hexdigest()[:12]
