"""macro-pulse — Weekly Macro Narrative Extraction Dashboard."""

from datetime import datetime

import streamlit as st

from dashboard.styles import inject_custom_css
from models.schemas import AssetClass
from storage.store import init_db, load_all_reports, load_latest_report

st.set_page_config(
    page_title="macro-pulse",
    page_icon="~",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
init_db()

# --- Sidebar ---
with st.sidebar:
    st.markdown(
        '<div style="padding: 8px 0 4px 0;">'
        '<span style="color: #00d4aa; font-size: 1.1rem; font-weight: 700; '
        'letter-spacing: 0.15em;">MACRO-PULSE</span>'
        '<br><span style="color: #4a5568; font-size: 0.6rem; '
        'letter-spacing: 0.1em;">WEEKLY MACRO NARRATIVE SYSTEM</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="height: 1px; background: #1a2332; margin: 8px 0;"></div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Navigate",
        options=["Overview", "Narratives", "Price Validation", "Regime"],
        label_visibility="collapsed",
    )

    st.markdown(
        '<div style="height: 1px; background: #1a2332; margin: 8px 0;"></div>',
        unsafe_allow_html=True,
    )

    # Run pipeline button
    if st.button("RUN WEEKLY PIPELINE", type="primary", use_container_width=True):
        with st.spinner("Running macro-pulse pipeline..."):
            try:
                from run_weekly import run_pipeline
                run_pipeline()
                st.success("Pipeline complete!")
                st.rerun()
            except Exception as e:
                st.error(f"Pipeline error: {e}")

    st.markdown(
        '<div style="height: 1px; background: #1a2332; margin: 8px 0;"></div>',
        unsafe_allow_html=True,
    )

    # Asset class filter
    st.markdown(
        '<div class="section-header">ASSET CLASS FILTER</div>',
        unsafe_allow_html=True,
    )
    ASSET_LABELS = {
        AssetClass.FX: "FX",
        AssetClass.METALS: "Metals",
        AssetClass.ENERGY: "Energy",
        AssetClass.CRYPTO: "Crypto",
        AssetClass.INDICES: "Indices",
        AssetClass.BONDS: "Bonds",
    }
    selected_assets = st.multiselect(
        "Filter by asset class",
        options=list(AssetClass),
        default=list(AssetClass),
        format_func=lambda a: ASSET_LABELS.get(a, a.value),
        label_visibility="collapsed",
    )

# --- Load Data ---
report = load_latest_report()
all_reports = load_all_reports()

# --- Header ---
st.markdown(
    '<div class="mp-header">'
    "<div>"
    '<div class="mp-title">'
    '<span class="pulse-dot"></span>'
    '<span style="text-decoration:none !important;">MACRO-PULSE</span>'
    "</div>"
    '<div class="mp-subtitle">Weekly Macro Narrative Extraction for Directional Trading</div>'
    "</div>"
    "</div>",
    unsafe_allow_html=True,
)

# Metrics row
m1, m2, m3, m4 = st.columns(4)
with m1:
    n_narratives = len(report.narratives) if report else 0
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-value">{n_narratives}</div>'
        f'<div class="metric-label">Narratives</div></div>',
        unsafe_allow_html=True,
    )
with m2:
    regime_val = report.regime.value.replace("_", " ").upper() if report else "N/A"
    regime_class = report.regime.value if report else "transition"
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-value"><span class="regime-badge regime-{regime_class}">'
        f'{regime_val}</span></div>'
        f'<div class="metric-label">Regime</div></div>',
        unsafe_allow_html=True,
    )
with m3:
    n_signals = report.signal_count if report else 0
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-value">{n_signals}</div>'
        f'<div class="metric-label">Signals</div></div>',
        unsafe_allow_html=True,
    )
with m4:
    last_run = report.generated_at.strftime("%b %d %H:%M") if report else "Never"
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-value" style="font-size: 0.95rem;">{last_run}</div>'
        f'<div class="metric-label">Last Run</div></div>',
        unsafe_allow_html=True,
    )

# --- Main Content ---
if page == "Overview":
    from dashboard.overview import render_overview
    render_overview(report)
elif page == "Narratives":
    from dashboard.narratives import render_narratives
    render_narratives(report)
elif page == "Price Validation":
    from dashboard.price_validation import render_price_validation
    render_price_validation(report)
elif page == "Regime":
    from dashboard.regime import render_regime
    render_regime(all_reports)
