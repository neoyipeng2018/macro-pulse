"""Match incoming signals to known transmission mechanisms via LLM."""

import json
import logging
import uuid
from datetime import datetime

from langchain_core.language_models import BaseChatModel

from ai.prompts.templates import MECHANISM_MATCHING_PROMPT
from models.schemas import (
    ActiveScenario,
    AssetClass,
    ChainStepProgress,
    ScenarioAssetImpact,
    SentimentDirection,
    Signal,
    TransmissionMechanism,
)

logger = logging.getLogger(__name__)


def _format_mechanisms(mechanisms: list[TransmissionMechanism]) -> str:
    """Render the mechanism catalog as readable text for the LLM prompt."""
    parts: list[str] = []
    for m in mechanisms:
        triggers = ", ".join(m.trigger_sources) if m.trigger_sources else "any"
        keywords = ", ".join(m.trigger_keywords[:10]) if m.trigger_keywords else ""

        steps = ""
        for i, step in enumerate(m.chain_steps):
            steps += f"    {i}. {step.description} (observe: {step.observable}, lag {step.lag_days[0]}-{step.lag_days[1]}d)\n"

        impacts = ""
        for imp in m.asset_impacts:
            impacts += f"    - {imp.ticker} ({imp.asset_class.value}): {imp.direction.value}, sensitivity={imp.sensitivity}\n"

        confirm = "; ".join(m.confirmation_criteria) if m.confirmation_criteria else "n/a"
        invalid = "; ".join(m.invalidation_criteria) if m.invalidation_criteria else "n/a"

        parts.append(
            f"[{m.id}] {m.name} ({m.category})\n"
            f"  {m.description}\n"
            f"  Triggers: sources={triggers}; keywords={keywords}\n"
            f"  Chain:\n{steps}"
            f"  Asset impacts:\n{impacts}"
            f"  Confirm: {confirm}\n"
            f"  Invalidate: {invalid}\n"
        )

    return "\n".join(parts)


def match_mechanisms(
    signals: list[Signal],
    mechanisms: list[TransmissionMechanism],
    llm: BaseChatModel,
) -> list[ActiveScenario]:
    """Match signals to known transmission mechanisms and return active scenarios."""
    if not signals or not mechanisms:
        return []

    # Format signals (same pattern as narrative_extractor)
    signal_text = "\n\n".join(
        f"[{s.id}] ({s.source.value}, {s.timestamp.strftime('%Y-%m-%d')}) {s.title}\n{s.content[:400]}"
        for s in signals
    )

    mechanism_text = _format_mechanisms(mechanisms)
    run_date = datetime.utcnow().strftime("%Y-%m-%d")

    chain = MECHANISM_MATCHING_PROMPT | llm
    response = chain.invoke({
        "signals": signal_text,
        "mechanisms": mechanism_text,
        "run_date": run_date,
    })

    try:
        raw = response.content
        # Handle markdown-wrapped JSON
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse mechanism matcher LLM response: %s", e)
        return []

    scenarios: list[ActiveScenario] = []
    for item in parsed:
        try:
            # Parse chain progress
            chain_progress: list[ChainStepProgress] = []
            for cp in item.get("chain_progress", []):
                if not isinstance(cp, dict):
                    continue
                chain_progress.append(
                    ChainStepProgress(
                        step_index=int(cp.get("step_index", 0)),
                        description=str(cp.get("description", "")),
                        status=str(cp.get("status", "not_started")),
                        evidence=str(cp.get("evidence", "")),
                        confidence=float(cp.get("confidence", 0.0)),
                    )
                )

            # Parse asset impacts
            asset_impacts: list[ScenarioAssetImpact] = []
            for ai_item in item.get("asset_impacts", []):
                if not isinstance(ai_item, dict):
                    continue
                try:
                    asset_impacts.append(
                        ScenarioAssetImpact(
                            ticker=str(ai_item["ticker"]),
                            asset_class=AssetClass(ai_item["asset_class"]),
                            direction=SentimentDirection(ai_item["direction"]),
                            magnitude=float(ai_item.get("magnitude", 0.5)),
                            conviction=float(ai_item.get("conviction", 0.5)),
                            rationale=str(ai_item.get("rationale", "")),
                        )
                    )
                except (KeyError, ValueError) as e:
                    logger.debug("Skipping malformed asset impact: %s", e)
                    continue

            scenario = ActiveScenario(
                id=uuid.uuid4().hex[:12],
                mechanism_id=str(item.get("mechanism_id", "")),
                mechanism_name=str(item.get("mechanism_name", "")),
                category=str(item.get("category", "")),
                probability=float(item.get("probability", 0.5)),
                trigger_signals=list(item.get("trigger_signals", [])),
                trigger_evidence=str(item.get("trigger_evidence", "")),
                chain_progress=chain_progress,
                current_stage=str(item.get("current_stage", "early")),
                expected_magnitude=str(item.get("expected_magnitude", "moderate")),
                asset_impacts=asset_impacts,
                watch_items=list(item.get("watch_items", [])),
                confirmation_status=str(item.get("confirmation_status", "")),
                invalidation_risk=str(item.get("invalidation_risk", "")),
                horizon=str(item.get("horizon", "1 week")),
                confidence=float(item.get("confidence", 0.5)),
            )
            scenarios.append(scenario)
        except (KeyError, ValueError) as e:
            logger.warning("Error parsing active scenario: %s", e)
            continue

    logger.info("Matched %d active scenarios from %d mechanisms", len(scenarios), len(mechanisms))
    return scenarios
