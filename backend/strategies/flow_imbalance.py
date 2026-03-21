"""Flow Imbalance Strategy — simplified for swing trading ($15/mo stack).

Rewritten for swing trading (3-10 day hold) using:
  A) SteadyAPI Options Flow — follow large institutional sweeps/blocks ($15/mo)
  B) FINRA ATS Dark Pool — detect institutional accumulation from delayed volume data (free)

Skipped (day-trading only):
  - GEX/gamma pinning (intraday phenomenon, needs real-time options chain greeks)
  - Real-time dark pool prints (needs Unusual Whales $50/mo)

Position sizing: 2-4% per trade, max 10% total flow exposure.
Expected hold: 3-10 days.

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
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

MAX_STRATEGY_EXPOSURE_PCT = 0.10
MAX_POSITION_PCT = 0.04
MAX_SIGNALS_PER_SCAN = 8

MIN_SWEEP_PREMIUM = 500_000
MIN_DARK_POOL_SCORE = 40.0


class FlowImbalanceStrategy(BaseStrategy):
    """Institutional flow imbalance trading strategy (swing-optimized).

    Uses SteadyAPI options flow ($15/mo) and free FINRA dark pool data
    instead of Polygon GEX and Unusual Whales.
    """

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
        """Generate trade signals from institutional flow analysis.

        kwargs:
            tickers: optional list[str] to scan (defaults to S&P 500 top-100)
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

        # Sub-Strategy A: SteadyAPI institutional sweep detection
        sweep_signals = self._generate_sweep_signals(tickers, vol, regime, params)
        for sig in sweep_signals:
            if cumulative_exposure >= MAX_STRATEGY_EXPOSURE_PCT:
                break
            if self.validate_signal(sig):
                signals.append(sig)
                cumulative_exposure += sig.kelly_size_pct / 100

        # Sub-Strategy B: FINRA dark pool accumulation
        dp_tickers = [t for t in tickers[:50] if not any(s.ticker == t for s in signals)]
        dp_signals = self._generate_dark_pool_signals(dp_tickers, vol, regime, params)
        for sig in dp_signals:
            if cumulative_exposure >= MAX_STRATEGY_EXPOSURE_PCT:
                break
            if self.validate_signal(sig):
                signals.append(sig)
                cumulative_exposure += sig.kelly_size_pct / 100

        signals.sort(key=lambda s: s.conviction, reverse=True)
        signals = signals[:MAX_SIGNALS_PER_SCAN]

        logger.info("Flow imbalance strategy generated %d signals", len(signals))
        return signals

    # ── Sub-Strategy A: SteadyAPI Institutional Sweeps ────────────────────

    def _generate_sweep_signals(
        self,
        tickers: list[str],
        vol: VolContext,
        regime: str,
        params: dict,
    ) -> list[TradeSignal]:
        """Detect institutional sweep orders via SteadyAPI and generate signals.

        Sweeps hit multiple exchanges simultaneously, indicating urgency.
        Combined with BuyToOpen label, this is a strong directional bet.
        """
        if not settings.enable_steadyapi or not settings.steadyapi_api_key:
            return []

        sweeps = data_fetcher.get_steadyapi_sweeps()
        if not sweeps:
            return []

        ticker_set = set(t.upper() for t in tickers)
        trade_signals: list[TradeSignal] = []

        # Group sweeps by ticker and compute net directional flow
        ticker_flow: dict[str, dict] = {}
        for sweep in sweeps:
            sym = sweep.get("symbol", "")
            if sym not in ticker_set:
                continue

            premium = sweep.get("premium", 0)
            if premium < MIN_SWEEP_PREMIUM:
                continue

            if sym not in ticker_flow:
                ticker_flow[sym] = {
                    "call_premium": 0.0,
                    "put_premium": 0.0,
                    "sweep_count": 0,
                    "top_sweeps": [],
                }
            entry = ticker_flow[sym]
            entry["sweep_count"] += 1

            if sweep.get("option_type") == "Call":
                entry["call_premium"] += premium
            else:
                entry["put_premium"] += premium

            entry["top_sweeps"].append(sweep)

        for ticker, flow in ticker_flow.items():
            flow["call_premium"] - flow["put_premium"]
            total_premium = flow["call_premium"] + flow["put_premium"]

            if total_premium < MIN_SWEEP_PREMIUM:
                continue

            # Determine direction from premium skew
            if flow["call_premium"] > flow["put_premium"] * 2:
                direction = "long"
            elif flow["put_premium"] > flow["call_premium"] * 2:
                direction = "short"
            else:
                continue  # skip ambiguous flow

            spot = data_fetcher.get_current_price(ticker)
            if spot is None or spot <= 0:
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

            if direction == "long":
                target = spot + stop_info["stop_distance_dollars"] * 2.5
            else:
                target = spot - stop_info["stop_distance_dollars"] * 2.5

            conviction = min(1.0, total_premium / 2_000_000 + flow["sweep_count"] / 10)

            # Build edge description from top sweep
            top_sweep = max(flow["top_sweeps"], key=lambda s: s.get("premium", 0))
            sweep_desc = (
                f"${top_sweep.get('premium', 0):,.0f} {top_sweep.get('option_type', '')} "
                f"sweep at ${top_sweep.get('strike', 0):.0f} "
                f"({top_sweep.get('dte', 0)}d DTE)"
            )

            signal = TradeSignal(
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
                    f"Institutional sweep flow: {flow['sweep_count']} sweeps, "
                    f"${total_premium:,.0f} total premium "
                    f"(call=${flow['call_premium']:,.0f} / put=${flow['put_premium']:,.0f}). "
                    f"Top: {sweep_desc}. "
                    f"Sweeps indicate urgency — institutional directional bet."
                ),
                kill_condition=(
                    f"Flow reverses direction (puts overtake calls or vice versa), "
                    f"or stop hit at {stop_info['stop_price']:.2f}, "
                    f"or {params['max_hold_days']}d time stop"
                ),
                expected_sharpe=1.4,
                signal_score=min(100, conviction * 100),
            )

            if self.validate_signal(signal):
                trade_signals.append(signal)

        return trade_signals

    # ── Sub-Strategy B: FINRA Dark Pool Accumulation ──────────────────────

    def _generate_dark_pool_signals(
        self,
        tickers: list[str],
        vol: VolContext,
        regime: str,
        params: dict,
    ) -> list[TradeSignal]:
        """Detect institutional accumulation from FINRA ATS dark pool data.

        Stocks with persistently rising dark pool volume suggest institutional
        buying not visible on lit exchanges — a swing-timeframe signal.
        """
        trade_signals: list[TradeSignal] = []

        for ticker in tickers:
            try:
                metrics = data_fetcher.get_dark_pool_activity(ticker)
                if metrics.get("signal_score", 0) < MIN_DARK_POOL_SCORE:
                    continue

                spot = data_fetcher.get_current_price(ticker)
                if spot is None or spot <= 0:
                    continue

                direction = "long"  # dark pool accumulation is a buy signal
                atr = self._get_atr(ticker)
                stop_info = compute_stop(spot, direction, atr, "flow", vol)

                kelly = compute_adaptive_kelly(
                    strategy="flow",
                    vol=vol,
                    regime=regime,
                    trailing_trades=self.trailing_trades,
                )
                # Dark pool signals get conservative sizing (delayed data)
                position_pct = min(kelly["kelly_fraction"] * 0.7, MAX_POSITION_PCT * vol.position_scale)
                target = spot + stop_info["stop_distance_dollars"] * 2.0

                zscore = metrics.get("volume_zscore", 0)
                weeks_inc = metrics.get("weeks_increasing", 0)
                conviction = min(1.0, metrics["signal_score"] / 100)

                signal = TradeSignal(
                    strategy=StrategyName.FLOW,
                    ticker=ticker,
                    direction=direction,
                    conviction=conviction,
                    kelly_size_pct=position_pct * 100,
                    entry_price=spot,
                    stop_loss=stop_info["stop_price"],
                    target=round(target, 2),
                    max_hold_days=min(params["max_hold_days"], 15),
                    edge_reason=(
                        f"Dark pool accumulation: volume z-score={zscore:.1f}, "
                        f"{weeks_inc} consecutive weeks increasing, "
                        f"avg weekly ATS volume={metrics.get('avg_weekly_volume', 0):,}. "
                        f"Institutional buying not visible on lit exchanges."
                    ),
                    kill_condition=(
                        f"Dark pool volume drops below 1σ (z<1.0), "
                        f"or stop hit at {stop_info['stop_price']:.2f}, "
                        f"or price breaks below 20-day SMA"
                    ),
                    expected_sharpe=1.1,
                    signal_score=min(100, conviction * 100),
                )

                if self.validate_signal(signal):
                    trade_signals.append(signal)
            except Exception:
                logger.debug("Dark pool signal failed for %s", ticker)

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
