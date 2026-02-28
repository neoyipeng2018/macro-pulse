"""FRED economic data collector."""

import hashlib
import logging
from datetime import datetime

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


class EconomicDataCollector(BaseCollector):
    """Collect latest readings from FRED economic data series."""

    source_name = "economic_data"

    def __init__(self, series: list[dict] | None = None):
        self.series = series or settings.sources.get("fred_series", [])

    def collect(self) -> list[Signal]:
        if not settings.fred_api_key:
            logger.info("FRED_API_KEY not set, skipping economic data")
            return []

        try:
            from fredapi import Fred
        except ImportError:
            logger.warning("fredapi not installed, skipping economic data")
            return []

        fred = Fred(api_key=settings.fred_api_key)
        signals: list[Signal] = []

        for item in self.series:
            series_id = item["id"]
            name = item.get("name", series_id)
            try:
                data = fred.get_series(series_id, observation_start="2024-01-01")
                if data.empty:
                    continue

                latest = data.dropna().iloc[-1]
                prev = data.dropna().iloc[-2] if len(data.dropna()) > 1 else latest
                change = latest - prev
                pct_change = (change / abs(prev) * 100) if prev != 0 else 0

                sig_id = hashlib.md5(
                    f"fred_{series_id}_{datetime.utcnow().date()}".encode()
                ).hexdigest()[:12]

                signals.append(
                    Signal(
                        id=sig_id,
                        source=SignalSource.ECONOMIC_DATA,
                        title=f"{name}: {latest:.2f} ({change:+.2f})",
                        content=(
                            f"{name} ({series_id}) latest reading: {latest:.4f}. "
                            f"Change from prior: {change:+.4f} ({pct_change:+.2f}%). "
                            f"Date: {data.dropna().index[-1].strftime('%Y-%m-%d')}"
                        ),
                        timestamp=datetime.utcnow(),
                        metadata={
                            "series_id": series_id,
                            "value": float(latest),
                            "prior_value": float(prev),
                            "change": float(change),
                            "pct_change": round(pct_change, 4),
                        },
                    )
                )
            except Exception as e:
                logger.warning("Error fetching FRED %s: %s", series_id, e)

        return signals
