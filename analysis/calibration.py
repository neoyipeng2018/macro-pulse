"""Confidence calibration based on historical trade performance.

After enough closed trades, adjusts the calibration multiplier to
reduce sizing when the system is wrong often, and modestly increase
sizing when it's accurate.
"""

from __future__ import annotations

import logging

from models.schemas import Trade

logger = logging.getLogger(__name__)

MIN_TRADES = 10
EXPECTED_HIT_RATE = 0.60  # 60% directional accuracy expected for macro
MIN_MULT = 0.5
MAX_MULT = 1.2


def calibration_multiplier(trade_history: list[Trade]) -> float:
    """Compute calibration multiplier from closed trade history.

    If system predicts direction correctly 60% of the time → mult = 1.0.
    If only 40% → mult ~0.67. If 72% → mult = 1.2 (capped).

    Returns 1.0 if fewer than MIN_TRADES closed trades exist.
    """
    closed = [
        t for t in trade_history
        if t.status in ("closed", "stopped") and t.pnl_usd is not None
    ]

    if len(closed) < MIN_TRADES:
        logger.debug(
            "Calibration: only %d closed trades (need %d), returning 1.0",
            len(closed), MIN_TRADES,
        )
        return 1.0

    hits = sum(1 for t in closed if t.pnl_usd > 0)
    hit_rate = hits / len(closed)

    mult = hit_rate / EXPECTED_HIT_RATE
    mult = max(MIN_MULT, min(MAX_MULT, mult))

    logger.info(
        "Calibration: %d/%d hits (%.1f%%), multiplier=%.2f",
        hits, len(closed), hit_rate * 100, mult,
    )
    return round(mult, 4)
