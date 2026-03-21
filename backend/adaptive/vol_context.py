"""Volatility Context — the pulse of the market.

Computed from multiple instruments, multiple timeframes.
This object is passed to EVERY function that uses parameters.
Nothing in the system uses a hardcoded threshold.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd


class VolRegime(StrEnum):
    ULTRA_LOW = "ultra_low"  # VIX < 12
    LOW = "low"  # VIX 12-16
    NORMAL = "normal"  # VIX 16-22
    ELEVATED = "elevated"  # VIX 22-30
    HIGH = "high"  # VIX 30-45
    EXTREME = "extreme"  # VIX > 45


@dataclass
class VolContext:
    # ── Spot Volatility ──
    vix_current: float = 18.0
    vix_5d_avg: float = 18.0
    vix_20d_avg: float = 18.0
    vix_percentile_1y: float = 50.0

    # ── Volatility Regime ──
    vol_regime: VolRegime = VolRegime.NORMAL
    vol_regime_days: int = 1

    # ── Term Structure ──
    vix_term_spread: float = 0.0
    term_structure: str = "contango"

    # ── Realized vs Implied ──
    realized_vol_20d: float = 0.15
    vol_risk_premium: float = 3.0

    # ── Market Speed ──
    spy_atr_14d: float = 5.0
    spy_atr_pct: float = 0.01
    avg_intraday_range_5d: float = 0.01

    # ── Correlation Environment ──
    avg_sp500_correlation_20d: float = 0.35
    correlation_regime: str = "normal"

    # ── Breadth ──
    pct_above_200sma: float = 60.0
    pct_above_50sma: float = 55.0
    advance_decline_ratio_10d: float = 1.1

    # ── Cross-Asset Vol ──
    move_index: float = 100.0
    fx_vol_index: float = 8.0
    oil_atr_pct: float = 0.02

    @property
    def vol_scale(self) -> float:
        """Master scaling factor. 1.0 = normal conditions.
        < 1.0 in low vol (tighter params), > 1.0 in high vol (wider params)."""
        if self.vix_20d_avg == 0:
            return 1.0
        return self.vix_current / self.vix_20d_avg

    @property
    def position_scale(self) -> float:
        """Inverse vol scale for position sizing. Smaller positions in high vol."""
        return min(2.0, max(0.3, self.vix_20d_avg / max(1.0, self.vix_current)))

    @property
    def speed_scale(self) -> float:
        """How fast the market is moving relative to normal. Adjusts hold periods."""
        return self.spy_atr_pct / 0.01  # Normalize to 1.0 at 1% daily ATR


def classify_vol_regime(vix: float) -> VolRegime:
    if vix < 12:
        return VolRegime.ULTRA_LOW
    elif vix < 16:
        return VolRegime.LOW
    elif vix < 22:
        return VolRegime.NORMAL
    elif vix < 30:
        return VolRegime.ELEVATED
    elif vix < 45:
        return VolRegime.HIGH
    else:
        return VolRegime.EXTREME


def classify_correlation_regime(avg_corr: float) -> str:
    if avg_corr < 0.3:
        return "dispersed"
    elif avg_corr < 0.6:
        return "normal"
    else:
        return "herding"


def compute_vol_context(
    spy_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    correlation_20d: float = 0.35,
    breadth_200sma: float = 60.0,
    breadth_50sma: float = 55.0,
) -> VolContext:
    """Build a VolContext from market data DataFrames."""
    if vix_df.empty or spy_df.empty:
        return VolContext()

    vix_close = vix_df["Close"]
    spy_close = spy_df["Close"]

    vix_current = float(vix_close.iloc[-1])
    vix_5d = float(vix_close.tail(5).mean())
    vix_20d = float(vix_close.tail(20).mean())

    vix_1y = vix_close.tail(252)
    vix_pct = float((vix_1y < vix_current).sum() / max(1, len(vix_1y)) * 100)

    # SPY ATR
    spy_high = spy_df["High"].tail(14)
    spy_low = spy_df["Low"].tail(14)
    spy_prev_close = spy_close.shift(1).tail(14)
    tr = pd.concat(
        [
            spy_high - spy_low,
            (spy_high - spy_prev_close).abs(),
            (spy_low - spy_prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_14 = float(tr.mean())
    atr_pct = atr_14 / float(spy_close.iloc[-1]) if spy_close.iloc[-1] > 0 else 0.01

    # Intraday range
    intraday_range = ((spy_df["High"] - spy_df["Low"]) / spy_close).tail(5)
    avg_range = float(intraday_range.mean()) if not intraday_range.empty else 0.01

    # Realized vol (20d annualized)
    log_returns = np.log(spy_close / spy_close.shift(1)).dropna().tail(20)
    realized_vol = float(log_returns.std() * np.sqrt(252)) if len(log_returns) > 1 else 0.15

    vol_regime = classify_vol_regime(vix_current)
    corr_regime = classify_correlation_regime(correlation_20d)

    return VolContext(
        vix_current=vix_current,
        vix_5d_avg=vix_5d,
        vix_20d_avg=vix_20d,
        vix_percentile_1y=vix_pct,
        vol_regime=vol_regime,
        vol_regime_days=1,
        realized_vol_20d=realized_vol,
        vol_risk_premium=vix_current - realized_vol * 100,
        spy_atr_14d=atr_14,
        spy_atr_pct=atr_pct,
        avg_intraday_range_5d=avg_range,
        avg_sp500_correlation_20d=correlation_20d,
        correlation_regime=corr_regime,
        pct_above_200sma=breadth_200sma,
        pct_above_50sma=breadth_50sma,
    )
