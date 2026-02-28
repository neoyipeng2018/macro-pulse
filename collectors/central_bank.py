"""Central bank communications collector — Fed speeches, minutes, ECB."""

import hashlib
import logging
from datetime import datetime

import feedparser

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


class CentralBankCollector(BaseCollector):
    """Collect signals from central bank RSS feeds (Fed, ECB)."""

    source_name = "central_bank"

    def __init__(self, feed_urls: list[str] | None = None):
        if feed_urls:
            self.feed_urls = feed_urls
        else:
            cb = settings.sources.get("central_bank", {})
            self.feed_urls = []
            for key in ("fed_speeches", "fed_press", "ecb"):
                self.feed_urls.extend(cb.get(key, []))

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []

        for url in self.feed_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:15]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", entry.get("description", ""))
                    link = entry.get("link", "")

                    published = entry.get("published_parsed")
                    if published:
                        timestamp = datetime(*published[:6])
                    else:
                        timestamp = datetime.utcnow()

                    sig_id = hashlib.md5(
                        f"{title}{link}".encode()
                    ).hexdigest()[:12]

                    signals.append(
                        Signal(
                            id=sig_id,
                            source=SignalSource.CENTRAL_BANK,
                            title=f"[Central Bank] {title}",
                            content=summary,
                            url=link,
                            timestamp=timestamp,
                            metadata={"feed_url": url},
                        )
                    )
            except Exception as e:
                logger.warning("Error fetching central bank feed %s: %s", url, e)

        return signals
