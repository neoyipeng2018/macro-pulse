"""Dashboard trade view: trade sheet, open positions, journal, and performance."""

from __future__ import annotations

import streamlit as st
from datetime import datetime

from models.schemas import Trade, WeeklyReport


def render_trade_view(report: WeeklyReport | None) -> None:
    """Render the trade management dashboard tab."""

    if not report:
        st.info("No report data yet. Run the pipeline to generate trades.")
        return

    tab_sheet, tab_positions, tab_journal, tab_performance = st.tabs([
        "Trade Sheet", "Open Positions", "Trade Journal", "Performance",
    ])

    with tab_sheet:
        _render_trade_sheet(report)

    with tab_positions:
        _render_open_positions()

    with tab_journal:
        _render_trade_journal()

    with tab_performance:
        _render_performance()


def _render_trade_sheet(report: WeeklyReport) -> None:
    """Display proposed trades from the latest report."""
    trades = report.trades

    if not trades:
        st.info("No trades generated in the latest run.")
        return

    # Summary header
    total_deployed = sum(t.position_usd for t in trades)
    st.markdown(
        f'<div style="background:#0d1117;border:1px solid #1a2332;border-radius:8px;'
        f'padding:16px;margin-bottom:16px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<div>'
        f'<span style="color:#00d4aa;font-size:1.1rem;font-weight:700;">TRADE SHEET</span>'
        f'<span style="color:#4a5568;margin-left:12px;">{report.generated_at.strftime("%b %d, %Y")}</span>'
        f'</div>'
        f'<div style="display:flex;gap:24px;">'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">REGIME</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">{report.regime.value.upper()}</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">TRADES</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">{len(trades)}</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">DEPLOYED</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">${total_deployed:,.0f}</span></div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )

    # Trade cards
    for i, t in enumerate(trades, 1):
        _render_trade_card(i, t)


def _render_trade_card(num: int, t: Trade) -> None:
    """Render a single trade card."""
    dir_color = "#00d4aa" if t.direction == "LONG" else "#ff6b6b"
    dir_icon = "▲" if t.direction == "LONG" else "▼"

    # Calculate stop/tp percentages from entry
    sl_pct = ((t.stop_loss_price - t.entry_price) / t.entry_price * 100) if t.entry_price else 0
    tp_pct = ((t.take_profit_price - t.entry_price) / t.entry_price * 100) if t.entry_price else 0

    # Unit label
    unit = t.ticker.split("-")[0] if "-" in t.ticker else t.ticker
    if t.entry_price >= 1000:
        size_str = f"{t.position_size:.4f} {unit}"
    elif t.entry_price >= 1:
        size_str = f"{t.position_size:.2f} {unit}"
    else:
        size_str = f"{t.position_size:.0f} {unit}"

    conflict_badge = (
        '<span style="background:#ff6b6b22;color:#ff6b6b;padding:2px 8px;'
        'border-radius:4px;font-size:0.7rem;margin-left:8px;">CONFLICT</span>'
        if t.conflict_flag else ""
    )

    invalidation_html = ""
    if t.invalidation_triggers:
        triggers = ", ".join(t.invalidation_triggers)
        invalidation_html = (
            f'<div style="margin-top:8px;padding:8px;background:#ff6b6b11;'
            f'border-left:2px solid #ff6b6b44;border-radius:4px;">'
            f'<span style="color:#ff6b6b;font-size:0.75rem;font-weight:600;">INVALIDATION: </span>'
            f'<span style="color:#a0aec0;font-size:0.75rem;">{triggers}</span></div>'
        )

    itp_html = ""
    if t.intermediate_tp_price:
        itp_pct = ((t.intermediate_tp_price - t.entry_price) / t.entry_price * 100) if t.entry_price else 0
        itp_html = (
            f'<div style="display:inline-block;margin-right:16px;">'
            f'<span style="color:#4a5568;font-size:0.75rem;">PARTIAL TP</span><br>'
            f'<span style="color:#e2e8f0;">${t.intermediate_tp_price:,.2f} ({itp_pct:+.1f}%)</span></div>'
        )

    st.markdown(
        f'<div style="background:#0d1117;border:1px solid #1a2332;border-radius:8px;'
        f'padding:16px;margin-bottom:12px;">'
        # Header
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'margin-bottom:12px;">'
        f'<div style="display:flex;align-items:center;gap:12px;">'
        f'<span style="color:#4a5568;font-weight:700;">#{num}</span>'
        f'<span style="color:#e2e8f0;font-size:1.1rem;font-weight:700;">{t.ticker}</span>'
        f'<span style="color:{dir_color};font-weight:700;">{dir_icon} {t.direction}</span>'
        f'{conflict_badge}'
        f'</div>'
        f'<span style="color:{dir_color};font-size:1.1rem;font-weight:700;">'
        f'Score: {t.composite_score:+.2f}</span></div>'
        # Entry + Size
        f'<div style="display:flex;gap:24px;margin-bottom:12px;">'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">ENTRY</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">${t.entry_price:,.2f}</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">SIZE</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">${t.position_usd:,.0f} ({size_str})</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">PORTFOLIO</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">{t.portfolio_pct:.0f}%</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">HORIZON</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">{t.horizon_days}d</span></div>'
        f'</div>'
        # Stop / TP / R:R
        f'<div style="display:flex;gap:24px;margin-bottom:12px;">'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">STOP LOSS</span><br>'
        f'<span style="color:#ff6b6b;">${t.stop_loss_price:,.2f} ({sl_pct:+.1f}%)</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">TAKE PROFIT</span><br>'
        f'<span style="color:#00d4aa;">${t.take_profit_price:,.2f} ({tp_pct:+.1f}%)</span></div>'
        f'{itp_html}'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">R:R</span><br>'
        f'<span style="color:#e2e8f0;font-weight:600;">{t.risk_reward:.1f}x</span></div>'
        f'</div>'
        # Risk / Reward
        f'<div style="display:flex;gap:24px;margin-bottom:8px;">'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">RISK</span><br>'
        f'<span style="color:#ff6b6b;">${t.risk_usd:,.0f}</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">REWARD</span><br>'
        f'<span style="color:#00d4aa;">${t.reward_usd:,.0f}</span></div>'
        f'<div><span style="color:#4a5568;font-size:0.75rem;">CONFIDENCE</span><br>'
        f'<span style="color:#e2e8f0;">{t.confidence:.0%}</span></div>'
        f'</div>'
        # Narrative
        f'<div style="margin-top:8px;padding:8px;background:#0a0f14;border-radius:4px;">'
        f'<span style="color:#4a5568;font-size:0.75rem;">NARRATIVE: </span>'
        f'<span style="color:#a0aec0;font-size:0.85rem;">{t.top_narrative}</span></div>'
        # Invalidation
        f'{invalidation_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_open_positions() -> None:
    """Show open positions with live unrealized P&L."""
    from storage.positions import load_trades
    from analysis.trade_params import fetch_current_prices

    open_trades = load_trades(status="open") + load_trades(status="partial_tp")

    if not open_trades:
        st.info("No open positions. Use --open-trade to mark a proposed trade as executed.")
        return

    tickers = list({t.ticker for t in open_trades})
    prices = fetch_current_prices(tickers)

    total_pnl = 0.0
    rows = []
    for t in open_trades:
        current = prices.get(t.ticker, 0)
        if current and t.entry_price:
            if t.direction == "LONG":
                pnl = (current - t.entry_price) * t.position_size
                pnl_pct = (current - t.entry_price) / t.entry_price * 100
            else:
                pnl = (t.entry_price - current) * t.position_size
                pnl_pct = (t.entry_price - current) / t.entry_price * 100
            total_pnl += pnl
        else:
            pnl = 0
            pnl_pct = 0

        rows.append({
            "Ticker": t.ticker,
            "Direction": t.direction,
            "Entry": f"${t.entry_price:,.2f}",
            "Current": f"${current:,.2f}" if current else "N/A",
            "Size USD": f"${t.position_usd:,.0f}",
            "P&L": f"${pnl:+,.2f}",
            "P&L %": f"{pnl_pct:+.1f}%",
            "Status": t.status,
            "ID": t.id,
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    pnl_color = "#00d4aa" if total_pnl >= 0 else "#ff6b6b"
    st.markdown(
        f'<div style="text-align:right;padding:8px;font-size:1.1rem;">'
        f'Total Unrealized P&L: '
        f'<span style="color:{pnl_color};font-weight:700;">${total_pnl:+,.2f}</span></div>',
        unsafe_allow_html=True,
    )


def _render_trade_journal() -> None:
    """Show historical trades with P&L."""
    from storage.positions import get_trade_journal, get_cumulative_pnl

    trades = get_trade_journal(limit=50)
    if not trades:
        st.info("No trade history yet.")
        return

    rows = []
    for t in trades:
        rows.append({
            "Ticker": t.ticker,
            "Direction": t.direction,
            "Entry": f"${t.entry_price:,.2f}" if t.entry_price else "—",
            "Exit": f"${t.exit_price:,.2f}" if t.exit_price else "—",
            "P&L $": f"${t.pnl_usd:+,.2f}" if t.pnl_usd is not None else "—",
            "P&L %": f"{t.pnl_pct:+.1f}%" if t.pnl_pct is not None else "—",
            "R:R": f"{t.risk_reward:.1f}x",
            "Status": t.status,
            "Score": f"{t.composite_score:+.2f}",
            "Reason": t.exit_reason or "—",
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    cum_pnl = get_cumulative_pnl()
    closed = [t for t in trades if t.status in ("closed", "stopped") and t.pnl_usd is not None]
    hits = sum(1 for t in closed if t.pnl_usd > 0)
    hit_rate = (hits / len(closed) * 100) if closed else 0

    col1, col2, col3 = st.columns(3)
    pnl_color = "#00d4aa" if cum_pnl >= 0 else "#ff6b6b"
    col1.markdown(
        f'<div style="text-align:center;">'
        f'<span style="color:#4a5568;font-size:0.75rem;">CUMULATIVE P&L</span><br>'
        f'<span style="color:{pnl_color};font-size:1.3rem;font-weight:700;">${cum_pnl:+,.2f}</span></div>',
        unsafe_allow_html=True,
    )
    col2.markdown(
        f'<div style="text-align:center;">'
        f'<span style="color:#4a5568;font-size:0.75rem;">HIT RATE</span><br>'
        f'<span style="color:#e2e8f0;font-size:1.3rem;font-weight:700;">{hit_rate:.0f}%</span></div>',
        unsafe_allow_html=True,
    )
    col3.markdown(
        f'<div style="text-align:center;">'
        f'<span style="color:#4a5568;font-size:0.75rem;">TOTAL TRADES</span><br>'
        f'<span style="color:#e2e8f0;font-size:1.3rem;font-weight:700;">{len(closed)}</span></div>',
        unsafe_allow_html=True,
    )


def _render_performance() -> None:
    """Show performance metrics and equity curve."""
    from storage.positions import get_trade_journal, get_cumulative_pnl

    trades = get_trade_journal(limit=200)
    closed = [
        t for t in trades
        if t.status in ("closed", "stopped") and t.pnl_usd is not None
    ]

    if len(closed) < 2:
        st.info("Need at least 2 closed trades to show performance metrics.")
        return

    # Equity curve
    import pandas as pd
    equity = []
    cumulative = 0.0
    for t in reversed(closed):  # oldest first
        cumulative += t.pnl_usd
        equity.append({
            "Trade": t.ticker,
            "Cumulative P&L": cumulative,
            "Date": t.exit_time or t.created_at,
        })

    df = pd.DataFrame(equity)
    st.line_chart(df, x="Date", y="Cumulative P&L", use_container_width=True)

    # Rolling hit rate (20-trade window)
    if len(closed) >= 5:
        rolling = []
        window = min(20, len(closed))
        for i in range(window, len(closed) + 1):
            batch = closed[i - window : i]
            wins = sum(1 for t in batch if t.pnl_usd > 0)
            rolling.append({
                "Trade #": i,
                "Hit Rate %": (wins / window) * 100,
            })
        df_roll = pd.DataFrame(rolling)
        st.line_chart(df_roll, x="Trade #", y="Hit Rate %", use_container_width=True)

    # Summary stats
    wins = [t.pnl_usd for t in closed if t.pnl_usd > 0]
    losses = [t.pnl_usd for t in closed if t.pnl_usd <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Avg Win", f"${avg_win:+,.2f}")
    col2.metric("Avg Loss", f"${avg_loss:+,.2f}")
    col3.metric("Win/Loss Ratio", f"{abs(avg_win / avg_loss):.2f}x" if avg_loss else "∞")
    col4.metric("Total Closed", str(len(closed)))
