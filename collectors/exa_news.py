"""Semantic search for breaking crypto/macro news via Exa (Agent-Reach mcporter)."""

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime, timedelta

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

QUERIES = [
    "bitcoin price analysis this week",
    "ethereum market outlook",
    "crypto regulatory news",
    "federal reserve impact on crypto",
    "bitcoin whale accumulation",
    "crypto derivatives liquidation",
    "stablecoin flows depegging risk",
]


class ExaNewsCollector(BaseCollector):
    """Semantic search for breaking crypto/macro news via Exa."""

    source_name = "exa_news"

    def collect(self) -> list[Signal]:
        if not shutil.which("mcporter"):
            logger.info("mcporter not installed, skipping Exa news collection")
            return []

        signals: list[Signal] = []
        since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        for query in QUERIES:
            try:
                result = subprocess.run(
                    [
                        "mcporter", "call",
                        f"exa.search(query='{query}', "
                        f"startPublishedDate='{since}', "
                        f"numResults=5, type='auto')",
                    ],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    for item in data.get("results", []):
                        url = item.get("url", "")
                        sig_id = hashlib.sha256(f"exa_{url}".encode()).hexdigest()[:16]

                        ts_raw = item.get("publishedDate", "")
                        try:
                            ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.utcnow()
                        except (ValueError, AttributeError):
                            ts = datetime.utcnow()

                        domain = url.split("/")[2] if len(url.split("/")) > 2 else ""

                        signals.append(Signal(
                            id=sig_id,
                            source=SignalSource.EXA_NEWS,
                            title=item.get("title", query),
                            content=item.get("text", item.get("highlight", ""))[:2000],
                            url=url,
                            timestamp=ts,
                            metadata={
                                "search_query": query,
                                "exa_score": item.get("score", 0),
                                "domain": domain,
                                "asset_class": "crypto",
                            },
                        ))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
                logger.warning("Exa search failed for '%s': %s", query, e)

        return signals
