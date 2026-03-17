"""Catalyst-Driven Event Trading Strategy.

Orchestrates four sub-strategies:
  A) Post-Earnings Announcement Drift (PEAD)
  B) Analyst Revision Momentum
  C) Institutional Flow Events (SteadyAPI sweeps, gated behind enable_steadyapi)
  D) Insider Buying Signal (SEC EDGAR Form 4, free)

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

        # Sub-Strategy C: Institutional Flow (SteadyAPI sweeps)
        if settings.enable_steadyapi and settings.steadyapi_api_key:
            flow_signals = self._scan_flow_events(tickers, vol, regime)
            for sig in flow_signals:
                if any(s.ticker == sig.ticker for s in signals):
                    continue
                if self.validate_signal(sig):
                    signals.append(sig)

        # Sub-Strategy D: Insider Buying (SEC EDGAR Form 4, free)
        insider_signals = self._scan_insider_buying(tickers[:50], vol, regime)
        for sig in insider_signals:
            if any(s.ticker == sig.ticker for s in signals):
                continue
            if self.validate_signal(sig):
                signals.append(sig)

        logger.info(
            "Catalyst strategy generated %d signals (PEAD=%d, Revisions=%d, Insider=%d)",
            len(signals),
            len(pead_signals),
            len(revision_signals),
            len(insider_signals),
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
        """Sub-Strategy C: institutional flow from SteadyAPI sweeps.

        Detects large call/put sweeps (>$500K premium) from SteadyAPI
        and generates directional signals for swing trading.
        """
        signals: list[TradeSignal] = []

        sweeps = data_fetcher.get_steadyapi_sweeps()
        if not sweeps:
            return signals

        ticker_set = set(t.upper() for t in tickers)
        params = self.get_params(vol)

        # Aggregate sweeps by ticker
        ticker_premium: dict[str, dict] = {}
        for sweep in sweeps:
            sym = sweep.get("symbol", "")
            if sym not in ticker_set:
                continue
            if sym not in ticker_premium:
                ticker_premium[sym] = {"call": 0.0, "put": 0.0, "count": 0}

            premium = sweep.get("premium", 0)
            if sweep.get("option_type") == "Call":
                ticker_premium[sym]["call"] += premium
            else:
                ticker_premium[sym]["put"] += premium
            ticker_premium[sym]["count"] += 1

        for ticker, flow in ticker_premium.items():
            total = flow["call"] + flow["put"]
            if total < 500_000:
                continue

            if flow["call"] > flow["put"] * 2:
                direction = "long"
            elif flow["put"] > flow["call"] * 2:
                direction = "short"
            else:
                continue

            price = data_fetcher.get_current_price(ticker)
            if price is None or price <= 0:
                continue

            atr = self._get_atr(ticker)
            stop_info = compute_stop(price, direction, atr, "catalyst", vol)

            target_mult = 1 + params["target_return_pct"] / 100
            target = price * target_mult if direction == "long" else price / target_mult

            kelly = compute_adaptive_kelly(
                strategy="catalyst", vol=vol, regime=regime,
                trailing_trades=self.trailing_trades,
            )
            conviction = min(1.0, total / 2_000_000 + flow["count"] / 10)

            signals.append(TradeSignal(
                strategy=StrategyName.CATALYST,
                ticker=ticker,
                direction=direction,
                conviction=conviction,
                kelly_size_pct=kelly["kelly_fraction"] * 0.8 * 100,
                entry_price=price,
                stop_loss=stop_info["stop_price"],
                target=round(target, 2),
                max_hold_days=params["max_hold_days"],
                edge_reason=(
                    f"Institutional sweep flow: {flow['count']} sweeps, "
                    f"${total:,.0f} total premium "
                    f"(call=${flow['call']:,.0f} / put=${flow['put']:,.0f}). "
                    f"Sweeps = urgency."
                ),
                kill_condition=(
                    f"Flow reverses or stop at {stop_info['stop_price']:.2f}"
                ),
                expected_sharpe=1.4,
                signal_score=min(100, conviction * 100),
            ))

        return signals

    def _scan_insider_buying(
        self,
        tickers: list[str],
        vol: VolContext,
        regime: str,
    ) -> list[TradeSignal]:
        """Sub-Strategy D: insider buying signal from SEC EDGAR Form 4.

        CEO/CFO/director buying own stock is a strong conviction signal.
        Cluster buys (2+ insiders in 30 days) are even stronger.
        Hold 5-20 days.
        """
        signals: list[TradeSignal] = []
        params = self.get_params(vol)

        for ticker in tickers:
            try:
                score_data = data_fetcher.get_insider_buying_score(ticker)
                score = score_data.get("signal_score", 0)

                if score < 30:
                    continue

                if score_data.get("buy_count", 0) == 0:
                    continue

                price = data_fetcher.get_current_price(ticker)
                if price is None or price <= 0:
                    continue

                direction = "long"
                atr = self._get_atr(ticker)
                stop_info = compute_stop(price, direction, atr, "catalyst", vol)

                target_mult = 1 + params["target_return_pct"] / 100 * 0.8
                target = price * target_mult

                kelly = compute_adaptive_kelly(
                    strategy="catalyst", vol=vol, regime=regime,
                    trailing_trades=self.trailing_trades,
                )
                # Insider signals get conservative sizing
                kelly_frac = kelly["kelly_fraction"] * 0.6
                conviction = min(1.0, score / 100)

                edge_parts = [
                    f"Insider buying: {score_data['buy_count']} buy(s), "
                    f"${score_data.get('total_buy_value', 0):,.0f} total value"
                ]
                if score_data.get("cluster_buy"):
                    edge_parts.append("cluster buy (2+ insiders in 30d)")
                if score_data.get("c_suite_buying"):
                    edge_parts.append("C-suite buying (CEO/CFO)")

                signals.append(TradeSignal(
                    strategy=StrategyName.CATALYST,
                    ticker=ticker,
                    direction=direction,
                    conviction=conviction,
                    kelly_size_pct=kelly_frac * 100,
                    entry_price=price,
                    stop_loss=stop_info["stop_price"],
                    target=round(target, 2),
                    max_hold_days=20,
                    edge_reason=". ".join(edge_parts) + ". Insiders have non-public conviction.",
                    kill_condition=(
                        f"Insider sells appear, or stop at {stop_info['stop_price']:.2f}, "
                        f"or 20d time stop"
                    ),
                    expected_sharpe=1.2,
                    signal_score=min(100, score),
                ))
            except Exception:
                logger.debug("Insider scan failed for %s", ticker)

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
