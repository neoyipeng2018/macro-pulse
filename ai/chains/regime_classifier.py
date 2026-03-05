"""Classify the current economic regime from extracted narratives."""

import json
import logging

from langchain_core.language_models import BaseChatModel

from ai.prompts.templates import (
    REGIME_CLASSIFICATION_PROMPT,
    REGIME_FROM_CONSENSUS_PROMPT,
    SUMMARY_FROM_CONSENSUS_PROMPT,
    WEEKLY_SUMMARY_PROMPT,
)
from models.schemas import (
    ActiveScenario,
    ConsensusView,
    EconomicRegime,
    Narrative,
    NonConsensusView,
    WeeklyAssetScore,
)

logger = logging.getLogger(__name__)


def classify_regime(
    narratives: list[Narrative], llm: BaseChatModel
) -> tuple[EconomicRegime, str, float]:
    """Classify the current economic regime based on narratives.

    Returns (regime, rationale, confidence).
    """
    if not narratives:
        return EconomicRegime.TRANSITION, "No narratives available", 0.0

    # Format narratives for the prompt
    narrative_text = "\n\n".join(
        f"**{n.title}** (confidence: {n.confidence:.1f}, trend: {n.trend})\n"
        f"{n.summary}\n"
        f"Asset sentiments: "
        + ", ".join(
            f"{s.ticker}={s.direction.value}({s.conviction:.1f})"
            for s in n.asset_sentiments
        )
        for n in narratives
    )

    chain = REGIME_CLASSIFICATION_PROMPT | llm
    response = chain.invoke({"narratives": narrative_text})

    try:
        raw = response.content
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())

        regime = EconomicRegime(parsed["regime"])
        rationale = parsed.get("rationale", "")
        confidence = float(parsed.get("confidence", 0.5))
        return regime, rationale, confidence
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to parse regime classification: %s", e)
        return EconomicRegime.TRANSITION, "Failed to classify regime", 0.0


def generate_weekly_summary(
    narratives: list[Narrative],
    asset_scores: list[WeeklyAssetScore],
    regime: EconomicRegime,
    regime_rationale: str,
    llm: BaseChatModel,
) -> str:
    """Generate a concise weekly executive summary."""
    if not narratives:
        return "No narratives available for this week."

    narrative_text = "\n\n".join(
        f"**{n.title}** (confidence: {n.confidence:.1f}, trend: {n.trend}, "
        f"horizon: {n.horizon})\n{n.summary}"
        for n in narratives
    )

    # Sort by absolute score for top movers
    sorted_scores = sorted(asset_scores, key=lambda s: abs(s.score), reverse=True)[:15]
    score_text = "\n".join(
        f"  {s.ticker} ({s.asset_class.value}): {s.score:+.2f} "
        f"[{s.direction.value}, conviction: {s.conviction:.1f}]"
        for s in sorted_scores
    )

    chain = WEEKLY_SUMMARY_PROMPT | llm
    response = chain.invoke({
        "regime": regime.value,
        "regime_rationale": regime_rationale,
        "narratives": narrative_text,
        "asset_scores": score_text,
    })

    return response.content.strip()


def classify_regime_from_consensus(
    consensus_views: list[ConsensusView],
    active_scenarios: list[ActiveScenario],
    llm: BaseChatModel,
) -> tuple[EconomicRegime, str, float]:
    """Classify the current economic regime from consensus views and active mechanisms."""
    if not consensus_views and not active_scenarios:
        return EconomicRegime.TRANSITION, "No consensus or scenario data available", 0.0

    consensus_text = "\n\n".join(
        f"{cv.ticker}: {cv.consensus_direction.value} "
        f"(quant={cv.quant_score:+.2f}, coherence={cv.consensus_coherence})\n"
        f"  Positioning: {cv.positioning_summary}\n"
        f"  Narrative: {cv.market_narrative[:200]}"
        for cv in consensus_views
    ) if consensus_views else "No consensus views available."

    scenario_text = "\n".join(
        f"[{s.mechanism_name}] ({s.category}, prob={s.probability:.0%}, "
        f"stage={s.current_stage}): {s.trigger_evidence[:200]}"
        for s in active_scenarios
    ) if active_scenarios else "No active transmission mechanisms."

    chain = REGIME_FROM_CONSENSUS_PROMPT | llm
    response = chain.invoke({
        "consensus_views": consensus_text,
        "active_scenarios": scenario_text,
    })

    try:
        raw = response.content
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())

        regime = EconomicRegime(parsed["regime"])
        rationale = parsed.get("rationale", "")
        confidence = float(parsed.get("confidence", 0.5))
        return regime, rationale, confidence
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to parse regime classification: %s", e)
        return EconomicRegime.TRANSITION, "Failed to classify regime", 0.0


def generate_summary_from_consensus(
    consensus_views: list[ConsensusView],
    non_consensus_views: list[NonConsensusView],
    active_scenarios: list[ActiveScenario],
    regime: EconomicRegime,
    regime_rationale: str,
    llm: BaseChatModel,
) -> str:
    """Generate a concise weekly summary from consensus + NC views."""
    if not consensus_views and not non_consensus_views:
        return "No data available for this week."

    cv_text = "\n".join(
        f"{cv.ticker}: {cv.consensus_direction.value} (quant={cv.quant_score:+.2f}) "
        f"— {cv.market_narrative[:150]}"
        for cv in consensus_views
    ) if consensus_views else "No consensus views."

    nc_text = "\n".join(
        f"{ncv.ticker}: consensus={ncv.consensus_direction.value} → "
        f"our view={ncv.our_direction.value} ({ncv.edge_type})\n"
        f"  Thesis: {ncv.thesis[:200]}\n"
        f"  Validity: {ncv.validity_score:.0%}, Sources: {ncv.independent_source_count}"
        for ncv in non_consensus_views
    ) if non_consensus_views else "No non-consensus views this week."

    scenario_text = "\n".join(
        f"[{s.mechanism_name}] ({s.category}, prob={s.probability:.0%}, "
        f"stage={s.current_stage})"
        for s in active_scenarios
    ) if active_scenarios else "No active mechanisms."

    chain = SUMMARY_FROM_CONSENSUS_PROMPT | llm
    response = chain.invoke({
        "regime": regime.value,
        "regime_rationale": regime_rationale,
        "consensus_views": cv_text,
        "non_consensus_views": nc_text,
        "active_scenarios": scenario_text,
    })

    return response.content.strip()
