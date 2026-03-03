"""Aggregate active scenarios into per-asset scenario views."""

import logging

from models.schemas import (
    ActiveScenario,
    AssetScenarioEntry,
    ScenarioAssetView,
    SentimentDirection,
)

logger = logging.getLogger(__name__)


def aggregate_scenarios(
    active_scenarios: list[ActiveScenario],
) -> list[ScenarioAssetView]:
    """Build per-asset scenario views from active scenarios.

    For each asset that appears in any active scenario:
    - Collect all scenario entries (mechanism, probability, direction, magnitude)
    - Sort by probability descending
    - Compute net_score as probability-weighted directional score
    - Detect conflict_flag when scenarios with probability >= 0.2 disagree on direction
    """
    if not active_scenarios:
        return []

    # Collect entries per ticker
    ticker_entries: dict[str, list[tuple[str, AssetScenarioEntry]]] = {}  # ticker -> [(asset_class, entry)]

    for scenario in active_scenarios:
        for impact in scenario.asset_impacts:
            entry = AssetScenarioEntry(
                mechanism_id=scenario.mechanism_id,
                mechanism_name=scenario.mechanism_name,
                category=scenario.category,
                probability=scenario.probability,
                direction=impact.direction,
                magnitude=impact.magnitude,
                conviction=impact.conviction,
                rationale=impact.rationale,
                trigger_evidence=scenario.trigger_evidence,
                chain_stage=scenario.current_stage,
                chain_progress=scenario.chain_progress,
                watch_items=scenario.watch_items,
            )
            ticker_entries.setdefault(impact.ticker, []).append(
                (impact.asset_class.value, entry)
            )

    views: list[ScenarioAssetView] = []
    for ticker, entries in ticker_entries.items():
        asset_class_val = entries[0][0]  # use first occurrence
        scenario_list = [e for _, e in entries]

        # Sort by probability descending
        scenario_list.sort(key=lambda e: e.probability, reverse=True)

        # Compute net_score: probability-weighted directional score
        # bullish = +1, bearish = -1, neutral = 0
        net_score = 0.0
        for entry in scenario_list:
            direction_sign = {
                SentimentDirection.BULLISH: 1.0,
                SentimentDirection.BEARISH: -1.0,
                SentimentDirection.NEUTRAL: 0.0,
            }.get(entry.direction, 0.0)
            net_score += entry.probability * entry.magnitude * direction_sign

        # Determine net direction
        if net_score > 0.15:
            net_direction = SentimentDirection.BULLISH
        elif net_score < -0.15:
            net_direction = SentimentDirection.BEARISH
        else:
            net_direction = SentimentDirection.NEUTRAL

        # Average probability across scenarios for this asset
        avg_probability = (
            sum(e.probability for e in scenario_list) / len(scenario_list)
            if scenario_list
            else 0.0
        )

        # Detect conflicts: scenarios with probability >= 0.2 disagree on direction
        significant_directions = {
            e.direction
            for e in scenario_list
            if e.probability >= 0.2 and e.direction != SentimentDirection.NEUTRAL
        }
        conflict_flag = len(significant_directions) > 1

        # Dominant scenario
        dominant = scenario_list[0].mechanism_name if scenario_list else ""

        from models.schemas import AssetClass
        views.append(
            ScenarioAssetView(
                ticker=ticker,
                asset_class=AssetClass(asset_class_val),
                scenarios=scenario_list,
                net_direction=net_direction,
                net_score=round(net_score, 4),
                avg_probability=round(avg_probability, 4),
                dominant_scenario=dominant,
                scenario_count=len(scenario_list),
                conflict_flag=conflict_flag,
            )
        )

    # Sort by abs(net_score) descending
    views.sort(key=lambda v: abs(v.net_score), reverse=True)

    logger.info("Aggregated scenarios for %d assets", len(views))
    return views
