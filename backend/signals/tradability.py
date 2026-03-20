"""Tradability gate — can this signal actually be executed?

Checks %ADV utilization, projected slippage, borrow availability,
and spread width before a signal is presented as actionable.
No API calls — uses cached OHLCV data already fetched by strategies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.data.fetcher import data_fetcher
from backend.models.schemas import TradeSignal

logger = logging.getLogger(__name__)

BASE_SLIPPAGE_BPS = 5.0
MAX_ADV_PCT = 0.02
WIDE_SPREAD_ATR_PCT = 0.05


@dataclass
class TradabilityResult:
    passed: bool
    projected_slippage_bps: float
    pct_adv_used: float
    borrow_available: bool
    spread_acceptable: bool
    reasons: list[str] = field(default_factory=list)


def check_tradability(
    signal: TradeSignal,
    capital: float = 100_000.0,
) -> TradabilityResult:
    """Run all tradability checks for a single signal.

    Uses cached OHLCV data — fast, no network calls.
    """
    reasons: list[str] = []
    passed = True

    df = data_fetcher.get_daily_ohlcv(signal.ticker, period="3mo")
    if df.empty or len(df) < 10:
        return TradabilityResult(
            passed=False,
            projected_slippage_bps=0,
            pct_adv_used=0,
            borrow_available=True,
            spread_acceptable=False,
            reasons=["Insufficient price data for tradability check"],
        )

    price = signal.entry_price
    position_dollars = capital * (signal.kelly_size_pct / 100)

    # %ADV check
    avg_volume_20d = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns else 0
    dollar_volume = avg_volume_20d * price if avg_volume_20d > 0 else 1
    pct_adv = position_dollars / dollar_volume if dollar_volume > 0 else 1.0

    if pct_adv > MAX_ADV_PCT:
        reasons.append(f"Position uses {pct_adv:.1%} of ADV (limit {MAX_ADV_PCT:.0%}) — would move the market")
        passed = False

    # Slippage estimate: scales up when position is larger fraction of volume
    slippage_multiplier = max(1.0, pct_adv / 0.005)
    projected_slippage_bps = BASE_SLIPPAGE_BPS * slippage_multiplier

    # Borrow heuristic for shorts
    borrow_available = True
    if signal.direction == "short":
        try:
            from backend.data.universe import fetch_sp500_constituents

            sp500 = fetch_sp500_constituents()
            is_sp500 = signal.ticker in sp500["ticker"].values
        except Exception:
            is_sp500 = False

        if not is_sp500:
            borrow_available = False
            reasons.append(f"{signal.ticker} is not in S&P 500 — borrow availability uncertain")

    # Spread check via ATR%
    close = df["Close"]
    high = df["High"].tail(14)
    low = df["Low"].tail(14)
    prev_close = close.shift(1).tail(14)
    import pandas as pd

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.mean())
    atr_pct = atr / price if price > 0 else 0

    spread_acceptable = atr_pct < WIDE_SPREAD_ATR_PCT
    if not spread_acceptable:
        reasons.append(f"ATR% is {atr_pct:.1%} (>{WIDE_SPREAD_ATR_PCT:.0%}) — wide spread risk, fills may be poor")

    if reasons and passed:
        passed = borrow_available and spread_acceptable

    return TradabilityResult(
        passed=passed,
        projected_slippage_bps=round(projected_slippage_bps, 1),
        pct_adv_used=round(pct_adv, 4),
        borrow_available=borrow_available,
        spread_acceptable=spread_acceptable,
        reasons=reasons if reasons else ["All tradability checks passed"],
    )
