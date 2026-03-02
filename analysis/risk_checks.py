"""Safety rails: hard-coded pre-trade checks that cannot be overridden by config.

These are the last line of defense before a trade is proposed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from models.schemas import CompositeAssetScore, Trade, TradeParams

logger = logging.getLogger(__name__)

# Hard limits — cannot be overridden by risk.yaml
HARD_LIMITS = {
    "max_single_position_pct": 25,      # never more than 25% in one trade
    "max_total_exposure_pct": 100,       # never more than 100% deployed (no leverage)
    "max_daily_trades": 3,              # max 3 new trades per pipeline run
    "min_risk_reward": 1.2,             # never take a trade below 1.2 R:R
    "max_correlated_positions": 3,      # BTC + ETH + SOL are all crypto
    "min_composite_score": 0.3,         # no-trade zone below this
    "cooldown_after_stop_hours": 24,    # don't re-enter same ticker within 24h of stop-out
}

# Assets considered correlated (all crypto)
CORRELATED_GROUPS = [
    {"BTC-USD", "Bitcoin", "ETH-USD", "Ethereum", "SOL-USD", "Solana"},
]


@dataclass
class RiskCheckResult:
    """Result of pre-trade risk checks."""

    passed: bool
    ticker: str
    rejections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_trade(
    score: CompositeAssetScore,
    params: TradeParams,
    position_usd: float,
    portfolio_pct: float,
    total_capital: float,
    existing_trades: list[Trade],
    proposed_count: int,
    technical_agrees: bool | None = None,
    recently_stopped: list[dict] | None = None,
) -> RiskCheckResult:
    """Run all pre-trade safety checks.

    Parameters
    ----------
    score : CompositeAssetScore
        Composite score for the asset.
    params : TradeParams
        Parsed trade parameters.
    position_usd : float
        Proposed position size in USD.
    portfolio_pct : float
        Position as % of capital.
    total_capital : float
        Total portfolio capital.
    existing_trades : list[Trade]
        Currently open/proposed trades.
    proposed_count : int
        Number of trades already proposed this run.
    technical_agrees : bool | None
        Whether technicals agree with narrative direction.
    recently_stopped : list[dict] | None
        Recent stop-outs: [{"ticker": str, "exit_time": datetime}, ...]

    Returns
    -------
    RiskCheckResult
        pass/fail with reasons.
    """
    result = RiskCheckResult(passed=True, ticker=score.ticker)

    # Check 1: R:R minimum
    if params.risk_reward < HARD_LIMITS["min_risk_reward"]:
        result.rejections.append(
            f"R:R {params.risk_reward:.1f}x below minimum {HARD_LIMITS['min_risk_reward']}x"
        )

    # Check 2: Composite score minimum
    if abs(score.composite_score) < HARD_LIMITS["min_composite_score"]:
        result.rejections.append(
            f"Composite score {score.composite_score:.2f} below minimum "
            f"±{HARD_LIMITS['min_composite_score']}"
        )

    # Check 3: Max trades per run
    if proposed_count >= HARD_LIMITS["max_daily_trades"]:
        result.rejections.append(
            f"Max {HARD_LIMITS['max_daily_trades']} trades per run already reached"
        )

    # Check 4: Hard position cap
    if portfolio_pct > HARD_LIMITS["max_single_position_pct"]:
        result.rejections.append(
            f"Position {portfolio_pct:.1f}% exceeds hard cap "
            f"{HARD_LIMITS['max_single_position_pct']}%"
        )

    # Check 5: Total exposure cap
    existing_exposure = sum(
        t.position_usd for t in existing_trades
        if t.status in ("open", "partial_tp", "proposed")
    )
    new_total = existing_exposure + position_usd
    max_exposure = total_capital * (HARD_LIMITS["max_total_exposure_pct"] / 100)
    if new_total > max_exposure:
        result.rejections.append(
            f"Total exposure ${new_total:.0f} exceeds hard cap ${max_exposure:.0f}"
        )

    # Check 6: Correlated positions
    existing_tickers = {
        t.ticker for t in existing_trades
        if t.status in ("open", "partial_tp", "proposed")
    }
    for group in CORRELATED_GROUPS:
        correlated_count = len(existing_tickers & group)
        if score.ticker in group:
            correlated_count += 1
        if correlated_count > HARD_LIMITS["max_correlated_positions"]:
            result.rejections.append(
                f"Correlated positions ({correlated_count}) exceeds limit "
                f"{HARD_LIMITS['max_correlated_positions']}"
            )

    # Check 7: Cooldown after stop-out
    if recently_stopped:
        cooldown = timedelta(hours=HARD_LIMITS["cooldown_after_stop_hours"])
        now = datetime.utcnow()
        for stop in recently_stopped:
            if stop["ticker"] == score.ticker:
                exit_time = stop["exit_time"]
                if isinstance(exit_time, str):
                    exit_time = datetime.fromisoformat(exit_time)
                if now - exit_time < cooldown:
                    result.rejections.append(
                        f"Cooldown: {score.ticker} stopped out {exit_time.isoformat()}, "
                        f"wait {HARD_LIMITS['cooldown_after_stop_hours']}h"
                    )

    # Warning (non-blocking): technical disagreement
    if technical_agrees is False:
        result.warnings.append(
            "Technicals disagree with narrative direction"
        )

    result.passed = len(result.rejections) == 0

    if not result.passed:
        logger.info(
            "REJECTED %s: %s", score.ticker, "; ".join(result.rejections)
        )
    elif result.warnings:
        logger.info(
            "WARNING %s: %s", score.ticker, "; ".join(result.warnings)
        )

    return result
