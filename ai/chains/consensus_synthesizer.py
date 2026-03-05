"""Synthesize qualitative consensus narrative from positioning + narrative data."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from langchain_core.language_models import BaseChatModel

from ai.prompts.templates import CONSENSUS_SYNTHESIS_PROMPT
from models.schemas import (
    AssetClass,
    ConsensusScore,
    ConsensusView,
    SentimentDirection,
    Signal,
)

logger = logging.getLogger(__name__)

_CRYPTO_TICKERS = {"Bitcoin", "Ethereum", "Solana"}


def synthesize_consensus(
    consensus_scores: list[ConsensusScore],
    positioning_signals: list[Signal],
    narrative_signals: list[Signal],
    market_signals: list[Signal],
    llm: BaseChatModel,
) -> list[ConsensusView]:
    """Build complete consensus picture: positioning + narrative + LLM synthesis.

    Parameters
    ----------
    consensus_scores
        Quantitative consensus from consensus_scorer.py
    positioning_signals
        Quantitative positioning signals (options, derivatives, ETF, funding, COT)
    narrative_signals
        Qualitative consensus signals (news, Reddit, fear_greed, prediction markets,
        central bank, economic calendar)
    market_signals
        Price action signals (market_data source)
    llm
        LLM for consensus synthesis
    """
    scores_text = _format_quant_scores(consensus_scores)

    positioning_text = "\n\n".join(
        f"[{s.source.value}] {s.title}\n{s.content[:500]}"
        for s in positioning_signals
    )

    narrative_text = "\n\n".join(
        f"[{s.source.value}] {s.title}\n{s.content[:400]}"
        for s in narrative_signals
    )

    market_text = "\n\n".join(
        f"{s.title}\n{s.content[:300]}"
        for s in market_signals
    )

    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    chain = CONSENSUS_SYNTHESIS_PROMPT | llm
    response = chain.invoke({
        "run_date": run_date,
        "consensus_scores_text": scores_text,
        "positioning_signals_text": positioning_text,
        "narrative_signals_text": narrative_text,
        "market_data_text": market_text,
    })

    try:
        raw = response.content
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse consensus synthesis: %s", e)
        return _fallback_consensus_views(consensus_scores)

    quant_map = {cs.ticker: cs for cs in consensus_scores}
    views: list[ConsensusView] = []

    for item in parsed:
        try:
            ticker = item["ticker"]
            quant = quant_map.get(ticker)

            views.append(ConsensusView(
                ticker=ticker,
                asset_class=_ticker_to_class(ticker),
                quant_score=quant.consensus_score if quant else 0.0,
                quant_direction=quant.consensus_direction if quant else "neutral",
                quant_components=quant.components if quant else {},
                positioning_consensus=item.get("positioning_consensus", ""),
                positioning_summary=item.get("positioning_summary", ""),
                narrative_consensus=item.get("narrative_consensus", ""),
                market_narrative=item.get("market_narrative", ""),
                consensus_coherence=item.get("consensus_coherence", "aligned"),
                coherence_detail=item.get("coherence_detail", ""),
                key_levels=item.get("key_levels", []),
                priced_in=item.get("priced_in", []),
                not_priced_in=item.get("not_priced_in", []),
                consensus_direction=SentimentDirection(
                    item.get("consensus_direction", "neutral")
                ),
                consensus_confidence=float(item.get("consensus_confidence", 0.5)),
            ))
        except (KeyError, ValueError) as e:
            logger.warning("Error parsing consensus view: %s", e)

    seen = {v.ticker for v in views}
    for cs in consensus_scores:
        if cs.ticker not in seen:
            views.append(ConsensusView(
                ticker=cs.ticker,
                asset_class=_ticker_to_class(cs.ticker),
                quant_score=cs.consensus_score,
                quant_direction=cs.consensus_direction,
                quant_components=cs.components,
                consensus_direction=SentimentDirection(cs.consensus_direction),
            ))

    logger.info(
        "Consensus synthesis: %s",
        ", ".join(
            f"{v.ticker}={v.consensus_direction.value}(coherence={v.consensus_coherence})"
            for v in views
        ),
    )
    return views


def _format_quant_scores(scores: list[ConsensusScore]) -> str:
    lines: list[str] = []
    for cs in scores:
        lines.append(f"{cs.ticker}: score={cs.consensus_score:+.2f} ({cs.consensus_direction})")
        for name, val in cs.components.items():
            lines.append(f"  {name}: {val:+.2f}")
        if cs.funding_rate_7d:
            lines.append(f"  raw_funding_7d: {cs.funding_rate_7d:+.4f}%")
        if cs.top_trader_ls_ratio:
            lines.append(f"  raw_top_trader_ls: {cs.top_trader_ls_ratio:.2f}")
        if cs.etf_flow_5d:
            lines.append(f"  raw_etf_5d_flow: ${cs.etf_flow_5d:+.0f}M")
        if cs.put_call_ratio:
            lines.append(f"  raw_put_call: {cs.put_call_ratio:.2f}")
        lines.append("")
    return "\n".join(lines)


def _fallback_consensus_views(
    consensus_scores: list[ConsensusScore],
) -> list[ConsensusView]:
    return [
        ConsensusView(
            ticker=cs.ticker,
            asset_class=_ticker_to_class(cs.ticker),
            quant_score=cs.consensus_score,
            quant_direction=cs.consensus_direction,
            quant_components=cs.components,
            consensus_direction=SentimentDirection(cs.consensus_direction),
        )
        for cs in consensus_scores
    ]


def _ticker_to_class(ticker: str) -> AssetClass:
    if ticker in _CRYPTO_TICKERS:
        return AssetClass.CRYPTO
    return AssetClass.CRYPTO
