"""Export WeeklyReport data to Google Sheets."""

import logging

import gspread

from models.schemas import WeeklyReport

logger = logging.getLogger("macro-pulse.sheets")


def export_to_sheets(report: WeeklyReport) -> None:
    """Append report data to 4 worksheets in the configured Google Sheet.

    Creates worksheets and header rows if they don't exist yet.
    Appends rows so historical data accumulates across runs.
    """
    from config.settings import settings

    creds_file = settings.google_sheets_credentials_file
    spreadsheet_id = settings.google_sheets_spreadsheet_id

    if not spreadsheet_id:
        logger.debug("No spreadsheet ID configured — skipping Sheets export")
        return

    gc = gspread.service_account(filename=creds_file)
    sh = gc.open_by_key(spreadsheet_id)

    week = report.week_start.strftime("%Y-%m-%d")

    _write_summary(sh, report, week)
    _write_asset_scores(sh, report, week)
    _write_scenarios(sh, report, week)
    _write_validations(sh, report, week)
    _write_trade_sheet(sh, report, week)

    logger.info("Report exported to Google Sheets (week: %s)", week)


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
        "Week", "Ticker", "Asset Class", "Direction", "Score",
        "Conviction", "Narrative Count", "Top Narrative",
    ]
    ws = _get_or_create_worksheet(sh, "Asset Scores", headers)
    rows = [
        [
            week,
            s.ticker,
            s.asset_class.value,
            s.direction.value,
            s.score,
            s.conviction,
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


def _write_trade_sheet(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
    headers = [
        "Week", "Ticker", "Direction", "Composite Score", "Entry Price",
        "Position USD", "Position Size", "Portfolio %", "Stop Loss",
        "Take Profit", "Partial TP", "R:R", "Risk USD", "Reward USD",
        "Horizon Days", "Confidence", "Regime", "Conflict", "Narrative",
    ]
    ws = _get_or_create_worksheet(sh, "Trade Sheet", headers)
    rows = [
        [
            week,
            t.ticker,
            t.direction,
            t.composite_score,
            t.entry_price,
            t.position_usd,
            t.position_size,
            t.portfolio_pct,
            t.stop_loss_price,
            t.take_profit_price,
            t.intermediate_tp_price or "",
            t.risk_reward,
            t.risk_usd,
            t.reward_usd,
            t.horizon_days,
            t.confidence,
            t.regime,
            t.conflict_flag,
            t.top_narrative,
        ]
        for t in report.trades
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _write_validations(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
    headers = [
        "Week", "Ticker", "Asset Class", "Predicted Direction", "Predicted Score",
        "Actual Return %", "Actual Direction", "Hit",
    ]
    ws = _get_or_create_worksheet(sh, "Validations", headers)
    rows = [
        [
            week,
            v.ticker,
            v.asset_class.value,
            v.predicted_direction.value,
            v.predicted_score,
            v.actual_return_pct,
            v.actual_direction.value,
            v.hit,
        ]
        for v in report.price_validations
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
