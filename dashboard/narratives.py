"""Narratives page — full list of macro narratives with asset sentiment detail."""

import streamlit as st

from models.schemas import Narrative, SentimentDirection, WeeklyReport

DIRECTION_COLORS = {
    SentimentDirection.BULLISH: "#00E676",
    SentimentDirection.BEARISH: "#FF1744",
    SentimentDirection.NEUTRAL: "#FFEA00",
}


def render_narratives(report: WeeklyReport | None) -> None:
    if not report or not report.narratives:
        st.info("No narratives available.")
        return

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        trend_filter = st.selectbox(
            "Filter by trend",
            options=["All", "intensifying", "stable", "fading"],
        )
    with col2:
        sort_by = st.selectbox(
            "Sort by",
            options=["Confidence (high)", "Confidence (low)", "Trend (intensifying first)"],
        )

    narratives = report.narratives
    if trend_filter != "All":
        narratives = [n for n in narratives if n.trend == trend_filter]

    if sort_by == "Confidence (high)":
        narratives = sorted(narratives, key=lambda n: n.confidence, reverse=True)
    elif sort_by == "Confidence (low)":
        narratives = sorted(narratives, key=lambda n: n.confidence)
    elif sort_by == "Trend (intensifying first)":
        order = {"intensifying": 0, "stable": 1, "fading": 2}
        narratives = sorted(narratives, key=lambda n: order.get(n.trend, 1))

    st.markdown(
        f'<div class="text-muted" style="margin-bottom: 12px;">'
        f'{len(narratives)} narratives</div>',
        unsafe_allow_html=True,
    )

    for narrative in narratives:
        _render_full_narrative(narrative)


def _render_full_narrative(narrative: Narrative) -> None:
    """Render a detailed narrative card."""
    # Summary header
    trend_color = {
        "intensifying": "#FF1744",
        "stable": "#FFEA00",
        "fading": "#00E676",
    }.get(narrative.trend, "#4a5568")

    with st.expander(
        f"{narrative.title} | conf: {narrative.confidence:.2f} | "
        f"trend: {narrative.trend} | horizon: {narrative.horizon}"
    ):
        st.markdown(narrative.summary)

        # Asset sentiments table
        if narrative.asset_sentiments:
            st.markdown("---")
            st.markdown("**Per-Asset Directional Sentiment:**")

            for sent in sorted(
                narrative.asset_sentiments,
                key=lambda s: s.conviction,
                reverse=True,
            ):
                color = DIRECTION_COLORS.get(sent.direction, "#4a5568")
                bar_width = int(sent.conviction * 100)

                st.markdown(
                    f'<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">'
                    f'<span style="min-width: 120px; font-weight: 700;">{sent.ticker}</span>'
                    f'<span class="badge badge-{sent.direction.value}">{sent.direction.value}</span>'
                    f'<div style="flex: 1; background: #1a2332; border-radius: 3px; height: 6px;">'
                    f'<div style="width: {bar_width}%; background: {color}; height: 100%; '
                    f'border-radius: 3px;"></div></div>'
                    f'<span style="color: #8892a4; font-size: 0.75rem; min-width: 40px;">'
                    f'{sent.conviction:.1f}</span>'
                    f'</div>'
                    f'<div style="color: #4a5568; font-size: 0.75rem; margin-left: 128px; '
                    f'margin-bottom: 8px;">{sent.rationale}</div>',
                    unsafe_allow_html=True,
                )

        # Source signals
        if narrative.signals:
            st.markdown("---")
            st.markdown(f"**Source Signals ({len(narrative.signals)}):**")
            for sig in narrative.signals[:8]:
                link = f"[link]({sig.url})" if sig.url else ""
                st.markdown(
                    f"- `{sig.source.value}` {sig.title} {link}"
                )
