"""Composite scoring: combine narrative, technical, scenario, and contrarian signals.

Replaces the saturated ±1.0 narrative-only score with a multi-factor composite
that actually differentiates strong from weak trades.
"""

from __future__ import annotations

import logging

from analysis.technicals import TechnicalSnapshot
from models.schemas import (
    AssetClass,
    CompositeAssetScore,
    ScenarioAssetView,
    SentimentDirection,
    WeeklyAssetScore,
)

logger = logging.getLogger(__name__)

# Component weights
W_NARRATIVE = 0.40
W_TECHNICAL = 0.25
W_SCENARIO = 0.20
W_CONTRARIAN = 0.15

# Contrarian bonus/penalty
CONTRARIAN_BONUS = 0.3
ALIGNED_PENALTY = -0.1


def _technical_score(snapshot: TechnicalSnapshot | None) -> float:
    """Map technical indicators to a ±1.0 score.

    Each indicator votes bullish (+1) or bearish (-1):
    - RSI oversold → bullish, overbought → bearish
    - MACD histogram > 0 → bullish, < 0 → bearish
    - Price above SMA → bullish, below → bearish

    Score = mean of the three votes.
    """
    if snapshot is None:
        return 0.0

    votes = []

    # RSI
    if snapshot.rsi_label == "Oversold":
        votes.append(1.0)   # contrarian bullish
    elif snapshot.rsi_label == "Overbought":
        votes.append(-1.0)  # contrarian bearish
    elif snapshot.rsi > 50:
        votes.append(0.33)
    else:
        votes.append(-0.33)

    # MACD
    if snapshot.macd_histogram > 0:
        votes.append(1.0)
    else:
        votes.append(-1.0)

    # SMA distance
    if snapshot.sma_20_dist_pct > 0:
        votes.append(1.0)
    else:
        votes.append(-1.0)

    return sum(votes) / len(votes) if votes else 0.0


def _scenario_score(view: ScenarioAssetView | None) -> float:
    """Extract net scenario score, already probability-weighted."""
    if view is None:
        return 0.0
    return view.net_score


def _contrarian_bonus(edge_type: str) -> float:
    """Contrarian edges get a boost; aligned views get a penalty."""
    if edge_type == "contrarian":
        return CONTRARIAN_BONUS
    elif edge_type == "aligned":
        return ALIGNED_PENALTY
    return 0.0


def compute_composite_scores(
    asset_scores: list[WeeklyAssetScore],
    technicals: dict[str, TechnicalSnapshot],
    scenario_views: list[ScenarioAssetView],
    edge_types: dict[str, str],
    calibration_mult: float = 1.0,
) -> list[CompositeAssetScore]:
    """Compute composite scores for all scored assets.

    Parameters
    ----------
    asset_scores : list[WeeklyAssetScore]
        Existing narrative-based scores from sentiment_aggregator.
    technicals : dict[str, TechnicalSnapshot]
        Technical indicators keyed by ticker.
    scenario_views : list[ScenarioAssetView]
        Scenario aggregations for scenario_score component.
    edge_types : dict[str, str]
        Per-ticker edge type from narrative asset sentiments.
    calibration_mult : float
        Calibration multiplier from trade history (default 1.0).

    Returns
    -------
    list[CompositeAssetScore]
        Sorted by abs(composite_score) descending.
    """
    scenario_by_ticker = {sv.ticker: sv for sv in scenario_views}

    results: list[CompositeAssetScore] = []
    for asset in asset_scores:
        nar_score = asset.score  # already ±1.0
        tech_score = _technical_score(technicals.get(asset.ticker))
        scen_score = _scenario_score(scenario_by_ticker.get(asset.ticker))
        cont_bonus = _contrarian_bonus(edge_types.get(asset.ticker, "aligned"))

        composite = (
            W_NARRATIVE * nar_score
            + W_TECHNICAL * tech_score
            + W_SCENARIO * scen_score
            + W_CONTRARIAN * cont_bonus
        )

        # Apply calibration
        composite *= calibration_mult

        # Confidence: average of narrative conviction + scenario probability (if exists)
        sv = scenario_by_ticker.get(asset.ticker)
        if sv and sv.avg_probability > 0:
            confidence = (asset.conviction + sv.avg_probability) / 2
        else:
            confidence = asset.conviction

        # Determine direction from composite score
        if composite > 0.1:
            direction = SentimentDirection.BULLISH
        elif composite < -0.1:
            direction = SentimentDirection.BEARISH
        else:
            direction = SentimentDirection.NEUTRAL

        conflict = sv.conflict_flag if sv else False

        results.append(
            CompositeAssetScore(
                ticker=asset.ticker,
                asset_class=asset.asset_class,
                direction=direction,
                composite_score=round(composite, 4),
                confidence=round(confidence, 4),
                narrative_score=round(nar_score, 4),
                technical_score=round(tech_score, 4),
                scenario_score=round(scen_score, 4),
                contrarian_bonus=round(cont_bonus, 4),
                narrative_count=asset.narrative_count,
                top_narrative=asset.top_narrative,
                conflict_flag=conflict,
                edge_type=edge_types.get(asset.ticker, "aligned"),
            )
        )

    results.sort(key=lambda s: abs(s.composite_score), reverse=True)
    logger.info(
        "Composite scores: %s",
        ", ".join(f"{r.ticker}={r.composite_score:+.3f}" for r in results[:5]),
    )
    return results
