"""Export WeeklyReport data to Google Sheets."""

import logging
from pathlib import Path

import gspread

from models.schemas import ActiveScenario, ConsensusView, NonConsensusView, WeeklyReport

logger = logging.getLogger("macro-pulse.sheets")


def _get_gspread_client(creds_file: str) -> gspread.Client:
    """Return an authenticated gspread client.

    Tries the local credentials file first. If the file doesn't exist
    (e.g. on Streamlit Cloud), falls back to ``st.secrets["gcp_service_account"]``.
    """
    if creds_file and Path(creds_file).exists():
        return gspread.service_account(filename=creds_file)

    try:
        import streamlit as st
        creds = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds:
            pk = creds["private_key"].replace("\\n", "\n").strip()
            creds["private_key"] = pk
            logger.debug(
                "Service-account key: client_email=%s, key starts=%s…, key ends=…%s",
                creds.get("client_email", "?"),
                pk[:30],
                pk[-30:],
            )
        return gspread.service_account_from_dict(creds)
    except KeyError:
        pass
    except Exception as exc:
        logger.error("Failed to authenticate with st.secrets: %s", exc)
        raise

    raise RuntimeError(
        "No Google Sheets credentials found. Set GOOGLE_SHEETS_CREDENTIALS_FILE "
        "or add a [gcp_service_account] section in Streamlit secrets."
    )


def _get_or_create_worksheet(
    sh: gspread.Spreadsheet, title: str, headers: list[str]
) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


def export_to_sheets(report: WeeklyReport) -> None:
    """Append report data to worksheets in the configured Google Sheet."""
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
    _write_consensus(sh, report, week)
    _write_consensus_views(sh, report.consensus_views, week)
    _write_non_consensus_views(sh, report.non_consensus_views, week)
    _write_active_mechanisms(sh, report.active_scenarios, week)

    logger.info("Report exported to Google Sheets (week: %s)", week)


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


def _write_consensus(
    sh: gspread.Spreadsheet, report: WeeklyReport, week: str
) -> None:
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


def _write_consensus_views(
    sh: gspread.Spreadsheet, views: list[ConsensusView], week: str
) -> None:
    if not views:
        return

    headers = [
        "Week", "Ticker", "Asset Class", "Quant Score", "Quant Direction",
        "Positioning Consensus", "Positioning Summary",
        "Narrative Consensus", "Market Narrative",
        "Coherence", "Coherence Detail",
        "Key Levels", "Priced In", "Not Priced In",
        "Direction", "Confidence",
    ]
    ws = _get_or_create_worksheet(sh, "Consensus Views", headers)
    rows = [
        [
            week,
            v.ticker,
            v.asset_class.value,
            v.quant_score,
            v.quant_direction,
            v.positioning_consensus,
            v.positioning_summary,
            v.narrative_consensus,
            v.market_narrative,
            v.consensus_coherence,
            v.coherence_detail,
            "; ".join(v.key_levels),
            "; ".join(v.priced_in),
            "; ".join(v.not_priced_in),
            v.consensus_direction.value,
            v.consensus_confidence,
        ]
        for v in views
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _write_non_consensus_views(
    sh: gspread.Spreadsheet, views: list[NonConsensusView], week: str
) -> None:
    if not views:
        return

    headers = [
        "Week", "Ticker", "Asset Class",
        "Consensus Direction", "Consensus Narrative",
        "Our Direction", "Our Conviction", "Thesis",
        "Edge Type", "Evidence Sources", "Independent Sources",
        "Testable Mechanism?", "Timing Edge?", "Catalyst",
        "Invalidation", "Validity Score",
        "Supporting Mechanisms", "Mechanism Stage",
        "Regime Context", "Consensus Quant Score", "Consensus Coherence",
    ]
    ws = _get_or_create_worksheet(sh, "Non-Consensus Views", headers)
    rows = [
        [
            week,
            v.ticker,
            v.asset_class.value,
            v.consensus_direction.value,
            v.consensus_narrative,
            v.our_direction.value,
            v.our_conviction,
            v.thesis,
            v.edge_type,
            "; ".join(f"{e.source}: {e.summary}" for e in v.evidence),
            v.independent_source_count,
            "Yes" if v.has_testable_mechanism else "No",
            "Yes" if v.has_timing_edge else "No",
            v.has_catalyst,
            v.invalidation,
            v.validity_score,
            ", ".join(v.supporting_mechanisms),
            v.mechanism_stage,
            v.regime_context,
            v.consensus_quant_score,
            v.consensus_coherence,
        ]
        for v in views
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _write_active_mechanisms(
    sh: gspread.Spreadsheet, scenarios: list[ActiveScenario], week: str
) -> None:
    if not scenarios:
        return

    headers = [
        "Week", "Mechanism", "Category", "Probability", "Stage",
        "Magnitude", "Confidence",
        "Chain Progress", "Asset Impacts", "Watch Items",
        "Confirmation Status", "Invalidation Risk",
    ]
    ws = _get_or_create_worksheet(sh, "Active Mechanisms", headers)
    rows = [
        [
            week,
            sc.mechanism_name,
            sc.category,
            sc.probability,
            sc.current_stage,
            sc.expected_magnitude,
            sc.confidence,
            " -> ".join(
                f"{step.description} ({step.status})"
                for step in sc.chain_progress
            ) if sc.chain_progress else "",
            "; ".join(
                f"{imp.ticker} {imp.direction.value}"
                for imp in sc.asset_impacts
            ) if sc.asset_impacts else "",
            "; ".join(sc.watch_items),
            sc.confirmation_status,
            sc.invalidation_risk,
        ]
        for sc in scenarios
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
