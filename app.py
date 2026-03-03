"""macro-pulse — Weekly Macro Narrative Extraction Dashboard."""

import logging
import threading
import time

import streamlit as st

from dashboard.actionable_view import render_actionable_view
from dashboard.styles import inject_custom_css
from models.schemas import AssetClass
from storage.store import init_db, load_latest_report

logger = logging.getLogger("macro-pulse.app")

st.set_page_config(
    page_title="macro-pulse",
    page_icon="~",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
init_db()


# --- Background trade validator ---
def _background_validator():
    """Runs every 6 hours while the app is alive.
    Checks for trades that can be validated and scores them."""
    while True:
        try:
            from analysis.outcome_tracker import validate_pending_trades
            from storage.store import (
                get_pending_trades,
                save_trade_outcome,
                update_trade_thesis_outcome,
            )

            pending = get_pending_trades()
            if pending:
                outcomes = validate_pending_trades(pending)
                for outcome in outcomes:
                    try:
                        save_trade_outcome(outcome)
                        for trade in pending:
                            if (trade["ticker"] == outcome.ticker
                                    and trade["entry_date"] == outcome.entry_date.isoformat()):
                                update_trade_thesis_outcome(
                                    trade_id=trade["id"],
                                    exit_price=outcome.exit_price,
                                    exit_date=outcome.exit_date.isoformat(),
                                    exit_reason=outcome.exit_reason,
                                    pnl_pct=outcome.pnl_pct,
                                    days_held=outcome.days_held,
                                    direction_correct=outcome.direction_correct,
                                )
                                break
                    except Exception as e:
                        logger.error("Background validator save error: %s", e)
                if outcomes:
                    logger.info("Background validator resolved %d trades", len(outcomes))
        except Exception as e:
            logger.error("Background validation failed: %s", e)
        time.sleep(6 * 3600)  # check every 6 hours


if "validator_started" not in st.session_state:
    thread = threading.Thread(target=_background_validator, daemon=True)
    thread.start()
    st.session_state.validator_started = True


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

# --- Main content ---
render_actionable_view(report, selected_assets, direction_filter, min_threshold)
