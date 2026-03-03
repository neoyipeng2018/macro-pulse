"""Tests for Pydantic models."""

from datetime import datetime

from models.schemas import (
    AssetClass,
    AssetSentiment,
    ConsensusScore,
    DivergenceMetrics,
    EconomicRegime,
    Narrative,
    SentimentDirection,
    Signal,
    SignalSource,
    TradeOutcome,
    TradeThesis,
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


def test_signal_source_consensus():
    assert SignalSource.OPTIONS.value == "options"
    assert SignalSource.DERIVATIVES_CONSENSUS.value == "derivatives_consensus"
    assert SignalSource.ETF_FLOWS.value == "etf_flows"


def test_consensus_score():
    cs = ConsensusScore(
        ticker="Bitcoin",
        consensus_score=0.62,
        consensus_direction="bullish",
        components={"options_skew": 0.45, "funding_7d": 0.78},
        options_skew=0.02,
        funding_rate_7d=0.078,
        top_trader_ls_ratio=1.22,
        etf_flow_5d=340.0,
        put_call_ratio=0.52,
    )
    assert cs.consensus_score == 0.62
    assert cs.consensus_direction == "bullish"
    assert cs.components["options_skew"] == 0.45


def test_divergence_metrics():
    dm = DivergenceMetrics(
        ticker="Bitcoin",
        consensus_score=0.62,
        our_score=-0.35,
        divergence=-0.97,
        abs_divergence=0.97,
        divergence_label="strongly_contrarian",
    )
    assert dm.divergence == -0.97
    assert dm.divergence_label == "strongly_contrarian"


def test_trade_thesis():
    tt = TradeThesis(
        ticker="Bitcoin",
        direction="bearish",
        entry_price=97500.0,
        take_profit_pct=6.0,
        stop_loss_pct=3.0,
        risk_reward_ratio=2.0,
        consensus_score_at_entry=0.62,
        our_score_at_entry=-0.35,
        divergence_at_entry=-0.97,
        divergence_label="strongly_contrarian",
    )
    assert tt.risk_reward_ratio == 2.0
    assert tt.exit_price is None
    assert tt.exit_reason is None


def test_trade_outcome():
    to = TradeOutcome(
        ticker="Bitcoin",
        week="2026-03-08",
        direction="bearish",
        entry_price=97500.0,
        entry_date=datetime(2026, 3, 8),
        exit_price=93600.0,
        exit_date=datetime(2026, 3, 12),
        exit_reason="tp_hit",
        pnl_pct=4.0,
        direction_correct=True,
        consensus_score=0.62,
        our_score=-0.35,
        divergence=-0.97,
    )
    assert to.pnl_pct == 4.0
    assert to.direction_correct is True


def test_weekly_report_with_consensus():
    report = WeeklyReport(
        id="rpt002",
        week_start=datetime(2026, 3, 2),
        week_end=datetime(2026, 3, 8),
        regime=EconomicRegime.TRANSITION,
        signal_count=200,
        consensus_scores=[
            ConsensusScore(ticker="Bitcoin", consensus_score=0.5, consensus_direction="bullish"),
        ],
        trade_theses=[
            TradeThesis(ticker="Bitcoin", direction="bullish", entry_price=95000.0,
                        take_profit_pct=6.0, stop_loss_pct=3.0, risk_reward_ratio=2.0),
        ],
    )
    assert len(report.consensus_scores) == 1
    assert len(report.trade_theses) == 1
