"""Google Trends collector — retail search interest as contrarian signals.

Tracks search interest for financial stress, asset, and policy keywords.
Spikes in these terms are treated as CONTRARIAN signals at the 1-week
horizon — retail panic often marks short-term bottoms.

Adapted from sentinel/sources/trends.py with 1-week tuning:
  - Timeframe: "today 1-m" (daily data, 30 days) for daily granularity
  - 7-day average ratio instead of 30-day for faster spike detection
  - Lower thresholds: strong spike >=70 at 1.5x, acceleration >=50 at 2.0x
"""

import hashlib
import logging
from datetime import datetime

import yaml

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

_DEFAULT_KEYWORDS = [
    # Stress
    "recession", "market crash", "bank run", "layoffs", "margin call", "sell stocks",
    # Assets
    "gold price", "bitcoin crash", "oil price", "dollar collapse", "safe haven",
    # Policy
    "rate cut", "inflation", "tariff", "trade war", "sanctions",
    # Crypto-specific
    "ethereum crash", "solana crash", "crypto crash", "crypto regulation",
    "bitcoin ETF", "crypto winter",
]


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class GoogleTrendsCollector(BaseCollector):
    """Collect Google Trends signals for financial stress/asset keywords."""

    source_name = "google_trends"

    def __init__(self):
        self.timeframe = "today 1-m"
        self.keywords = list(_DEFAULT_KEYWORDS)
        self._load_config()

    def _load_config(self) -> None:
        """Load keywords and timeframe from sources.yaml if available."""
        try:
            with open("config/sources.yaml") as f:
                cfg = yaml.safe_load(f)
            gt_cfg = cfg.get("google_trends", {})
            if gt_cfg.get("timeframe"):
                self.timeframe = gt_cfg["timeframe"]
            if gt_cfg.get("keywords"):
                self.keywords = gt_cfg["keywords"]
        except Exception:
            pass

    def collect(self) -> list[Signal]:
        try:
            from pytrends.request import TrendReq
        except ImportError:
            logger.warning("pytrends not installed — skipping Google Trends collection")
            return []

        signals: list[Signal] = []

        try:
            pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        except Exception as e:
            logger.warning("Error initializing pytrends: %s", e)
            return signals

        # Process keywords in batches of 5 (Google Trends API limit)
        for i in range(0, len(self.keywords), 5):
            batch = self.keywords[i : i + 5]
            try:
                pytrends.build_payload(batch, timeframe=self.timeframe, geo="US")
                df = pytrends.interest_over_time()
            except Exception as e:
                logger.warning("Error fetching trends for %s: %s", batch, e)
                continue

            if df.empty:
                continue

            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])

            for kw in batch:
                if kw not in df.columns:
                    continue

                series = df[kw].dropna()
                if len(series) < 7:
                    continue

                current = float(series.iloc[-1])
                # 7-day average for faster spike detection (vs sentinel's 30-day)
                avg_7d = float(series.iloc[-7:].mean())
                avg_30d = float(series.mean())  # full period average
                peak = float(series.max())

                if avg_7d == 0:
                    continue

                ratio_vs_7d = current / avg_7d

                if current >= 70 and ratio_vs_7d >= 1.5:
                    # Strong spike — contrarian signal
                    signals.append(Signal(
                        id=_make_id("trends", kw),
                        source=SignalSource.GOOGLE_TRENDS,
                        title=f'Google searches for "{kw}" spiking ({current:.0f}/100)',
                        content=(
                            f'Search interest for "{kw}" is at {current:.0f}/100 '
                            f"(Google Trends), {ratio_vs_7d:.1f}x its 7-day average "
                            f"({avg_7d:.0f}). 30-day average: {avg_30d:.0f}, "
                            f"peak: {peak:.0f}/100. "
                            f"Sharp spikes in retail search interest for financial stress "
                            f"terms are historically CONTRARIAN indicators — peak public "
                            f"anxiety often coincides with short-term market bottoms at "
                            f"the 1-week horizon."
                        ),
                        metadata={
                            "signal_type": "search_spike",
                            "keyword": kw,
                            "current_interest": round(current),
                            "avg_7d": round(avg_7d),
                            "avg_30d": round(avg_30d),
                            "peak_30d": round(peak),
                            "ratio_vs_7d": round(ratio_vs_7d, 2),
                        },
                    ))
                elif current >= 50 and ratio_vs_7d >= 2.0:
                    # Rapid acceleration — emerging narrative
                    signals.append(Signal(
                        id=_make_id("trends", kw),
                        source=SignalSource.GOOGLE_TRENDS,
                        title=f'Google searches for "{kw}" accelerating ({current:.0f}/100)',
                        content=(
                            f'Search interest for "{kw}" is at {current:.0f}/100, '
                            f"{ratio_vs_7d:.1f}x its 7-day average ({avg_7d:.0f}). "
                            f"Rapid acceleration in search interest suggests a narrative "
                            f"gaining public attention. At the 1-week horizon, this level "
                            f"of retail attention often marks a contrarian inflection point."
                        ),
                        metadata={
                            "signal_type": "search_acceleration",
                            "keyword": kw,
                            "current_interest": round(current),
                            "avg_7d": round(avg_7d),
                            "avg_30d": round(avg_30d),
                            "ratio_vs_7d": round(ratio_vs_7d, 2),
                        },
                    ))

        return signals
