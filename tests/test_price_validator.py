"""Tests for price_validator asset-class-aware thresholds."""

from analysis.price_validator import validate_predictions, _direction_threshold
from models.schemas import AssetClass, SentimentDirection, WeeklyAssetScore


def test_crypto_threshold_is_2_percent():
    assert _direction_threshold(AssetClass.CRYPTO) == 2.0


def test_equity_threshold_is_025_percent():
    assert _direction_threshold(AssetClass.INDICES) == 0.25


def test_crypto_15pct_return_is_neutral():
    """BTC with 1.5% actual return should be neutral (below 2% crypto threshold)."""
    scores = [
        WeeklyAssetScore(
            ticker="Bitcoin",
            asset_class=AssetClass.CRYPTO,
            direction=SentimentDirection.BULLISH,
            score=0.6,
            conviction=0.7,
            narrative_count=2,
        )
    ]
    actual = {"Bitcoin": 1.5}
    results = validate_predictions(scores, actual)
    assert len(results) == 1
    assert results[0].actual_direction == SentimentDirection.NEUTRAL
    assert results[0].hit is False


def test_equity_15pct_return_is_bullish():
    """S&P 500 with 1.5% actual return should be bullish (above 0.25% threshold)."""
    scores = [
        WeeklyAssetScore(
            ticker="S&P 500",
            asset_class=AssetClass.INDICES,
            direction=SentimentDirection.BULLISH,
            score=0.5,
            conviction=0.6,
            narrative_count=1,
        )
    ]
    actual = {"S&P 500": 1.5}
    results = validate_predictions(scores, actual)
    assert len(results) == 1
    assert results[0].actual_direction == SentimentDirection.BULLISH
    assert results[0].hit is True


def test_crypto_3pct_return_is_bullish():
    """BTC with 3.0% return should be bullish (above 2% crypto threshold)."""
    scores = [
        WeeklyAssetScore(
            ticker="Bitcoin",
            asset_class=AssetClass.CRYPTO,
            direction=SentimentDirection.BULLISH,
            score=0.7,
            conviction=0.8,
            narrative_count=3,
        )
    ]
    actual = {"Bitcoin": 3.0}
    results = validate_predictions(scores, actual)
    assert len(results) == 1
    assert results[0].actual_direction == SentimentDirection.BULLISH
    assert results[0].hit is True


def test_crypto_negative_3pct_is_bearish():
    """BTC with -3.0% return should be bearish."""
    scores = [
        WeeklyAssetScore(
            ticker="Bitcoin",
            asset_class=AssetClass.CRYPTO,
            direction=SentimentDirection.BEARISH,
            score=-0.5,
            conviction=0.6,
            narrative_count=1,
        )
    ]
    actual = {"Bitcoin": -3.0}
    results = validate_predictions(scores, actual)
    assert len(results) == 1
    assert results[0].actual_direction == SentimentDirection.BEARISH
    assert results[0].hit is True
