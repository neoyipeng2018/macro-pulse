"""Tests for collector infrastructure."""

from collectors.base import BaseCollector
from collectors.rss_news import RSSNewsCollector
from collectors.reddit import RedditCollector
from collectors.central_bank import CentralBankCollector
from collectors.economic_data import EconomicDataCollector
from collectors.cot_reports import COTCollector
from collectors.fear_greed import FearGreedCollector
from collectors.market_data import MarketDataCollector
from collectors.twitter import TwitterCollector


def test_all_collectors_inherit_base():
    """Verify all collectors implement the BaseCollector ABC."""
    collectors = [
        RSSNewsCollector,
        RedditCollector,
        CentralBankCollector,
        EconomicDataCollector,
        COTCollector,
        FearGreedCollector,
        MarketDataCollector,
        TwitterCollector,
    ]
    for cls in collectors:
        assert issubclass(cls, BaseCollector), f"{cls.__name__} must inherit BaseCollector"
        instance = cls()
        assert hasattr(instance, "source_name")
        assert hasattr(instance, "collect")


def test_rss_collector_has_feeds():
    """RSSNewsCollector should have feed URLs configured."""
    collector = RSSNewsCollector()
    assert len(collector.feed_urls) > 0


def test_market_data_collector_has_assets():
    """MarketDataCollector should have assets from config."""
    collector = MarketDataCollector()
    tickers = collector._get_all_tickers()
    assert len(tickers) > 0


def test_twitter_placeholder_returns_empty():
    """Twitter collector should return empty list when no API key is set."""
    collector = TwitterCollector()
    signals = collector.collect()
    assert signals == []
