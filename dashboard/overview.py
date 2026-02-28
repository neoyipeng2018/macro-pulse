"""Overview page — sentiment heatmap, regime badge, top narratives, executive summary."""

import streamlit as st
import plotly.graph_objects as go

from models.schemas import (
    AssetClass,
    EconomicRegime,
    Narrative,
    SentimentDirection,
    WeeklyAssetScore,
    WeeklyReport,
)


DIRECTION_COLORS = {
    SentimentDirection.BULLISH: "#00E676",
    SentimentDirection.BEARISH: "#FF1744",
    SentimentDirection.NEUTRAL: "#FFEA00",
}

ASSET_CLASS_LABELS = {
    AssetClass.FX: "FX",
    AssetClass.METALS: "Metals",
    AssetClass.ENERGY: "Energy",
    AssetClass.CRYPTO: "Crypto",
    AssetClass.INDICES: "Indices",
    AssetClass.BONDS: "Bonds",
}


def render_overview(report: WeeklyReport | None) -> None:
    if not report:
        st.info("No report available. Run the weekly pipeline first.")
        return

    # Regime badge
    regime = report.regime
    st.markdown(
        f'<div style="margin-bottom: 16px;">'
        f'<span class="regime-badge regime-{regime.value}">{regime.value.replace("_", " ")}</span>'
        f'<span style="color: #8892a4; font-size: 0.8rem; margin-left: 12px;">'
        f'{report.regime_rationale}</span></div>',
        unsafe_allow_html=True,
    )

    # Executive summary
    if report.summary:
        st.markdown(
            f'<div class="briefing-panel"><div class="briefing-text">{report.summary}</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("")

    # Sentiment heatmap by asset class
    st.markdown('<div class="section-header">SENTIMENT HEATMAP</div>', unsafe_allow_html=True)
    _render_heatmap(report.asset_scores)

    # Sentiment bar chart
    st.markdown('<div class="section-header">DIRECTIONAL SCORES</div>', unsafe_allow_html=True)
    _render_score_chart(report.asset_scores)

    # Top narratives
    st.markdown('<div class="section-header">TOP NARRATIVES</div>', unsafe_allow_html=True)
    sorted_narratives = sorted(report.narratives, key=lambda n: n.confidence, reverse=True)
    for narrative in sorted_narratives[:8]:
        _render_narrative_card(narrative)


def _render_heatmap(scores: list[WeeklyAssetScore]) -> None:
    """Render a grid of asset sentiment cells grouped by asset class."""
    for asset_class in AssetClass:
        class_scores = [s for s in scores if s.asset_class == asset_class]
        if not class_scores:
            continue

        label = ASSET_CLASS_LABELS.get(asset_class, asset_class.value)
        st.markdown(
            f'<div style="color: #8892a4; font-size: 0.7rem; letter-spacing: 0.1em; '
            f'margin: 8px 0 4px 0;">{label.upper()}</div>',
            unsafe_allow_html=True,
        )

        cols = st.columns(min(len(class_scores), 6))
        for i, score in enumerate(class_scores):
            col_idx = i % len(cols)
            color = DIRECTION_COLORS.get(score.direction, "#4a5568")
            arrow = "^" if score.score > 0 else "v" if score.score < 0 else "-"

            with cols[col_idx]:
                st.markdown(
                    f'<div class="heatmap-cell">'
                    f'<div class="heatmap-ticker">{score.ticker}</div>'
                    f'<div class="heatmap-score" style="color: {color};">{score.score:+.2f}</div>'
                    f'<div class="heatmap-direction" style="color: {color};">'
                    f'{arrow} {score.direction.value}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


def _render_score_chart(scores: list[WeeklyAssetScore]) -> None:
    """Horizontal bar chart of asset scores."""
    if not scores:
        return

    # Top 15 by absolute score
    top = sorted(scores, key=lambda s: abs(s.score), reverse=True)[:15]
    top.reverse()  # Plotly draws bottom-up

    colors = [
        DIRECTION_COLORS.get(s.direction, "#4a5568") for s in top
    ]

    fig = go.Figure(
        go.Bar(
            x=[s.score for s in top],
            y=[s.ticker for s in top],
            orientation="h",
            marker_color=colors,
            text=[f"{s.score:+.2f}" for s in top],
            textposition="outside",
            textfont=dict(size=11, family="SF Mono, Consolas, monospace"),
        )
    )
    fig.update_layout(
        height=max(400, len(top) * 32),
        paper_bgcolor="#0a0e14",
        plot_bgcolor="#0a0e14",
        font=dict(color="#8892a4", family="SF Mono, Consolas, monospace"),
        xaxis=dict(
            gridcolor="#1a2332",
            zeroline=True,
            zerolinecolor="#2a3442",
            range=[-1.1, 1.1],
            title="Score (bearish <-> bullish)",
        ),
        yaxis=dict(gridcolor="#1a2332"),
        margin=dict(l=120, r=60, t=10, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_narrative_card(narrative: Narrative) -> None:
    """Render a single narrative as an expandable card."""
    trend_icon = {"intensifying": "^", "stable": "-", "fading": "v"}.get(narrative.trend, "-")
    trend_color = {"intensifying": "#FF1744", "stable": "#FFEA00", "fading": "#00E676"}.get(
        narrative.trend, "#4a5568"
    )

    # Determine dominant sentiment for border color
    bullish_count = sum(1 for s in narrative.asset_sentiments if s.direction == SentimentDirection.BULLISH)
    bearish_count = sum(1 for s in narrative.asset_sentiments if s.direction == SentimentDirection.BEARISH)
    if bullish_count > bearish_count:
        panel_class = "cmd-panel-bullish"
    elif bearish_count > bullish_count:
        panel_class = "cmd-panel-bearish"
    else:
        panel_class = "cmd-panel-neutral"

    with st.expander(f"{narrative.title} — conf: {narrative.confidence:.1f}, trend: {narrative.trend}"):
        st.markdown(f"**{narrative.summary}**")
        st.markdown(f"Horizon: `{narrative.horizon}` | Trend: `{narrative.trend}` | "
                     f"Confidence: `{narrative.confidence:.2f}`")

        if narrative.asset_sentiments:
            st.markdown("**Asset Sentiments:**")
            for sent in narrative.asset_sentiments:
                color = DIRECTION_COLORS.get(sent.direction, "#4a5568")
                st.markdown(
                    f'<span style="color: {color}; font-weight: 700;">'
                    f'{sent.direction.value.upper()}</span> '
                    f'**{sent.ticker}** ({sent.asset_class.value}) — '
                    f'conviction: {sent.conviction:.1f} — {sent.rationale}',
                    unsafe_allow_html=True,
                )

        if narrative.signals:
            st.markdown(f"**Signals ({len(narrative.signals)}):**")
            for sig in narrative.signals[:5]:
                st.markdown(f"- [{sig.source.value}] {sig.title}")
