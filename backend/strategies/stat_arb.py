"""Statistical Arbitrage — Pairs & Basket Trading.

Finds cointegrated pairs within GICS sub-industries and trades
mean-reversion of spreads using adaptive z-score thresholds.
"""

import logging
from itertools import combinations

import numpy as np
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
    compute_hurst_exponent,
    compute_spread,
    compute_zscore,
    validate_pair,
)
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

MIN_CORRELATION_252D = 0.70
MIN_AVG_DOLLAR_VOLUME = 5_000_000
SHARPE_PAUSE_THRESHOLD = 0.5
HURST_DECAY_THRESHOLD = 0.5


class StatArbStrategy(BaseStrategy):
    """Statistical arbitrage pairs trading strategy."""

    def __init__(self):
        self.active_pairs: list[dict] = []
        self.trailing_trades: list[dict] = []
        self.paused_pairs: dict[str, int] = {}  # "t1/t2" -> days remaining

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

                # Liquidity filter: both legs must have avg dollar volume >= $5M
                if not self._passes_liquidity_filter(s1) or not self._passes_liquidity_filter(s2):
                    continue

                # Correlation filter: rolling 252-day correlation must exceed 0.70
                corr = self._compute_rolling_correlation(s1["Close"], s2["Close"])
                if corr < MIN_CORRELATION_252D:
                    continue

                result = validate_pair(
                    s1["Close"],
                    s2["Close"],
                    min_adf_pvalue=params["min_adf_pvalue"],
                    min_half_life=params["min_half_life_days"],
                    max_half_life=params["max_half_life_days"],
                )

                if result["is_valid"]:
                    compute_spread(s1["Close"], s2["Close"])
                    valid_pairs.append(
                        {
                            "ticker_a": t1,
                            "ticker_b": t2,
                            "sub_industry": sub_industry,
                            "half_life": result["half_life"],
                            "hurst": result["hurst_exponent"],
                            "adf_pvalue": result["adf"]["pvalue"],
                            "eg_pvalue": result["engle_granger"]["pvalue"],
                            "johansen_cointegrated": result["johansen"]["is_cointegrated"],
                            "tests_passed": result["tests_passed"],
                            "correlation_252d": corr,
                            "spread_mean": result["spread_stats"]["mean"],
                            "spread_std": result["spread_stats"]["std"],
                        }
                    )
                    pairs_found += 1

            logger.info("Sub-industry %s: found %d pairs from %d tickers", sub_industry, pairs_found, len(tickers))

        self.active_pairs = valid_pairs
        logger.info("Total valid pairs found: %d", len(valid_pairs))
        return valid_pairs

    def generate_signals(self, vol: VolContext, **kwargs) -> list[TradeSignal]:
        """Generate trade signals for all active pairs."""
        params = self.get_params(vol)
        regime = kwargs.get("regime", "bull_choppy")
        signals = []

        for pair in self.active_pairs:
            try:
                signal = self._evaluate_pair(pair, vol, params, regime=regime)
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
        regime: str = "bull_choppy",
    ) -> TradeSignal | None:
        """Evaluate a single pair for entry/exit signals."""
        t1, t2 = pair["ticker_a"], pair["ticker_b"]
        pair_key = f"{t1}/{t2}"

        # Sharpe-based pause: skip pairs that have been paused
        if pair_key in self.paused_pairs:
            if self.paused_pairs[pair_key] > 0:
                self.paused_pairs[pair_key] -= 1
                return None
            del self.paused_pairs[pair_key]

        s1 = data_fetcher.get_daily_ohlcv(t1, period="6mo")
        s2 = data_fetcher.get_daily_ohlcv(t2, period="6mo")

        if s1.empty or s2.empty:
            return None

        spread = compute_spread(s1["Close"], s2["Close"])

        # Edge decay monitor: rolling 60-day Hurst exponent
        recent_spread = spread.tail(120)
        current_hurst = compute_hurst_exponent(recent_spread)
        if current_hurst >= HURST_DECAY_THRESHOLD:
            logger.info(
                "Pair %s/%s skipped: Hurst=%.2f (>= %.2f, trending)",
                t1,
                t2,
                current_hurst,
                HURST_DECAY_THRESHOLD,
            )
            return None

        # Check trailing 60-day Sharpe for this pair
        pair_sharpe = self._compute_pair_sharpe(spread, window=60)
        if pair_sharpe < SHARPE_PAUSE_THRESHOLD:
            logger.info(
                "Pair %s/%s paused: 60d Sharpe=%.2f < %.2f",
                t1,
                t2,
                pair_sharpe,
                SHARPE_PAUSE_THRESHOLD,
            )
            self.paused_pairs[pair_key] = 5
            return None

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
            regime=regime,
            trailing_trades=self.trailing_trades,
        )

        conviction = min(1.0, abs(current_z) / stop_z)

        # Target: price corresponding to exit z-score (|z| < exit_z = spread normalized)
        exit_z = pair_params["exit_z"]
        spread_mean = pair["spread_mean"]
        spread_std = pair["spread_std"]
        if current_z > 0:
            target_spread = spread_mean + exit_z * spread_std
        else:
            target_spread = spread_mean - exit_z * spread_std
        # Translate spread target back to price of ticker A
        price_b = float(s2["Close"].iloc[-1])
        target = round(target_spread * price_b, 2)

        return TradeSignal(
            strategy=StrategyName.STAT_ARB,
            ticker=ticker,
            direction=direction,
            conviction=conviction,
            kelly_size_pct=kelly["kelly_fraction"] * 100,
            entry_price=entry_price,
            stop_loss=stop_info["stop_price"],
            target=target,
            max_hold_days=pair_params["max_hold_days"],
            edge_reason=(
                f"Pair {t1}/{t2} spread at {current_z:.1f}σ divergence. "
                f"Cointegrated (ADF p={pair['adf_pvalue']:.4f}), "
                f"half-life={pair['half_life']:.1f}d, Hurst={pair['hurst']:.2f}. "
                f"Exit when |z| < {exit_z:.2f} (spread normalizes)"
            ),
            kill_condition=(f"Spread exceeds {stop_z:.1f}σ (cointegration breaking) or Hurst > 0.5 on revalidation"),
            expected_sharpe=1.5,
            signal_score=min(100, conviction * 100),
        )

    @staticmethod
    def _passes_liquidity_filter(df: pd.DataFrame) -> bool:
        """Both legs must have avg dollar volume >= $5M."""
        if df.empty or "Volume" not in df.columns or "Close" not in df.columns:
            return False
        avg_dollar_vol = (df["Close"] * df["Volume"]).tail(20).mean()
        return float(avg_dollar_vol) >= MIN_AVG_DOLLAR_VOLUME

    @staticmethod
    def _compute_rolling_correlation(
        series_a: pd.Series,
        series_b: pd.Series,
        window: int = 252,
    ) -> float:
        """Compute trailing rolling correlation between two price series."""
        common = series_a.index.intersection(series_b.index)
        if len(common) < window:
            return 0.0
        a = series_a.loc[common].tail(window)
        b = series_b.loc[common].tail(window)
        corr = float(a.corr(b))
        return corr if np.isfinite(corr) else 0.0

    @staticmethod
    def _compute_pair_sharpe(spread: pd.Series, window: int = 60) -> float:
        """Compute trailing Sharpe ratio of the spread's returns."""
        if len(spread) < window + 1:
            return 1.0  # default to acceptable when insufficient data
        returns = spread.pct_change().dropna().tail(window)
        if returns.empty or returns.std() == 0:
            return 0.0
        return float(returns.mean() / returns.std() * np.sqrt(252))

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Compute ATR for a stock."""
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


stat_arb_strategy = StatArbStrategy()
