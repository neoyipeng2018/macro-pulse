"""Reddit signal collector — adapted from sentinel/sources/social.py."""

import hashlib
import json
import logging
import urllib.request
from datetime import datetime

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


class RedditCollector(BaseCollector):
    """Collect signals from macro-relevant subreddits using public JSON API."""

    source_name = "reddit"

    def __init__(self, subreddits: list[str] | None = None, limit: int = 25):
        self.subreddits = subreddits or settings.sources.get("subreddits", [
            "wallstreetbets", "investing", "economics", "Forex",
            "CryptoCurrency", "Gold", "commodities",
        ])
        self.limit = limit

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []

        for sub in self.subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit={self.limit}"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "macro-pulse/0.1"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                for post in data.get("data", {}).get("children", []):
                    p = post["data"]
                    if p.get("stickied"):
                        continue

                    title = p.get("title", "")
                    selftext = p.get("selftext", "")[:500]
                    permalink = f"https://reddit.com{p.get('permalink', '')}"
                    created = datetime.utcfromtimestamp(p.get("created_utc", 0))
                    score = p.get("score", 0)
                    num_comments = p.get("num_comments", 0)

                    sig_id = hashlib.md5(
                        f"{title}{permalink}".encode()
                    ).hexdigest()[:12]

                    signals.append(
                        Signal(
                            id=sig_id,
                            source=SignalSource.SOCIAL,
                            title=title,
                            content=selftext if selftext else title,
                            url=permalink,
                            timestamp=created,
                            metadata={
                                "subreddit": sub,
                                "score": score,
                                "num_comments": num_comments,
                                "upvote_ratio": p.get("upvote_ratio", 0),
                            },
                        )
                    )
            except Exception as e:
                logger.warning("Error fetching r/%s: %s", sub, e)

        return signals
