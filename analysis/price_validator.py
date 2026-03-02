"""Compare predicted sentiment direction vs actual weekly returns."""

import logging

from models.schemas import (
    AssetClass,
    PriceValidation,
    SentimentDirection,
    WeeklyAssetScore,
)

logger = logging.getLogger(__name__)


def _direction_threshold(asset_class: AssetClass) -> float:
    """Minimum weekly return % to count as directional."""
    if asset_class == AssetClass.CRYPTO:
        return 2.0   # crypto needs >2% to be directional
    return 0.25       # traditional assets


def validate_predictions(
    asset_scores: list[WeeklyAssetScore],
    actual_returns: dict[str, float],
) -> list[PriceValidation]:
    """Compare sentiment predictions against actual weekly returns.

    Args:
        asset_scores: Predicted directional sentiment per asset.
        actual_returns: Dict of ticker/name → weekly return percentage.
    """
    validations: list[PriceValidation] = []

    for score in asset_scores:
        # Look up actual return by ticker name
        actual_pct = actual_returns.get(score.ticker)
        if actual_pct is None:
            continue

        # Determine actual direction (crypto needs a wider threshold)
        threshold = _direction_threshold(score.asset_class)
        if actual_pct > threshold:
            actual_dir = SentimentDirection.BULLISH
        elif actual_pct < -threshold:
            actual_dir = SentimentDirection.BEARISH
        else:
            actual_dir = SentimentDirection.NEUTRAL

        # Did we get the direction right?
        hit = False
        if score.direction == SentimentDirection.NEUTRAL:
            hit = actual_dir == SentimentDirection.NEUTRAL
        elif score.direction == actual_dir:
            hit = True

        validations.append(
            PriceValidation(
                ticker=score.ticker,
                asset_class=score.asset_class,
                predicted_direction=score.direction,
                predicted_score=score.score,
                actual_return_pct=round(actual_pct, 4),
                actual_direction=actual_dir,
                hit=hit,
            )
        )

    return validations


def compute_hit_rate(validations: list[PriceValidation]) -> dict:
    """Compute overall and per-asset-class hit rates."""
    if not validations:
        return {"overall": 0.0, "by_class": {}, "total": 0}

    total = len(validations)
    hits = sum(1 for v in validations if v.hit)

    by_class: dict[str, dict] = {}
    for v in validations:
        ac = v.asset_class.value
        if ac not in by_class:
            by_class[ac] = {"hits": 0, "total": 0}
        by_class[ac]["total"] += 1
        if v.hit:
            by_class[ac]["hits"] += 1

    return {
        "overall": round(hits / total, 4) if total > 0 else 0.0,
        "by_class": {
            ac: round(d["hits"] / d["total"], 4) if d["total"] > 0 else 0.0
            for ac, d in by_class.items()
        },
        "total": total,
        "hits": hits,
    }
