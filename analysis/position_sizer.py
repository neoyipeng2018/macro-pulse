"""Position sizing engine: convert composite scores into dollar-sized positions.

Uses risk-budget approach: risk_budget / stop_distance = position_size,
with conviction scaling, regime dampening, and portfolio-level caps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from models.schemas import CompositeAssetScore, EconomicRegime, TradeParams

logger = logging.getLogger(__name__)

RISK_CONFIG_PATH = Path(__file__).parent.parent / "config" / "risk.yaml"


@dataclass
class RiskConfig:
    """Parsed risk configuration."""

    total_capital_usd: float
    max_single_position_pct: float
    max_total_exposure_pct: float
    max_correlated_exposure_pct: float
    base_risk_per_trade_pct: float
    max_risk_per_trade_pct: float
    min_risk_per_trade_pct: float
    conviction_thresholds: list[dict]  # [{min_score, risk_mult}, ...]
    regime_dampening: dict[str, float]


def load_risk_config(path: Path | None = None) -> RiskConfig:
    """Load risk configuration from YAML."""
    cfg_path = path or RISK_CONFIG_PATH
    with open(cfg_path) as f:
        raw = yaml.safe_load(f)

    return RiskConfig(
        total_capital_usd=raw["portfolio"]["total_capital_usd"],
        max_single_position_pct=raw["portfolio"]["max_single_position_pct"],
        max_total_exposure_pct=raw["portfolio"]["max_total_exposure_pct"],
        max_correlated_exposure_pct=raw["portfolio"]["max_correlated_exposure_pct"],
        base_risk_per_trade_pct=raw["risk"]["base_risk_per_trade_pct"],
        max_risk_per_trade_pct=raw["risk"]["max_risk_per_trade_pct"],
        min_risk_per_trade_pct=raw["risk"]["min_risk_per_trade_pct"],
        conviction_thresholds=raw["conviction_scaling"]["thresholds"],
        regime_dampening=raw["regime_dampening"],
    )


@dataclass
class SizedPosition:
    """Output of the position sizer for a single trade."""

    ticker: str
    position_usd: float
    risk_budget_usd: float
    portfolio_pct: float
    conviction_mult: float
    regime_mult: float
    capped: bool  # True if position was capped by limits
    skip_reason: str | None  # if set, trade should be skipped


def _conviction_multiplier(
    composite_score: float,
    thresholds: list[dict],
) -> float:
    """Map composite score to risk multiplier using configured thresholds.

    Thresholds are checked in descending order (highest min_score first).
    """
    abs_score = abs(composite_score)
    for t in sorted(thresholds, key=lambda x: x["min_score"], reverse=True):
        if abs_score >= t["min_score"]:
            return t["risk_mult"]
    return 0.0


def _regime_multiplier(regime: EconomicRegime, dampening: dict[str, float]) -> float:
    """Get regime dampening factor."""
    return dampening.get(regime.value, 0.6)


def size_positions(
    composite_scores: list[CompositeAssetScore],
    trade_params: list[TradeParams],
    regime: EconomicRegime,
    existing_exposure_usd: float = 0.0,
    risk_config: RiskConfig | None = None,
) -> list[SizedPosition]:
    """Size positions for all candidate trades.

    Parameters
    ----------
    composite_scores : list[CompositeAssetScore]
        Scored assets with composite_score and conflict_flag.
    trade_params : list[TradeParams]
        Parsed stop-loss / take-profit for each asset.
    regime : EconomicRegime
        Current regime for dampening.
    existing_exposure_usd : float
        Already-deployed capital from open positions.
    risk_config : RiskConfig | None
        Risk configuration (loaded from YAML if not provided).

    Returns
    -------
    list[SizedPosition]
        Sized positions, including skipped trades (skip_reason set).
    """
    cfg = risk_config or load_risk_config()
    capital = cfg.total_capital_usd

    params_by_ticker = {tp.ticker: tp for tp in trade_params}
    regime_mult = _regime_multiplier(regime, cfg.regime_dampening)

    results: list[SizedPosition] = []
    cumulative_exposure = existing_exposure_usd

    for score in composite_scores:
        tp = params_by_ticker.get(score.ticker)
        if tp is None:
            continue

        # Skip neutral direction
        if score.direction.value == "neutral":
            results.append(SizedPosition(
                ticker=score.ticker, position_usd=0, risk_budget_usd=0,
                portfolio_pct=0, conviction_mult=0, regime_mult=regime_mult,
                capped=False, skip_reason="neutral direction",
            ))
            continue

        conv_mult = _conviction_multiplier(
            score.composite_score, cfg.conviction_thresholds
        )

        # No-trade zone
        if conv_mult == 0.0:
            results.append(SizedPosition(
                ticker=score.ticker, position_usd=0, risk_budget_usd=0,
                portfolio_pct=0, conviction_mult=0, regime_mult=regime_mult,
                capped=False, skip_reason=f"below threshold (score={score.composite_score:.2f})",
            ))
            continue

        # Risk budget calculation
        risk_pct = cfg.base_risk_per_trade_pct * conv_mult * regime_mult
        risk_pct = max(cfg.min_risk_per_trade_pct, min(cfg.max_risk_per_trade_pct, risk_pct))
        risk_budget = capital * (risk_pct / 100)

        # Conflict penalty: cut size by 50%
        if score.conflict_flag:
            risk_budget *= 0.5

        # Position size = risk_budget / stop_distance
        stop_distance = abs(tp.stop_loss_pct) / 100
        if stop_distance == 0:
            stop_distance = 0.05  # 5% default

        position_usd = risk_budget / stop_distance

        # Cap 1: max single position
        max_single = capital * (cfg.max_single_position_pct / 100)
        capped = position_usd > max_single
        position_usd = min(position_usd, max_single)

        # Cap 2: max total exposure
        max_remaining = capital * (cfg.max_total_exposure_pct / 100) - cumulative_exposure
        if position_usd > max_remaining:
            if max_remaining <= 0:
                results.append(SizedPosition(
                    ticker=score.ticker, position_usd=0, risk_budget_usd=risk_budget,
                    portfolio_pct=0, conviction_mult=conv_mult, regime_mult=regime_mult,
                    capped=True, skip_reason="portfolio exposure cap reached",
                ))
                continue
            position_usd = max_remaining
            capped = True

        cumulative_exposure += position_usd
        portfolio_pct = (position_usd / capital) * 100

        results.append(SizedPosition(
            ticker=score.ticker,
            position_usd=round(position_usd, 2),
            risk_budget_usd=round(risk_budget, 2),
            portfolio_pct=round(portfolio_pct, 2),
            conviction_mult=conv_mult,
            regime_mult=regime_mult,
            capped=capped,
            skip_reason=None,
        ))

    logger.info(
        "Sized %d positions, total exposure: $%.0f (%.1f%% of $%.0f)",
        sum(1 for r in results if r.skip_reason is None),
        cumulative_exposure,
        (cumulative_exposure / capital) * 100 if capital else 0,
        capital,
    )
    return results
