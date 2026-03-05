"""LEGACY — only used by run_pipeline_legacy(). Deterministic aggregation of per-asset sentiment across narratives."""

from models.schemas import (
    AssetClass,
    Narrative,
    SentimentDirection,
    WeeklyAssetScore,
)


def aggregate_asset_scores(narratives: list[Narrative]) -> list[WeeklyAssetScore]:
    """Aggregate per-asset sentiment across all narratives into weekly scores.

    Each asset gets a score from -1 (max bearish) to +1 (max bullish),
    weighted by conviction and narrative confidence.
    """
    # Collect all sentiment votes per ticker
    ticker_votes: dict[str, list[dict]] = {}
    ticker_class: dict[str, AssetClass] = {}

    for narrative in narratives:
        for sent in narrative.asset_sentiments:
            key = sent.ticker
            if key not in ticker_votes:
                ticker_votes[key] = []
                ticker_class[key] = sent.asset_class

            # Direction as numeric: bullish=+1, bearish=-1, neutral=0
            dir_val = {
                SentimentDirection.BULLISH: 1.0,
                SentimentDirection.BEARISH: -1.0,
                SentimentDirection.NEUTRAL: 0.0,
            }[sent.direction]

            weight = sent.conviction * narrative.confidence

            ticker_votes[key].append({
                "direction_val": dir_val,
                "weight": weight,
                "conviction": sent.conviction,
                "narrative_title": narrative.title,
                "narrative_confidence": narrative.confidence,
            })

    # Compute weighted average score per ticker
    scores: list[WeeklyAssetScore] = []
    for ticker, votes in ticker_votes.items():
        total_weight = sum(v["weight"] for v in votes)
        if total_weight == 0:
            continue

        weighted_score = sum(v["direction_val"] * v["weight"] for v in votes) / total_weight
        avg_conviction = sum(v["conviction"] for v in votes) / len(votes)

        # Determine direction from score
        if weighted_score > 0.15:
            direction = SentimentDirection.BULLISH
        elif weighted_score < -0.15:
            direction = SentimentDirection.BEARISH
        else:
            direction = SentimentDirection.NEUTRAL

        # Find highest-conviction narrative for this ticker
        best_vote = max(votes, key=lambda v: v["weight"])

        scores.append(
            WeeklyAssetScore(
                ticker=ticker,
                asset_class=ticker_class[ticker],
                direction=direction,
                score=round(weighted_score, 4),
                conviction=round(avg_conviction, 4),
                narrative_count=len(votes),
                top_narrative=best_vote["narrative_title"],
            )
        )

    # Sort by absolute score descending
    scores.sort(key=lambda s: abs(s.score), reverse=True)
    return scores
