"""Crypto Fear & Greed Index collector."""

import hashlib
import logging
from datetime import datetime

import httpx

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


class FearGreedCollector(BaseCollector):
    """Collect Crypto Fear & Greed Index from alternative.me."""

    source_name = "fear_greed"

    API_URL = "https://api.alternative.me/fng/?limit=7&format=json"

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []

        try:
            resp = httpx.get(self.API_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for entry in data.get("data", []):
                value = int(entry["value"])
                classification = entry["value_classification"]
                ts = datetime.utcfromtimestamp(int(entry["timestamp"]))

                sig_id = hashlib.md5(
                    f"fng_{entry['timestamp']}".encode()
                ).hexdigest()[:12]

                signals.append(
                    Signal(
                        id=sig_id,
                        source=SignalSource.FEAR_GREED,
                        title=f"Crypto Fear & Greed: {value} ({classification})",
                        content=(
                            f"Crypto Fear & Greed Index: {value}/100 — {classification}. "
                            f"Values below 25 indicate extreme fear (potential buying opportunity), "
                            f"above 75 indicate extreme greed (potential overheating)."
                        ),
                        timestamp=ts,
                        metadata={
                            "value": value,
                            "classification": classification,
                        },
                    )
                )
        except Exception as e:
            logger.warning("Error fetching Fear & Greed: %s", e)

        return signals
