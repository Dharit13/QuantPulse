"""Cross-Asset Regime Momentum — Sector rotation driven by macro signals.

Equity sectors respond to macro signals (yields, VIX, commodities, credit,
dollar) with a 1-5 day lag.  This strategy detects cross-asset z-score
breakouts and rotates into the sectors that historically benefit.

Position sizing: 3-5% per sector ETF, max 15% total cross-asset exposure.
Expected hold: 3-15 days (until z-score normalizes).

Reference: QUANTPULSE_FINAL_SPEC.md §6
"""

from __future__ import annotations

import logging

import pandas as pd

from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.stops import compute_stop
from backend.adaptive.thresholds import get_cross_asset_params
from backend.adaptive.vol_context import VolContext
from backend.data.cross_asset import SECTOR_ETFS, cross_asset_data
from backend.data.fetcher import data_fetcher
from backend.models.schemas import StrategyName, TradeSignal
from backend.signals.cross_asset_signals import (
    CrossAssetSignal,
    aggregate_sector_scores,
    scan_all_cross_asset_signals,
)
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

MAX_STRATEGY_EXPOSURE_PCT = 0.15
MAX_POSITION_ETF_PCT = 0.05
MIN_SECTOR_SCORE = 0.5
MAX_SIGNALS_PER_SCAN = 6


class CrossAssetMomentumStrategy(BaseStrategy):
    """Sector rotation strategy driven by cross-asset macro signals."""

    def __init__(self) -> None:
        self.trailing_trades: list[dict] = []
        self.last_signals: list[CrossAssetSignal] = []
        self.active_positions: list[dict] = []

    @property
    def name(self) -> str:
        return StrategyName.CROSS_ASSET.value

    def get_params(self, vol: VolContext) -> dict:
        return get_cross_asset_params(vol)

    def generate_signals(
        self,
        vol: VolContext,
        **kwargs,
    ) -> list[TradeSignal]:
        """Scan cross-asset indicators and generate sector rotation signals.

        kwargs:
            regime: current regime string for Kelly computation
            max_signals: cap on total signals returned
        """
        regime = kwargs.get("regime", "bull_trend")
        max_signals = kwargs.get("max_signals", MAX_SIGNALS_PER_SCAN)
        params = self.get_params(vol)

        cross_asset_sigs = scan_all_cross_asset_signals(
            vol=vol,
            z_threshold=params["signal_z_threshold"],
            active_signals=params["active_signals"],
        )

        if not cross_asset_sigs:
            logger.info("No cross-asset signals fired")
            return []

        self.last_signals = cross_asset_sigs

        sector_scores = aggregate_sector_scores(cross_asset_sigs)

        trade_signals = self._generate_sector_trades(
            sector_scores=sector_scores,
            fired_signals=cross_asset_sigs,
            vol=vol,
            regime=regime,
            params=params,
        )

        trade_signals.sort(key=lambda s: abs(s.conviction), reverse=True)
        trade_signals = trade_signals[:max_signals]

        logger.info(
            "Cross-asset strategy generated %d signals from %d macro signals",
            len(trade_signals),
            len(cross_asset_sigs),
        )
        return trade_signals

    def _generate_sector_trades(
        self,
        sector_scores: dict[str, float],
        fired_signals: list[CrossAssetSignal],
        vol: VolContext,
        regime: str,
        params: dict,
    ) -> list[TradeSignal]:
        """Convert sector scores into TradeSignal objects via ETFs."""
        signals: list[TradeSignal] = []
        cumulative_exposure = 0.0
        sector_data = cross_asset_data.get_sector_etf_data(period="6mo")

        for sector, score in sorted(
            sector_scores.items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        ):
            if abs(score) < MIN_SECTOR_SCORE:
                continue
            if cumulative_exposure >= MAX_STRATEGY_EXPOSURE_PCT:
                break

            etf_ticker = SECTOR_ETFS.get(sector)
            if not etf_ticker:
                continue

            direction = "long" if score > 0 else "short"

            etf_df = sector_data.get(sector)
            if etf_df is None or etf_df.empty:
                etf_df = data_fetcher.get_daily_ohlcv(etf_ticker, period="6mo")
            if etf_df.empty:
                continue

            entry_price = float(etf_df["Close"].iloc[-1])
            if entry_price <= 0:
                continue

            atr = _compute_atr(etf_df)
            stop_info = compute_stop(entry_price, direction, atr, "cross_asset", vol)

            contributing = [
                s
                for s in fired_signals
                if (sector in s.long_sectors and score > 0)
                or (sector in s.short_sectors and score < 0)
            ]
            max_z = max((abs(s.z_score) for s in contributing), default=0)
            conviction = min(1.0, max_z / 4.0 + abs(score) / 8.0)

            if conviction < 0.3:
                continue

            kelly = compute_adaptive_kelly(
                strategy="cross_asset",
                vol=vol,
                regime=regime,
                trailing_trades=self.trailing_trades,
            )

            position_pct = min(
                kelly["kelly_fraction"],
                MAX_POSITION_ETF_PCT * vol.position_scale,
            )

            if cumulative_exposure + position_pct > MAX_STRATEGY_EXPOSURE_PCT:
                position_pct = MAX_STRATEGY_EXPOSURE_PCT - cumulative_exposure

            if direction == "long":
                target = entry_price + stop_info["stop_distance_dollars"] * 2.5
            else:
                target = entry_price - stop_info["stop_distance_dollars"] * 2.5

            contributing_desc = "; ".join(s.description for s in contributing[:3])
            signal = TradeSignal(
                strategy=StrategyName.CROSS_ASSET,
                ticker=etf_ticker,
                direction=direction,
                conviction=conviction,
                kelly_size_pct=position_pct * 100,
                entry_price=entry_price,
                stop_loss=stop_info["stop_price"],
                target=round(target, 2),
                max_hold_days=params["max_hold_days"],
                edge_reason=(
                    f"Cross-asset sector rotation: {sector} {direction} "
                    f"(aggregate score={score:+.2f}). "
                    f"Macro drivers: {contributing_desc}"
                ),
                kill_condition=(
                    f"All contributing z-scores normalize below "
                    f"{params['signal_z_threshold']:.1f} threshold, "
                    f"or regime shifts to crisis, "
                    f"or stop hit at {stop_info['stop_price']:.2f}"
                ),
                expected_sharpe=1.2,
                signal_score=min(100, conviction * 100),
            )

            if self.validate_signal(signal):
                signals.append(signal)
                cumulative_exposure += position_pct

        return signals


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR for stop-loss computation."""
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


cross_asset_momentum_strategy = CrossAssetMomentumStrategy()
