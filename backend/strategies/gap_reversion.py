"""Overnight Gap & Intraday Mean Reversion Strategy.

Exploits the structural difference between overnight (thin-liquidity) and
intraday (full-liquidity) price formation.  Gaps > 1σ revert 60-65% of the
time within the first 90 minutes of trading.

Logic (from spec §8):
  1. Pre-market: gap_pct = (premarket_price − prev_close) / prev_close
  2. Filter: adaptive min/max gap %, no recent catalyst, VIX gate
  3. Entry at open: gap UP → short (bet on fill), gap DOWN → long
  4. Target: previous close (full gap fill) or 50% gap fill (partial)
  5. Stop: adaptive % of gap in the wrong direction
  6. Time stop: close by 10:30–11:00 AM depending on vol

Sizing: 1-2% per trade, 3-8 trades/day expected.
Expected: 62% win rate, 1.3:1 avg win/loss.

Reference: QUANTPULSE_FINAL_SPEC.md §8
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.stops import compute_stop
from backend.adaptive.thresholds import get_gap_reversion_params
from backend.adaptive.vol_context import VolContext
from backend.config import settings
from backend.data.fetcher import data_fetcher
from backend.data.universe import fetch_sp500_constituents
from backend.models.schemas import StrategyName, TradeSignal
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

MAX_STRATEGY_EXPOSURE_PCT = 0.06
MAX_POSITION_PCT = 0.02
MAX_SIGNALS_PER_SCAN = 8


class GapReversionStrategy(BaseStrategy):
    """Overnight gap mean-reversion trading strategy."""

    def __init__(self) -> None:
        self.trailing_trades: list[dict] = []
        self._gap_fill_cache: dict[str, float] = {}

    @property
    def name(self) -> str:
        return StrategyName.INTRADAY.value

    def get_params(self, vol: VolContext) -> dict:
        return get_gap_reversion_params(vol)

    def generate_signals(
        self,
        vol: VolContext,
        **kwargs,
    ) -> list[TradeSignal]:
        """Scan universe for overnight gap reversion opportunities.

        kwargs:
            tickers: optional list[str] to scan (defaults to S&P 500)
            regime: current regime string for Kelly computation
            premarket_prices: optional dict[str, float] mapping ticker → premarket price
        """
        regime = kwargs.get("regime", "bull_trend")
        tickers = kwargs.get("tickers")
        premarket_prices: dict[str, float] = kwargs.get("premarket_prices", {})
        params = self.get_params(vol)

        if vol.vix_current > params["max_vix_for_trading"]:
            logger.info(
                "Gap reversion disabled: VIX %.1f > %.0f threshold",
                vol.vix_current,
                params["max_vix_for_trading"],
            )
            return []

        if tickers is None:
            tickers = self._get_universe()

        if not tickers:
            return []

        signals: list[TradeSignal] = []
        cumulative_exposure = 0.0

        for ticker in tickers:
            if cumulative_exposure >= MAX_STRATEGY_EXPOSURE_PCT:
                break

            signal = self._evaluate_gap(
                ticker, vol, regime, params, premarket_prices.get(ticker),
            )
            if signal is None:
                continue

            if not self.validate_signal(signal):
                continue

            signals.append(signal)
            cumulative_exposure += signal.kelly_size_pct / 100

        signals.sort(key=lambda s: s.conviction, reverse=True)
        signals = signals[:MAX_SIGNALS_PER_SCAN]

        logger.info("Gap reversion strategy generated %d signals", len(signals))
        return signals

    # ── Core gap evaluation ──────────────────────────────────────────────

    def _evaluate_gap(
        self,
        ticker: str,
        vol: VolContext,
        regime: str,
        params: dict,
        premarket_price: float | None = None,
    ) -> TradeSignal | None:
        """Evaluate a single ticker for gap-fill trade."""
        df = data_fetcher.get_daily_ohlcv(ticker, period="3mo")
        if df.empty or len(df) < 20:
            return None

        prev_close = float(df["Close"].iloc[-1])
        if prev_close <= 0:
            return None

        if premarket_price is None:
            current = data_fetcher.get_current_price(ticker)
            if current is None or current <= 0:
                return None
            premarket_price = current

        gap_pct = (premarket_price - prev_close) / prev_close * 100

        if abs(gap_pct) < params["min_gap_pct"] or abs(gap_pct) > params["max_gap_pct"]:
            return None

        if not self._passes_catalyst_filter(ticker):
            return None

        if not self._passes_volume_filter(df):
            return None

        historical_fill_rate = self._compute_historical_gap_fill_rate(df, params)
        if historical_fill_rate < 0.55:
            return None

        # Gap UP → short (bet on fill); Gap DOWN → long
        direction = "short" if gap_pct > 0 else "long"

        # Targets: full gap fill (prev close) and 50% fill
        gap_dollars = premarket_price - prev_close
        target_full = prev_close
        target_partial = premarket_price - gap_dollars * 0.5

        # Stop: gap extension by stop_pct_of_gap
        stop_extension = abs(gap_dollars) * params["stop_pct_of_gap"]
        if direction == "short":
            stop_price = premarket_price + stop_extension
        else:
            stop_price = premarket_price - stop_extension

        atr = self._compute_atr(df)
        gap_atr_ratio = abs(gap_dollars) / max(0.01, atr)

        conviction = self._compute_conviction(
            gap_pct=gap_pct,
            historical_fill_rate=historical_fill_rate,
            gap_atr_ratio=gap_atr_ratio,
            vol=vol,
        )

        kelly = compute_adaptive_kelly(
            strategy="gap_reversion",
            vol=vol,
            regime=regime,
            trailing_trades=self.trailing_trades,
        )
        position_pct = min(
            kelly["kelly_fraction"],
            MAX_POSITION_PCT * vol.position_scale,
            params["max_position_pct"],
        )

        if position_pct <= 0:
            return None

        edge_reason = (
            f"Overnight gap {gap_pct:+.1f}%: thin pre-market liquidity creates "
            f"systematic overreaction. Historical fill rate={historical_fill_rate:.0%} "
            f"for this ticker. Gap is {gap_atr_ratio:.1f}x ATR — "
            f"{'large enough to revert' if gap_atr_ratio > 1 else 'moderate'}. "
            f"VIX={vol.vix_current:.1f} (below {params['max_vix_for_trading']} gate)."
        )

        kill_condition = (
            f"Gap extends >{params['stop_pct_of_gap']:.0%} beyond open "
            f"(stop at {stop_price:.2f}), or no fill by {params['close_by_time']} "
            f"(time stop), or VIX spikes above {params['max_vix_for_trading']}, "
            f"or news catalyst emerges intraday."
        )

        return TradeSignal(
            strategy=StrategyName.INTRADAY,
            ticker=ticker,
            direction=direction,
            conviction=conviction,
            kelly_size_pct=position_pct * 100,
            entry_price=round(premarket_price, 2),
            stop_loss=round(stop_price, 2),
            target=round(target_full, 2),
            max_hold_days=1,
            edge_reason=edge_reason,
            kill_condition=kill_condition,
            expected_sharpe=1.1,
            signal_score=min(100, conviction * 100),
        )

    # ── Filters ──────────────────────────────────────────────────────────

    def _passes_catalyst_filter(self, ticker: str) -> bool:
        """Reject if there's a recent earnings/catalyst event.

        Catalyst-driven gaps are continuation events, not reversion opportunities.
        """
        try:
            earnings_data = data_fetcher.get_earnings_data(ticker)
            if not earnings_data:
                return True

            latest = earnings_data[0]
            report_date = latest.get("date")
            if report_date is None:
                return True

            if isinstance(report_date, str):
                report_date = date.fromisoformat(report_date)

            days_since = (date.today() - report_date).days
            return days_since > 2
        except Exception:
            return True

    @staticmethod
    def _passes_volume_filter(df: pd.DataFrame) -> bool:
        """Check that recent volume is adequate for entry/exit.

        Require that last-day volume exceeds 50% of 20-day avg
        (very loose — real version checks first-5-min bars when intraday available).
        """
        if "Volume" not in df.columns or len(df) < 20:
            return True

        avg_vol_20d = float(df["Volume"].tail(20).mean())
        last_vol = float(df["Volume"].iloc[-1])

        return avg_vol_20d > 100_000 and last_vol > avg_vol_20d * 0.5

    def _compute_historical_gap_fill_rate(
        self,
        df: pd.DataFrame,
        params: dict,
    ) -> float:
        """Backtest per-ticker gap fill rate over recent history.

        A gap "fills" if price crosses the previous close within the same day
        (using daily candle: the low < prev_close for gap-up, high > prev_close
        for gap-down).
        """
        if len(df) < 40:
            return 0.60

        opens = df["Open"].values
        closes = df["Close"].values
        highs = df["High"].values
        lows = df["Low"].values

        gap_count = 0
        fill_count = 0

        for i in range(1, len(df)):
            prev_close = closes[i - 1]
            if prev_close <= 0:
                continue

            gap_pct = (opens[i] - prev_close) / prev_close * 100

            if abs(gap_pct) < params["min_gap_pct"] or abs(gap_pct) > params["max_gap_pct"]:
                continue

            gap_count += 1

            if gap_pct > 0 and lows[i] <= prev_close:
                fill_count += 1
            elif gap_pct < 0 and highs[i] >= prev_close:
                fill_count += 1

        if gap_count < 3:
            return 0.60

        return fill_count / gap_count

    # ── Conviction scoring ───────────────────────────────────────────────

    @staticmethod
    def _compute_conviction(
        gap_pct: float,
        historical_fill_rate: float,
        gap_atr_ratio: float,
        vol: VolContext,
    ) -> float:
        """Composite conviction score (0.0–1.0) for gap-fill trade.

        Components:
          40% — historical fill rate for this ticker
          30% — gap size relative to ATR (sweet spot: 1.0–2.5x ATR)
          20% — vol environment favorability (lower vol = higher fill rate)
          10% — gap size in the optimal range (not too small, not too large)
        """
        fill_score = min(1.0, historical_fill_rate / 0.70) * 0.40

        if 1.0 <= gap_atr_ratio <= 2.5:
            atr_score = 1.0
        elif gap_atr_ratio < 1.0:
            atr_score = gap_atr_ratio
        else:
            atr_score = max(0.3, 1.0 - (gap_atr_ratio - 2.5) * 0.2)
        atr_score *= 0.30

        vol_score = min(1.0, vol.position_scale) * 0.20

        abs_gap = abs(gap_pct)
        if 1.0 <= abs_gap <= 3.0:
            gap_range_score = 1.0
        elif abs_gap < 1.0:
            gap_range_score = abs_gap
        else:
            gap_range_score = max(0.2, 1.0 - (abs_gap - 3.0) * 0.15)
        gap_range_score *= 0.10

        raw = fill_score + atr_score + vol_score + gap_range_score
        return round(min(1.0, max(0.0, raw)), 3)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return float(df["Close"].std()) if not df.empty else 1.0

        high = df["High"].tail(period)
        low = df["Low"].tail(period)
        prev_close = df["Close"].shift(1).tail(period)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        return float(tr.mean())

    @staticmethod
    def _get_universe(top_n: int = 200) -> list[str]:
        try:
            sp500 = fetch_sp500_constituents()
            return sp500["ticker"].tolist()[:top_n]
        except Exception:
            logger.warning("Failed to fetch S&P 500 constituents for gap scan")
            return []


gap_reversion_strategy = GapReversionStrategy()
