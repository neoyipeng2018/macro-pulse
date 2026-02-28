"""Classify the current economic regime from extracted narratives."""

import json
import logging

from langchain_core.language_models import BaseChatModel

from ai.prompts.templates import REGIME_CLASSIFICATION_PROMPT, WEEKLY_SUMMARY_PROMPT
from models.schemas import EconomicRegime, Narrative, WeeklyAssetScore

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
