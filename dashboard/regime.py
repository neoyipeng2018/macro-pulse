"""Regime page — regime timeline and history across weeks."""

import streamlit as st
import plotly.graph_objects as go

from models.schemas import EconomicRegime, WeeklyReport

REGIME_COLORS = {
    EconomicRegime.RISK_ON: "#00E676",
    EconomicRegime.RISK_OFF: "#FF1744",
    EconomicRegime.REFLATION: "#FF9100",
    EconomicRegime.STAGFLATION: "#FF5252",
    EconomicRegime.GOLDILOCKS: "#00d4aa",
    EconomicRegime.TRANSITION: "#FFEA00",
}

REGIME_Y = {
    EconomicRegime.RISK_ON: 5,
    EconomicRegime.GOLDILOCKS: 4,
    EconomicRegime.REFLATION: 3,
    EconomicRegime.TRANSITION: 2,
    EconomicRegime.STAGFLATION: 1,
    EconomicRegime.RISK_OFF: 0,
}


def render_regime(reports: list[WeeklyReport]) -> None:
    if not reports:
        st.info("No reports available. Run the weekly pipeline to generate data.")
        return

    latest = reports[0]

    # Current regime display
    regime = latest.regime
    color = REGIME_COLORS.get(regime, "#4a5568")

    st.markdown(
        f'<div class="cmd-panel" style="border-left: 3px solid {color};">'
        f'<div style="display: flex; align-items: center; gap: 12px;">'
        f'<span class="regime-badge regime-{regime.value}">'
        f'{regime.value.replace("_", " ")}</span>'
        f'<span style="color: #c5c8d4; font-size: 0.9rem;">{latest.regime_rationale}</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("")

    # Regime positioning guide
    st.markdown('<div class="section-header">REGIME POSITIONING GUIDE</div>', unsafe_allow_html=True)
    _render_positioning_guide(regime)

    # Timeline chart
    if len(reports) > 1:
        st.markdown('<div class="section-header">REGIME TIMELINE</div>', unsafe_allow_html=True)
        _render_timeline(reports)

    # Historical regime table
    st.markdown('<div class="section-header">REGIME HISTORY</div>', unsafe_allow_html=True)
    for r in reports[:12]:
        rc = REGIME_COLORS.get(r.regime, "#4a5568")
        st.markdown(
            f'<div style="display: flex; align-items: center; gap: 12px; padding: 4px 0; '
            f'border-bottom: 1px solid #111827;">'
            f'<span style="color: #4a5568; min-width: 100px;">'
            f'{r.week_start.strftime("%b %d")}</span>'
            f'<span class="regime-badge regime-{r.regime.value}">'
            f'{r.regime.value.replace("_", " ")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_positioning_guide(regime: EconomicRegime) -> None:
    """Show what to be long/short in the current regime."""
    guides = {
        EconomicRegime.RISK_ON: {
            "long": ["Equities", "EM FX", "Crypto", "Copper", "AUD"],
            "short": ["USD (DXY)", "Gold", "Bonds (TLT)", "VIX"],
        },
        EconomicRegime.RISK_OFF: {
            "long": ["USD (DXY)", "Gold", "Bonds (TLT)", "JPY", "CHF"],
            "short": ["Equities", "Crypto", "EM FX", "Copper", "AUD"],
        },
        EconomicRegime.REFLATION: {
            "long": ["Commodities", "EM FX", "Copper", "Energy", "AUD"],
            "short": ["Bonds (TLT)", "USD (DXY)", "Growth stocks"],
        },
        EconomicRegime.STAGFLATION: {
            "long": ["Gold", "Energy", "CHF"],
            "short": ["Equities", "Bonds (TLT)", "Crypto", "Copper"],
        },
        EconomicRegime.GOLDILOCKS: {
            "long": ["Equities", "Bonds (TLT)", "Crypto", "Growth stocks"],
            "short": ["VIX", "Gold"],
        },
        EconomicRegime.TRANSITION: {
            "long": ["Reduce all positions", "Cash"],
            "short": ["Reduce all positions"],
        },
    }

    guide = guides.get(regime, guides[EconomicRegime.TRANSITION])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            '<div class="cmd-panel" style="border-left: 3px solid #00E676;">'
            '<div style="color: #00E676; font-size: 0.7rem; letter-spacing: 0.1em; '
            'margin-bottom: 8px;">FAVORED (LONG)</div>'
            + "".join(
                f'<div style="color: #c5c8d4; padding: 2px 0;">+ {item}</div>'
                for item in guide["long"]
            )
            + "</div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            '<div class="cmd-panel" style="border-left: 3px solid #FF1744;">'
            '<div style="color: #FF1744; font-size: 0.7rem; letter-spacing: 0.1em; '
            'margin-bottom: 8px;">AVOID (SHORT)</div>'
            + "".join(
                f'<div style="color: #c5c8d4; padding: 2px 0;">- {item}</div>'
                for item in guide["short"]
            )
            + "</div>",
            unsafe_allow_html=True,
        )


def _render_timeline(reports: list[WeeklyReport]) -> None:
    """Plot regime evolution over time."""
    sorted_reports = sorted(reports, key=lambda r: r.week_start)

    dates = [r.week_start for r in sorted_reports]
    y_vals = [REGIME_Y.get(r.regime, 2) for r in sorted_reports]
    colors = [REGIME_COLORS.get(r.regime, "#4a5568") for r in sorted_reports]
    labels = [r.regime.value.replace("_", " ") for r in sorted_reports]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=y_vals,
            mode="lines+markers",
            line=dict(color="#2a3442", width=1),
            marker=dict(size=12, color=colors),
            text=labels,
            hovertemplate="<b>%{text}</b><br>Week of %{x}<extra></extra>",
        )
    )

    # Add regime zone bands
    regime_labels = ["RISK OFF", "STAGFLATION", "TRANSITION", "REFLATION", "GOLDILOCKS", "RISK ON"]
    for i, label in enumerate(regime_labels):
        fig.add_annotation(
            x=dates[0], y=i, text=label,
            showarrow=False, xanchor="right", xshift=-10,
            font=dict(size=9, color="#4a5568", family="SF Mono, monospace"),
        )

    fig.update_layout(
        height=300,
        showlegend=False,
        paper_bgcolor="#0a0e14",
        plot_bgcolor="#0a0e14",
        font=dict(color="#8892a4", family="SF Mono, monospace"),
        xaxis=dict(gridcolor="#1a2332"),
        yaxis=dict(
            gridcolor="#1a2332",
            showticklabels=False,
            range=[-0.5, 5.5],
        ),
        margin=dict(l=100, r=30, t=10, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)
