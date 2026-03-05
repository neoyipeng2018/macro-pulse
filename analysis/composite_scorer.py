"""LEGACY — only used by run_pipeline_legacy(). Composite scoring: combine narrative, technical, and scenario signals.

Three weighted components (50/25/25) plus a divergence-scaled contrarian nudge,
clamped to [-1.0, +1.0].

The nudge is proportional to how non-consensus we are (divergence magnitude),
replacing the old flat +0.10/-0.05 approach.
"""

from __future__ import annotations

import logging
import math

from analysis.technicals import TechnicalSnapshot
from models.schemas import (
    AssetClass,
    CompositeAssetScore,
    ConsensusScore,
    NonConsensusView,
    ScenarioAssetView,
    SentimentDirection,
    WeeklyAssetScore,
)

logger = logging.getLogger(__name__)

# Component weights
W_NARRATIVE = 0.50
W_TECHNICAL = 0.25
W_SCENARIO = 0.25


def _technical_score(snapshot: TechnicalSnapshot | None) -> float:
    """Map technical indicators to a ±1.0 score.

    Each indicator casts a binary vote: +1 (bullish) or -1 (bearish).
    Score = mean of the three votes.
    """
    if snapshot is None:
        return 0.0

    votes = []

    # RSI: binary vote based on position relative to 50
    if snapshot.rsi > 50:
        votes.append(1.0)
    else:
        votes.append(-1.0)

    # MACD: binary vote based on histogram sign
    if snapshot.macd_histogram > 0:
        votes.append(1.0)
    else:
        votes.append(-1.0)

    # SMA distance: binary vote based on price vs SMA
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


def _divergence_nudge(
    our_score: float,
    consensus_score: float | None,
    edge_type: str,
) -> float:
    """Divergence-scaled nudge replacing the old flat contrarian bonus.

    When consensus data is available, the nudge scales with divergence magnitude:
    - |divergence| > 0.5: ±0.15 (strong conviction for high divergence)
    - |divergence| > 0.2: ±0.08 (moderate bonus)
    - |divergence| <= 0.2: -0.05 (penalty for consensus-following)

    Falls back to flat nudge when no consensus data is available.
    """
    if consensus_score is None:
        # Fallback: flat nudge (legacy behavior)
        if edge_type == "contrarian":
            return 0.10
        elif edge_type == "aligned":
            return -0.05
        return 0.0

    divergence = our_score - consensus_score
    abs_div = abs(divergence)
    sign = 1.0 if our_score >= 0 else -1.0

    if abs_div > 0.5:
        return 0.15 * sign
    elif abs_div > 0.2:
        return 0.08 * sign
    else:
        return -0.05 * sign


def _nc_validity_nudge(
    ticker: str,
    nc_views: dict[str, NonConsensusView],
) -> float:
    """Nudge based on non-consensus validity from Phase 2."""
    ncv = nc_views.get(ticker)
    if ncv is None:
        return -0.05
    return 0.05 + ncv.validity_score * 0.15


def compute_composite_scores(
    asset_scores: list[WeeklyAssetScore],
    technicals: dict[str, TechnicalSnapshot],
    scenario_views: list[ScenarioAssetView],
    edge_types: dict[str, str],
    consensus_scores: list[ConsensusScore] | None = None,
    non_consensus_views: dict[str, NonConsensusView] | None = None,
) -> list[CompositeAssetScore]:
    """Compute composite scores for all scored assets.

    When non_consensus_views is provided (three-phase pipeline), uses
    NC validity-based nudge. Otherwise falls back to divergence-based nudge.
    """
    scenario_by_ticker = {sv.ticker: sv for sv in scenario_views}
    consensus_by_ticker: dict[str, float] = {}
    if consensus_scores:
        consensus_by_ticker = {cs.ticker: cs.consensus_score for cs in consensus_scores}

    results: list[CompositeAssetScore] = []
    for asset in asset_scores:
        nar_score = asset.score
        tech_score = _technical_score(technicals.get(asset.ticker))
        scen_score = _scenario_score(scenario_by_ticker.get(asset.ticker))

        pre_nudge = (
            W_NARRATIVE * nar_score
            + W_TECHNICAL * tech_score
            + W_SCENARIO * scen_score
        )

        if non_consensus_views is not None:
            nudge = _nc_validity_nudge(asset.ticker, non_consensus_views)
        else:
            nudge = _divergence_nudge(
                our_score=pre_nudge,
                consensus_score=consensus_by_ticker.get(asset.ticker),
                edge_type=edge_types.get(asset.ticker, "aligned"),
            )

        composite = max(-1.0, min(1.0, pre_nudge + nudge))

        if composite > 0.15:
            direction = SentimentDirection.BULLISH
        elif composite < -0.15:
            direction = SentimentDirection.BEARISH
        else:
            direction = SentimentDirection.NEUTRAL

        sv = scenario_by_ticker.get(asset.ticker)
        conflict = sv.conflict_flag if sv else False

        results.append(
            CompositeAssetScore(
                ticker=asset.ticker,
                asset_class=asset.asset_class,
                direction=direction,
                composite_score=round(composite, 4),
                narrative_score=round(nar_score, 4),
                technical_score=round(tech_score, 4),
                scenario_score=round(scen_score, 4),
                contrarian_bonus=round(nudge, 4),
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
