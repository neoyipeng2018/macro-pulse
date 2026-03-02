"""Tests for Pydantic models."""

from datetime import datetime

from models.schemas import (
    AssetClass,
    AssetSentiment,
    EconomicRegime,
    Narrative,
    PriceValidation,
    SentimentDirection,
    Signal,
    SignalSource,
    WeeklyAssetScore,
    WeeklyReport,
)


def test_signal_creation():
    sig = Signal(
        id="test123",
        source=SignalSource.NEWS,
        title="Fed signals rate cut",
        content="The Federal Reserve indicated...",
    )
    assert sig.id == "test123"
    assert sig.source == SignalSource.NEWS


def test_asset_sentiment():
    sent = AssetSentiment(
        ticker="Gold",
        asset_class=AssetClass.METALS,
        direction=SentimentDirection.BULLISH,
        conviction=0.8,
        rationale="Safe-haven demand rising",
    )
    assert sent.direction == SentimentDirection.BULLISH
    assert sent.conviction == 0.8


def test_narrative_creation():
    nar = Narrative(
        id="nar001",
        title="USD weakness on dovish Fed",
        summary="The Fed's dovish pivot is weakening the dollar.",
        asset_sentiments=[
            AssetSentiment(
                ticker="DXY",
                asset_class=AssetClass.FX,
                direction=SentimentDirection.BEARISH,
                conviction=0.7,
            ),
            AssetSentiment(
                ticker="Gold",
                asset_class=AssetClass.METALS,
                direction=SentimentDirection.BULLISH,
                conviction=0.8,
            ),
        ],
        affected_asset_classes=[AssetClass.FX, AssetClass.METALS],
        confidence=0.75,
        trend="intensifying",
    )
    assert len(nar.asset_sentiments) == 2
    assert nar.confidence == 0.75


def test_weekly_asset_score():
    score = WeeklyAssetScore(
        ticker="Gold",
        asset_class=AssetClass.METALS,
        direction=SentimentDirection.BULLISH,
        score=0.65,
        conviction=0.7,
        narrative_count=3,
        top_narrative="USD weakness on dovish Fed",
    )
    assert score.score == 0.65
    assert score.direction == SentimentDirection.BULLISH


def test_price_validation():
    pv = PriceValidation(
        ticker="Gold",
        asset_class=AssetClass.METALS,
        predicted_direction=SentimentDirection.BULLISH,
        predicted_score=0.65,
        actual_return_pct=2.3,
        actual_direction=SentimentDirection.BULLISH,
        hit=True,
    )
    assert pv.hit is True


def test_weekly_report():
    report = WeeklyReport(
        id="rpt001",
        week_start=datetime(2026, 2, 23),
        week_end=datetime(2026, 3, 1),
        regime=EconomicRegime.RISK_OFF,
        regime_rationale="Recession fears dominating",
        signal_count=150,
        summary="Risk-off week dominated by recession fears.",
    )
    assert report.regime == EconomicRegime.RISK_OFF
    assert report.signal_count == 150


def test_sentiment_direction_enum():
    assert SentimentDirection.BULLISH.value == "bullish"
    assert SentimentDirection.BEARISH.value == "bearish"
    assert SentimentDirection.NEUTRAL.value == "neutral"


def test_economic_regime_enum():
    assert EconomicRegime.RISK_ON.value == "risk_on"
    assert EconomicRegime.STAGFLATION.value == "stagflation"
    assert EconomicRegime.TRANSITION.value == "transition"


def test_signal_source_funding_rates():
    assert SignalSource.FUNDING_RATES.value == "funding_rates"


def test_signal_source_onchain():
    assert SignalSource.ONCHAIN.value == "onchain"
