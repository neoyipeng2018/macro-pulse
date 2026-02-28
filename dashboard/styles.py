"""Global CSS for macro-pulse command-center dashboard."""

import streamlit as st

CUSTOM_CSS = """
<style>
/* === BASE TYPOGRAPHY === */
*, .stMarkdown, .stText, p, span, div, li, td, th, label, .stSelectbox, .stMultiSelect {
    font-family: 'SF Mono', 'Cascadia Code', 'Consolas', 'Fira Code', monospace !important;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* === HIDE DEFAULT STREAMLIT CHROME === */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {
    background-color: #0a0e14 !important;
    height: 0px !important;
    min-height: 0px !important;
    padding: 0 !important;
}

/* === MAIN CONTAINER === */
.stApp { background-color: #0a0e14; }
section[data-testid="stSidebar"] {
    background-color: #0d1117 !important;
    border-right: 1px solid #1a2332 !important;
}

/* === COMPACT SPACING === */
.block-container { padding-top: 1rem !important; padding-bottom: 0 !important; }
div[data-testid="stVerticalBlock"] > div { gap: 0.4rem; }

/* === SCROLLBAR === */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0a0e14; }
::-webkit-scrollbar-thumb { background: #1a2332; border-radius: 3px; }

/* === PANEL CARD === */
.cmd-panel {
    background: #1a1f2e;
    border: 1px solid #1a2332;
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 8px;
    transition: border-color 0.2s ease;
}
.cmd-panel:hover { border-color: #2a3442; }

/* === SENTIMENT DIRECTION PANELS === */
.cmd-panel-bullish { border-left: 3px solid #00E676; }
.cmd-panel-bearish { border-left: 3px solid #FF1744; }
.cmd-panel-neutral { border-left: 3px solid #FFEA00; }

/* === SENTIMENT BADGES === */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.badge-bullish {
    background: rgba(0, 230, 118, 0.2);
    color: #00E676;
    border: 1px solid rgba(0, 230, 118, 0.3);
}
.badge-bearish {
    background: rgba(255, 23, 68, 0.2);
    color: #FF1744;
    border: 1px solid rgba(255, 23, 68, 0.3);
}
.badge-neutral {
    background: rgba(255, 234, 0, 0.2);
    color: #FFEA00;
    border: 1px solid rgba(255, 234, 0, 0.3);
}

/* === REGIME BADGES === */
.regime-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}
.regime-risk_on { background: rgba(0, 230, 118, 0.15); color: #00E676; border: 1px solid rgba(0, 230, 118, 0.3); }
.regime-risk_off { background: rgba(255, 23, 68, 0.15); color: #FF1744; border: 1px solid rgba(255, 23, 68, 0.3); }
.regime-reflation { background: rgba(255, 145, 0, 0.15); color: #FF9100; border: 1px solid rgba(255, 145, 0, 0.3); }
.regime-stagflation { background: rgba(255, 23, 68, 0.15); color: #FF5252; border: 1px solid rgba(255, 23, 68, 0.3); }
.regime-goldilocks { background: rgba(0, 212, 170, 0.15); color: #00d4aa; border: 1px solid rgba(0, 212, 170, 0.3); }
.regime-transition { background: rgba(255, 234, 0, 0.15); color: #FFEA00; border: 1px solid rgba(255, 234, 0, 0.3); }

/* === SOURCE CHIPS === */
.source-chip {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    background: rgba(0, 212, 170, 0.1);
    color: #00d4aa;
    border: 1px solid rgba(0, 212, 170, 0.2);
}

/* === PULSE DOT === */
@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(0, 212, 170, 0.7); }
    70% { box-shadow: 0 0 0 6px rgba(0, 212, 170, 0); }
    100% { box-shadow: 0 0 0 0 rgba(0, 212, 170, 0); }
}
.pulse-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #00d4aa;
    animation: pulse 2s infinite;
    margin-right: 8px;
    vertical-align: middle;
}

/* === HEADER === */
.mp-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 0;
    border-bottom: 1px solid #1a2332;
    margin-bottom: 16px;
}
.mp-title {
    font-size: 1.4rem;
    font-weight: 700;
    color: #e0e4ec;
    letter-spacing: 0.15em;
    display: flex;
    align-items: center;
    gap: 8px;
    text-decoration: none !important;
}
.mp-title * { text-decoration: none !important; }
.mp-subtitle {
    font-size: 0.65rem;
    color: #4a5568;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 2px;
}

/* === METRICS ROW === */
.metric-box {
    background: #1a1f2e;
    border: 1px solid #1a2332;
    border-radius: 4px;
    padding: 8px 14px;
    text-align: center;
}
.metric-value { font-size: 1.4rem; font-weight: 700; color: #e0e4ec; }
.metric-label { font-size: 0.6rem; color: #4a5568; text-transform: uppercase; letter-spacing: 0.1em; }

/* === HEATMAP CELL === */
.heatmap-cell {
    background: #1a1f2e;
    border: 1px solid #1a2332;
    border-radius: 6px;
    padding: 12px;
    text-align: center;
    min-height: 80px;
}
.heatmap-ticker { font-size: 0.85rem; font-weight: 700; color: #e0e4ec; margin-bottom: 4px; }
.heatmap-score { font-size: 1.2rem; font-weight: 700; }
.heatmap-direction { font-size: 0.6rem; letter-spacing: 0.08em; text-transform: uppercase; }

/* === BRIEFING PANEL === */
.briefing-panel {
    background: #1a1f2e;
    border: 1px solid #1a2332;
    border-radius: 6px;
    padding: 20px 24px;
}
.briefing-text { color: #c5c8d4; line-height: 1.7; font-size: 0.9rem; }

/* === EXPANDER OVERRIDE === */
details[data-testid="stExpander"] {
    background: #1a1f2e !important;
    border: 1px solid #1a2332 !important;
    border-radius: 6px !important;
}

/* === BUTTONS === */
.stButton > button[kind="primary"] {
    background: rgba(0, 212, 170, 0.15) !important;
    color: #00d4aa !important;
    border: 1px solid rgba(0, 212, 170, 0.3) !important;
    font-family: 'SF Mono', monospace !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.75rem;
}

/* === MUTED TEXT / SECTION HEADERS === */
.text-muted { color: #4a5568; font-size: 0.75rem; }
.section-header {
    font-size: 0.7rem;
    color: #4a5568;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding-bottom: 8px;
    border-bottom: 1px solid #1a2332;
    margin-bottom: 12px;
}
</style>
"""


def inject_custom_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
