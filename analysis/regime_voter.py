"""Quantitative regime pre-scoring from market indicators."""

from __future__ import annotations

from dataclasses import dataclass

from models.schemas import ConsensusScore, Signal


@dataclass
class RegimeVote:
    indicator: str
    regime: str
    confidence: float
    rationale: str


def compute_regime_votes(
    signals: list[Signal],
    quant_scores: list[ConsensusScore],
) -> list[RegimeVote]:
    """Each indicator independently votes on the current regime."""
    votes: list[RegimeVote] = []

    vix = _extract_vix(signals)
    if vix is not None:
        if vix > 30:
            votes.append(RegimeVote("VIX", "risk_off", 0.8, f"VIX at {vix:.0f} = elevated fear"))
        elif vix > 20:
            votes.append(RegimeVote("VIX", "transition", 0.5, f"VIX at {vix:.0f} = cautious"))
        else:
            votes.append(RegimeVote("VIX", "risk_on", 0.7, f"VIX at {vix:.0f} = complacent"))

    t10y2y = _extract_fred("T10Y2Y", signals)
    if t10y2y is not None:
        if t10y2y < -0.5:
            votes.append(RegimeVote("Yield Curve", "risk_off", 0.7, f"10Y-2Y at {t10y2y:.2f} = deeply inverted"))
        elif t10y2y < 0:
            votes.append(RegimeVote("Yield Curve", "transition", 0.5, f"10Y-2Y at {t10y2y:.2f} = inverted"))
        else:
            votes.append(RegimeVote("Yield Curve", "goldilocks", 0.5, f"10Y-2Y at {t10y2y:.2f} = normal"))

    stress = _extract_fred("STLFSI2", signals)
    if stress is not None:
        if stress > 1.5:
            votes.append(RegimeVote("Fin Stress", "risk_off", 0.9, f"St. Louis FSI at {stress:.2f} = severe stress"))
        elif stress > 0.5:
            votes.append(RegimeVote("Fin Stress", "transition", 0.6, f"FSI at {stress:.2f} = elevated"))
        elif stress < -0.5:
            votes.append(RegimeVote("Fin Stress", "risk_on", 0.6, f"FSI at {stress:.2f} = benign"))

    hy_oas = _extract_fred("BAMLH0A0HYM2", signals)
    if hy_oas is not None:
        if hy_oas > 500:
            votes.append(RegimeVote("Credit", "risk_off", 0.8, f"HY OAS at {hy_oas:.0f}bp = distressed"))
        elif hy_oas > 400:
            votes.append(RegimeVote("Credit", "transition", 0.5, f"HY OAS at {hy_oas:.0f}bp = wide"))
        else:
            votes.append(RegimeVote("Credit", "risk_on", 0.5, f"HY OAS at {hy_oas:.0f}bp = tight"))

    for qs in quant_scores:
        if qs.ticker == "Bitcoin" and qs.funding_rate_7d:
            funding = qs.funding_rate_7d
            if funding > 0.05:
                votes.append(RegimeVote("BTC Funding", "risk_on", 0.6, f"7d funding {funding:.4f} = euphoric longs"))
            elif funding < -0.03:
                votes.append(RegimeVote("BTC Funding", "risk_off", 0.6, f"7d funding {funding:.4f} = capitulation"))

    dxy_ret = _extract_weekly_return("DX-Y.NYB", signals)
    if dxy_ret is not None:
        if dxy_ret > 1.0:
            votes.append(RegimeVote("DXY", "risk_off", 0.5, f"DXY up {dxy_ret:.1f}% = USD strength"))
        elif dxy_ret < -1.0:
            votes.append(RegimeVote("DXY", "reflation", 0.4, f"DXY down {dxy_ret:.1f}% = USD weakness"))

    t10yie = _extract_fred("T10YIE", signals)
    if t10yie is not None:
        if t10yie > 2.8:
            votes.append(RegimeVote("Breakevens", "reflation", 0.5, f"10Y BE at {t10yie:.2f}% = rising inflation expectations"))
        elif t10yie < 2.0:
            votes.append(RegimeVote("Breakevens", "goldilocks", 0.4, f"10Y BE at {t10yie:.2f}% = well-anchored"))

    return votes


def tally_regime_votes(votes: list[RegimeVote]) -> tuple[str, float, str]:
    """Tally votes into a regime pre-score. Returns (regime, confidence, rationale)."""
    if not votes:
        return "transition", 0.3, "Insufficient data for regime classification"

    regime_scores: dict[str, float] = {}
    for v in votes:
        regime_scores[v.regime] = regime_scores.get(v.regime, 0.0) + v.confidence

    winner = max(regime_scores, key=lambda k: regime_scores[k])
    total = sum(regime_scores.values())
    confidence = regime_scores[winner] / total if total > 0 else 0.3

    supporting = [v for v in votes if v.regime == winner]
    rationale = "; ".join(v.rationale for v in supporting[:3])

    return winner, round(confidence, 2), rationale


def _extract_vix(signals: list[Signal]) -> float | None:
    for s in signals:
        if s.source.value == "spreads" and s.metadata.get("metric") == "vix_level":
            return s.metadata.get("vix_level")
        if s.source.value == "market_data" and s.metadata.get("ticker") == "^VIX":
            return s.metadata.get("price")
    return None


def _extract_fred(series_id: str, signals: list[Signal]) -> float | None:
    for s in signals:
        if s.source.value == "economic_data" and s.metadata.get("series_id") == series_id:
            return s.metadata.get("value")
    return None


def _extract_weekly_return(ticker: str, signals: list[Signal]) -> float | None:
    for s in signals:
        if s.source.value == "market_data" and s.metadata.get("ticker") == ticker:
            return s.metadata.get("weekly_return_pct")
    return None
