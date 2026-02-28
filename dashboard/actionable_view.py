"""Actionable single-page view — what assets will do well, for how long, and why."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import streamlit as st

from models.schemas import (
    AssetClass,
    Narrative,
    SentimentDirection,
    WeeklyAssetScore,
    WeeklyReport,
)

ASSET_LABELS = {
    AssetClass.FX: "FX",
    AssetClass.METALS: "Metals",
    AssetClass.ENERGY: "Energy",
    AssetClass.CRYPTO: "Crypto",
    AssetClass.INDICES: "Indices",
    AssetClass.BONDS: "Bonds",
}


@dataclass
class NarrativeContext:
    """A single narrative's contribution to an asset's view."""

    narrative_title: str
    confidence: float
    horizon: str
    trend: str
    rationale: str


@dataclass
class AssetIntel:
    """Enriched per-asset intelligence combining score + narrative context."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    score: float
    conviction: float
    narrative_count: int
    horizon: str  # from highest-confidence matching narrative
    trend: str  # majority vote across narratives
    primary_rationale: str  # from highest-confidence matching narrative
    source_narrative: str  # title of that narrative
    extra_narratives: list[NarrativeContext] = field(default_factory=list)


def build_asset_intel(report: WeeklyReport) -> list[AssetIntel]:
    """Link WeeklyAssetScore back to Narrative data to enrich each asset."""

    # Index narratives by ticker → list of (narrative, asset_sentiment)
    ticker_narratives: dict[str, list[tuple[Narrative, object]]] = {}
    for narrative in report.narratives:
        for asent in narrative.asset_sentiments:
            ticker_narratives.setdefault(asent.ticker, []).append(
                (narrative, asent)
            )

    results: list[AssetIntel] = []
    for score in report.asset_scores:
        entries = ticker_narratives.get(score.ticker, [])

        # Sort by narrative confidence descending to find the primary one
        entries.sort(key=lambda x: x[0].confidence, reverse=True)

        if entries:
            primary_narr, primary_asent = entries[0]
            horizon = primary_narr.horizon
            primary_rationale = primary_asent.rationale or primary_narr.summary
            source_narrative = primary_narr.title

            # Majority vote for trend
            trend_counts = Counter(n.trend for n, _ in entries)
            trend = trend_counts.most_common(1)[0][0]

            # Build extra narratives (skip the primary)
            extra = []
            for narr, asent in entries[1:]:
                extra.append(
                    NarrativeContext(
                        narrative_title=narr.title,
                        confidence=narr.confidence,
                        horizon=narr.horizon,
                        trend=narr.trend,
                        rationale=asent.rationale or narr.summary,
                    )
                )
        else:
            horizon = "—"
            trend = "stable"
            primary_rationale = ""
            source_narrative = score.top_narrative
            extra = []

        results.append(
            AssetIntel(
                ticker=score.ticker,
                asset_class=score.asset_class,
                direction=score.direction,
                score=score.score,
                conviction=score.conviction,
                narrative_count=score.narrative_count,
                horizon=horizon,
                trend=trend,
                primary_rationale=primary_rationale,
                source_narrative=source_narrative,
                extra_narratives=extra,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_regime_banner(report: WeeklyReport) -> None:
    """Compact regime badge + rationale + executive summary."""
    regime_val = report.regime.value.replace("_", " ").upper()
    regime_class = report.regime.value
    rationale = report.regime_rationale or ""
    summary = report.summary or ""

    # Combine rationale and summary — keep it compact
    detail = rationale
    if summary and summary != rationale:
        detail = f"{rationale}  ·  {summary}" if rationale else summary

    st.markdown(
        f'<div class="regime-banner">'
        f'<span class="regime-badge regime-{regime_class}">{regime_val}</span>'
        f'<span class="regime-summary">{detail}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _conviction_bar_html(conviction: float, direction: SentimentDirection) -> str:
    pct = int(conviction * 100)
    dir_class = direction.value
    return (
        f'<span class="conviction-bar-bg">'
        f'<span class="conviction-bar-fill conviction-bar-fill-{dir_class}" '
        f'style="width:{pct}%"></span></span>'
        f'<span class="conviction-label">{conviction:.0%}</span>'
    )


def _extra_narratives_html(extra: list[NarrativeContext]) -> str:
    """Build HTML <details> block for additional narratives."""
    count = len(extra)
    label = f"{count} more narrative{'s' if count != 1 else ''}"
    items = ""
    for ctx in extra:
        trend_cls = f"trend-{ctx.trend}"
        items += (
            f'<div style="margin-bottom:8px;">'
            f'<span style="color:#e0e4ec;font-size:0.8rem;font-weight:600;">'
            f"{ctx.narrative_title}</span> "
            f'<span class="horizon-chip">{ctx.horizon}</span> '
            f'<span class="trend-chip {trend_cls}">{ctx.trend}</span> '
            f'<span style="color:#4a5568;font-size:0.65rem;">'
            f"conf {ctx.confidence:.0%}</span>"
            f'<div class="rationale-text">{ctx.rationale}</div>'
            f"</div>"
        )
    return (
        f'<details class="extra-narratives">'
        f"<summary>{label}</summary>"
        f'<div style="padding-top:8px;">{items}</div>'
        f"</details>"
    )


def _render_asset_card(intel: AssetIntel) -> None:
    """Render a single asset intel card."""
    dir_val = intel.direction.value
    score_sign = "+" if intel.score > 0 else ""
    score_class = f"score-{dir_val}"
    trend_class = f"trend-{intel.trend}"
    ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)

    extra_html = ""
    if intel.extra_narratives:
        extra_html = _extra_narratives_html(intel.extra_narratives)

    card_html = (
        f'<div class="asset-card asset-card-{dir_val}">'
        # Header row
        f'<div class="asset-card-header">'
        f'<span class="asset-ticker">{intel.ticker}</span>'
        f'<span class="asset-class-label">{ac_label}</span>'
        f'<span class="badge badge-{dir_val}">{dir_val}</span>'
        f'<span class="{score_class} score-value">{score_sign}{intel.score:.2f}</span>'
        f'{_conviction_bar_html(intel.conviction, intel.direction)}'
        f'<span class="horizon-chip">{intel.horizon}</span>'
        f'<span class="trend-chip {trend_class}">{intel.trend}</span>'
        f"</div>"
        # Rationale
        f'<div class="rationale-text">{intel.primary_rationale}</div>'
        # Source
        f'<div class="source-narrative">via {intel.source_narrative}'
        f" · {intel.narrative_count} narrative{'s' if intel.narrative_count != 1 else ''}"
        f"</div>"
        # Extra narratives (inline HTML details/summary)
        f"{extra_html}"
        f"</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def render_actionable_view(
    report: WeeklyReport | None,
    selected_assets: list[AssetClass],
    direction_filter: str,
    min_conviction: float,
) -> None:
    """Main render entry point for the single-page actionable view."""

    if not report:
        st.info("No report data yet. Run the weekly pipeline to generate your first report.")
        return

    # --- Regime banner ---
    _render_regime_banner(report)

    # --- Build enriched intel ---
    all_intel = build_asset_intel(report)

    # --- Apply filters ---
    filtered = [
        i for i in all_intel
        if i.asset_class in selected_assets and i.conviction >= min_conviction
    ]

    if direction_filter == "Bullish":
        filtered = [i for i in filtered if i.direction == SentimentDirection.BULLISH]
    elif direction_filter == "Bearish":
        filtered = [i for i in filtered if i.direction == SentimentDirection.BEARISH]

    # --- Partition by direction ---
    bullish = sorted(
        [i for i in filtered if i.direction == SentimentDirection.BULLISH],
        key=lambda i: abs(i.score),
        reverse=True,
    )
    bearish = sorted(
        [i for i in filtered if i.direction == SentimentDirection.BEARISH],
        key=lambda i: abs(i.score),
        reverse=True,
    )
    neutral = sorted(
        [i for i in filtered if i.direction == SentimentDirection.NEUTRAL],
        key=lambda i: abs(i.conviction),
        reverse=True,
    )

    # --- Bullish calls ---
    if bullish:
        st.markdown(
            f'<div class="call-section-header call-section-bullish">'
            f"BULLISH CALLS ({len(bullish)})</div>",
            unsafe_allow_html=True,
        )
        for intel in bullish:
            _render_asset_card(intel)

    # --- Bearish calls ---
    if bearish:
        st.markdown(
            f'<div class="call-section-header call-section-bearish">'
            f"BEARISH CALLS ({len(bearish)})</div>",
            unsafe_allow_html=True,
        )
        for intel in bearish:
            _render_asset_card(intel)

    # --- Neutral (collapsed) ---
    if neutral:
        neutral_rows = ""
        for intel in neutral:
            ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)
            neutral_rows += (
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:6px 0;border-bottom:1px solid #1a2332;">'
                f'<span class="asset-ticker" style="font-size:0.85rem;">{intel.ticker}</span>'
                f'<span class="asset-class-label">{ac_label}</span>'
                f'{_conviction_bar_html(intel.conviction, intel.direction)}'
                f'<span class="horizon-chip">{intel.horizon}</span>'
                f'<span class="rationale-text" style="flex:1;">{intel.primary_rationale}</span>'
                f"</div>"
            )
        st.markdown(
            f'<details class="extra-narratives" style="margin-top:12px;">'
            f'<summary class="call-section-header call-section-neutral" '
            f'style="cursor:pointer;">NEUTRAL ({len(neutral)})</summary>'
            f'<div style="padding-top:8px;">{neutral_rows}</div>'
            f"</details>",
            unsafe_allow_html=True,
        )

    if not bullish and not bearish and not neutral:
        st.markdown(
            '<div class="text-muted" style="text-align:center;padding:40px 0;">'
            "No asset calls match the current filters.</div>",
            unsafe_allow_html=True,
        )
