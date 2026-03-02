"""Trade sheet generator: assemble and display actionable trade output.

Combines composite scores, trade params, position sizes, and risk checks
into a formatted trade sheet printed at end of pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from analysis.position_sizer import RiskConfig, SizedPosition, load_risk_config
from analysis.risk_checks import RiskCheckResult, check_trade
from models.schemas import (
    CompositeAssetScore,
    EconomicRegime,
    Trade,
    TradeParams,
)

logger = logging.getLogger(__name__)


def build_trades(
    composite_scores: list[CompositeAssetScore],
    trade_params: list[TradeParams],
    sized_positions: list[SizedPosition],
    risk_results: list[RiskCheckResult],
    regime: EconomicRegime,
    report_id: str = "",
) -> list[Trade]:
    """Assemble Trade objects from all components.

    Returns a list of Trade objects sorted by composite_score descending.
    Trades that failed risk checks are excluded.
    """
    params_by_ticker = {tp.ticker: tp for tp in trade_params}
    sizes_by_ticker = {sp.ticker: sp for sp in sized_positions}
    checks_by_ticker = {rc.ticker: rc for rc in risk_results}

    trades: list[Trade] = []

    for score in composite_scores:
        tp = params_by_ticker.get(score.ticker)
        sz = sizes_by_ticker.get(score.ticker)
        rc = checks_by_ticker.get(score.ticker)

        if tp is None or sz is None:
            continue

        # Skip if risk check failed
        if rc and not rc.passed:
            continue

        # Skip if position sizer says skip
        if sz.skip_reason:
            continue

        entry = tp.entry_price
        if entry <= 0:
            continue

        direction = tp.direction.upper()

        # Compute price levels
        if direction == "LONG":
            stop_price = entry * (1 + tp.stop_loss_pct / 100)
            tp_price = entry * (1 + tp.take_profit_pct / 100)
            itp_price = (
                entry * (1 + tp.intermediate_tp_pct / 100)
                if tp.intermediate_tp_pct
                else None
            )
        else:  # SHORT
            stop_price = entry * (1 - tp.stop_loss_pct / 100)
            tp_price = entry * (1 - tp.take_profit_pct / 100)
            itp_price = (
                entry * (1 - tp.intermediate_tp_pct / 100)
                if tp.intermediate_tp_pct
                else None
            )

        position_size = sz.position_usd / entry if entry > 0 else 0
        risk_usd = sz.risk_budget_usd
        reward_usd = risk_usd * tp.risk_reward if tp.risk_reward > 0 else 0

        trades.append(
            Trade(
                id=uuid.uuid4().hex[:12],
                report_id=report_id,
                ticker=score.ticker,
                direction=direction,
                composite_score=score.composite_score,
                entry_price=round(entry, 2),
                position_usd=sz.position_usd,
                position_size=round(position_size, 6),
                portfolio_pct=sz.portfolio_pct,
                stop_loss_price=round(stop_price, 2),
                take_profit_price=round(tp_price, 2),
                intermediate_tp_price=round(itp_price, 2) if itp_price else None,
                risk_reward=tp.risk_reward,
                risk_usd=round(risk_usd, 2),
                reward_usd=round(reward_usd, 2),
                horizon_days=tp.horizon_days,
                confidence=score.confidence,
                top_narrative=score.top_narrative,
                invalidation_triggers=tp.invalidation_triggers,
                conflict_flag=score.conflict_flag,
                regime=regime.value,
                status="proposed",
            )
        )

    trades.sort(key=lambda t: abs(t.composite_score), reverse=True)
    return trades


def format_trade_sheet(
    trades: list[Trade],
    skipped: list[tuple[str, str]],
    regime: EconomicRegime,
    regime_mult: float,
    capital: float | None = None,
) -> str:
    """Format trades into a printable CLI trade sheet.

    Parameters
    ----------
    trades : list[Trade]
        Accepted trades to display.
    skipped : list[tuple[str, str]]
        Skipped assets: [(ticker, reason), ...].
    regime : EconomicRegime
        Current regime.
    regime_mult : float
        Regime dampening multiplier.
    capital : float | None
        Portfolio capital (loaded from config if None).

    Returns
    -------
    str
        Formatted trade sheet string.
    """
    if capital is None:
        try:
            cfg = load_risk_config()
            capital = cfg.total_capital_usd
        except Exception:
            capital = 10000.0

    now = datetime.utcnow()
    deployed = sum(t.position_usd for t in trades)
    deployed_pct = (deployed / capital) * 100 if capital else 0

    lines = []
    w = 70
    lines.append("=" * w)
    lines.append(
        f"  TRADE SHEET — {now.strftime('%b %d, %Y')}  |  "
        f"Regime: {regime.value.upper()} ({regime_mult:.1f}x)"
    )
    lines.append(
        f"  Capital: ${capital:,.0f}  |  "
        f"Risk/trade: 2.0%  |  "
        f"Deployed: {deployed_pct:.0f}%"
    )
    lines.append("=" * w)

    for i, t in enumerate(trades, 1):
        lines.append("")
        lines.append(
            f"  #{i}  {t.ticker}   {t.direction}    "
            f"Score: {t.composite_score:+.2f}"
        )
        # Size line
        if t.entry_price >= 1000:
            size_str = f"{t.position_size:.4f}"
        elif t.entry_price >= 1:
            size_str = f"{t.position_size:.2f}"
        else:
            size_str = f"{t.position_size:.0f}"

        unit = t.ticker.split("-")[0] if "-" in t.ticker else t.ticker
        lines.append(
            f"      Entry: ${t.entry_price:,.2f}  |  "
            f"Size: ${t.position_usd:,.0f} ({size_str} {unit})  |  "
            f"{t.portfolio_pct:.0f}% of cap"
        )
        lines.append(
            f"      Stop: ${t.stop_loss_price:,.2f} ({t.stop_loss_price / t.entry_price * 100 - 100:+.1f}%)  |  "
            f"TP: ${t.take_profit_price:,.2f} ({t.take_profit_price / t.entry_price * 100 - 100:+.1f}%)"
            if t.entry_price > 0 else
            f"      Stop: ${t.stop_loss_price:,.2f}  |  TP: ${t.take_profit_price:,.2f}"
        )
        if t.intermediate_tp_price:
            lines.append(
                f"      Partial TP: ${t.intermediate_tp_price:,.2f}  |  "
                f"R:R = {t.risk_reward:.1f}x"
            )
        else:
            lines.append(f"      R:R = {t.risk_reward:.1f}x")

        lines.append(
            f"      Risk: ${t.risk_usd:,.0f}  |  Reward: ${t.reward_usd:,.0f}"
        )
        if t.invalidation_triggers:
            lines.append(
                f"      Invalidation: {', '.join(t.invalidation_triggers)}"
            )
        if t.conflict_flag:
            lines.append(f"      ** CONFLICT: scenarios disagree on direction **")
        lines.append(f'      Narrative: "{t.top_narrative}"')

    # Skipped assets
    for ticker, reason in skipped:
        lines.append("")
        lines.append(f"  NO TRADE: {ticker}  ({reason})")

    lines.append("")
    lines.append("=" * w)

    return "\n".join(lines)
