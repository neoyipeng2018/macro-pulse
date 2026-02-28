"""RSS news feed collector — adapted from sentinel/sources/news.py."""

import hashlib
import logging
from datetime import datetime

import feedparser

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


def _make_id(title: str, url: str) -> str:
    return hashlib.md5(f"{title}{url}".encode()).hexdigest()[:12]


class RSSNewsCollector(BaseCollector):
    """Collect signals from macro/financial news RSS feeds."""

    source_name = "news"

    def __init__(self, feed_urls: list[str] | None = None):
        sources = settings.sources
        all_feeds = []
        for category in ("macro_news", "fx_commodities", "crypto"):
            all_feeds.extend(sources.get("rss_feeds", {}).get(category, []))
        self.feed_urls = feed_urls or all_feeds

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []

        for url in self.feed_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", entry.get("description", ""))
                    link = entry.get("link", "")

                    published = entry.get("published_parsed")
                    if published:
                        timestamp = datetime(*published[:6])
                    else:
                        timestamp = datetime.utcnow()

                    signals.append(
                        Signal(
                            id=_make_id(title, link),
                            source=SignalSource.NEWS,
                            title=title,
                            content=summary,
                            url=link,
                            timestamp=timestamp,
                            metadata={
                                "feed_url": url,
                                "feed_title": feed.feed.get("title", ""),
                            },
                        )
                    )
            except Exception as e:
                logger.warning("Error fetching RSS %s: %s", url, e)

        return signals
