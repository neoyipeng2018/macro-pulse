"""macro-pulse — Weekly Macro Narrative Extraction Dashboard."""

import streamlit as st

from dashboard.actionable_view import render_actionable_view
from dashboard.styles import inject_custom_css
from dashboard.trade_view import render_trade_view
from models.schemas import AssetClass
from storage.store import init_db, load_latest_report

st.set_page_config(
    page_title="macro-pulse",
    page_icon="~",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
init_db()

# --- Sidebar ---
ASSET_LABELS = {
    AssetClass.FX: "FX",
    AssetClass.METALS: "Metals",
    AssetClass.ENERGY: "Energy",
    AssetClass.CRYPTO: "Crypto",
    AssetClass.INDICES: "Indices",
    AssetClass.BONDS: "Bonds",
}

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
    selected_assets = st.multiselect(
        "ASSET CLASS FILTER",
        options=list(AssetClass),
        default=list(AssetClass),
        format_func=lambda a: ASSET_LABELS.get(a, a.value),
    )

    st.markdown(
        '<div style="height: 1px; background: #1a2332; margin: 8px 0;"></div>',
        unsafe_allow_html=True,
    )

    # Direction filter
    direction_filter = st.radio(
        "DIRECTION",
        options=["All", "Bullish", "Bearish"],
        horizontal=True,
    )

    st.markdown(
        '<div style="height: 1px; background: #1a2332; margin: 8px 0;"></div>',
        unsafe_allow_html=True,
    )

    # Min probability / conviction slider
    min_threshold_pct = st.slider(
        "MIN PROBABILITY",
        min_value=0,
        max_value=100,
        value=0,
        step=5,
        format="%d%%",
    )
    min_threshold = min_threshold_pct / 100.0

# --- Load Data ---
report = load_latest_report()

# --- Header ---
st.markdown(
    '<div class="mp-header">'
    "<div>"
    '<div class="mp-title">'
    '<span class="pulse-dot"></span>'
    '<span style="text-decoration:none !important;">MACRO-PULSE</span>'
    "</div>"
    '<div class="mp-subtitle">Forward-Looking Asset Calls</div>'
    "</div>"
    "</div>",
    unsafe_allow_html=True,
)

# --- Main content tabs ---
tab_intel, tab_trades = st.tabs(["Intelligence", "Trading"])

with tab_intel:
    render_actionable_view(report, selected_assets, direction_filter, min_threshold)

with tab_trades:
    render_trade_view(report)
