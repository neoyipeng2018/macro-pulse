"""Spreads & intermarket signals — VIX term structure, credit spreads, yield curve, and ratios.

Computes derived indicators from market data that signal stress and risk appetite
shifts at 1-week resolution:
  - VIX term structure (backwardation = near-term fear)
  - VIX/VVIX ratio (vol-of-vol leading indicator)
  - HYG/LQD ratio (credit spread proxy, 10-day z-score)
  - 10Y-3M treasury spread (yield curve shape)
  - Copper/Gold ratio (global risk appetite proxy)
"""

import hashlib
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

_SPREAD_TICKERS = [
    "^VIX",    # VIX spot
    "^VIX3M",  # VIX 3-month
    "^VVIX",   # CBOE VIX of VIX
    "^TNX",    # 10Y treasury yield
    "^FVX",    # 5Y treasury yield
    "^TYX",    # 30Y treasury yield
    "^IRX",    # 13-week T-bill rate
    "HYG",     # High-yield corporate bond ETF
    "LQD",     # Investment-grade corporate bond ETF
    "GC=F",    # Gold futures
    "HG=F",    # Copper futures
]


def _make_id(*parts: str) -> str:
    raw = "".join(str(p) for p in parts) + str(datetime.utcnow().date())
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _get_close(data: pd.DataFrame, ticker: str) -> pd.Series | None:
    """Safely extract close prices for a ticker."""
    try:
        if ticker in data.columns.get_level_values(0):
            series = data[ticker]["Close"].dropna()
            if len(series) >= 5:
                return series
    except Exception:
        pass
    return None


class SpreadsCollector(BaseCollector):
    """Collect spread-based and intermarket signals for 1-week directional trading."""

    source_name = "spreads"

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = yf.download(
                _SPREAD_TICKERS, period="3mo", group_by="ticker", progress=False
            )
        except Exception as e:
            logger.warning("Error fetching spread data: %s", e)
            return signals

        signals.extend(self._vix_term_structure(data))
        signals.extend(self._vix_vvix_ratio(data))
        signals.extend(self._credit_spread(data))
        signals.extend(self._yield_curve(data))
        signals.extend(self._copper_gold_ratio(data))
        return signals

    # ── VIX term structure ──────────────────────────────────────────────

    def _vix_term_structure(self, data: pd.DataFrame) -> list[Signal]:
        """VIX spot vs VIX3M — backwardation signals near-term fear."""
        signals: list[Signal] = []
        vix = _get_close(data, "^VIX")
        vix3m = _get_close(data, "^VIX3M")
        if vix is None or vix3m is None:
            return signals

        common = vix.index.intersection(vix3m.index)
        if len(common) < 20:
            return signals

        vix_now = float(vix.loc[common].iloc[-1])
        vix3m_now = float(vix3m.loc[common].iloc[-1])
        if vix3m_now == 0:
            return signals

        ratio = vix_now / vix3m_now
        ratio_series = vix.loc[common] / vix3m.loc[common]
        ratio_20d = float(ratio_series.rolling(20).mean().iloc[-1])

        if ratio > 1.05:
            severity = "significant" if ratio > 1.15 else "moderate"
            signals.append(Signal(
                id=_make_id("vix_term"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"VIX term structure in backwardation (ratio: {ratio:.2f})",
                content=(
                    f"VIX spot ({vix_now:.1f}) is trading above VIX3M ({vix3m_now:.1f}), "
                    f"ratio {ratio:.2f}. This indicates {severity} near-term fear exceeding "
                    f"longer-term expectations. 20-day avg ratio: {ratio_20d:.2f}. "
                    f"Backwardation historically signals elevated short-term risk and is a "
                    f"strong 1-week bearish signal for equities."
                ),
                metadata={
                    "signal_type": "vix_term_structure",
                    "vix_spot": round(vix_now, 2),
                    "vix3m": round(vix3m_now, 2),
                    "ratio": round(ratio, 3),
                    "ratio_20d_avg": round(ratio_20d, 3),
                    "state": "backwardation",
                },
            ))
        elif ratio < 0.85:
            signals.append(Signal(
                id=_make_id("vix_term"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"VIX term structure in deep contango (ratio: {ratio:.2f})",
                content=(
                    f"VIX spot ({vix_now:.1f}) is well below VIX3M ({vix3m_now:.1f}), "
                    f"ratio {ratio:.2f}. Deep contango may indicate market complacency — "
                    f"historically precedes vol spikes within 1-2 weeks. "
                    f"20-day avg ratio: {ratio_20d:.2f}."
                ),
                metadata={
                    "signal_type": "vix_term_structure",
                    "vix_spot": round(vix_now, 2),
                    "vix3m": round(vix3m_now, 2),
                    "ratio": round(ratio, 3),
                    "ratio_20d_avg": round(ratio_20d, 3),
                    "state": "deep_contango",
                },
            ))

        if vix_now > 25:
            level = "extremely elevated" if vix_now > 35 else "elevated"
            # VIX >30 is contrarian bullish at 1-week — mean reversion
            contrarian_note = ""
            if vix_now > 30:
                contrarian_note = (
                    " VIX above 30 historically mean-reverts within 5-10 trading days — "
                    "this is a contrarian bullish signal for equities at the 1-week horizon."
                )
            signals.append(Signal(
                id=_make_id("vix_level"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"VIX {level} at {vix_now:.1f}",
                content=(
                    f"The VIX is at {vix_now:.1f}, which is {level}. "
                    f"VIX above 25 indicates significant market stress. "
                    f"VIX3M at {vix3m_now:.1f}.{contrarian_note}"
                ),
                metadata={
                    "signal_type": "vix_level",
                    "vix_spot": round(vix_now, 2),
                    "level": level,
                },
            ))

        return signals

    # ── VIX / VVIX ratio ───────────────────────────────────────────────

    def _vix_vvix_ratio(self, data: pd.DataFrame) -> list[Signal]:
        """VVIX vs VIX — vol-of-vol as a leading indicator for 1-week vol expansion."""
        signals: list[Signal] = []
        vix = _get_close(data, "^VIX")
        vvix = _get_close(data, "^VVIX")
        if vix is None or vvix is None:
            return signals

        common = vix.index.intersection(vvix.index)
        if len(common) < 5:
            return signals

        vix_now = float(vix.loc[common].iloc[-1])
        vvix_now = float(vvix.loc[common].iloc[-1])

        # VVIX high while VIX low = vol breakout imminent
        if vvix_now > 120 and vix_now < 20:
            signals.append(Signal(
                id=_make_id("vix_vvix_divergence"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"VVIX/VIX divergence: VVIX {vvix_now:.0f} with VIX only {vix_now:.1f}",
                content=(
                    f"The VVIX (volatility of VIX) is at {vvix_now:.0f} while VIX is "
                    f"only at {vix_now:.1f}. This divergence — high options demand on VIX "
                    f"itself while realized vol remains low — historically precedes a "
                    f"volatility breakout within 3-7 trading days. Traders are buying "
                    f"tail protection, signaling expected disruption ahead."
                ),
                metadata={
                    "signal_type": "vix_vvix_divergence",
                    "vix_spot": round(vix_now, 2),
                    "vvix": round(vvix_now, 2),
                    "state": "divergence_breakout_risk",
                },
            ))

        # VVIX 3-day spike >15%
        if len(common) >= 4:
            vvix_3d_ago = float(vvix.loc[common].iloc[-4])
            if vvix_3d_ago > 0:
                vvix_change = (vvix_now / vvix_3d_ago - 1) * 100
                if vvix_change > 15:
                    signals.append(Signal(
                        id=_make_id("vvix_spike"),
                        source=SignalSource.SPREADS,
                        title=f"VVIX surging {vvix_change:.0f}% in 3 days (now {vvix_now:.0f})",
                        content=(
                            f"The VVIX has jumped {vvix_change:.1f}% in 3 trading days "
                            f"(from {vvix_3d_ago:.0f} to {vvix_now:.0f}). Rapid spikes in "
                            f"vol-of-vol indicate institutional hedging activity is spiking — "
                            f"a leading indicator for VIX expansion within the next week. "
                            f"Current VIX: {vix_now:.1f}."
                        ),
                        metadata={
                            "signal_type": "vvix_spike",
                            "vvix": round(vvix_now, 2),
                            "vvix_3d_ago": round(vvix_3d_ago, 2),
                            "vvix_change_pct": round(vvix_change, 1),
                            "vix_spot": round(vix_now, 2),
                        },
                    ))

        return signals

    # ── Credit spread ───────────────────────────────────────────────────

    def _credit_spread(self, data: pd.DataFrame) -> list[Signal]:
        """HYG/LQD ratio as credit spread proxy — 10-day z-score for 1-week sensitivity."""
        signals: list[Signal] = []
        hyg = _get_close(data, "HYG")
        lqd = _get_close(data, "LQD")
        if hyg is None or lqd is None:
            return signals

        common = hyg.index.intersection(lqd.index)
        if len(common) < 15:
            return signals

        ratio = hyg.loc[common] / lqd.loc[common]
        ratio_now = float(ratio.iloc[-1])
        # 10-day window (tightened from sentinel's 20-day for 1-week detection)
        ratio_10d = float(ratio.rolling(10).mean().iloc[-1])
        ratio_std = float(ratio.rolling(10).std().iloc[-1])

        if ratio_std == 0:
            return signals

        z = (ratio_now - ratio_10d) / ratio_std

        if z < -1.5:
            severity = "sharply" if z < -2.5 else "notably"
            signals.append(Signal(
                id=_make_id("credit_spread"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Credit spreads {severity} widening (HYG/LQD z: {z:.1f})",
                content=(
                    f"High-yield bonds (HYG) are underperforming investment grade (LQD) — "
                    f"HYG/LQD ratio z-score {z:.1f} on a 10-day window. "
                    f"Current ratio: {ratio_now:.4f}, 10-day avg: {ratio_10d:.4f}. "
                    f"Widening credit spreads signal deteriorating risk appetite "
                    f"and typically propagate to equities within 3-5 trading days."
                ),
                metadata={
                    "signal_type": "credit_spread",
                    "hyg_lqd_ratio": round(ratio_now, 4),
                    "ratio_10d_avg": round(ratio_10d, 4),
                    "z_score": round(z, 2),
                    "direction": "widening",
                },
            ))
        elif z > 1.5:
            signals.append(Signal(
                id=_make_id("credit_spread"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Credit spreads tightening (HYG/LQD z: {z:.1f})",
                content=(
                    f"High-yield bonds (HYG) are outperforming investment grade (LQD) — "
                    f"HYG/LQD ratio z-score {z:.1f} on a 10-day window. "
                    f"Current ratio: {ratio_now:.4f}, 10-day avg: {ratio_10d:.4f}. "
                    f"Tightening credit spreads indicate improving risk appetite "
                    f"and are bullish for equities over the next week."
                ),
                metadata={
                    "signal_type": "credit_spread",
                    "hyg_lqd_ratio": round(ratio_now, 4),
                    "ratio_10d_avg": round(ratio_10d, 4),
                    "z_score": round(z, 2),
                    "direction": "tightening",
                },
            ))

        return signals

    # ── Yield curve ─────────────────────────────────────────────────────

    def _yield_curve(self, data: pd.DataFrame) -> list[Signal]:
        """10Y-3M treasury spread — classic recession indicator with 1-week rapid-move threshold."""
        signals: list[Signal] = []
        tnx = _get_close(data, "^TNX")  # 10Y yield
        irx = _get_close(data, "^IRX")  # 3M yield

        if tnx is None or irx is None:
            return signals

        common = tnx.index.intersection(irx.index)
        if len(common) < 10:
            return signals

        spread = tnx.loc[common] - irx.loc[common]
        current = float(spread.iloc[-1])
        prev_5d = float(spread.iloc[-5]) if len(spread) >= 5 else current
        change = current - prev_5d

        if current < 0:
            signals.append(Signal(
                id=_make_id("yc_10y3m"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Yield curve inverted: 10Y-3M at {current:.2f}%",
                content=(
                    f"The 10Y-3M treasury spread is {current:.2f}%, inverted. "
                    f"5-day change: {change:+.2f}%. "
                    f"10Y: {float(tnx.loc[common].iloc[-1]):.2f}%, "
                    f"3M: {float(irx.loc[common].iloc[-1]):.2f}%. "
                    f"An inverted 10Y-3M curve signals recession risk and is "
                    f"bearish for equities, bullish for bonds and gold."
                ),
                metadata={
                    "signal_type": "yield_curve",
                    "spread": "10Y-3M",
                    "value": round(current, 3),
                    "change_5d": round(change, 3),
                    "state": "inverted",
                },
            ))
        elif current < 0.5:
            signals.append(Signal(
                id=_make_id("yc_10y3m"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Yield curve near flat: 10Y-3M at {current:.2f}%",
                content=(
                    f"The 10Y-3M treasury spread is {current:.2f}%, near flat. "
                    f"5-day change: {change:+.2f}%. "
                    f"A flat curve signals slowing growth expectations."
                ),
                metadata={
                    "signal_type": "yield_curve",
                    "spread": "10Y-3M",
                    "value": round(current, 3),
                    "change_5d": round(change, 3),
                    "state": "flat",
                },
            ))

        # Rapid move threshold lowered to 0.15% for 1-week sensitivity
        if abs(change) > 0.15:
            direction = "steepening" if change > 0 else "flattening"
            signals.append(Signal(
                id=_make_id("yc_10y3m_move"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Yield curve rapidly {direction}: 10Y-3M moved {change:+.2f}% in 5d",
                content=(
                    f"The 10Y-3M spread moved {change:+.2f}% over 5 days "
                    f"(from {prev_5d:.2f}% to {current:.2f}%). "
                    f"Rapid {direction} signals shifting rate expectations "
                    f"and is a strong directional signal for bonds and FX over the next week."
                ),
                metadata={
                    "signal_type": "yield_curve_move",
                    "spread": "10Y-3M",
                    "value": round(current, 3),
                    "change_5d": round(change, 3),
                    "direction": direction,
                },
            ))

        return signals

    # ── Copper / Gold ratio ─────────────────────────────────────────────

    def _copper_gold_ratio(self, data: pd.DataFrame) -> list[Signal]:
        """Cu/Au ratio z-score as a global risk appetite proxy."""
        signals: list[Signal] = []
        copper = _get_close(data, "HG=F")
        gold = _get_close(data, "GC=F")
        if copper is None or gold is None:
            return signals

        common = copper.index.intersection(gold.index)
        if len(common) < 25:
            return signals

        ratio = copper.loc[common] / gold.loc[common]
        ratio_now = float(ratio.iloc[-1])
        ratio_20d = float(ratio.rolling(20).mean().iloc[-1])
        ratio_std = float(ratio.rolling(20).std().iloc[-1])

        if ratio_std == 0:
            return signals

        z = (ratio_now - ratio_20d) / ratio_std

        if z < -1.5:
            severity = "sharply" if z < -2.5 else "notably"
            signals.append(Signal(
                id=_make_id("copper_gold"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Copper/Gold ratio {severity} declining (z: {z:.1f}) — risk-off signal",
                content=(
                    f"The Copper/Gold ratio z-score is {z:.1f} on a 20-day window. "
                    f"Current ratio: {ratio_now:.6f}, 20-day avg: {ratio_20d:.6f}. "
                    f"A falling Cu/Au ratio signals weakening global growth expectations "
                    f"and risk-off positioning. This is a leading indicator: bearish for "
                    f"equities and EM FX, bullish for gold and USD over the next week."
                ),
                metadata={
                    "signal_type": "copper_gold_ratio",
                    "ratio": round(ratio_now, 6),
                    "ratio_20d_avg": round(ratio_20d, 6),
                    "z_score": round(z, 2),
                    "direction": "risk_off",
                },
            ))
        elif z > 1.5:
            signals.append(Signal(
                id=_make_id("copper_gold"),
                source=SignalSource.SPREADS,
                url="https://finance.yahoo.com/quote/%5EVIX",
                title=f"Copper/Gold ratio rising (z: {z:.1f}) — risk-on signal",
                content=(
                    f"The Copper/Gold ratio z-score is {z:.1f} on a 20-day window. "
                    f"Current ratio: {ratio_now:.6f}, 20-day avg: {ratio_20d:.6f}. "
                    f"A rising Cu/Au ratio signals improving global growth expectations "
                    f"and risk-on positioning. Bullish for equities, commodities, and "
                    f"EM FX; bearish for gold and safe-haven assets over the next week."
                ),
                metadata={
                    "signal_type": "copper_gold_ratio",
                    "ratio": round(ratio_now, 6),
                    "ratio_20d_avg": round(ratio_20d, 6),
                    "z_score": round(z, 2),
                    "direction": "risk_on",
                },
            ))

        return signals
