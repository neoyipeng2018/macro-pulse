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
from collectors.economic_calendar import EconomicCalendarCollector


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
        EconomicCalendarCollector,
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


def test_economic_calendar_event_to_signal():
    """_event_to_signal() produces correct format from a calendar event."""
    from datetime import datetime
    collector = EconomicCalendarCollector()
    event = {
        "country": "USD",
        "date": "2026-03-18T14:00:00-05:00",
        "title": "FOMC Rate Decision",
        "impact": "High",
        "forecast": "4.5%",
        "previous": "4.75%",
    }
    # Set now to before the event so it isn't filtered as past
    signal = collector._event_to_signal(event, now=datetime(2026, 3, 1))
    assert signal is not None
    assert signal.title.startswith("[UPCOMING]")
    assert signal.metadata["is_forward_looking"] is True
    assert signal.metadata["event_name"] == "FOMC Rate Decision"
    assert signal.metadata["country"] == "US"
    assert signal.metadata["impact"] == "high"
    assert signal.source.value == "economic_data"


def test_economic_calendar_filters_low_impact():
    """Low-impact events should be filtered out."""
    collector = EconomicCalendarCollector()
    event = {
        "country": "USD",
        "date": "2026-03-18T10:00:00-05:00",
        "title": "Some Minor Report",
        "impact": "Low",
    }
    signal = collector._event_to_signal(event)
    assert signal is None


def test_economic_calendar_fomc_fallback():
    """Hardcoded fallback returns FOMC dates when no API key is set."""
    collector = EconomicCalendarCollector()
    signals = collector._collect_fomc_fallback()
    for s in signals:
        assert s.title.startswith("[UPCOMING] FOMC")
        assert s.metadata["is_forward_looking"] is True
        assert s.metadata["event_name"] == "FOMC Rate Decision"
        assert s.metadata["impact"] == "high"
