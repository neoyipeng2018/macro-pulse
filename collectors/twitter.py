"""Crypto Twitter sentiment via xreach CLI (Agent-Reach)."""

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)


class TwitterCryptoCollector(BaseCollector):
    """Collect crypto sentiment from Twitter/X via xreach CLI."""

    source_name = "twitter_crypto"

    DEFAULT_ACCOUNTS = [
        "100trillionUSD",
        "CryptoHayes",
        "zaborow",
        "inversebrah",
        "EmberCN",
    ]

    DEFAULT_SEARCHES = [
        "bitcoin liquidation",
        "crypto regulation",
        "stablecoin mint",
        "ETH unlock",
    ]

    def collect(self) -> list[Signal]:
        if not shutil.which("xreach"):
            logger.info("xreach not installed, skipping Twitter collection")
            return []

        twitter_cfg = settings.sources.get("twitter_crypto", {})
        accounts = twitter_cfg.get("accounts", self.DEFAULT_ACCOUNTS)
        searches = twitter_cfg.get("searches", self.DEFAULT_SEARCHES)

        signals: list[Signal] = []

        for account in accounts:
            try:
                result = subprocess.run(
                    ["xreach", "twitter", "user-tweets", account, "--limit", "10"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    tweets = json.loads(result.stdout)
                    for tweet in tweets:
                        signals.append(self._tweet_to_signal(tweet, account))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
                logger.warning("xreach failed for @%s: %s", account, e)

        for query in searches:
            try:
                result = subprocess.run(
                    ["xreach", "twitter", "search", query, "--limit", "20"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    tweets = json.loads(result.stdout)
                    for tweet in tweets:
                        signals.append(self._tweet_to_signal(tweet, f"search:{query}"))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
                logger.warning("xreach search failed for '%s': %s", query, e)

        return signals

    def _tweet_to_signal(self, tweet: dict, source_label: str) -> Signal:
        tweet_id = tweet.get("id", "")
        sig_id = hashlib.sha256(f"twitter_{tweet_id}".encode()).hexdigest()[:16]
        text = tweet.get("text", "")
        author = tweet.get("author", source_label)

        ts_raw = tweet.get("created_at", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.utcnow()
        except (ValueError, AttributeError):
            ts = datetime.utcnow()

        engagement = (
            tweet.get("retweets", 0) * 3
            + tweet.get("likes", 0)
            + tweet.get("replies", 0) * 2
        )

        return Signal(
            id=sig_id,
            source=SignalSource.TWITTER,
            title=f"@{author}: {text[:80]}",
            content=text,
            url=tweet.get("url", f"https://x.com/{author}/status/{tweet_id}"),
            timestamp=ts,
            metadata={
                "platform": "twitter",
                "author": author,
                "likes": tweet.get("likes", 0),
                "retweets": tweet.get("retweets", 0),
                "replies": tweet.get("replies", 0),
                "engagement_score": engagement,
                "source_label": source_label,
                "asset_class": "crypto",
            },
        )
