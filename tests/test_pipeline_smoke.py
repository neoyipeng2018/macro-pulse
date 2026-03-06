"""Smoke tests for new analysis modules and pipeline wiring."""

from datetime import datetime

from analysis.nc_validator import NCValidation, validate_nc_view
from analysis.regime_voter import RegimeVote, compute_regime_votes, tally_regime_votes
from analysis.direction_targets import compute_consensus_range
from analysis.chain_verifier import verify_chain_progression
from models.schemas import ConsensusScore, Signal, SignalSource


def test_nc_validation_both_pass():
    v = NCValidation(
        multi_source_pass=True,
        independent_sources=["reddit", "news"],
        source_count=2,
        causal_pass=True,
        mechanism_id="test_mech",
    )
    assert v.is_valid is True


def test_nc_validation_multi_source_fail():
    v = NCValidation(
        multi_source_pass=False,
        independent_sources=["reddit"],
        source_count=1,
        causal_pass=True,
        mechanism_id="test_mech",
    )
    assert v.is_valid is False


def test_nc_validation_causal_fail():
    v = NCValidation(
        multi_source_pass=True,
        independent_sources=["reddit", "news"],
        source_count=2,
        causal_pass=False,
    )
    assert v.is_valid is False


def test_nc_validation_both_fail():
    v = NCValidation(
        multi_source_pass=False,
        independent_sources=[],
        source_count=0,
        causal_pass=False,
    )
    assert v.is_valid is False


def test_consensus_range_btc():
    result = compute_consensus_range(
        spot_price=95000,
        atm_iv=0.60,
        max_pain=93000,
        consensus_score=0.3,
        horizon_days=7,
    )
    assert result["spot"] == 95000
    assert result["consensus_low"] < result["consensus_mid"] < result["consensus_high"]
    assert result["consensus_low"] > 80000
    assert result["consensus_high"] < 115000
    assert result["sigma_1w_usd"] > 0
    assert result["max_pain"] == 93000


def test_consensus_range_neutral():
    result = compute_consensus_range(
        spot_price=100000,
        atm_iv=0.50,
        max_pain=100000,
        consensus_score=0.0,
    )
    assert abs(result["consensus_mid"] - 100000) < 100
    assert result["positioning_bias"] == 0.0


def test_regime_votes_with_mock_signals():
    signals = [
        Signal(
            id="vix1",
            source=SignalSource.SPREADS,
            title="VIX",
            content="",
            metadata={"metric": "vix_level", "vix_level": 15.0},
        ),
        Signal(
            id="fred1",
            source=SignalSource.ECONOMIC_DATA,
            title="T10Y2Y",
            content="",
            metadata={"series_id": "T10Y2Y", "value": 0.5},
        ),
    ]
    votes = compute_regime_votes(signals, [])
    assert len(votes) >= 2
    vix_vote = next(v for v in votes if v.indicator == "VIX")
    assert vix_vote.regime == "risk_on"
    yield_vote = next(v for v in votes if v.indicator == "Yield Curve")
    assert yield_vote.regime == "goldilocks"


def test_tally_regime_votes():
    votes = [
        RegimeVote("VIX", "risk_on", 0.7, "low"),
        RegimeVote("Credit", "risk_on", 0.5, "tight"),
        RegimeVote("DXY", "reflation", 0.4, "weak"),
    ]
    regime, conf, rationale = tally_regime_votes(votes)
    assert regime == "risk_on"
    assert conf > 0.5


def test_chain_verifier_with_mock():
    mechanism = {
        "id": "test_mech",
        "trigger_keywords": ["liquidation_unique_kw"],
        "chain_steps": [
            {"description": "Funding spike", "observable": "perpetual funding spike elevated", "lag_days": [0, 3]},
            {"description": "Liquidation cascade", "observable": "massive cascade liquidation event", "lag_days": [1, 5]},
            {"description": "Price recovery", "observable": "recovery bounce reversal mean", "lag_days": [3, 7]},
        ],
    }
    signals = [
        Signal(
            id="s1",
            source=SignalSource.NEWS,
            title="Perpetual funding spike reaches elevated levels",
            content="Funding rates have surged to elevated territory",
            timestamp=datetime.utcnow(),
        ),
        Signal(
            id="s2",
            source=SignalSource.NEWS,
            title="Massive cascade liquidation event hits market",
            content="Cascade liquidation event across exchanges",
            timestamp=datetime.utcnow(),
        ),
    ]
    result = verify_chain_progression(mechanism, signals, datetime.utcnow())
    assert result["total_steps"] == 3
    assert len(result["fired_steps"]) == 2
    assert len(result["pending_steps"]) == 1
    assert result["stage"] == "late"


def test_validate_nc_view_passes():
    nc_view = {
        "ticker": "Bitcoin",
        "our_direction": "bearish",
        "evidence": [
            {"source": "reddit", "summary": "test1", "signal_id": "s1"},
            {"source": "news", "summary": "test2", "signal_id": "s2"},
        ],
    }
    scenario = {
        "mechanism_id": "test_mech",
        "mechanism_name": "Test",
        "asset_impacts": [
            {"ticker": "Bitcoin", "direction": "bearish"},
        ],
    }
    mechanism = {
        "id": "test_mech",
        "trigger_keywords": ["bitcoin"],
        "chain_steps": [
            {"description": "Step 1", "observable": "bitcoin test signal", "lag_days": [0, 7]},
        ],
    }
    signals = [
        Signal(
            id="s1",
            source=SignalSource.NEWS,
            title="Bitcoin test signal observed",
            content="Bitcoin related content",
            timestamp=datetime.utcnow(),
        ),
    ]
    result = validate_nc_view(nc_view, [scenario], [mechanism], signals)
    assert result.multi_source_pass is True
    assert result.causal_pass is True
    assert result.is_valid is True
