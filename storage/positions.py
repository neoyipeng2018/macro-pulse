"""Position tracker: trade lifecycle management and trade journal.

Manages the trades and portfolio_snapshots tables for tracking
proposed → open → closed trade lifecycle with P&L computation.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from models.schemas import PortfolioSnapshot, Trade

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "macro_pulse.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def save_trades(trades: list[Trade]) -> None:
    """Save proposed trades to database."""
    if not trades:
        return
    conn = _get_conn()
    for t in trades:
        conn.execute(
            """INSERT OR REPLACE INTO trades
            (id, report_id, ticker, direction, entry_price, entry_time,
             position_usd, position_size, stop_loss_price, take_profit_price,
             intermediate_tp_price, risk_reward, composite_score, status,
             exit_price, exit_time, exit_reason, pnl_usd, pnl_pct, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                t.id, t.report_id, t.ticker, t.direction, t.entry_price,
                t.created_at.isoformat(), t.position_usd, t.position_size,
                t.stop_loss_price, t.take_profit_price,
                t.intermediate_tp_price, t.risk_reward,
                t.composite_score, t.status,
                t.exit_price,
                t.exit_time.isoformat() if t.exit_time else None,
                t.exit_reason, t.pnl_usd, t.pnl_pct, t.notes,
            ),
        )
    conn.commit()
    conn.close()
    logger.info("Saved %d trades", len(trades))


def load_trades(status: str | None = None, ticker: str | None = None, limit: int = 100) -> list[Trade]:
    """Load trades from database with optional filters."""
    conn = _get_conn()
    query = "SELECT * FROM trades WHERE 1=1"
    params: list = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker)

    query += " ORDER BY rowid DESC LIMIT ?"
    params.append(limit)

    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    trades = []
    for r in rows:
        trades.append(Trade(
            id=r["id"],
            report_id=r["report_id"] or "",
            ticker=r["ticker"],
            direction=r["direction"],
            entry_price=r["entry_price"] or 0.0,
            position_usd=r["position_usd"] or 0.0,
            position_size=r["position_size"] or 0.0,
            stop_loss_price=r["stop_loss_price"] or 0.0,
            take_profit_price=r["take_profit_price"] or 0.0,
            intermediate_tp_price=r["intermediate_tp_price"],
            risk_reward=r["risk_reward"] or 0.0,
            composite_score=r["composite_score"] or 0.0,
            status=r["status"] or "proposed",
            exit_price=r["exit_price"],
            exit_time=datetime.fromisoformat(r["exit_time"]) if r["exit_time"] else None,
            exit_reason=r["exit_reason"],
            pnl_usd=r["pnl_usd"],
            pnl_pct=r["pnl_pct"],
            notes=r["notes"] or "",
            created_at=datetime.fromisoformat(r["entry_time"]) if r["entry_time"] else datetime.utcnow(),
        ))

    conn.close()
    return trades


def update_trade_status(
    trade_id: str,
    status: str,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    notes: str | None = None,
    entry_price: float | None = None,
) -> None:
    """Update a trade's status, computing P&L if closing."""
    conn = _get_conn()

    # Fetch current trade
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Trade {trade_id} not found")

    updates = {"status": status}

    if entry_price is not None:
        updates["entry_price"] = entry_price

    if status in ("closed", "stopped", "expired", "partial_tp") and exit_price is not None:
        updates["exit_price"] = exit_price
        updates["exit_time"] = datetime.utcnow().isoformat()
        updates["exit_reason"] = exit_reason or status

        # Compute P&L
        ep = entry_price if entry_price is not None else row["entry_price"]
        direction = row["direction"]
        pos_size = row["position_size"] or 0

        if direction == "LONG":
            pnl = (exit_price - ep) * pos_size
        else:
            pnl = (ep - exit_price) * pos_size

        pnl_pct = ((exit_price - ep) / ep * 100) if ep else 0
        if direction == "SHORT":
            pnl_pct = -pnl_pct

        updates["pnl_usd"] = round(pnl, 2)
        updates["pnl_pct"] = round(pnl_pct, 2)

    if notes:
        updates["notes"] = notes

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [trade_id]
    conn.execute(f"UPDATE trades SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()

    logger.info("Updated trade %s → %s", trade_id, status)


def check_open_positions(current_prices: dict[str, float]) -> list[dict]:
    """Check open positions against current prices for stop/TP hits.

    Returns a list of events: [{"trade_id", "ticker", "event", "price"}, ...]
    """
    open_trades = load_trades(status="open") + load_trades(status="partial_tp")
    events = []

    for t in open_trades:
        price = current_prices.get(t.ticker)
        if price is None:
            continue

        if t.direction == "LONG":
            if price <= t.stop_loss_price:
                events.append({
                    "trade_id": t.id, "ticker": t.ticker,
                    "event": "stop_hit", "price": price,
                })
                update_trade_status(t.id, "stopped", exit_price=price, exit_reason="stop_hit")
            elif t.take_profit_price and price >= t.take_profit_price:
                events.append({
                    "trade_id": t.id, "ticker": t.ticker,
                    "event": "tp_hit", "price": price,
                })
                update_trade_status(t.id, "closed", exit_price=price, exit_reason="tp_hit")
            elif (
                t.intermediate_tp_price
                and price >= t.intermediate_tp_price
                and t.status != "partial_tp"
            ):
                events.append({
                    "trade_id": t.id, "ticker": t.ticker,
                    "event": "partial_tp", "price": price,
                })
                update_trade_status(t.id, "partial_tp", exit_price=price, exit_reason="partial_tp")
        else:  # SHORT
            if price >= t.stop_loss_price:
                events.append({
                    "trade_id": t.id, "ticker": t.ticker,
                    "event": "stop_hit", "price": price,
                })
                update_trade_status(t.id, "stopped", exit_price=price, exit_reason="stop_hit")
            elif t.take_profit_price and price <= t.take_profit_price:
                events.append({
                    "trade_id": t.id, "ticker": t.ticker,
                    "event": "tp_hit", "price": price,
                })
                update_trade_status(t.id, "closed", exit_price=price, exit_reason="tp_hit")
            elif (
                t.intermediate_tp_price
                and price <= t.intermediate_tp_price
                and t.status != "partial_tp"
            ):
                events.append({
                    "trade_id": t.id, "ticker": t.ticker,
                    "event": "partial_tp", "price": price,
                })
                update_trade_status(t.id, "partial_tp", exit_price=price, exit_reason="partial_tp")

    # Check expired trades (horizon exceeded)
    now = datetime.utcnow()
    for t in open_trades:
        from datetime import timedelta
        if t.created_at and (now - t.created_at).days > t.horizon_days:
            events.append({
                "trade_id": t.id, "ticker": t.ticker,
                "event": "expired", "price": current_prices.get(t.ticker),
            })
            # Don't auto-close expired — flag for review
            update_trade_status(
                t.id, t.status, notes=f"EXPIRED: horizon {t.horizon_days}d exceeded"
            )

    return events


def get_recently_stopped(hours: int = 24) -> list[dict]:
    """Get trades stopped out within the last N hours."""
    conn = _get_conn()
    cutoff = datetime.utcnow()
    from datetime import timedelta
    cutoff = cutoff - timedelta(hours=hours)

    try:
        rows = conn.execute(
            """SELECT id, ticker, exit_time FROM trades
            WHERE status = 'stopped' AND exit_time >= ?
            ORDER BY exit_time DESC""",
            (cutoff.isoformat(),),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    conn.close()
    return [
        {"ticker": r["ticker"], "exit_time": r["exit_time"]}
        for r in rows
    ]


def save_portfolio_snapshot(snapshot: PortfolioSnapshot) -> None:
    """Save a portfolio snapshot."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO portfolio_snapshots
        (id, timestamp, total_capital, deployed_capital,
         open_positions, unrealized_pnl, realized_pnl_cumulative)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot.id, snapshot.timestamp.isoformat(),
            snapshot.total_capital, snapshot.deployed_capital,
            snapshot.open_positions, snapshot.unrealized_pnl,
            snapshot.realized_pnl_cumulative,
        ),
    )
    conn.commit()
    conn.close()


def get_trade_journal(limit: int = 50) -> list[Trade]:
    """Get closed/stopped trades for the trade journal."""
    return load_trades(status=None, limit=limit)


def get_cumulative_pnl() -> float:
    """Get cumulative realized P&L from all closed trades."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl_usd), 0) as total FROM trades WHERE status IN ('closed', 'stopped')"
        ).fetchone()
    except sqlite3.OperationalError:
        conn.close()
        return 0.0
    conn.close()
    return float(row["total"]) if row else 0.0
