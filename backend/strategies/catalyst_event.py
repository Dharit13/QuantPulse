"""Catalyst-Driven Event Trading Strategy.

Orchestrates three sub-strategies:
  A) Post-Earnings Announcement Drift (PEAD)
  B) Analyst Revision Momentum
  C) Institutional Flow Events (gated behind enable_smart_money)

Each sub-strategy uses adaptive parameters from get_catalyst_params().
"""

import logging

import pandas as pd

from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.stops import compute_stop
from backend.adaptive.thresholds import get_catalyst_params
from backend.adaptive.vol_context import VolContext
from backend.config import settings
from backend.data.fetcher import data_fetcher
from backend.data.universe import fetch_sp500_constituents
from backend.models.schemas import StrategyName, TradeSignal
from backend.signals.earnings import detect_pead, scan_universe_for_pead
from backend.signals.revisions import detect_revision_momentum, scan_universe_for_revisions
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class CatalystEventStrategy(BaseStrategy):
    """Catalyst-driven event trading strategy."""

    def __init__(self):
        self.trailing_trades: list[dict] = []

    @property
    def name(self) -> str:
        return StrategyName.CATALYST.value

    def get_params(self, vol: VolContext) -> dict:
        return get_catalyst_params(vol)

    def generate_signals(
        self,
        vol: VolContext,
        **kwargs,
    ) -> list[TradeSignal]:
        """Generate trade signals from all catalyst sub-strategies.

        kwargs:
            tickers: optional list[str] to scan (defaults to S&P 500)
            regime: current regime string for Kelly computation
            pead_lookback: days back to look for earnings (default 5)
        """
        tickers = kwargs.get("tickers")
        regime = kwargs.get("regime", "bull_trend")
        pead_lookback = kwargs.get("pead_lookback", 5)

        if tickers is None:
            try:
                sp500 = fetch_sp500_constituents()
                tickers = sp500["ticker"].tolist()
            except Exception:
                logger.exception("Failed to fetch S&P 500, using empty ticker list")
                tickers = []

        signals: list[TradeSignal] = []

        # Sub-Strategy A: PEAD
        pead_signals = scan_universe_for_pead(tickers, vol, lookback_days=pead_lookback)
        for es in pead_signals:
            try:
                sig = self._pead_to_trade_signal(es, vol, regime)
                if sig and self.validate_signal(sig):
                    signals.append(sig)
            except Exception:
                logger.exception("Failed to convert PEAD signal for %s", es.ticker)

        # Sub-Strategy B: Revision Momentum
        revision_signals = scan_universe_for_revisions(tickers, vol)
        for rs in revision_signals:
            if any(s.ticker == rs.ticker for s in signals):
                continue
            try:
                sig = self._revision_to_trade_signal(rs, vol, regime)
                if sig and self.validate_signal(sig):
                    signals.append(sig)
            except Exception:
                logger.exception("Failed to convert revision signal for %s", rs.ticker)

        # Sub-Strategy C: Institutional Flow (requires paid data)
        if settings.enable_smart_money and settings.uw_api_key:
            flow_signals = self._scan_flow_events(tickers, vol, regime)
            for sig in flow_signals:
                if any(s.ticker == sig.ticker for s in signals):
                    continue
                if self.validate_signal(sig):
                    signals.append(sig)

        logger.info(
            "Catalyst strategy generated %d signals (PEAD=%d, Revisions=%d)",
            len(signals),
            len(pead_signals),
            len(revision_signals),
        )
        return signals

    def _pead_to_trade_signal(
        self,
        es,
        vol: VolContext,
        regime: str,
    ) -> TradeSignal | None:
        """Convert an EarningsSignal into a TradeSignal."""
        params = self.get_params(vol)
        direction = "long" if es.surprise_pct > 0 else "short"

        price = data_fetcher.get_current_price(es.ticker)
        if price is None or price <= 0:
            return None

        atr = self._get_atr(es.ticker)
        stop_info = compute_stop(price, direction, atr, "catalyst", vol)

        if direction == "long":
            target = price * (1 + params["target_return_pct"] / 100)
        else:
            target = price * (1 - params["target_return_pct"] / 100)

        kelly = compute_adaptive_kelly(
            strategy="catalyst",
            vol=vol,
            regime=regime,
            trailing_trades=self.trailing_trades,
        )

        conviction = min(1.0, es.composite_score / 100)

        return TradeSignal(
            strategy=StrategyName.CATALYST,
            ticker=es.ticker,
            direction=direction,
            conviction=conviction,
            kelly_size_pct=kelly["kelly_fraction"] * 100,
            entry_price=price,
            stop_loss=stop_info["stop_price"],
            target=round(target, 2),
            max_hold_days=params["max_hold_days"],
            edge_reason=(
                f"PEAD: EPS surprise {es.surprise_pct:+.1f}%, "
                f"earnings day gap {es.earnings_day_gap_pct:+.1f}%, "
                f"revision trend {es.revision_trend_pre:+.2f}, "
                f"historical drift avg {es.historical_drift_avg:+.3f}"
            ),
            kill_condition=(
                f"Price reverses through stop ({stop_info['stop_price']:.2f}), "
                f"or guidance is revised down, "
                f"or drift exhausted before target"
            ),
            expected_sharpe=1.5,
            signal_score=es.composite_score,
        )

    def _revision_to_trade_signal(
        self,
        rs,
        vol: VolContext,
        regime: str,
    ) -> TradeSignal | None:
        """Convert a RevisionSignal into a TradeSignal."""
        params = self.get_params(vol)

        price = data_fetcher.get_current_price(rs.ticker)
        if price is None or price <= 0:
            return None

        direction = "long" if rs.breadth_30d > 0 else "short"
        atr = self._get_atr(rs.ticker)
        stop_info = compute_stop(price, direction, atr, "catalyst", vol)

        if direction == "long":
            target = price * (1 + params["target_return_pct"] / 100 * 0.7)
        else:
            target = price * (1 - params["target_return_pct"] / 100 * 0.7)

        kelly = compute_adaptive_kelly(
            strategy="catalyst",
            vol=vol,
            regime=regime,
            trailing_trades=self.trailing_trades,
        )

        # Revision signals get slightly lower sizing than PEAD
        kelly_frac = kelly["kelly_fraction"] * 0.7
        conviction = min(1.0, rs.composite_score / 100)

        return TradeSignal(
            strategy=StrategyName.CATALYST,
            ticker=rs.ticker,
            direction=direction,
            conviction=conviction,
            kelly_size_pct=kelly_frac * 100,
            entry_price=price,
            stop_loss=stop_info["stop_price"],
            target=round(target, 2),
            max_hold_days=min(params["max_hold_days"], 30),
            edge_reason=(
                f"Revision momentum: breadth {rs.breadth_30d:+.2f}, "
                f"acceleration {rs.acceleration_15d:+.2f}, "
                f"price only moved {rs.price_moved_pct:.1f}% (room to run)"
            ),
            kill_condition=(
                f"Price reverses through stop ({stop_info['stop_price']:.2f}), "
                f"or revision breadth turns negative, "
                f"or earnings report incoming within 5 days"
            ),
            expected_sharpe=1.3,
            signal_score=rs.composite_score,
        )

    def _scan_flow_events(
        self,
        tickers: list[str],
        vol: VolContext,
        regime: str,
    ) -> list[TradeSignal]:
        """Sub-Strategy C: institutional flow events.

        Requires enable_smart_money + uw_api_key. Stubbed interface
        for when paid data becomes available.
        """
        signals: list[TradeSignal] = []
        for ticker in tickers[:50]:
            try:
                flow = data_fetcher.get_options_flow(ticker)
                if not flow:
                    continue
                # Future: parse sweep data, check premium thresholds,
                # generate directional signals from institutional flow
            except Exception:
                logger.debug("Flow scan skipped for %s", ticker)
        return signals

    @staticmethod
    def _get_atr(ticker: str, period: int = 14) -> float:
        """Compute ATR for stop-loss calculation."""
        df = data_fetcher.get_daily_ohlcv(ticker, period="3mo")
        if df.empty or len(df) < period + 1:
            return float(df["Close"].std()) if not df.empty else 1.0

        high = df["High"].tail(period)
        low = df["Low"].tail(period)
        prev_close = df["Close"].shift(1).tail(period)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        return float(tr.mean())


catalyst_event_strategy = CatalystEventStrategy()
