"""Regime indicator computation.

Computes the 4 indicator pillars used by the regime detector:
1. VIX level + term structure (25%)
2. Market breadth (25%)
3. Trend strength — ADX of SPY (25%)
4. Cross-asset confirmation (25%)
"""

import pandas as pd


def compute_vix_indicator(vix_df: pd.DataFrame) -> dict:
    """VIX level classification and term structure assessment."""
    if vix_df.empty:
        return {"level": "normal", "score": 0.5, "vix": 18.0, "term_structure": "contango"}

    vix = float(vix_df["Close"].iloc[-1])

    if vix < 15:
        level, score = "low", 0.8
    elif vix < 20:
        level, score = "normal", 0.6
    elif vix < 25:
        level, score = "elevated", 0.4
    elif vix < 35:
        level, score = "high", 0.2
    else:
        level, score = "extreme", 0.0

    # Approximate term structure from VIX slope (5d vs 20d avg)
    vix_5d = float(vix_df["Close"].tail(5).mean())
    vix_20d = float(vix_df["Close"].tail(20).mean())

    if vix_5d < vix_20d * 0.95:
        term_structure = "contango"
    elif vix_5d > vix_20d * 1.05:
        term_structure = "backwardation"
    else:
        term_structure = "flat"

    return {"level": level, "score": score, "vix": vix, "term_structure": term_structure}


def compute_breadth_indicator(
    spy_constituents_df: pd.DataFrame | None = None, pct_above_200sma: float | None = None
) -> dict:
    """Market breadth: % of S&P 500 stocks above 200-day SMA."""
    if pct_above_200sma is not None:
        pct = pct_above_200sma
    elif spy_constituents_df is not None and not spy_constituents_df.empty:
        closes = spy_constituents_df
        sma_200 = closes.rolling(200).mean()
        above = (closes.iloc[-1] > sma_200.iloc[-1]).sum()
        total = len(closes.columns)
        pct = (above / total * 100) if total > 0 else 50.0
    else:
        pct = 50.0

    if pct > 70:
        regime_signal = "bull_trend"
        score = 0.9
    elif pct > 50:
        regime_signal = "bull_choppy"
        score = 0.6
    elif pct > 30:
        regime_signal = "bear_or_mean_revert"
        score = 0.3
    else:
        regime_signal = "crisis"
        score = 0.1

    return {"pct_above_200sma": pct, "signal": regime_signal, "score": score}


def compute_adx_indicator(spy_df: pd.DataFrame, period: int = 14) -> dict:
    """Trend strength via ADX of SPY."""
    if spy_df.empty or len(spy_df) < period + 1:
        return {"adx": 20.0, "di_plus": 0.5, "di_minus": 0.5, "signal": "neutral"}

    high = spy_df["High"]
    low = spy_df["Low"]
    close = spy_df["Close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1))
    adx = dx.ewm(span=period, adjust=False).mean()

    adx_val = float(adx.iloc[-1])
    di_p = float(plus_di.iloc[-1])
    di_m = float(minus_di.iloc[-1])

    if adx_val > 30 and di_p > di_m:
        signal = "bull_trend"
    elif adx_val > 30 and di_m > di_p:
        signal = "bear_trend"
    elif adx_val < 20:
        signal = "mean_reverting"
    else:
        signal = "choppy"

    return {"adx": adx_val, "di_plus": di_p, "di_minus": di_m, "signal": signal}


def compute_cross_asset_confirmation(
    yield_curve_slope: float | None = None,
    credit_spread_ratio: float | None = None,
) -> dict:
    """Cross-asset risk-on/risk-off signal from yield curve and credit spreads."""
    risk_on_signals = 0
    risk_off_signals = 0

    if yield_curve_slope is not None:
        if yield_curve_slope > 0.5:
            risk_on_signals += 1
        elif yield_curve_slope < -0.2:
            risk_off_signals += 1

    if credit_spread_ratio is not None:
        # HYG/LQD ratio: higher = tighter spreads = risk-on
        if credit_spread_ratio > 0.82:
            risk_on_signals += 1
        elif credit_spread_ratio < 0.78:
            risk_off_signals += 1

    if risk_off_signals > risk_on_signals:
        return {"signal": "risk_off", "score": 0.2}
    elif risk_on_signals > risk_off_signals:
        return {"signal": "risk_on", "score": 0.8}
    else:
        return {"signal": "neutral", "score": 0.5}
