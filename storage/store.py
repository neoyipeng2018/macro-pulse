"""SQLite persistence for weekly reports, narratives, and asset scores."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from models.schemas import (
    ActiveScenario,
    AssetClass,
    AssetScenarioEntry,
    AssetSentiment,
    ChainStepProgress,
    CompositeAssetScore,
    ConsensusScore,
    DivergenceMetrics,
    EconomicRegime,
    EdgeType,
    Narrative,
    ScenarioAssetImpact,
    ScenarioAssetView,
    SentimentDirection,
    Signal,
    SignalSource,
    TradeOutcome,
    TradeThesis,
    WeeklyAssetScore,
    WeeklyReport,
)

DB_PATH = Path(__file__).parent.parent / "macro_pulse.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id TEXT PRIMARY KEY,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            regime TEXT NOT NULL,
            regime_rationale TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            signal_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS narratives (
            id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            asset_sentiments TEXT NOT NULL DEFAULT '[]',
            affected_asset_classes TEXT NOT NULL DEFAULT '[]',
            horizon TEXT NOT NULL DEFAULT '1-4 weeks',
            confidence REAL NOT NULL DEFAULT 0.5,
            trend TEXT NOT NULL DEFAULT 'stable',
            consensus_view TEXT NOT NULL DEFAULT '',
            consensus_sources TEXT NOT NULL DEFAULT '[]',
            edge_type TEXT NOT NULL DEFAULT 'aligned',
            edge_rationale TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            url TEXT,
            timestamp TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS narrative_signals (
            narrative_id TEXT NOT NULL,
            signal_id TEXT NOT NULL,
            PRIMARY KEY (narrative_id, signal_id),
            FOREIGN KEY (narrative_id) REFERENCES narratives(id),
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );

        CREATE TABLE IF NOT EXISTS weekly_asset_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            direction TEXT NOT NULL,
            score REAL NOT NULL,
            conviction REAL NOT NULL DEFAULT 0.0,
            narrative_count INTEGER NOT NULL DEFAULT 0,
            top_narrative TEXT,
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS active_scenarios (
            id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL,
            mechanism_id TEXT,
            mechanism_name TEXT,
            category TEXT,
            probability REAL,
            trigger_signals TEXT,
            trigger_evidence TEXT,
            chain_progress TEXT,
            current_stage TEXT,
            expected_magnitude TEXT,
            asset_impacts TEXT,
            watch_items TEXT,
            confirmation_status TEXT,
            invalidation_risk TEXT,
            horizon TEXT,
            confidence REAL,
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS scenario_asset_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            ticker TEXT,
            asset_class TEXT,
            scenarios TEXT,
            net_direction TEXT,
            net_score REAL,
            dominant_scenario TEXT,
            scenario_count INTEGER,
            conflict_flag INTEGER,
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS composite_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            direction TEXT NOT NULL,
            composite_score REAL NOT NULL DEFAULT 0.0,
            confidence REAL NOT NULL DEFAULT 0.0,
            narrative_score REAL NOT NULL DEFAULT 0.0,
            technical_score REAL NOT NULL DEFAULT 0.0,
            scenario_score REAL NOT NULL DEFAULT 0.0,
            contrarian_bonus REAL NOT NULL DEFAULT 0.0,
            narrative_count INTEGER NOT NULL DEFAULT 0,
            top_narrative TEXT,
            conflict_flag INTEGER NOT NULL DEFAULT 0,
            edge_type TEXT NOT NULL DEFAULT 'aligned',
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS consensus_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            consensus_score REAL NOT NULL DEFAULT 0.0,
            consensus_direction TEXT NOT NULL DEFAULT 'neutral',
            components TEXT NOT NULL DEFAULT '{}',
            options_skew REAL NOT NULL DEFAULT 0.0,
            funding_rate_7d REAL NOT NULL DEFAULT 0.0,
            top_trader_ls_ratio REAL NOT NULL DEFAULT 0.0,
            etf_flow_5d REAL NOT NULL DEFAULT 0.0,
            put_call_ratio REAL NOT NULL DEFAULT 0.0,
            max_pain_distance_pct REAL NOT NULL DEFAULT 0.0,
            oi_change_7d_pct REAL NOT NULL DEFAULT 0.0,
            data_timestamp TEXT NOT NULL,
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS trade_theses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL DEFAULT 0.0,
            entry_date TEXT NOT NULL,
            take_profit_pct REAL NOT NULL DEFAULT 0.0,
            stop_loss_pct REAL NOT NULL DEFAULT 0.0,
            risk_reward_ratio REAL NOT NULL DEFAULT 0.0,
            max_holding_days INTEGER NOT NULL DEFAULT 7,
            consensus_score_at_entry REAL NOT NULL DEFAULT 0.0,
            our_score_at_entry REAL NOT NULL DEFAULT 0.0,
            divergence_at_entry REAL NOT NULL DEFAULT 0.0,
            divergence_label TEXT NOT NULL DEFAULT 'aligned',
            composite_score REAL NOT NULL DEFAULT 0.0,
            rationale TEXT NOT NULL DEFAULT '',
            exit_price REAL,
            exit_date TEXT,
            exit_reason TEXT,
            pnl_pct REAL,
            days_held INTEGER,
            direction_correct INTEGER,
            FOREIGN KEY (report_id) REFERENCES weekly_reports(id)
        );

        CREATE TABLE IF NOT EXISTS trade_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            week TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_date TEXT NOT NULL,
            exit_price REAL NOT NULL,
            exit_date TEXT NOT NULL,
            exit_reason TEXT NOT NULL,
            pnl_pct REAL NOT NULL,
            direction_correct INTEGER NOT NULL,
            consensus_score REAL NOT NULL DEFAULT 0.0,
            our_score REAL NOT NULL DEFAULT 0.0,
            divergence REAL NOT NULL DEFAULT 0.0,
            divergence_label TEXT NOT NULL DEFAULT 'aligned',
            days_held INTEGER NOT NULL DEFAULT 0
        );
    """
    )
    # Migrate: add consensus columns if missing (existing databases)
    try:
        conn.execute("SELECT consensus_view FROM narratives LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE narratives ADD COLUMN consensus_view TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE narratives ADD COLUMN consensus_sources TEXT NOT NULL DEFAULT '[]'")
        conn.execute("ALTER TABLE narratives ADD COLUMN edge_type TEXT NOT NULL DEFAULT 'aligned'")
        conn.execute("ALTER TABLE narratives ADD COLUMN edge_rationale TEXT NOT NULL DEFAULT ''")

    conn.commit()
    conn.close()


def save_report(report: WeeklyReport) -> None:
    """Persist a complete weekly report with all related data."""
    conn = _get_conn()

    conn.execute(
        """INSERT OR REPLACE INTO weekly_reports
        (id, week_start, week_end, generated_at, regime, regime_rationale, summary, signal_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report.id,
            report.week_start.isoformat(),
            report.week_end.isoformat(),
            report.generated_at.isoformat(),
            report.regime.value,
            report.regime_rationale,
            report.summary,
            report.signal_count,
        ),
    )

    # Save narratives
    for narrative in report.narratives:
        conn.execute(
            """INSERT OR REPLACE INTO narratives
            (id, report_id, title, summary, asset_sentiments, affected_asset_classes,
             horizon, confidence, trend, consensus_view, consensus_sources,
             edge_type, edge_rationale, first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                narrative.id,
                report.id,
                narrative.title,
                narrative.summary,
                json.dumps([s.model_dump() for s in narrative.asset_sentiments]),
                json.dumps([a.value for a in narrative.affected_asset_classes]),
                narrative.horizon,
                narrative.confidence,
                narrative.trend,
                narrative.consensus_view,
                json.dumps(narrative.consensus_sources),
                narrative.edge_type.value,
                narrative.edge_rationale,
                narrative.first_seen.isoformat(),
                narrative.last_updated.isoformat(),
            ),
        )

        # Save signals
        for signal in narrative.signals:
            conn.execute(
                """INSERT OR IGNORE INTO signals
                (id, source, title, content, url, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.id,
                    signal.source.value,
                    signal.title,
                    signal.content,
                    signal.url,
                    signal.timestamp.isoformat(),
                    json.dumps(signal.metadata),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO narrative_signals (narrative_id, signal_id) VALUES (?, ?)",
                (narrative.id, signal.id),
            )

    # Save asset scores
    for score in report.asset_scores:
        conn.execute(
            """INSERT INTO weekly_asset_scores
            (report_id, ticker, asset_class, direction, score, conviction,
             narrative_count, top_narrative)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                score.ticker,
                score.asset_class.value,
                score.direction.value,
                score.score,
                score.conviction,
                score.narrative_count,
                score.top_narrative,
            ),
        )

    # Save active scenarios
    for sc in report.active_scenarios:
        conn.execute(
            """INSERT OR REPLACE INTO active_scenarios
            (id, report_id, mechanism_id, mechanism_name, category,
             probability, trigger_signals, trigger_evidence,
             chain_progress, current_stage, expected_magnitude,
             asset_impacts, watch_items, confirmation_status,
             invalidation_risk, horizon, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sc.id,
                report.id,
                sc.mechanism_id,
                sc.mechanism_name,
                sc.category,
                sc.probability,
                json.dumps(sc.trigger_signals),
                sc.trigger_evidence,
                json.dumps([cp.model_dump() for cp in sc.chain_progress]),
                sc.current_stage,
                sc.expected_magnitude,
                json.dumps([ai.model_dump() for ai in sc.asset_impacts]),
                json.dumps(sc.watch_items),
                sc.confirmation_status,
                sc.invalidation_risk,
                sc.horizon,
                sc.confidence,
            ),
        )

    # Save scenario asset views
    for sv in report.scenario_views:
        conn.execute(
            """INSERT INTO scenario_asset_views
            (report_id, ticker, asset_class, scenarios,
             net_direction, net_score, dominant_scenario,
             scenario_count, conflict_flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                sv.ticker,
                sv.asset_class.value,
                json.dumps([s.model_dump() for s in sv.scenarios]),
                sv.net_direction.value,
                sv.net_score,
                sv.dominant_scenario,
                sv.scenario_count,
                1 if sv.conflict_flag else 0,
            ),
        )

    # Save composite scores
    for cs in report.composite_scores:
        conn.execute(
            """INSERT INTO composite_scores
            (report_id, ticker, asset_class, direction,
             composite_score, confidence, narrative_score,
             technical_score, scenario_score, contrarian_bonus,
             narrative_count, top_narrative, conflict_flag, edge_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                cs.ticker,
                cs.asset_class.value,
                cs.direction.value,
                cs.composite_score,
                cs.confidence,
                cs.narrative_score,
                cs.technical_score,
                cs.scenario_score,
                cs.contrarian_bonus,
                cs.narrative_count,
                cs.top_narrative,
                1 if cs.conflict_flag else 0,
                cs.edge_type,
            ),
        )

    # Save consensus scores
    for cns in report.consensus_scores:
        conn.execute(
            """INSERT INTO consensus_scores
            (report_id, ticker, consensus_score, consensus_direction,
             components, options_skew, funding_rate_7d, top_trader_ls_ratio,
             etf_flow_5d, put_call_ratio, max_pain_distance_pct,
             oi_change_7d_pct, data_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                cns.ticker,
                cns.consensus_score,
                cns.consensus_direction,
                json.dumps(cns.components),
                cns.options_skew,
                cns.funding_rate_7d,
                cns.top_trader_ls_ratio,
                cns.etf_flow_5d,
                cns.put_call_ratio,
                cns.max_pain_distance_pct,
                cns.oi_change_7d_pct,
                cns.data_timestamp.isoformat(),
            ),
        )

    # Save trade theses
    for tt in report.trade_theses:
        conn.execute(
            """INSERT INTO trade_theses
            (report_id, ticker, direction, entry_price, entry_date,
             take_profit_pct, stop_loss_pct, risk_reward_ratio,
             max_holding_days, consensus_score_at_entry, our_score_at_entry,
             divergence_at_entry, divergence_label, composite_score, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                tt.ticker,
                tt.direction,
                tt.entry_price,
                tt.entry_date.isoformat(),
                tt.take_profit_pct,
                tt.stop_loss_pct,
                tt.risk_reward_ratio,
                tt.max_holding_days,
                tt.consensus_score_at_entry,
                tt.our_score_at_entry,
                tt.divergence_at_entry,
                tt.divergence_label,
                tt.composite_score,
                tt.rationale,
            ),
        )

    conn.commit()
    conn.close()


def load_latest_report() -> WeeklyReport | None:
    """Load the most recent weekly report."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM weekly_reports ORDER BY generated_at DESC LIMIT 1"
    ).fetchone()

    if not row:
        conn.close()
        return None

    report = _load_report_from_row(conn, row)
    conn.close()
    return report


def load_all_reports() -> list[WeeklyReport]:
    """Load all weekly reports (metadata only, without full narrative signals)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM weekly_reports ORDER BY generated_at DESC"
    ).fetchall()

    reports = []
    for row in rows:
        reports.append(_load_report_from_row(conn, row))

    conn.close()
    return reports


def _load_report_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> WeeklyReport:
    """Reconstruct a WeeklyReport from a database row."""
    report_id = row["id"]

    # Load narratives
    nar_rows = conn.execute(
        "SELECT * FROM narratives WHERE report_id = ? ORDER BY confidence DESC",
        (report_id,),
    ).fetchall()

    narratives = []
    for nr in nar_rows:
        # Load signals for this narrative
        sig_rows = conn.execute(
            """SELECT s.* FROM signals s
            JOIN narrative_signals ns ON s.id = ns.signal_id
            WHERE ns.narrative_id = ?""",
            (nr["id"],),
        ).fetchall()

        signals = [
            Signal(
                id=sr["id"],
                source=SignalSource(sr["source"]),
                title=sr["title"],
                content=sr["content"],
                url=sr["url"] or "",
                timestamp=datetime.fromisoformat(sr["timestamp"]),
                metadata=json.loads(sr["metadata"]) if sr["metadata"] else {},
            )
            for sr in sig_rows
        ]

        # Deserialize asset sentiments
        raw_sents = json.loads(nr["asset_sentiments"])
        asset_sentiments = []
        for s in raw_sents:
            if isinstance(s, dict):
                try:
                    asset_sentiments.append(AssetSentiment(**s))
                except (ValueError, KeyError):
                    continue

        # Parse edge type safely (handle old data without these columns)
        try:
            edge_type = EdgeType(nr["edge_type"]) if nr["edge_type"] else EdgeType.ALIGNED
        except (ValueError, IndexError, KeyError):
            edge_type = EdgeType.ALIGNED

        try:
            consensus_sources = json.loads(nr["consensus_sources"]) if nr["consensus_sources"] else []
        except (json.JSONDecodeError, IndexError, KeyError):
            consensus_sources = []

        narratives.append(
            Narrative(
                id=nr["id"],
                title=nr["title"],
                summary=nr["summary"],
                asset_sentiments=asset_sentiments,
                affected_asset_classes=[
                    AssetClass(a) for a in json.loads(nr["affected_asset_classes"])
                ],
                signals=signals,
                horizon=nr["horizon"],
                confidence=nr["confidence"],
                trend=nr["trend"],
                consensus_view=nr["consensus_view"] if "consensus_view" in nr.keys() else "",
                consensus_sources=consensus_sources,
                edge_type=edge_type,
                edge_rationale=nr["edge_rationale"] if "edge_rationale" in nr.keys() else "",
                first_seen=datetime.fromisoformat(nr["first_seen"]),
                last_updated=datetime.fromisoformat(nr["last_updated"]),
            )
        )

    # Load asset scores
    score_rows = conn.execute(
        "SELECT * FROM weekly_asset_scores WHERE report_id = ? ORDER BY score DESC",
        (report_id,),
    ).fetchall()

    asset_scores = [
        WeeklyAssetScore(
            ticker=sr["ticker"],
            asset_class=AssetClass(sr["asset_class"]),
            direction=SentimentDirection(sr["direction"]),
            score=sr["score"],
            conviction=sr["conviction"],
            narrative_count=sr["narrative_count"],
            top_narrative=sr["top_narrative"] or "",
        )
        for sr in score_rows
    ]

    # Load active scenarios
    active_scenarios = []
    try:
        sc_rows = conn.execute(
            "SELECT * FROM active_scenarios WHERE report_id = ? ORDER BY probability DESC",
            (report_id,),
        ).fetchall()
        for sr in sc_rows:
            chain_progress = []
            for cp in json.loads(sr["chain_progress"] or "[]"):
                if isinstance(cp, dict):
                    try:
                        chain_progress.append(ChainStepProgress(**cp))
                    except (ValueError, KeyError):
                        continue

            ai_list = []
            for ai_item in json.loads(sr["asset_impacts"] or "[]"):
                if isinstance(ai_item, dict):
                    try:
                        ai_list.append(ScenarioAssetImpact(**ai_item))
                    except (ValueError, KeyError):
                        continue

            active_scenarios.append(
                ActiveScenario(
                    id=sr["id"],
                    mechanism_id=sr["mechanism_id"] or "",
                    mechanism_name=sr["mechanism_name"] or "",
                    category=sr["category"] or "",
                    probability=sr["probability"] or 0.0,
                    trigger_signals=json.loads(sr["trigger_signals"] or "[]"),
                    trigger_evidence=sr["trigger_evidence"] or "",
                    chain_progress=chain_progress,
                    current_stage=sr["current_stage"] or "early",
                    expected_magnitude=sr["expected_magnitude"] or "moderate",
                    asset_impacts=ai_list,
                    watch_items=json.loads(sr["watch_items"] or "[]"),
                    confirmation_status=sr["confirmation_status"] or "",
                    invalidation_risk=sr["invalidation_risk"] or "",
                    horizon=sr["horizon"] or "1 week",
                    confidence=sr["confidence"] or 0.0,
                )
            )
    except sqlite3.OperationalError:
        # Table may not exist in older databases
        pass

    # Load scenario asset views
    scenario_views = []
    try:
        sv_rows = conn.execute(
            "SELECT * FROM scenario_asset_views WHERE report_id = ? ORDER BY net_score DESC",
            (report_id,),
        ).fetchall()
        for svr in sv_rows:
            scenarios_list = []
            for s in json.loads(svr["scenarios"] or "[]"):
                if isinstance(s, dict):
                    try:
                        scenarios_list.append(AssetScenarioEntry(**s))
                    except (ValueError, KeyError):
                        continue

            scenario_views.append(
                ScenarioAssetView(
                    ticker=svr["ticker"] or "",
                    asset_class=AssetClass(svr["asset_class"]),
                    scenarios=scenarios_list,
                    net_direction=SentimentDirection(svr["net_direction"]),
                    net_score=svr["net_score"] or 0.0,
                    dominant_scenario=svr["dominant_scenario"] or "",
                    scenario_count=svr["scenario_count"] or 0,
                    conflict_flag=bool(svr["conflict_flag"]),
                )
            )
    except sqlite3.OperationalError:
        # Table may not exist in older databases
        pass

    # Load composite scores
    composite_scores = []
    try:
        cs_rows = conn.execute(
            "SELECT * FROM composite_scores WHERE report_id = ? ORDER BY composite_score DESC",
            (report_id,),
        ).fetchall()
        for csr in cs_rows:
            composite_scores.append(
                CompositeAssetScore(
                    ticker=csr["ticker"],
                    asset_class=AssetClass(csr["asset_class"]),
                    direction=SentimentDirection(csr["direction"]),
                    composite_score=csr["composite_score"],
                    confidence=csr["confidence"],
                    narrative_score=csr["narrative_score"],
                    technical_score=csr["technical_score"],
                    scenario_score=csr["scenario_score"],
                    contrarian_bonus=csr["contrarian_bonus"],
                    narrative_count=csr["narrative_count"],
                    top_narrative=csr["top_narrative"] or "",
                    conflict_flag=bool(csr["conflict_flag"]),
                    edge_type=csr["edge_type"] or "aligned",
                )
            )
    except sqlite3.OperationalError:
        # Table may not exist in older databases
        pass

    # Load consensus scores
    consensus_scores_list = []
    try:
        cns_rows = conn.execute(
            "SELECT * FROM consensus_scores WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        for cr in cns_rows:
            consensus_scores_list.append(
                ConsensusScore(
                    ticker=cr["ticker"],
                    consensus_score=cr["consensus_score"],
                    consensus_direction=cr["consensus_direction"],
                    components=json.loads(cr["components"]) if cr["components"] else {},
                    options_skew=cr["options_skew"],
                    funding_rate_7d=cr["funding_rate_7d"],
                    top_trader_ls_ratio=cr["top_trader_ls_ratio"],
                    etf_flow_5d=cr["etf_flow_5d"],
                    put_call_ratio=cr["put_call_ratio"],
                    max_pain_distance_pct=cr["max_pain_distance_pct"],
                    oi_change_7d_pct=cr["oi_change_7d_pct"],
                    data_timestamp=datetime.fromisoformat(cr["data_timestamp"]),
                )
            )
    except sqlite3.OperationalError:
        pass

    # Load trade theses
    trade_theses = []
    try:
        tt_rows = conn.execute(
            "SELECT * FROM trade_theses WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        for tr in tt_rows:
            trade_theses.append(
                TradeThesis(
                    ticker=tr["ticker"],
                    direction=tr["direction"],
                    entry_price=tr["entry_price"],
                    entry_date=datetime.fromisoformat(tr["entry_date"]),
                    take_profit_pct=tr["take_profit_pct"],
                    stop_loss_pct=tr["stop_loss_pct"],
                    risk_reward_ratio=tr["risk_reward_ratio"],
                    max_holding_days=tr["max_holding_days"],
                    consensus_score_at_entry=tr["consensus_score_at_entry"],
                    our_score_at_entry=tr["our_score_at_entry"],
                    divergence_at_entry=tr["divergence_at_entry"],
                    divergence_label=tr["divergence_label"],
                    composite_score=tr["composite_score"],
                    rationale=tr["rationale"],
                    exit_price=tr["exit_price"],
                    exit_date=datetime.fromisoformat(tr["exit_date"]) if tr["exit_date"] else None,
                    exit_reason=tr["exit_reason"],
                    pnl_pct=tr["pnl_pct"],
                    days_held=tr["days_held"],
                    direction_correct=bool(tr["direction_correct"]) if tr["direction_correct"] is not None else None,
                )
            )
    except sqlite3.OperationalError:
        pass

    # Build divergence metrics from consensus + composite scores
    divergence_metrics = []
    if consensus_scores_list and composite_scores:
        composite_map = {c.ticker: c.composite_score for c in composite_scores}
        for cns in consensus_scores_list:
            our = composite_map.get(cns.ticker, 0.0)
            div = our - cns.consensus_score
            abs_div = abs(div)
            if abs_div > 1.0:
                label = "strongly_contrarian"
            elif abs_div > 0.5:
                label = "contrarian"
            elif abs_div > 0.2:
                label = "mildly_non_consensus"
            else:
                label = "aligned"
            our_dir = "bullish" if our > 0.1 else ("bearish" if our < -0.1 else "neutral")
            divergence_metrics.append(
                DivergenceMetrics(
                    ticker=cns.ticker,
                    consensus_score=cns.consensus_score,
                    our_score=our,
                    divergence=round(div, 4),
                    abs_divergence=round(abs_div, 4),
                    divergence_label=label,
                    consensus_direction=cns.consensus_direction,
                    our_direction=our_dir,
                )
            )

    return WeeklyReport(
        id=report_id,
        week_start=datetime.fromisoformat(row["week_start"]),
        week_end=datetime.fromisoformat(row["week_end"]),
        generated_at=datetime.fromisoformat(row["generated_at"]),
        regime=EconomicRegime(row["regime"]),
        regime_rationale=row["regime_rationale"],
        narratives=narratives,
        asset_scores=asset_scores,
        signal_count=row["signal_count"],
        summary=row["summary"],
        active_scenarios=active_scenarios,
        scenario_views=scenario_views,
        composite_scores=composite_scores,
        consensus_scores=consensus_scores_list,
        divergence_metrics=divergence_metrics,
        trade_theses=trade_theses,
    )


def get_pending_trades() -> list[dict]:
    """Get all trade theses that haven't been resolved yet (no exit_price)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT tt.*, wr.week_start as week FROM trade_theses tt
            JOIN weekly_reports wr ON tt.report_id = wr.id
            WHERE tt.exit_price IS NULL
            ORDER BY tt.entry_date ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def save_trade_outcome(outcome: TradeOutcome) -> None:
    """Save a resolved trade outcome."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO trade_outcomes
        (ticker, week, direction, entry_price, entry_date,
         exit_price, exit_date, exit_reason, pnl_pct,
         direction_correct, consensus_score, our_score,
         divergence, divergence_label, days_held)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            outcome.ticker,
            outcome.week,
            outcome.direction,
            outcome.entry_price,
            outcome.entry_date.isoformat(),
            outcome.exit_price,
            outcome.exit_date.isoformat(),
            outcome.exit_reason,
            outcome.pnl_pct,
            1 if outcome.direction_correct else 0,
            outcome.consensus_score,
            outcome.our_score,
            outcome.divergence,
            outcome.divergence_label,
            outcome.days_held,
        ),
    )
    conn.commit()
    conn.close()


def update_trade_thesis_outcome(
    trade_id: int,
    exit_price: float,
    exit_date: str,
    exit_reason: str,
    pnl_pct: float,
    days_held: int,
    direction_correct: bool,
) -> None:
    """Update a trade thesis with its outcome."""
    conn = _get_conn()
    conn.execute(
        """UPDATE trade_theses SET
        exit_price = ?, exit_date = ?, exit_reason = ?,
        pnl_pct = ?, days_held = ?, direction_correct = ?
        WHERE id = ?""",
        (
            exit_price,
            exit_date,
            exit_reason,
            pnl_pct,
            days_held,
            1 if direction_correct else 0,
            trade_id,
        ),
    )
    conn.commit()
    conn.close()


def get_all_outcomes() -> list[dict]:
    """Get all trade outcomes for performance tracking."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trade_outcomes ORDER BY exit_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_score_history(ticker: str | None = None, limit: int = 12) -> list[dict]:
    """Get historical asset scores across weeks for trend charting."""
    conn = _get_conn()
    if ticker:
        rows = conn.execute(
            """SELECT ws.*, wr.week_start FROM weekly_asset_scores ws
            JOIN weekly_reports wr ON ws.report_id = wr.id
            WHERE ws.ticker = ?
            ORDER BY wr.week_start DESC LIMIT ?""",
            (ticker, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT ws.*, wr.week_start FROM weekly_asset_scores ws
            JOIN weekly_reports wr ON ws.report_id = wr.id
            ORDER BY wr.week_start DESC LIMIT ?""",
            (limit * 30,),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]
