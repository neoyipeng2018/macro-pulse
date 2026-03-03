"""Export WeeklyReport data to Google Sheets."""

import logging
from pathlib import Path

import gspread

from models.schemas import TradeOutcome, WeeklyReport

logger = logging.getLogger("macro-pulse.sheets")


def _get_gspread_client(creds_file: str) -> gspread.Client:
    """Return an authenticated gspread client.

    Tries the local credentials file first. If the file doesn't exist
    (e.g. on Streamlit Cloud), falls back to ``st.secrets["gcp_service_account"]``
    which should contain the service-account JSON as a TOML section.
    """
    if creds_file and Path(creds_file).exists():
        return gspread.service_account(filename=creds_file)

    # Streamlit Cloud: credentials stored in st.secrets
    try:
        import streamlit as st
        creds = dict(st.secrets["gcp_service_account"])
        return gspread.service_account_from_dict(creds)
    except Exception:
        pass

    raise RuntimeError(
        "No Google Sheets credentials found. Set GOOGLE_SHEETS_CREDENTIALS_FILE "
        "or add a [gcp_service_account] section in Streamlit secrets."
    )


def export_to_sheets(report: WeeklyReport) -> None:
    """Append report data to worksheets in the configured Google Sheet.

    Creates worksheets and header rows if they don't exist yet.
    Appends rows so historical data accumulates across runs.
    """
    from config.settings import settings

    creds_file = settings.google_sheets_credentials_file
    spreadsheet_id = settings.google_sheets_spreadsheet_id

    if not spreadsheet_id:
        logger.debug("No spreadsheet ID configured — skipping Sheets export")
        return

    gc = _get_gspread_client(creds_file)
    sh = gc.open_by_key(spreadsheet_id)

    week = report.week_start.strftime("%Y-%m-%d")

    _write_summary(sh, report, week)
    _write_asset_scores(sh, report, week)
    _write_scenarios(sh, report, week)
    _write_trades(sh, report, week)
    _write_consensus(sh, report, week)

    logger.info("Report exported to Google Sheets (week: %s)", week)


def export_outcomes_to_sheets(outcomes: list[TradeOutcome]) -> None:
    """Export resolved trade outcomes to the Outcomes worksheet."""
    from config.settings import settings

    creds_file = settings.google_sheets_credentials_file
    spreadsheet_id = settings.google_sheets_spreadsheet_id

    if not spreadsheet_id or not outcomes:
        return

    gc = _get_gspread_client(creds_file)
    sh = gc.open_by_key(spreadsheet_id)

    headers = [
        "Week", "Ticker", "Direction", "Entry Price", "Exit Price",
        "Exit Reason", "P&L %", "Direction Correct?",
        "Consensus Score", "Our Score", "Divergence",
        "Divergence Label", "Days Held",
    ]
    ws = _get_or_create_worksheet(sh, "Outcomes", headers)

    rows = [
        [
            o.week,
            o.ticker,
            o.direction,
            o.entry_price,
            o.exit_price,
            o.exit_reason,
            o.pnl_pct,
            "Yes" if o.direction_correct else "No",
            o.consensus_score,
            o.our_score,
            o.divergence,
            o.divergence_label,
            o.days_held,
        ]
        for o in outcomes
    ]

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info("Exported %d outcomes to Google Sheets", len(rows))


def _get_or_create_worksheet(
    sh: gspread.Spreadsheet, title: str, headers: list[str]
) -> gspread.Worksheet:
    """Return existing worksheet or create it with a header row."""
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


def _write_summary(sh: gspread.Spreadsheet, report: WeeklyReport, week: str) -> None:
    headers = [
        "Week", "Regime", "Regime Rationale", "Signal Count", "Summary", "Generated At",
    ]
    ws = _get_or_create_worksheet(sh, "Summary", headers)
    ws.append_row(
        [
            week,
            report.regime.value,
            report.regime_rationale,
            report.signal_count,
            report.summary,
            report.generated_at.isoformat(),
        ],
        value_input_option="USER_ENTERED",
    )


def _write_asset_scores(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
    headers = [
        "Week", "Ticker", "Asset Class", "Direction",
        "Composite Score", "Narrative (50%)", "Technical (25%)",
        "Scenario (25%)", "Contrarian Nudge",
        "Conviction", "Conflict", "Edge Type",
        "Narrative Count", "Top Narrative",
    ]
    ws = _get_or_create_worksheet(sh, "Asset Scores", headers)

    # Build conviction lookup from asset_scores
    conviction_by_ticker = {s.ticker: s.conviction for s in report.asset_scores}

    # Prefer composite scores (full breakdown); fall back to basic asset scores
    if report.composite_scores:
        rows = [
            [
                week,
                cs.ticker,
                cs.asset_class.value,
                cs.direction.value,
                cs.composite_score,
                cs.narrative_score,
                cs.technical_score,
                cs.scenario_score,
                cs.contrarian_bonus,
                conviction_by_ticker.get(cs.ticker, 0.0),
                cs.conflict_flag,
                cs.edge_type,
                cs.narrative_count,
                cs.top_narrative,
            ]
            for cs in report.composite_scores
        ]
    else:
        rows = [
            [
                week,
                s.ticker,
                s.asset_class.value,
                s.direction.value,
                s.score,
                s.score,  # narrative only
                "", "", "",  # no technical/scenario/contrarian
                s.conviction,
                False,
                "",
                s.narrative_count,
                s.top_narrative,
            ]
            for s in report.asset_scores
        ]

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _write_scenarios(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
    headers = [
        "Week", "Mechanism", "Category", "Probability", "Stage",
        "Magnitude", "Confidence", "Watch Items",
    ]
    ws = _get_or_create_worksheet(sh, "Scenarios", headers)
    rows = [
        [
            week,
            sc.mechanism_name,
            sc.category,
            sc.probability,
            sc.current_stage,
            sc.expected_magnitude,
            sc.confidence,
            "; ".join(sc.watch_items),
        ]
        for sc in report.active_scenarios
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _write_trades(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
    """Write trade theses to the Trades worksheet."""
    headers = [
        "Week", "Ticker", "Direction", "Entry Price",
        "TP %", "SL %", "R:R",
        "Consensus Score", "Our Score", "Divergence",
        "Divergence Label", "Composite Score", "Rationale",
    ]
    ws = _get_or_create_worksheet(sh, "Trades", headers)
    rows = [
        [
            week,
            tt.ticker,
            tt.direction,
            tt.entry_price,
            tt.take_profit_pct,
            tt.stop_loss_pct,
            tt.risk_reward_ratio,
            tt.consensus_score_at_entry,
            tt.our_score_at_entry,
            tt.divergence_at_entry,
            tt.divergence_label,
            tt.composite_score,
            tt.rationale,
        ]
        for tt in report.trade_theses
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _write_consensus(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
    """Write consensus scores to the Consensus worksheet."""
    if not report.consensus_scores:
        return

    headers = [
        "Week", "Ticker", "Consensus Score", "Direction",
        "Options Skew", "Funding 7d", "Top Trader L/S",
        "ETF Flow 5d", "Put/Call Ratio", "Max Pain Dist %",
        "OI Change 7d %",
    ]
    ws = _get_or_create_worksheet(sh, "Consensus", headers)
    rows = [
        [
            week,
            cs.ticker,
            cs.consensus_score,
            cs.consensus_direction,
            cs.options_skew,
            cs.funding_rate_7d,
            cs.top_trader_ls_ratio,
            cs.etf_flow_5d,
            cs.put_call_ratio,
            cs.max_pain_distance_pct,
            cs.oi_change_7d_pct,
        ]
        for cs in report.consensus_scores
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
