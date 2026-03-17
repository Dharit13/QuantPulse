"""Statistical Arbitrage — Pairs & Basket Trading.

Finds cointegrated pairs within GICS sub-industries and trades
mean-reversion of spreads using adaptive z-score thresholds.
"""

import logging
from itertools import combinations

import pandas as pd

from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.pair_params import calibrate_pair_params
from backend.adaptive.stops import compute_stop
from backend.adaptive.thresholds import get_stat_arb_params
from backend.adaptive.vol_context import VolContext
from backend.data.fetcher import data_fetcher
from backend.data.universe import get_sub_industry_groups
from backend.models.schemas import StrategyName, TradeSignal
from backend.signals.cointegration import (
    compute_half_life,
    compute_hurst_exponent,
    compute_spread,
    compute_zscore,
    validate_pair,
)
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class StatArbStrategy(BaseStrategy):
    """Statistical arbitrage pairs trading strategy."""

    def __init__(self):
        self.active_pairs: list[dict] = []
        self.trailing_trades: list[dict] = []

    @property
    def name(self) -> str:
        return StrategyName.STAT_ARB.value

    def get_params(self, vol: VolContext) -> dict:
        return get_stat_arb_params(vol)

    def find_pairs(
        self,
        vol: VolContext,
        max_pairs_per_industry: int = 5,
        period: str = "2y",
    ) -> list[dict]:
        """Scan universe for cointegrated pairs within GICS sub-industries."""
        params = self.get_params(vol)
        groups = get_sub_industry_groups()
        valid_pairs = []

        for sub_industry, tickers in groups.items():
            if len(tickers) < 2:
                continue

            price_data = data_fetcher.get_multiple_ohlcv(tickers, period=period)

            pairs_found = 0
            for t1, t2 in combinations(tickers, 2):
                if pairs_found >= max_pairs_per_industry:
                    break

                s1 = price_data.get(t1)
                s2 = price_data.get(t2)
                if s1 is None or s2 is None or s1.empty or s2.empty:
                    continue

                result = validate_pair(
                    s1["Close"],
                    s2["Close"],
                    min_adf_pvalue=params["min_adf_pvalue"],
                    min_half_life=params["min_half_life_days"],
                    max_half_life=params["max_half_life_days"],
                )

                if result["is_valid"]:
                    spread = compute_spread(s1["Close"], s2["Close"])
                    valid_pairs.append({
                        "ticker_a": t1,
                        "ticker_b": t2,
                        "sub_industry": sub_industry,
                        "half_life": result["half_life"],
                        "hurst": result["hurst_exponent"],
                        "adf_pvalue": result["adf"]["pvalue"],
                        "eg_pvalue": result["engle_granger"]["pvalue"],
                        "spread_mean": result["spread_stats"]["mean"],
                        "spread_std": result["spread_stats"]["std"],
                    })
                    pairs_found += 1

            logger.info("Sub-industry %s: found %d pairs from %d tickers", sub_industry, pairs_found, len(tickers))

        self.active_pairs = valid_pairs
        logger.info("Total valid pairs found: %d", len(valid_pairs))
        return valid_pairs

    def generate_signals(self, vol: VolContext, **kwargs) -> list[TradeSignal]:
        """Generate trade signals for all active pairs."""
        params = self.get_params(vol)
        signals = []

        for pair in self.active_pairs:
            try:
                signal = self._evaluate_pair(pair, vol, params)
                if signal and self.validate_signal(signal):
                    signals.append(signal)
            except Exception:
                logger.exception("Error evaluating pair %s/%s", pair["ticker_a"], pair["ticker_b"])

        return signals

    def _evaluate_pair(
        self,
        pair: dict,
        vol: VolContext,
        params: dict,
    ) -> TradeSignal | None:
        """Evaluate a single pair for entry/exit signals."""
        t1, t2 = pair["ticker_a"], pair["ticker_b"]
        s1 = data_fetcher.get_daily_ohlcv(t1, period="6mo")
        s2 = data_fetcher.get_daily_ohlcv(t2, period="6mo")

        if s1.empty or s2.empty:
            return None

        spread = compute_spread(s1["Close"], s2["Close"])
        zscore = compute_zscore(spread)

        if zscore.empty:
            return None

        current_z = float(zscore.iloc[-1])

        # Calibrate per-pair parameters
        pair_params = calibrate_pair_params(
            spread_series=spread,
            half_life=pair["half_life"],
            spread_vol=pair["spread_std"],
            vol=vol,
        )

        entry_z = pair_params["entry_z"]
        stop_z = pair_params["stop_z"]

        if abs(current_z) < entry_z:
            return None

        if current_z > entry_z:
            # Spread too wide: short A (outperformer), long B (underperformer)
            direction = "short"
            ticker = t1
            entry_price = float(s1["Close"].iloc[-1])
        else:
            # Spread too narrow: long A, short B
            direction = "long"
            ticker = t1
            entry_price = float(s1["Close"].iloc[-1])

        # ATR for stop computation
        atr = self._compute_atr(s1)
        stop_info = compute_stop(entry_price, direction, atr, "stat_arb", vol)

        kelly = compute_adaptive_kelly(
            strategy="stat_arb",
            vol=vol,
            regime=kwargs.get("regime", "bull_choppy") if "kwargs" in dir() else "bull_choppy",
            trailing_trades=self.trailing_trades,
        )

        conviction = min(1.0, abs(current_z) / stop_z)

        return TradeSignal(
            strategy=StrategyName.STAT_ARB,
            ticker=ticker,
            direction=direction,
            conviction=conviction,
            kelly_size_pct=kelly["kelly_fraction"] * 100,
            entry_price=entry_price,
            stop_loss=stop_info["stop_price"],
            target=entry_price * (1.05 if direction == "long" else 0.95),
            max_hold_days=pair_params["max_hold_days"],
            edge_reason=(
                f"Pair {t1}/{t2} spread at {current_z:.1f}σ divergence. "
                f"Cointegrated (ADF p={pair['adf_pvalue']:.4f}), "
                f"half-life={pair['half_life']:.1f}d, Hurst={pair['hurst']:.2f}"
            ),
            kill_condition=(
                f"Spread exceeds {stop_z:.1f}σ (cointegration breaking) "
                f"or Hurst > 0.5 on revalidation"
            ),
            expected_sharpe=1.5,
            signal_score=min(100, conviction * 100),
        )

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Compute ATR for a stock."""
        if len(df) < period + 1:
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


stat_arb_strategy = StatArbStrategy()
