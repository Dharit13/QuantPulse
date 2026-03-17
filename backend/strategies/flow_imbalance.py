"""Microstructure & Flow Imbalance Strategy — institutional flow trading.

Orchestrates three sub-strategies driven by market microstructure:
  A) GEX Pin Risk — mean-revert near positive-GEX strikes, momentum near negative
  B) Dark Pool Level Trading — trade pullbacks to institutional support/resistance
  C) Unusual Options Sweep — follow large institutional directional bets

ALL sub-strategies require paid data (Unusual Whales, Polygon).  When those
flags are disabled the strategy returns no signals and degrades gracefully.

Position sizing: 2-4% per trade, max 10% total flow exposure.
Expected hold: 2-10 days.

Reference: QUANTPULSE_FINAL_SPEC.md §7
"""

from __future__ import annotations

import logging

import pandas as pd

from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.stops import compute_stop
from backend.adaptive.thresholds import get_flow_params
from backend.adaptive.vol_context import VolContext
from backend.config import settings
from backend.data.fetcher import data_fetcher
from backend.data.universe import fetch_sp500_constituents
from backend.models.schemas import StrategyName, TradeSignal
from backend.signals.microstructure import (
    DarkPoolProfile,
    GEXProfile,
    UnusualVolumeSignal,
    compute_dark_pool_levels,
    compute_gex_profile,
    scan_universe_for_flow,
)
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

MAX_STRATEGY_EXPOSURE_PCT = 0.10
MAX_POSITION_PCT = 0.04
MAX_SIGNALS_PER_SCAN = 8


class FlowImbalanceStrategy(BaseStrategy):
    """Institutional flow imbalance trading strategy."""

    def __init__(self) -> None:
        self.trailing_trades: list[dict] = []

    @property
    def name(self) -> str:
        return StrategyName.FLOW.value

    def get_params(self, vol: VolContext) -> dict:
        return get_flow_params(vol)

    def generate_signals(
        self,
        vol: VolContext,
        **kwargs,
    ) -> list[TradeSignal]:
        """Generate trade signals from microstructure analysis.

        kwargs:
            tickers: optional list[str] to scan (defaults to S&P 500 top-100 by volume)
            regime: current regime string for Kelly computation
        """
        regime = kwargs.get("regime", "bull_trend")
        tickers = kwargs.get("tickers")
        params = self.get_params(vol)

        if tickers is None:
            tickers = self._get_liquid_universe()

        if not tickers:
            return []

        signals: list[TradeSignal] = []
        cumulative_exposure = 0.0

        # Sub-Strategy C first — sweep detection scans the full universe
        sweep_signals = self._generate_sweep_signals(tickers, vol, regime, params)
        for sig in sweep_signals:
            if cumulative_exposure >= MAX_STRATEGY_EXPOSURE_PCT:
                break
            if self.validate_signal(sig):
                signals.append(sig)
                cumulative_exposure += sig.kelly_size_pct / 100

        # Sub-Strategies A & B — GEX + dark pool on tickers that had flow activity,
        # plus the top-volume tickers
        gex_dp_tickers = [s.ticker for s in signals] + tickers[:30]
        seen = set()
        gex_dp_tickers = [t for t in gex_dp_tickers if t not in seen and not seen.add(t)]

        for ticker in gex_dp_tickers:
            if cumulative_exposure >= MAX_STRATEGY_EXPOSURE_PCT:
                break

            # Sub-Strategy A: GEX
            gex_sig = self._generate_gex_signal(ticker, vol, regime, params)
            if gex_sig and self.validate_signal(gex_sig):
                if not any(s.ticker == ticker for s in signals):
                    signals.append(gex_sig)
                    cumulative_exposure += gex_sig.kelly_size_pct / 100

            # Sub-Strategy B: Dark Pool
            dp_sig = self._generate_dark_pool_signal(ticker, vol, regime, params)
            if dp_sig and self.validate_signal(dp_sig):
                if not any(s.ticker == ticker and s.direction == dp_sig.direction for s in signals):
                    signals.append(dp_sig)
                    cumulative_exposure += dp_sig.kelly_size_pct / 100

        signals.sort(key=lambda s: s.conviction, reverse=True)
        signals = signals[:MAX_SIGNALS_PER_SCAN]

        logger.info("Flow imbalance strategy generated %d signals", len(signals))
        return signals

    # ── Sub-Strategy A: GEX Pin Risk ─────────────────────────────────────

    def _generate_gex_signal(
        self,
        ticker: str,
        vol: VolContext,
        regime: str,
        params: dict,
    ) -> TradeSignal | None:
        """GEX-based mean-reversion or momentum signal."""
        if not settings.enable_polygon:
            return None

        gex = compute_gex_profile(ticker, vol)
        if gex is None or not gex.levels:
            return None

        spot = gex.spot_price

        if gex.is_positive_gex_environment and gex.nearest_pin is not None:
            # Positive GEX = pinning: mean-revert toward nearest pin
            pin_distance_pct = (gex.nearest_pin - spot) / spot
            if abs(pin_distance_pct) < 0.005:
                return None  # already at pin

            direction = "long" if pin_distance_pct > 0 else "short"
            target = gex.nearest_pin
            edge = (
                f"GEX pinning: net GEX={gex.net_gex_total:,.0f}, "
                f"nearest pin at {gex.nearest_pin:.2f} ({pin_distance_pct:+.1%} away). "
                f"MM hedging dampens moves — mean-revert toward pin."
            )
            kill = (
                f"GEX profile flips negative (regime change), "
                f"or price breaks through pin by >{abs(pin_distance_pct)*2:.1%}"
            )
            conviction = min(1.0, abs(pin_distance_pct) * 10 + 0.3)

        elif not gex.is_positive_gex_environment and gex.flip_price is not None:
            # Negative GEX = acceleration: momentum trade away from flip
            flip_distance_pct = (spot - gex.flip_price) / spot
            if abs(flip_distance_pct) < 0.003:
                return None

            direction = "long" if flip_distance_pct > 0 else "short"
            target = spot * (1.03 if direction == "long" else 0.97)
            edge = (
                f"Negative GEX regime: net GEX={gex.net_gex_total:,.0f}, "
                f"flip at {gex.flip_price:.2f}. "
                f"MM hedging amplifies moves — momentum trade."
            )
            kill = (
                f"GEX flips positive (pinning restored), "
                f"or price reverses through flip at {gex.flip_price:.2f}"
            )
            conviction = min(1.0, abs(flip_distance_pct) * 8 + 0.25)

        else:
            return None

        atr = self._get_atr(ticker)
        stop_info = compute_stop(spot, direction, atr, "flow", vol)

        kelly = compute_adaptive_kelly(
            strategy="flow",
            vol=vol,
            regime=regime,
            trailing_trades=self.trailing_trades,
        )
        position_pct = min(kelly["kelly_fraction"], MAX_POSITION_PCT * vol.position_scale)

        return TradeSignal(
            strategy=StrategyName.FLOW,
            ticker=ticker,
            direction=direction,
            conviction=conviction,
            kelly_size_pct=position_pct * 100,
            entry_price=spot,
            stop_loss=stop_info["stop_price"],
            target=round(target, 2),
            max_hold_days=params["max_hold_days"],
            edge_reason=edge,
            kill_condition=kill,
            expected_sharpe=1.3,
            signal_score=min(100, conviction * 100),
        )

    # ── Sub-Strategy B: Dark Pool Levels ─────────────────────────────────

    def _generate_dark_pool_signal(
        self,
        ticker: str,
        vol: VolContext,
        regime: str,
        params: dict,
    ) -> TradeSignal | None:
        """Trade pullbacks to dark pool support/resistance clusters."""
        if not settings.enable_smart_money:
            return None

        dp = compute_dark_pool_levels(ticker, vol)
        if dp is None or not dp.levels:
            return None

        spot = dp.spot_price

        # Look for price sitting near a high-significance dark pool level
        for level in dp.levels:
            if level.significance < 0.3:
                continue

            distance_pct = (spot - level.price_level) / spot
            if abs(distance_pct) > 0.02:
                continue  # too far from level

            if level.side == "buy" and distance_pct < 0:
                # Price pulling back toward institutional buy cluster
                direction = "long"
                target = spot * 1.03
            elif level.side == "sell" and distance_pct > 0:
                # Price rallying toward institutional sell cluster
                direction = "short"
                target = spot * 0.97
            else:
                continue

            atr = self._get_atr(ticker)
            stop_info = compute_stop(spot, direction, atr, "flow", vol)

            kelly = compute_adaptive_kelly(
                strategy="flow",
                vol=vol,
                regime=regime,
                trailing_trades=self.trailing_trades,
            )
            position_pct = min(kelly["kelly_fraction"], MAX_POSITION_PCT * vol.position_scale)

            conviction = min(1.0, level.significance + abs(distance_pct) * 20)

            return TradeSignal(
                strategy=StrategyName.FLOW,
                ticker=ticker,
                direction=direction,
                conviction=conviction,
                kelly_size_pct=position_pct * 100,
                entry_price=spot,
                stop_loss=stop_info["stop_price"],
                target=round(target, 2),
                max_hold_days=params["max_hold_days"],
                edge_reason=(
                    f"Dark pool {level.side} cluster at {level.price_level:.2f} "
                    f"(${level.total_notional:,.0f} notional, {level.print_count} prints, "
                    f"significance={level.significance:.2f}). "
                    f"Institutional S/R not visible on public charts."
                ),
                kill_condition=(
                    f"Price breaks through dark pool level by >1.5%, "
                    f"or new dark pool prints invalidate the level, "
                    f"or stop hit at {stop_info['stop_price']:.2f}"
                ),
                expected_sharpe=1.2,
                signal_score=min(100, conviction * 100),
            )

        return None

    # ── Sub-Strategy C: Sweep / Unusual Options Volume ───────────────────

    def _generate_sweep_signals(
        self,
        tickers: list[str],
        vol: VolContext,
        regime: str,
        params: dict,
    ) -> list[TradeSignal]:
        """Detect unusual options sweeps and follow institutional direction."""
        if not settings.enable_smart_money:
            return []

        flow_signals = scan_universe_for_flow(tickers, vol, max_results=20)
        trade_signals: list[TradeSignal] = []

        for fs in flow_signals:
            if fs.direction == "neutral":
                continue

            direction = "long" if fs.direction == "bullish" else "short"

            spot = data_fetcher.get_current_price(fs.ticker)
            if spot is None or spot <= 0:
                continue

            atr = self._get_atr(fs.ticker)
            stop_info = compute_stop(spot, direction, atr, "flow", vol)

            kelly = compute_adaptive_kelly(
                strategy="flow",
                vol=vol,
                regime=regime,
                trailing_trades=self.trailing_trades,
            )
            position_pct = min(kelly["kelly_fraction"], MAX_POSITION_PCT * vol.position_scale)

            if direction == "long":
                target = spot + stop_info["stop_distance_dollars"] * 2.5
            else:
                target = spot - stop_info["stop_distance_dollars"] * 2.5

            sweep_desc = ""
            if fs.sweeps:
                top_sweep = max(fs.sweeps, key=lambda s: s.premium)
                sweep_desc = (
                    f" Top sweep: {top_sweep.contract_type} ${top_sweep.strike:.0f} "
                    f"({top_sweep.expiry_days}d DTE, ${top_sweep.premium:,.0f} premium)."
                )

            conviction = min(1.0, fs.confidence)

            signal = TradeSignal(
                strategy=StrategyName.FLOW,
                ticker=fs.ticker,
                direction=direction,
                conviction=conviction,
                kelly_size_pct=position_pct * 100,
                entry_price=spot,
                stop_loss=stop_info["stop_price"],
                target=round(target, 2),
                max_hold_days=params["max_hold_days"],
                edge_reason=(
                    f"Unusual options volume: {fs.volume_ratio:.1f}x avg "
                    f"(C/P ratio={fs.call_put_ratio:.2f}, "
                    f"net premium=${fs.net_premium:,.0f}).{sweep_desc} "
                    f"Institutional time-sensitive directional bet."
                ),
                kill_condition=(
                    f"Options volume normalizes (<1.5x avg), "
                    f"or net premium reverses direction, "
                    f"or stop hit at {stop_info['stop_price']:.2f}, "
                    f"or {params['max_hold_days']}d time stop"
                ),
                expected_sharpe=1.4,
                signal_score=min(100, conviction * 100),
            )

            if self.validate_signal(signal):
                trade_signals.append(signal)

        return trade_signals

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_liquid_universe(top_n: int = 100) -> list[str]:
        """Get top-N most liquid S&P 500 stocks by recent volume."""
        try:
            sp500 = fetch_sp500_constituents()
            return sp500["ticker"].tolist()[:top_n]
        except Exception:
            logger.warning("Failed to fetch S&P 500 constituents")
            return []

    @staticmethod
    def _get_atr(ticker: str, period: int = 14) -> float:
        """Compute ATR for stop-loss calculation."""
        df = data_fetcher.get_daily_ohlcv(ticker, period="3mo")
        if df.empty or len(df) < period + 1:
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


flow_imbalance_strategy = FlowImbalanceStrategy()
