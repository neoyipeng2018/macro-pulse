"""Price validation page — sentiment predictions vs actual returns."""

import streamlit as st
import plotly.graph_objects as go

from models.schemas import PriceValidation, SentimentDirection, WeeklyReport

DIRECTION_COLORS = {
    SentimentDirection.BULLISH: "#00E676",
    SentimentDirection.BEARISH: "#FF1744",
    SentimentDirection.NEUTRAL: "#FFEA00",
}


def render_price_validation(report: WeeklyReport | None) -> None:
    if not report:
        st.info("No report available.")
        return

    validations = report.price_validations
    if not validations:
        st.info("No price validation data available for this week.")
        return

    # Hit rate summary
    hits = sum(1 for v in validations if v.hit)
    total = len(validations)
    hit_rate = hits / total if total > 0 else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        color = "#00E676" if hit_rate >= 0.5 else "#FF1744"
        st.markdown(
            f'<div class="metric-box">'
            f'<div class="metric-value" style="color: {color};">{hit_rate:.0%}</div>'
            f'<div class="metric-label">Hit Rate</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-box">'
            f'<div class="metric-value">{hits}/{total}</div>'
            f'<div class="metric-label">Correct Calls</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        avg_score = sum(abs(v.predicted_score) for v in validations) / total if total else 0
        st.markdown(
            f'<div class="metric-box">'
            f'<div class="metric-value">{avg_score:.2f}</div>'
            f'<div class="metric-label">Avg Conviction</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # Scatter plot: predicted score vs actual return
    st.markdown('<div class="section-header">PREDICTED VS ACTUAL</div>', unsafe_allow_html=True)
    _render_scatter(validations)

    # Detailed table
    st.markdown('<div class="section-header">VALIDATION DETAIL</div>', unsafe_allow_html=True)
    _render_table(validations)


def _render_scatter(validations: list[PriceValidation]) -> None:
    """Scatter plot of predicted sentiment score vs actual weekly return."""
    fig = go.Figure()

    for v in validations:
        color = "#00E676" if v.hit else "#FF1744"
        fig.add_trace(
            go.Scatter(
                x=[v.predicted_score],
                y=[v.actual_return_pct],
                mode="markers+text",
                marker=dict(size=10, color=color, opacity=0.8),
                text=[v.ticker],
                textposition="top center",
                textfont=dict(size=9, color="#8892a4", family="SF Mono, monospace"),
                showlegend=False,
                hovertemplate=(
                    f"<b>{v.ticker}</b><br>"
                    f"Predicted: {v.predicted_score:+.2f} ({v.predicted_direction.value})<br>"
                    f"Actual: {v.actual_return_pct:+.2f}%<br>"
                    f"{'HIT' if v.hit else 'MISS'}<extra></extra>"
                ),
            )
        )

    # Add quadrant lines
    fig.add_hline(y=0, line_dash="dash", line_color="#2a3442")
    fig.add_vline(x=0, line_dash="dash", line_color="#2a3442")

    fig.update_layout(
        height=450,
        paper_bgcolor="#0a0e14",
        plot_bgcolor="#0a0e14",
        font=dict(color="#8892a4", family="SF Mono, monospace"),
        xaxis=dict(title="Predicted Score", gridcolor="#1a2332", zeroline=False),
        yaxis=dict(title="Actual Return (%)", gridcolor="#1a2332", zeroline=False),
        margin=dict(l=60, r=30, t=10, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_table(validations: list[PriceValidation]) -> None:
    """Render validation results as styled rows."""
    sorted_v = sorted(validations, key=lambda v: abs(v.predicted_score), reverse=True)

    for v in sorted_v:
        pred_color = DIRECTION_COLORS.get(v.predicted_direction, "#4a5568")
        actual_color = DIRECTION_COLORS.get(v.actual_direction, "#4a5568")
        hit_icon = "OK" if v.hit else "X"
        hit_color = "#00E676" if v.hit else "#FF1744"

        st.markdown(
            f'<div style="display: flex; align-items: center; gap: 12px; padding: 6px 0; '
            f'border-bottom: 1px solid #111827;">'
            f'<span style="min-width: 120px; font-weight: 700; color: #e0e4ec;">{v.ticker}</span>'
            f'<span style="min-width: 80px; color: {pred_color};">'
            f'{v.predicted_direction.value} ({v.predicted_score:+.2f})</span>'
            f'<span style="color: #4a5568;">-></span>'
            f'<span style="min-width: 80px; color: {actual_color};">'
            f'{v.actual_return_pct:+.2f}%</span>'
            f'<span style="color: {hit_color}; font-weight: 700;">[{hit_icon}]</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
