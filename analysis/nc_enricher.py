"""Enrich non-consensus views with mechanism links and consensus context."""

from models.schemas import (
    ActiveScenario,
    ConsensusScore,
    ConsensusView,
    EconomicRegime,
    NonConsensusView,
)

_STAGE_ORDER = {"early": 0, "mid": 1, "late": 2, "complete": 3}


def enrich_nc_views(
    nc_views: list[NonConsensusView],
    active_scenarios: list[ActiveScenario],
    quant_scores: list[ConsensusScore],
    consensus_views: list[ConsensusView],
    regime: EconomicRegime,
) -> list[NonConsensusView]:
    """Link NC views to supporting mechanisms and consensus data."""
    quant_by_ticker: dict[str, ConsensusScore] = {cs.ticker: cs for cs in quant_scores}
    cv_by_ticker: dict[str, ConsensusView] = {cv.ticker: cv for cv in consensus_views}

    for ncv in nc_views:
        supporting: list[str] = []
        earliest_stage = "complete"

        for scenario in active_scenarios:
            for impact in scenario.asset_impacts:
                if impact.ticker == ncv.ticker and impact.direction == ncv.our_direction:
                    supporting.append(scenario.mechanism_id)
                    if _STAGE_ORDER.get(scenario.current_stage, 3) < _STAGE_ORDER.get(earliest_stage, 3):
                        earliest_stage = scenario.current_stage
                    break

        ncv.supporting_mechanisms = supporting
        ncv.mechanism_stage = earliest_stage if supporting else ""

        qs = quant_by_ticker.get(ncv.ticker)
        if qs:
            ncv.consensus_quant_score = qs.consensus_score

        cv = cv_by_ticker.get(ncv.ticker)
        if cv:
            ncv.consensus_coherence = cv.consensus_coherence

        ncv.regime_context = regime.value

    return nc_views
