"""Extract macro narratives with per-asset directional sentiment from raw signals."""

import json
import logging
import uuid
from datetime import datetime

from langchain_core.language_models import BaseChatModel

from ai.prompts.templates import NARRATIVE_EXTRACTION_PROMPT
from models.schemas import AssetClass, AssetSentiment, EdgeType, Narrative, SentimentDirection, Signal

logger = logging.getLogger(__name__)


def extract_narratives(signals: list[Signal], llm: BaseChatModel) -> list[Narrative]:
    """Process a batch of signals and extract macro narratives with asset sentiments."""
    if not signals:
        return []

    # Format signals for the prompt, including timestamps for temporal context
    signal_text = "\n\n".join(
        f"[{s.id}] ({s.source.value}, {s.timestamp.strftime('%Y-%m-%d')}) {s.title}\n{s.content[:400]}"
        for s in signals
    )

    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    chain = NARRATIVE_EXTRACTION_PROMPT | llm
    response = chain.invoke({"signals": signal_text, "run_date": run_date})

    # Build a lookup for signals by ID
    signal_map = {s.id: s for s in signals}

    try:
        raw = response.content
        # Handle markdown-wrapped JSON
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse LLM response: %s", e)
        return []

    narratives: list[Narrative] = []
    for item in parsed:
        try:
            matched_signals = [
                signal_map[sid]
                for sid in item.get("signal_ids", [])
                if sid in signal_map
            ]

            # Backfill: ensure each asset sentiment has its market_data
            # signal attached (the LLM sometimes omits them).
            matched_ids = {s.id for s in matched_signals}
            for sent in item.get("asset_sentiments", []):
                ticker = str(sent.get("ticker", ""))
                if not ticker:
                    continue
                # Check if a market_data signal for this ticker is already matched
                has_market = any(
                    s.source.value == "market_data"
                    and s.metadata.get("ticker") == ticker
                    for s in matched_signals
                )
                if has_market:
                    continue
                # Also match by name (e.g. "Bitcoin" → metadata ticker "BTC-USD")
                has_market_by_name = any(
                    s.source.value == "market_data"
                    and ticker.lower() in s.title.lower()
                    for s in matched_signals
                )
                if has_market_by_name:
                    continue
                # Find the missing market_data signal in the full pool
                for s in signals:
                    if s.id in matched_ids:
                        continue
                    if s.source.value != "market_data":
                        continue
                    meta_ticker = s.metadata.get("ticker", "")
                    if meta_ticker == ticker or ticker.lower() in s.title.lower():
                        matched_signals.append(s)
                        matched_ids.add(s.id)
                        break

            # Parse asset sentiments
            asset_sentiments: list[AssetSentiment] = []
            for sent in item.get("asset_sentiments", []):
                if not isinstance(sent, dict):
                    continue
                try:
                    asset_sentiments.append(
                        AssetSentiment(
                            ticker=str(sent["ticker"]),
                            asset_class=AssetClass(sent["asset_class"]),
                            direction=SentimentDirection(sent["direction"]),
                            conviction=float(sent.get("conviction", 0.5)),
                            rationale=str(sent.get("rationale", "")),
                            consensus_view=str(sent.get("consensus_view", "")),
                            edge_type=str(sent.get("edge_type", "aligned")),
                            edge_rationale=str(sent.get("edge_rationale", "")),
                            catalyst=str(sent.get("catalyst", "")),
                            exit_condition=str(sent.get("exit_condition", "")),
                        )
                    )
                except (KeyError, ValueError) as e:
                    logger.debug("Skipping malformed asset sentiment: %s", e)
                    continue

            # Parse affected asset classes
            affected = []
            for a in item.get("affected_asset_classes", []):
                try:
                    affected.append(AssetClass(a))
                except ValueError:
                    continue

            # Parse edge type
            try:
                edge_type = EdgeType(item.get("edge_type", "aligned"))
            except ValueError:
                edge_type = EdgeType.ALIGNED

            narrative = Narrative(
                id=uuid.uuid4().hex[:12],
                title=item["title"],
                summary=item["summary"],
                asset_sentiments=asset_sentiments,
                affected_asset_classes=affected,
                signals=matched_signals,
                horizon=item.get("horizon", "1-4 weeks"),
                confidence=float(item.get("confidence", 0.5)),
                trend=item.get("trend", "stable"),
                consensus_view=str(item.get("consensus_view", "")),
                consensus_sources=list(item.get("consensus_sources", [])),
                edge_type=edge_type,
                edge_rationale=str(item.get("edge_rationale", "")),
                first_seen=datetime.utcnow(),
                last_updated=datetime.utcnow(),
            )
            narratives.append(narrative)
        except (KeyError, ValueError) as e:
            logger.warning("Error parsing narrative: %s", e)
            continue

    return narratives
