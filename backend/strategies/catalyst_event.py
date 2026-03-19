"""Catalyst-Driven Event Trading Strategy.

Orchestrates four sub-strategies:
  A) Post-Earnings Announcement Drift (PEAD)
  B) Analyst Revision Momentum
  C) Institutional Flow Events (SteadyAPI sweeps, gated behind enable_steadyapi)
  D) Insider Buying Signal (SEC EDGAR Form 4, free)

Each sub-strategy uses adaptive parameters from get_catalyst_params().
"""

import logging
from concurrent.futures import ThreadPoolExecutor

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
            progress_cb: optional callback(done, total, step) for progress
            progress_total: total ticker count for progress reporting
        """
        tickers = kwargs.get("tickers")
        regime = kwargs.get("regime", "bull_trend")
        pead_lookback = kwargs.get("pead_lookback", 5)
        self._progress_cb = kwargs.get("progress_cb")
        self._progress_total = kwargs.get("progress_total", 0)

        if tickers is None:
            try:
                sp500 = fetch_sp500_constituents()
                tickers = sp500["ticker"].tolist()
            except Exception:
                logger.exception("Failed to fetch S&P 500, using empty ticker list")
                tickers = []

        total = self._progress_total or len(tickers)
        cb = self._progress_cb
        params = self.get_params(vol)
        kelly = compute_adaptive_kelly(
            strategy="catalyst", vol=vol, regime=regime,
            trailing_trades=self.trailing_trades,
        )
        kelly_frac = kelly["kelly_fraction"] * 0.6

        signals: list[TradeSignal] = []
        seen: set[str] = set()

        # For small ticker lists (e.g. single-stock analysis), scan them
        # directly. Only use the AI ticker picker for full scanner scans.
        if len(tickers) <= 50:
            scan_tickers = tickers
        else:
            if cb:
                cb(int(total * 0.02), total, "AI selecting the most interesting stocks to scan...")

            from backend.ai.market_ai import ai_pick_scan_tickers
            from backend.regime.detector import detect_regime

            vix_val = 0.0
            breadth_val = 0.0
            try:
                vix_df = data_fetcher.get_daily_ohlcv("^VIX", period="3mo", live=True)
                spy_df = data_fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
                if not vix_df.empty:
                    vix_val = float(vix_df["Close"].iloc[-1])
                regime_result = detect_regime(vix_df, spy_df)
                regime_str = regime_result.get("regime", regime)
                if hasattr(regime_str, "value"):
                    regime_str = regime_str.value
                breadth_val = regime_result.get("breadth_pct", 0)
            except Exception:
                regime_str = regime

            ai_picks = ai_pick_scan_tickers(regime_str, tickers, vix=vix_val, breadth_pct=breadth_val)

            if ai_picks:
                scan_tickers = ai_picks
            else:
                step = len(tickers) / 50
                scan_tickers = [tickers[int(i * step)] for i in range(50)]

        n_scan = len(scan_tickers)

        if cb:
            cb(int(total * 0.10), total,
               f"Scanning {n_scan} AI-selected stocks for insider buying and catalysts...")

        done_count = [0]

        def _scan_one(ticker: str) -> list[TradeSignal]:
            """Check one ticker for all catalyst types: earnings, revisions, insider buying."""
            results: list[TradeSignal] = []

            # 1) Earnings surprise (PEAD)
            try:
                from backend.signals.earnings import detect_pead
                es = detect_pead(ticker, vol, pead_lookback)
                if es is not None:
                    sig = self._pead_to_trade_signal(es, vol, regime)
                    if sig and self.validate_signal(sig):
                        results.append(sig)
            except Exception:
                pass

            # 2) Analyst revision momentum
            if not results:
                try:
                    from backend.signals.revisions import detect_revision_momentum
                    rs = detect_revision_momentum(ticker, vol)
                    if rs is not None:
                        sig = self._revision_to_trade_signal(rs, vol, regime)
                        if sig and self.validate_signal(sig):
                            results.append(sig)
                except Exception:
                    pass

            # 3) Insider buying (SEC EDGAR)
            if not results:
                try:
                    score_data = data_fetcher.get_insider_buying_score(ticker)
                    score = score_data.get("signal_score", 0)
                    if score >= 30 and score_data.get("buy_count", 0) > 0:
                        df = data_fetcher.get_daily_ohlcv(ticker, period="3mo")
                        if not df.empty and len(df) >= 15:
                            price = float(df["Close"].iloc[-1])
                            if price > 0:
                                high = df["High"].tail(14)
                                low = df["Low"].tail(14)
                                prev_close = df["Close"].shift(1).tail(14)
                                tr = pd.concat([
                                    high - low, (high - prev_close).abs(),
                                    (low - prev_close).abs()
                                ], axis=1).max(axis=1)
                                atr = float(tr.mean())
                                stop_price = round(max(0.01, price - atr * 2), 2)
                                target_price = round(price + atr * 3, 2)
                                conviction = min(1.0, score / 100)
                                buy_count = score_data["buy_count"]
                                buy_val = score_data.get("total_buy_value", 0)
                                if buy_val >= 1_000_000:
                                    val_str = f"${buy_val / 1_000_000:.1f}M"
                                elif buy_val >= 1_000:
                                    val_str = f"${buy_val / 1_000:.0f}K"
                                else:
                                    val_str = f"${buy_val:,.0f}"
                                edge_parts = [
                                    f"{buy_count} company insider(s) bought {val_str} worth of stock"
                                ]
                                if score_data.get("cluster_buy"):
                                    edge_parts.append(
                                        "multiple insiders bought around the same time — "
                                        "they usually know something the market doesn't"
                                    )
                                if score_data.get("c_suite_buying"):
                                    edge_parts.append(
                                        "the CEO or CFO is buying — the people running the "
                                        "company are putting their own money in"
                                    )
                                results.append(TradeSignal(
                                    strategy=StrategyName.CATALYST, ticker=ticker,
                                    direction="long", conviction=conviction,
                                    kelly_size_pct=kelly_frac * 100, entry_price=price,
                                    stop_loss=stop_price,
                                    target=target_price, max_hold_days=365,
                                    edge_reason=". ".join(edge_parts) + ".",
                                    kill_condition=f"Insider sells appear, or if it drops below ${stop_price:.2f} (2x ATR stop), re-evaluate",
                                    expected_sharpe=1.2, signal_score=min(100, score),
                                ))
                except Exception:
                    pass

            done_count[0] += 1
            if cb:
                pct = done_count[0] / n_scan
                cb(int(total * (0.05 + pct * 0.90)), total,
                   f"Checking stocks... {done_count[0]}/{n_scan}")

            return results

        with ThreadPoolExecutor(max_workers=10) as pool:
            for ticker_results in pool.map(_scan_one, scan_tickers):
                for sig in ticker_results:
                    if sig.ticker not in seen:
                        seen.add(sig.ticker)
                        signals.append(sig)

        # Institutional Flow (single API call, not per-ticker)
        if settings.enable_steadyapi and settings.steadyapi_api_key:
            for sig in self._scan_flow_events(tickers, vol, regime):
                if sig.ticker not in seen and self.validate_signal(sig):
                    seen.add(sig.ticker)
                    signals.append(sig)

        logger.info(
            "Catalyst strategy generated %d signals from %d tickers",
            len(signals),
            n_scan,
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
