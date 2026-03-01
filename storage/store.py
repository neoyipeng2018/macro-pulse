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
    EconomicRegime,
    EdgeType,
    Narrative,
    PriceValidation,
    ScenarioAssetImpact,
    ScenarioAssetView,
    SentimentDirection,
    Signal,
    SignalSource,
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

        CREATE TABLE IF NOT EXISTS price_validations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            predicted_direction TEXT NOT NULL,
            predicted_score REAL NOT NULL,
            actual_return_pct REAL NOT NULL,
            actual_direction TEXT NOT NULL,
            hit INTEGER NOT NULL DEFAULT 0,
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

    # Save price validations
    for pv in report.price_validations:
        conn.execute(
            """INSERT INTO price_validations
            (report_id, ticker, asset_class, predicted_direction, predicted_score,
             actual_return_pct, actual_direction, hit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                pv.ticker,
                pv.asset_class.value,
                pv.predicted_direction.value,
                pv.predicted_score,
                pv.actual_return_pct,
                pv.actual_direction.value,
                1 if pv.hit else 0,
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

    # Load price validations
    pv_rows = conn.execute(
        "SELECT * FROM price_validations WHERE report_id = ?",
        (report_id,),
    ).fetchall()

    price_validations = [
        PriceValidation(
            ticker=pv["ticker"],
            asset_class=AssetClass(pv["asset_class"]),
            predicted_direction=SentimentDirection(pv["predicted_direction"]),
            predicted_score=pv["predicted_score"],
            actual_return_pct=pv["actual_return_pct"],
            actual_direction=SentimentDirection(pv["actual_direction"]),
            hit=bool(pv["hit"]),
        )
        for pv in pv_rows
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

    return WeeklyReport(
        id=report_id,
        week_start=datetime.fromisoformat(row["week_start"]),
        week_end=datetime.fromisoformat(row["week_end"]),
        generated_at=datetime.fromisoformat(row["generated_at"]),
        regime=EconomicRegime(row["regime"]),
        regime_rationale=row["regime_rationale"],
        narratives=narratives,
        asset_scores=asset_scores,
        price_validations=price_validations,
        signal_count=row["signal_count"],
        summary=row["summary"],
        active_scenarios=active_scenarios,
        scenario_views=scenario_views,
    )


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
