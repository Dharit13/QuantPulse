#!/usr/bin/env python3
"""Backtest regime detection accuracy against historical data.

Tests how well the regime detector would have classified past market
conditions by running it on rolling windows of historical data.

Usage:
    python -m scripts.regime_backtest [--years 5] [--window 252]
"""

import argparse
import logging
import sys
from datetime import datetime

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest regime detection")
    parser.add_argument("--years", type=int, default=5, help="Years of history to test")
    parser.add_argument("--window", type=int, default=252, help="Rolling window size (trading days)")
    args = parser.parse_args()

    from backend.data.fetcher import DataFetcher
    from backend.regime.detector import detect_regime

    fetcher = DataFetcher()
    period = f"{args.years}y"

    logger.info("Fetching %s of data for VIX and SPY...", period)
    vix_df = fetcher.get_daily_ohlcv("^VIX", period=period)
    spy_df = fetcher.get_daily_ohlcv("SPY", period=period)

    if vix_df.empty or spy_df.empty:
        logger.error("Failed to fetch data")
        sys.exit(1)

    logger.info("VIX: %d days, SPY: %d days", len(vix_df), len(spy_df))

    min_len = min(len(vix_df), len(spy_df))
    vix_df = vix_df.iloc[-min_len:]
    spy_df = spy_df.iloc[-min_len:]

    results: list[dict] = []
    test_start = args.window

    logger.info("Running regime detection on %d rolling windows...", min_len - test_start)

    for i in range(test_start, min_len, 5):
        vix_window = vix_df.iloc[max(0, i - args.window):i]
        spy_window = spy_df.iloc[max(0, i - args.window):i]

        try:
            result = detect_regime(vix_window, spy_window)
            spy_close = float(spy_window["Close"].iloc[-1])
            vix_close = float(vix_window["Close"].iloc[-1])

            date_idx = spy_window.index[-1]
            date_str = date_idx.strftime("%Y-%m-%d") if hasattr(date_idx, "strftime") else str(date_idx)

            spy_ret_20d = 0.0
            if i + 20 < min_len:
                future_price = float(spy_df["Close"].iloc[i + 20])
                spy_ret_20d = (future_price - spy_close) / spy_close

            results.append({
                "date": date_str,
                "regime": result["regime"].value,
                "confidence": result["confidence"],
                "vix": vix_close,
                "spy": spy_close,
                "spy_20d_fwd_return": round(spy_ret_20d * 100, 2),
            })
        except Exception as e:
            logger.debug("Error at index %d: %s", i, e)

    if not results:
        logger.error("No results generated")
        sys.exit(1)

    df = pd.DataFrame(results)

    print("\n" + "=" * 70)
    print("  REGIME DETECTION BACKTEST")
    print("=" * 70)

    regime_stats = df.groupby("regime").agg(
        count=("regime", "count"),
        avg_confidence=("confidence", "mean"),
        avg_vix=("vix", "mean"),
        avg_20d_fwd=("spy_20d_fwd_return", "mean"),
        median_20d_fwd=("spy_20d_fwd_return", "median"),
    ).round(2)

    print("\nPer-Regime Statistics:")
    print(regime_stats.to_string())

    print(f"\nTotal observations: {len(df)}")
    print(f"Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
    print(f"Regime distribution:")
    for regime, count in df["regime"].value_counts().items():
        pct = count / len(df) * 100
        print(f"  {regime:20s}: {count:4d} ({pct:.1f}%)")

    # Validate: bull regimes should have positive forward returns
    bull_regimes = df[df["regime"].isin(["bull_trend", "bull_choppy"])]
    bear_regimes = df[df["regime"].isin(["bear_trend", "crisis"])]

    if len(bull_regimes) > 0:
        bull_avg = bull_regimes["spy_20d_fwd_return"].mean()
        print(f"\nBull regime avg 20-day forward return: {bull_avg:+.2f}%")

    if len(bear_regimes) > 0:
        bear_avg = bear_regimes["spy_20d_fwd_return"].mean()
        print(f"Bear regime avg 20-day forward return: {bear_avg:+.2f}%")

    if len(bull_regimes) > 0 and len(bear_regimes) > 0:
        spread = bull_regimes["spy_20d_fwd_return"].mean() - bear_regimes["spy_20d_fwd_return"].mean()
        verdict = "PASS" if spread > 0 else "FAIL"
        print(f"Bull-Bear spread: {spread:+.2f}% — {verdict}")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
