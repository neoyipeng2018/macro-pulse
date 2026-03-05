"""Discover and validate non-consensus views against established consensus."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from langchain_core.language_models import BaseChatModel

from ai.prompts.templates import NON_CONSENSUS_DISCOVERY_PROMPT
from models.schemas import (
    AssetClass,
    ConsensusView,
    EvidenceSource,
    NonConsensusView,
    SentimentDirection,
    Signal,
)

logger = logging.getLogger(__name__)

_CRYPTO_TICKERS = {"Bitcoin", "Ethereum", "Solana"}


def discover_non_consensus(
    consensus_views: list[ConsensusView],
    alpha_signals: list[Signal],
    llm: BaseChatModel,
) -> list[NonConsensusView]:
    """Find where alpha signals disagree with established consensus."""
    if not consensus_views or not alpha_signals:
        logger.warning("Missing consensus views or alpha signals")
        return []

    consensus_text = _format_consensus_views(consensus_views)

    alpha_text = "\n\n".join(
        f"[{s.id}] ({s.source.value}, {s.timestamp.strftime('%Y-%m-%d')}) "
        f"{s.title}\n{s.content[:400]}"
        for s in alpha_signals
    )

    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    chain = NON_CONSENSUS_DISCOVERY_PROMPT | llm
    response = chain.invoke({
        "run_date": run_date,
        "consensus_views_text": consensus_text,
        "alpha_signals_text": alpha_text,
    })

    try:
        raw = response.content
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse non-consensus discovery: %s", e)
        return []

    views: list[NonConsensusView] = []
    for item in parsed:
        try:
            evidence = [
                EvidenceSource(
                    signal_id=ev.get("signal_id", ""),
                    source=ev.get("source", ""),
                    summary=ev.get("summary", ""),
                    strength=float(ev.get("strength", 0.5)),
                )
                for ev in item.get("evidence", [])
                if isinstance(ev, dict)
            ]

            view = NonConsensusView(
                ticker=item["ticker"],
                asset_class=_ticker_to_class(item["ticker"]),
                consensus_direction=SentimentDirection(item["consensus_direction"]),
                consensus_narrative=item.get("consensus_summary", ""),
                our_direction=SentimentDirection(item["our_direction"]),
                our_conviction=float(item.get("our_conviction", 0.5)),
                thesis=item.get("thesis", ""),
                edge_type=item.get("edge_type", "contrarian"),
                evidence=evidence,
                independent_source_count=int(item.get("independent_source_count", 0)),
                has_testable_mechanism=bool(item.get("has_testable_mechanism", False)),
                has_timing_edge=bool(item.get("has_timing_edge", False)),
                has_catalyst=item.get("catalyst", ""),
                invalidation=item.get("invalidation", ""),
                validity_score=float(item.get("validity_score", 0.0)),
                signal_ids=item.get("signal_ids", []),
            )

            if view.independent_source_count < 2:
                logger.info(
                    "Dropping %s non-consensus view: only %d source(s)",
                    view.ticker, view.independent_source_count,
                )
                continue

            views.append(view)

        except (KeyError, ValueError) as e:
            logger.warning("Error parsing non-consensus view: %s", e)
            continue

    views.sort(key=lambda v: v.validity_score, reverse=True)

    logger.info(
        "Discovered %d valid non-consensus views: %s",
        len(views),
        ", ".join(f"{v.ticker} ({v.edge_type}, validity={v.validity_score:.2f})" for v in views),
    )
    return views


def _format_consensus_views(views: list[ConsensusView]) -> str:
    parts: list[str] = []
    for cv in views:
        parts.append(
            f"--- {cv.ticker} ({cv.asset_class.value}) ---\n"
            f"Consensus direction: {cv.consensus_direction.value} "
            f"(quant score: {cv.quant_score:+.2f}, confidence: {cv.consensus_confidence:.1f})\n"
            f"Consensus coherence: {cv.consensus_coherence} — {cv.coherence_detail}\n"
            f"Positioning consensus: {cv.positioning_consensus}\n"
            f"Narrative consensus: {cv.narrative_consensus}\n"
            f"Market narrative: {cv.market_narrative}\n"
            f"Key levels: {', '.join(cv.key_levels)}\n"
            f"Priced in: {', '.join(cv.priced_in)}\n"
            f"Not priced in: {', '.join(cv.not_priced_in)}"
        )
    return "\n\n".join(parts)


def _ticker_to_class(ticker: str) -> AssetClass:
    if ticker in _CRYPTO_TICKERS:
        return AssetClass.CRYPTO
    return AssetClass.CRYPTO
