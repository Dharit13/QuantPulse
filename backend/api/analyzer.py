"""Single-stock analysis endpoint — full trading cockpit for one ticker."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from backend.adaptive.vol_context import compute_vol_context
from backend.data.fetcher import DataFetcher
from backend.data.sources.yfinance_src import yfinance_source
from backend.models.schemas import Regime, StockAnalysis, TradeSignal
from backend.regime.detector import detect_regime
from backend.strategies.catalyst_event import CatalystEventStrategy
from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy

router = APIRouter(prefix="/analyze", tags=["analyzer"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=2)


def _compute_technicals(df: pd.DataFrame) -> dict:
    """Compute key technical indicators from OHLCV data."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    current = float(close.iloc[-1])

    sma_20 = float(close.tail(20).mean())
    sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else None

    # RSI (14-period)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).tail(14).mean()
    loss = (-delta.where(delta < 0, 0)).tail(14).mean()
    rs = gain / loss if loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # ATR (14-period)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    atr_pct = atr / current * 100 if current > 0 else 0

    # 52-week high/low
    yearly = close.tail(252)
    high_52w = float(yearly.max())
    low_52w = float(yearly.min())
    pct_from_high = (current - high_52w) / high_52w * 100

    # Recent performance
    ret_1d = float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) >= 2 else 0
    ret_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 else 0
    ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0
    ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else 0

    # Volume analysis
    avg_vol_20d = float(volume.tail(20).mean())
    latest_vol = float(volume.iloc[-1])
    vol_ratio = latest_vol / avg_vol_20d if avg_vol_20d > 0 else 1.0

    # Trend assessment
    if sma_50 and sma_200:
        if current > sma_20 > sma_50 > sma_200:
            trend = "Strong Uptrend"
        elif current > sma_50 > sma_200:
            trend = "Uptrend"
        elif current < sma_20 < sma_50 and sma_50 < sma_200:
            trend = "Strong Downtrend"
        elif current < sma_50 < sma_200:
            trend = "Downtrend"
        elif current > sma_200 and current < sma_50:
            trend = "Pullback in Uptrend"
        elif current < sma_200 and current > sma_50:
            trend = "Bounce in Downtrend"
        else:
            trend = "Choppy / Sideways"
    else:
        trend = "Insufficient data"

    # Support/Resistance levels
    recent_20d = df.tail(20)
    support = float(recent_20d["Low"].min())
    resistance = float(recent_20d["High"].max())

    return {
        "current_price": round(current, 2),
        "sma_20": round(sma_20, 2),
        "sma_50": round(sma_50, 2) if sma_50 else None,
        "sma_200": round(sma_200, 2) if sma_200 else None,
        "rsi_14": round(float(rsi), 1),
        "atr_14": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "pct_from_52w_high": round(pct_from_high, 1),
        "return_1d": round(ret_1d, 2),
        "return_5d": round(ret_5d, 2),
        "return_20d": round(ret_20d, 2),
        "return_60d": round(ret_60d, 2),
        "volume_latest": int(latest_vol),
        "volume_avg_20d": int(avg_vol_20d),
        "volume_ratio": round(vol_ratio, 2),
        "trend": trend,
        "support_20d": round(support, 2),
        "resistance_20d": round(resistance, 2),
    }


def _build_system_take(technicals: dict, fundamentals: dict, regime: str) -> dict:
    """Generate an opinionated system assessment."""
    notes: list[str] = []
    bias = "neutral"
    score = 50

    rsi = technicals.get("rsi_14", 50)
    trend = technicals.get("trend", "")
    pct_from_high = technicals.get("pct_from_52w_high", 0)
    vol_ratio = technicals.get("volume_ratio", 1.0)

    if rsi < 30:
        notes.append(f"RSI at {rsi:.0f} — oversold, potential bounce setup")
        score += 15
    elif rsi > 70:
        notes.append(f"RSI at {rsi:.0f} — overbought, momentum may exhaust")
        score -= 10
    elif 40 <= rsi <= 60:
        notes.append(f"RSI at {rsi:.0f} — neutral, no directional edge from momentum")

    if "Strong Uptrend" in trend:
        notes.append("Price above all key MAs — strong uptrend")
        score += 15
        bias = "bullish"
    elif "Uptrend" in trend:
        notes.append("Above 50/200 SMA — uptrend intact")
        score += 10
        bias = "lean bullish"
    elif "Strong Downtrend" in trend:
        notes.append("Below all key MAs — strong downtrend, avoid longs")
        score -= 20
        bias = "bearish"
    elif "Downtrend" in trend:
        notes.append("Below 50/200 SMA — downtrend")
        score -= 10
        bias = "lean bearish"
    elif "Pullback" in trend:
        notes.append("Pullback within an uptrend — potential buy-the-dip")
        score += 5
        bias = "cautiously bullish"

    if pct_from_high > -3:
        notes.append(f"Near 52-week high ({pct_from_high:+.1f}%) — breakout or resistance?")
    elif pct_from_high < -20:
        notes.append(f"{pct_from_high:+.1f}% from 52-week high — significant drawdown")
        score -= 5

    if vol_ratio > 2.0:
        notes.append(f"Volume {vol_ratio:.1f}x average — institutional activity likely")
    elif vol_ratio < 0.5:
        notes.append(f"Volume {vol_ratio:.1f}x average — low conviction moves")

    pe = fundamentals.get("pe_ratio")
    fwd_pe = fundamentals.get("forward_pe")
    target = fundamentals.get("analyst_target")
    current = technicals.get("current_price", 0)

    if pe and fwd_pe and fwd_pe < pe:
        notes.append(f"Forward P/E ({fwd_pe:.1f}) < trailing ({pe:.1f}) — earnings expected to grow")
        score += 5
    if target and current:
        upside = (target - current) / current * 100
        if upside > 15:
            notes.append(f"Analyst target ${target:.0f} implies {upside:.0f}% upside")
            score += 10
        elif upside < -5:
            notes.append(f"Analyst target ${target:.0f} implies {abs(upside):.0f}% downside — caution")
            score -= 5

    if "bear" in regime.lower() or "crisis" in regime.lower():
        notes.append(f"Market regime is {regime.replace('_', ' ')} — elevated risk, prefer smaller sizing")
        score -= 10

    score = max(0, min(100, score))

    # Plain-English summary for non-quant users
    summary = _build_plain_english_summary(
        technicals, fundamentals, bias, score, regime
    )

    return {
        "bias": bias,
        "score": score,
        "notes": notes,
        "summary": summary,
    }


def _build_plain_english_summary(
    technicals: dict,
    fundamentals: dict,
    bias: str,
    score: int,
    regime: str,
) -> str:
    """Generate a conversational analysis summary a non-quant can understand."""
    price = technicals.get("current_price", 0)
    ret_1d = technicals.get("return_1d", 0)
    ret_5d = technicals.get("return_5d", 0)
    ret_20d = technicals.get("return_20d", 0)
    rsi = technicals.get("rsi_14", 50)
    trend = technicals.get("trend", "")
    sma_200 = technicals.get("sma_200") or price
    vol_ratio = technicals.get("volume_ratio", 1.0)
    atr_pct = technicals.get("atr_pct", 2.0)
    pct_from_high = technicals.get("pct_from_52w_high", 0)

    analyst_target = (fundamentals.get("analyst_target") or 0)
    sector = fundamentals.get("sector", "this sector")

    parts: list[str] = []

    # What happened today
    if ret_1d > 2:
        parts.append(f"The stock is up {ret_1d:+.1f}% today — a strong move higher.")
    elif ret_1d > 0.5:
        parts.append(f"The stock is up {ret_1d:+.1f}% today — modestly positive.")
    elif ret_1d < -2:
        parts.append(f"The stock is down {ret_1d:+.1f}% today — selling pressure.")
    elif ret_1d < -0.5:
        parts.append(f"The stock is down {ret_1d:+.1f}% today — slight weakness.")
    else:
        parts.append("The stock is roughly flat today — no strong move either way.")

    # Why (context from recent trend)
    if ret_5d > 5:
        parts.append(f"It's been on a tear this week (+{ret_5d:.1f}% in 5 days), so today's move is part of a larger rally.")
    elif ret_5d < -5:
        parts.append(f"It's been falling hard this week ({ret_5d:+.1f}% in 5 days), so the selling isn't just today.")
    elif ret_20d > 10:
        parts.append(f"Over the past month it's up {ret_20d:+.1f}% — a strong run that may be getting stretched.")
    elif ret_20d < -10:
        parts.append(f"Over the past month it's down {ret_20d:+.1f}% — a meaningful decline.")

    # Regime context
    if "bear" in regime:
        parts.append("The broader market is in a bear trend right now, which means most stocks face headwinds regardless of their individual story.")
    elif "crisis" in regime:
        parts.append("The market is in crisis mode — this is not the time for aggressive bets.")
    elif "bull_trend" in regime:
        parts.append("The market is in a bull trend, which provides a tailwind for most stocks.")

    # Where it stands technically
    if price < sma_200:
        parts.append(
            f"Price is below its 200-day average (${sma_200:.0f}), which means the long-term trend is broken. "
            f"Historically, stocks below this level underperform until they reclaim it."
        )
    elif rsi < 30:
        parts.append(
            f"RSI is at {rsi:.0f} — this is 'oversold' territory. Stocks this oversold often bounce in the next 3-5 days, "
            f"but catching a falling knife is risky."
        )
    elif rsi > 70:
        parts.append(
            f"RSI is at {rsi:.0f} — 'overbought.' The stock has run up fast and may need to cool off. "
            f"Don't chase it here; wait for a pullback."
        )

    # What analysts think
    if analyst_target and price > 0:
        upside = (analyst_target - price) / price * 100
        if upside > 20:
            parts.append(f"Wall Street analysts have a target of ${analyst_target:.0f}, implying {upside:.0f}% upside from here — they think it goes higher.")
        elif upside < -5:
            parts.append(f"Analysts target ${analyst_target:.0f}, which is actually below the current price — a warning sign.")

    # The bottom line
    if score >= 70 and "bullish" in bias:
        parts.append(
            "Bottom line: This looks like a good setup. If you're looking to buy, now is a reasonable entry. "
            "Set a stop-loss and don't go all-in — allocate 2-5% of your capital."
        )
    elif score >= 55 and price > sma_200:
        parts.append(
            "Bottom line: Decent setup but not screaming 'buy.' If you already own it, hold. "
            "If you want in, wait for a small dip (2-3% pullback) for a better entry."
        )
    elif score >= 45:
        parts.append(
            "Bottom line: No strong edge either way. If you own it and it's profitable, consider tightening your stop. "
            "If you're looking to buy, there are probably better opportunities elsewhere right now."
        )
    elif price < sma_200:
        parts.append(
            "Bottom line: The trend is broken and the risk is elevated. If you own it and need the capital, sell now. "
            "If you can hold through volatility and believe in the long-term story, set a hard stop and be prepared for more downside."
        )
    else:
        parts.append(
            "Bottom line: Conditions aren't favorable. Avoid new positions here. "
            "If you own it, have a stop-loss in place and stick to it."
        )

    # Hold guidance
    if score >= 60 and price > sma_200:
        daily_move = atr_pct / 100 * price
        if analyst_target and analyst_target > price:
            days_est = max(3, int((analyst_target - price) / (daily_move * 0.4)))
            parts.append(
                f"If you hold, the stock could reach the analyst target of ${analyst_target:.0f} in roughly {days_est} trading days "
                f"(~{days_est // 5} weeks), assuming the trend continues."
            )
    elif price < sma_200:
        parts.append(
            f"To recover, the stock needs to get back above ${sma_200:.0f} (its 200-day average). "
            f"Until that happens, the path of least resistance is down."
        )

    return " ".join(parts)


def _compute_sell_window(
    price: float, rsi: float, atr: float, atr_pct: float,
    sma_20: float, sma_50: float, sma_200: float,
    resistance: float, ret_20d: float, analyst_target: float,
) -> dict:
    """Estimate when to sell before the stock turns down.

    Uses RSI trajectory, distance to resistance, and trend exhaustion
    to estimate a sell window.
    """
    daily_move = atr_pct / 100 * price if atr_pct > 0 else 1
    urgency = "none"
    sell_at = 0.0
    sell_by = "—"
    reason = ""

    if rsi > 75:
        urgency = "NOW"
        sell_at = round(price, 2)
        sell_by = "Today or next 1-2 days"
        reason = (
            f"RSI at {rsi:.0f} — already overbought. Historically, stocks reverse "
            f"within 3-5 days of RSI > 75. Sell now or set a trailing stop at ${sma_20:.2f} (20-SMA)."
        )
    elif rsi > 65 and price > resistance * 0.98:
        days_to_ohb = max(1, int((75 - rsi) / 2))
        urgency = "SOON"
        sell_at = round(resistance, 2)
        sell_by = f"~{days_to_ohb} days — approaching overbought + resistance"
        reason = (
            f"RSI at {rsi:.0f} heading toward overbought, and price near resistance (${resistance:.2f}). "
            f"Sell at ${resistance:.2f} or if RSI crosses 75."
        )
    elif analyst_target > 0 and price > analyst_target * 0.95:
        pct_left = (analyst_target - price) / price * 100
        days_est = max(1, int(abs(analyst_target - price) / (daily_move * 0.4))) if daily_move > 0 else 30
        urgency = "NEAR TERM"
        sell_at = round(analyst_target, 2)
        sell_by = f"~{days_est} days — within {pct_left:.1f}% of analyst target"
        reason = (
            f"Price is within {pct_left:.1f}% of the analyst consensus target (${analyst_target:.2f}). "
            f"This is where institutional selling typically increases. "
            f"Sell at ${analyst_target:.2f} or set a trailing stop."
        )
    elif rsi > 55 and ret_20d > 10:
        days_est = max(3, int((70 - rsi) / 1.5))
        urgency = "WATCH"
        sell_at = round(price * 1.03, 2)
        sell_by = f"~{days_est} days if momentum continues"
        reason = (
            f"Stock up {ret_20d:.1f}% this month with RSI at {rsi:.0f}. "
            f"Strong runs typically exhaust after 15-25 days. "
            f"Watch for RSI > 70 or a gap-up day on high volume as exit signal."
        )
    elif price < sma_200:
        urgency = "ALREADY LATE"
        sell_at = round(price, 2)
        sell_by = "Now — trend already broken"
        reason = (
            f"Price is below the 200-SMA (${sma_200:.2f}). The long-term trend is already broken. "
            f"The sell window was when it crossed below 200-SMA. Exit now to limit further losses."
        )
    else:
        if price > sma_50:
            breakdown_price = round(sma_50, 2)
            days_est = max(5, int((price - sma_50) / (daily_move * 0.3))) if daily_move > 0 else 20
        else:
            breakdown_price = round(sma_200, 2)
            days_est = max(5, int((price - sma_200) / (daily_move * 0.3))) if daily_move > 0 and price > sma_200 else 20
        urgency = "NOT YET"
        sell_at = breakdown_price
        sell_by = f"Sell IF price breaks below ${breakdown_price:.2f}"
        reason = (
            f"No immediate sell signal. Trend is still intact. "
            f"Set a stop-loss at ${breakdown_price:.2f} — if price breaks below this level, "
            f"exit the position. Otherwise, hold and reassess weekly."
        )

    return {
        "urgency": urgency,
        "sell_at": sell_at,
        "sell_by": sell_by,
        "reason": reason,
    }


def _build_trade_plan(
    ticker: str,
    technicals: dict,
    fundamentals: dict,
    system_take: dict,
    regime: str,
    capital: float,
    strategy_signals: list | None = None,
) -> dict:
    """Generate a concrete trade plan: buy/wait/avoid, entry, stop, target, sizing.

    This is the 'what should I do' answer. Uses ATR-based stops/targets,
    analyst targets for upside estimation, and Kelly-inspired sizing.
    strategy_signals: optional list of TradeSignal objects for conflict resolution.
    """
    price = technicals.get("current_price", 0)
    atr = technicals.get("atr_14", 0)
    atr_pct = technicals.get("atr_pct", 2.0)
    score = system_take.get("score", 50)
    bias = system_take.get("bias", "neutral")
    support = technicals.get("support_20d", 0)
    resistance = technicals.get("resistance_20d", 0)
    sma_20 = technicals.get("sma_20", price)
    sma_50 = technicals.get("sma_50") or price
    rsi = technicals.get("rsi_14", 50)
    analyst_target = (fundamentals.get("analyst_target") or 0)

    if price <= 0 or atr <= 0:
        return {"action": "INSUFFICIENT DATA", "reason": "Cannot compute plan without price/ATR data"}

    # ── Decision: BUY / WAIT / AVOID
    sma_200_check = technicals.get("sma_200") or price
    if price < sma_200_check:
        action = "AVOID"
    elif score >= 65 and bias in ("bullish", "lean bullish", "cautiously bullish"):
        action = "BUY"
    elif score >= 55 and "bearish" not in bias:
        action = "WAIT FOR BETTER ENTRY"
    elif score >= 45:
        action = "HOLD OFF — NO EDGE"
    else:
        action = "AVOID"

    if "crisis" in regime.lower() and action == "BUY":
        action = "WAIT FOR BETTER ENTRY"

    # ── Entry price: where to buy
    if action == "BUY":
        if rsi < 35:
            entry = round(price, 2)
            entry_note = "Enter now — oversold bounce in progress"
        elif price < sma_20:
            entry = round(price, 2)
            entry_note = f"Enter now — price below 20-SMA (${sma_20:.2f}), dip-buying zone"
        else:
            entry = round(min(sma_20, price * 0.98), 2)
            entry_note = f"Wait for pullback to ${entry:.2f} (near 20-SMA or 2% dip)"
    elif action == "WAIT FOR BETTER ENTRY":
        entry = round(min(support, sma_50, price * 0.95), 2)
        entry_note = f"Wait for ${entry:.2f} — near 20d support or 50-SMA"
    else:
        entry = 0
        entry_note = "No entry recommended"

    # ── Stop loss: 2x ATR below entry
    stop_distance = round(atr * 2, 2)
    stop = round(entry - stop_distance, 2) if entry > 0 else 0
    stop_pct = round(stop_distance / entry * 100, 1) if entry > 0 else 0

    # ── Targets: ATR-based + analyst target
    target_1 = round(entry + atr * 3, 2) if entry > 0 else 0
    target_1_pct = round((target_1 - entry) / entry * 100, 1) if entry > 0 else 0

    target_2 = round(entry + atr * 5, 2) if entry > 0 else 0
    target_2_pct = round((target_2 - entry) / entry * 100, 1) if entry > 0 else 0

    # Use analyst target if it implies more upside than ATR target
    if analyst_target > target_2 and entry > 0:
        target_2 = round(analyst_target, 2)
        target_2_pct = round((target_2 - entry) / entry * 100, 1)

    rr_ratio = round(target_1_pct / stop_pct, 1) if stop_pct > 0 else 0

    # ── Hold period estimate based on ATR speed
    # Higher ATR% = price moves faster = shorter hold
    if atr_pct > 3:
        hold_days = "10-20 days (high volatility, moves fast)"
    elif atr_pct > 2:
        hold_days = "20-40 days"
    elif atr_pct > 1:
        hold_days = "40-80 days"
    else:
        hold_days = "60-120 days (low volatility, slow mover)"

    # ── 50% return feasibility
    time_to_50pct = None
    if atr_pct > 0 and entry > 0:
        daily_move = atr_pct / 100
        # Assume favorable trend captures ~40% of daily ATR as directional gain
        effective_daily_return = daily_move * 0.4
        if effective_daily_return > 0:
            days_for_50pct = int(0.50 / effective_daily_return)
            months = days_for_50pct / 21
            if months <= 2:
                time_to_50pct = f"~{days_for_50pct} trading days (~{months:.1f} months) — aggressive but possible"
            elif months <= 6:
                time_to_50pct = f"~{days_for_50pct} trading days (~{months:.0f} months) — realistic with strong trend"
            elif months <= 12:
                time_to_50pct = f"~{days_for_50pct} trading days (~{months:.0f} months) — requires sustained momentum"
            else:
                time_to_50pct = f"~{months:.0f} months — unlikely from this stock alone, consider options or higher-beta alternatives"

    # ── Position sizing for given capital
    if entry > 0 and stop > 0:
        risk_per_share = entry - stop
        risk_budget = capital * 0.02  # risk 2% of capital per trade
        shares = max(1, int(risk_budget / risk_per_share))
        position_value = round(shares * entry, 2)
        position_pct = round(position_value / capital * 100, 1)
        # Cap at 20% of capital
        if position_pct > 20:
            shares = max(1, int(capital * 0.20 / entry))
            position_value = round(shares * entry, 2)
            position_pct = round(position_value / capital * 100, 1)
        max_loss = round(shares * risk_per_share, 2)
        gain_t1 = round(shares * (target_1 - entry), 2)
        gain_t2 = round(shares * (target_2 - entry), 2)
    else:
        shares = 0
        position_value = 0
        position_pct = 0
        max_loss = 0
        gain_t1 = 0
        gain_t2 = 0

    # ── Sell window first — it can override the own-it recommendation
    sma_200 = technicals.get("sma_200") or price
    ret_20d = technicals.get("return_20d", 0)
    ret_60d = technicals.get("return_60d", 0)

    sell_window = _compute_sell_window(price, rsi, atr, atr_pct, sma_20, sma_50, sma_200, resistance, ret_20d, analyst_target)

    # Check if strong strategy signals exist (e.g., insider buying)
    _best_signal_score = 0
    _best_signal_edge = ""
    _best_signal_dir = ""
    if strategy_signals:
        for _sig in strategy_signals:
            _score = getattr(_sig, "signal_score", 0) or 0
            if _score > _best_signal_score:
                _best_signal_score = _score
                _best_signal_edge = getattr(_sig, "edge_reason", "") or ""
                _best_signal_dir = getattr(_sig, "direction", "") or ""

    # ── If you already own it: SELL / HOLD / BUY MORE
    # Strong strategy signals can override pure technical sell calls
    if sell_window["urgency"] == "NOW" and rsi > 75:
        own_action = "SELL"
        own_reason = sell_window["reason"]
        own_stop = 0
        own_target = 0
    elif sell_window["urgency"] in ("NOW", "ALREADY LATE") and _best_signal_score >= 70 and _best_signal_dir == "long":
        own_action = "HOLD — INSIDER CONVICTION"
        own_reason = (
            f"Technicals say sell (below 200-SMA at ${sma_200:.2f}), but strong insider/catalyst "
            f"signal (score {_best_signal_score:.0f}) suggests smart money disagrees. "
            f"If you believe in the insider signal: hold with a tight stop at ${round(support, 2)} (20d low). "
            f"If you don't: exit now and redeploy."
        )
        own_stop = round(support, 2)
        own_target = round(sma_200, 2)
    elif sell_window["urgency"] in ("NOW", "ALREADY LATE"):
        own_action = "SELL"
        own_reason = sell_window["reason"]
        own_stop = 0
        own_target = 0
    elif rsi > 75:
        own_action = "SELL PARTIAL — TAKE PROFITS"
        own_reason = (
            f"RSI at {rsi:.0f} — overbought. Sell 50% to lock in profits, "
            f"let the rest ride with stop at ${round(sma_20, 2)} (20-SMA)."
        )
        own_stop = round(sma_20, 2)
        own_target = target_2
    elif sell_window["urgency"] == "SOON":
        own_action = "HOLD — PREPARE TO SELL"
        own_reason = (
            f"Sell signal approaching. {sell_window['reason']} "
            f"Set a trailing stop at ${round(sma_20, 2)} (20-SMA) now."
        )
        own_stop = round(sma_20, 2)
        own_target = round(sell_window.get("sell_at", resistance), 2)
    elif score >= 70 and rsi < 40 and price > sma_200:
        own_action = "BUY MORE"
        own_reason = (
            f"Strong setup (score {score}) with oversold RSI ({rsi:.0f}) above 200-SMA. "
            f"Add to your position on this dip."
        )
        own_stop = round(sma_200 * 0.97, 2)
        own_target = target_1
    elif score >= 60 and price > sma_200:
        own_action = "HOLD"
        own_reason = (
            f"Conditions still favorable (score {score}), price above 200-SMA (${sma_200:.2f}). "
            f"Keep holding. Tighten stop to ${round(support, 2)} (20d support)."
        )
        own_stop = round(support, 2)
        own_target = target_1
    elif price < sma_200:
        own_action = "SELL"
        own_reason = (
            f"Price below 200-SMA (${sma_200:.2f}). Long-term trend is broken. "
            f"Exit and redeploy capital into stronger sectors."
        )
        own_stop = 0
        own_target = 0
    elif score < 40:
        own_action = "SELL"
        own_reason = (
            f"Weak score ({score}) with no catalyst to reverse. "
            f"Exit and look for better opportunities."
        )
        own_stop = 0
        own_target = 0
    elif score >= 45 and price > sma_200:
        own_action = "HOLD — TIGHTEN STOP"
        own_reason = (
            f"Neutral score ({score}) but still above 200-SMA. "
            f"Hold but raise stop to ${round(max(support, sma_50), 2)} to protect gains."
        )
        own_stop = round(max(support, sma_50), 2)
        own_target = resistance
    else:
        own_action = "HOLD"
        own_reason = (
            f"No strong signal either way (score {score}). "
            f"Hold with stop at ${round(support, 2)} and reassess weekly."
        )
        own_stop = round(support, 2)
        own_target = resistance

    # Estimate days to reach stop/target based on daily ATR movement
    daily_atr = atr_pct / 100 * price if atr_pct > 0 else 1
    days_to_stop = "—"
    days_to_target = "—"
    days_to_target_raw = 0
    if own_stop and own_stop > 0 and price > own_stop:
        dist = price - own_stop
        raw = max(1, int(dist / (daily_atr * 0.5)))
        days_to_stop = f"~{raw}d" if raw <= 5 else f"~{raw}d ({raw // 5}w)"
    if own_target and own_target > price:
        dist = own_target - price
        days_to_target_raw = max(1, int(dist / (daily_atr * 0.4)))
        days_to_target = f"~{days_to_target_raw}d" if days_to_target_raw <= 5 else f"~{days_to_target_raw}d ({days_to_target_raw // 5}w)"

    # Build hold duration for any HOLD recommendation
    hold_duration = ""
    if "HOLD" in own_action and own_target and own_stop:
        if days_to_target_raw > 0:
            hold_duration = (
                f"Hold for ~{days_to_target_raw} trading days. "
                f"Reassess if price hits target (${own_target:.2f}) or stop (${own_stop:.2f}), whichever comes first."
            )
        elif own_target > price:
            hold_duration = f"Hold until price reaches ${own_target:.2f} or breaks below ${own_stop:.2f}."
        else:
            hold_duration = f"Hold with stop at ${own_stop:.2f}. Reassess weekly."
    elif "HOLD" in own_action:
        hold_duration = "Reassess weekly — no clear time-based exit, use stop-loss as the trigger."

    return {
        "action": action,
        "entry_price": entry,
        "entry_note": entry_note,
        "stop_loss": stop,
        "stop_pct": stop_pct,
        "target_1": target_1,
        "target_1_pct": target_1_pct,
        "target_2": target_2,
        "target_2_pct": target_2_pct,
        "risk_reward": rr_ratio,
        "hold_period": hold_days,
        "time_to_50pct": time_to_50pct,
        "sizing": {
            "capital": capital,
            "shares": shares,
            "position_value": position_value,
            "position_pct": position_pct,
            "max_loss": max_loss,
            "gain_at_target_1": gain_t1,
            "gain_at_target_2": gain_t2,
        },
        "if_you_own_it": {
            "action": own_action,
            "reason": own_reason,
            "hold_duration": hold_duration,
            "stop_loss": own_stop,
            "target": own_target,
            "days_to_stop": days_to_stop,
            "days_to_target": days_to_target,
            "sell_window": sell_window,
        },
    }


def _analyze_sync(ticker: str, capital: float) -> dict:
    """Full analysis — runs in thread pool."""
    ohlcv = _fetcher.get_daily_ohlcv(ticker, period="2y")
    if ohlcv.empty:
        raise ValueError(f"No data for {ticker}")

    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y")
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y")

    regime_result = detect_regime(vix_df, spy_df)
    regime = regime_result["regime"]
    vol = compute_vol_context(spy_df, vix_df)

    technicals = _compute_technicals(ohlcv)
    fundamentals = yfinance_source.get_fundamentals(ticker)
    system_take = _build_system_take(technicals, fundamentals or {}, regime.value)

    # Generate strategy signals first so the trade plan can factor them in
    signals: list[TradeSignal] = []
    try:
        catalyst = CatalystEventStrategy()
        cat_signals = catalyst.generate_signals(vol, tickers=[ticker])
        signals.extend(s for s in cat_signals if s.ticker.upper() == ticker.upper())
    except Exception as e:
        logger.debug("Catalyst skipped for %s: %s", ticker, e)
    try:
        cross = CrossAssetMomentumStrategy()
        cross_signals = cross.generate_signals(vol, tickers=[ticker])
        signals.extend(s for s in cross_signals if s.ticker.upper() == ticker.upper())
    except Exception as e:
        logger.debug("CrossAsset skipped for %s: %s", ticker, e)

    trade_plan = _build_trade_plan(
        ticker, technicals, fundamentals or {}, system_take, regime.value, capital,
        strategy_signals=signals,
    )

    # Reconcile: if strong strategy signals conflict with the technical verdict,
    # upgrade the trade plan to reflect the tension
    if signals and trade_plan["action"] in ("AVOID", "HOLD OFF — NO EDGE"):
        best_signal = max(signals, key=lambda s: s.signal_score or 0)
        if (best_signal.signal_score or 0) >= 70:
            trade_plan["signal_override"] = {
                "has_conflict": True,
                "signal_direction": best_signal.direction,
                "signal_score": best_signal.signal_score,
                "signal_strategy": best_signal.strategy.value if hasattr(best_signal.strategy, "value") else str(best_signal.strategy),
                "signal_edge": best_signal.edge_reason,
                "note": (
                    f"Technical analysis says '{trade_plan['action']}' (below key SMAs), "
                    f"but a strong {best_signal.strategy.value if hasattr(best_signal.strategy, 'value') else best_signal.strategy} signal "
                    f"(score {best_signal.signal_score:.0f}) suggests a counter-trend "
                    f"{best_signal.direction} trade. This is a higher-risk contrarian setup — "
                    f"use smaller sizing (half-Kelly) and tighter stops."
                ),
            }

    return {
        "ticker": ticker,
        "current_price": technicals["current_price"],
        "sector": (fundamentals or {}).get("sector", "Unknown"),
        "regime": regime.value,
        "signals": [s.model_dump() for s in signals],
        "technicals": technicals,
        "fundamentals": fundamentals or {},
        "system_take": system_take,
        "trade_plan": trade_plan,
    }


def _resolve_ticker(raw: str) -> str:
    """Resolve a company name or ticker to a valid ticker symbol.

    1. If it looks like a ticker already (short, uppercase), use it directly.
    2. Search the S&P 500 universe (already cached) by company name.
    3. Fall back to yfinance search API.
    """
    cleaned = raw.strip()

    if len(cleaned) <= 5 and cleaned == cleaned.upper() and cleaned.isalpha():
        return cleaned

    cleaned = cleaned.upper()

    # Search universe by name
    try:
        from backend.data.universe import fetch_sp500_constituents
        df = fetch_sp500_constituents()
        if not df.empty and "name" in df.columns:
            match = df[df["name"].str.upper().str.contains(cleaned, na=False)]
            if not match.empty:
                return match.iloc[0]["ticker"]
    except Exception:
        pass

    # Fall back to yfinance search
    try:
        import yfinance as yf
        results = yf.Search(cleaned).quotes
        if results:
            return results[0].get("symbol", cleaned)
    except Exception:
        pass

    return cleaned


@router.get("/{ticker}")
async def analyze_stock(ticker: str, capital: float = Query(default=10000, ge=1)) -> dict:
    """Full single-stock analysis with trade plan.

    Accepts ticker symbols (NVDA) or company names (NVIDIA).
    """
    resolved = _resolve_ticker(ticker)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _analyze_sync, resolved, capital)
        if resolved != ticker.upper():
            result["resolved_from"] = ticker
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"{str(e)} (input: '{ticker}' → resolved: '{resolved}')")
    except Exception as e:
        logger.error("Analysis failed for %s: %s", resolved, e)
        raise HTTPException(status_code=500, detail=str(e))
