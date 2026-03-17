#!/usr/bin/env python3
"""Walk-forward backtest CLI.

Usage:
    python scripts/run_backtest.py --strategy stat_arb --years 3
    python scripts/run_backtest.py --strategy catalyst --years 2 --slippage 0.001
    python scripts/run_backtest.py --all --years 5

Runs walk-forward backtesting with transaction costs, prints a tear sheet,
runs statistical validation, and saves results to backtest_results/.
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.data.fetcher import DataFetcher
from backend.models.schemas import BacktestConfig, StrategyName
from backtest import (
    TransactionCostModel,
    WalkForwardEngine,
    generate_tear_sheet,
    run_validation,
    to_performance_stats,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = Path("backtest_results")

STRATEGY_MAP = {
    "stat_arb": StrategyName.STAT_ARB,
    "catalyst": StrategyName.CATALYST,
    "cross_asset": StrategyName.CROSS_ASSET,
    "flow": StrategyName.FLOW,
    "gap_reversion": StrategyName.INTRADAY,
}


def _build_strategy(name: str):
    """Instantiate a strategy by name."""
    if name == "stat_arb":
        from backend.strategies.stat_arb import StatArbStrategy
        return StatArbStrategy()
    elif name == "catalyst":
        from backend.strategies.catalyst_event import CatalystEventStrategy
        return CatalystEventStrategy()
    elif name == "cross_asset":
        from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy
        return CrossAssetMomentumStrategy()
    elif name == "flow":
        from backend.strategies.flow_imbalance import FlowImbalanceStrategy
        return FlowImbalanceStrategy()
    elif name == "gap_reversion":
        from backend.strategies.gap_reversion import GapReversionStrategy
        return GapReversionStrategy()
    else:
        raise ValueError(f"Unknown strategy: {name}")


def _fetch_data(years: int, tickers: list[str]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """Fetch all price data needed for backtesting."""
    fetcher = DataFetcher()
    period = f"{years}y"

    logger.info("Fetching SPY and VIX data (%s)...", period)
    spy_df = fetcher.get_daily_ohlcv("SPY", period=period)
    vix_df = fetcher.get_daily_ohlcv("^VIX", period=period)

    logger.info("Fetching price data for %d tickers...", len(tickers))
    price_data = fetcher.get_multiple_ohlcv(tickers, period=period)

    return price_data, spy_df, vix_df


def _get_tickers_for_strategy(strategy_name: str) -> list[str]:
    """Get the appropriate ticker universe for a strategy."""
    base = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
        "JPM", "V", "UNH", "JNJ", "XOM", "PG", "MA", "HD", "COST", "ABBV",
        "CRM", "MRK", "CVX", "LLY", "PEP", "KO", "AVGO", "TMO",
    ]

    if strategy_name == "cross_asset":
        return ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE"]
    elif strategy_name == "stat_arb":
        return base + ["AMD", "INTC", "QCOM", "AMAT", "ADI", "GS", "MS", "BAC", "WFC"]
    return base


def run_single_backtest(
    strategy_name: str,
    years: int,
    config: BacktestConfig,
    cost_model: TransactionCostModel,
) -> dict | None:
    """Run a walk-forward backtest for one strategy."""
    logger.info("=" * 60)
    logger.info("BACKTEST: %s (%d years)", strategy_name.upper(), years)
    logger.info("=" * 60)

    try:
        strategy = _build_strategy(strategy_name)
    except Exception as e:
        logger.error("Failed to instantiate strategy %s: %s", strategy_name, e)
        return None

    tickers = _get_tickers_for_strategy(strategy_name)
    price_data, spy_df, vix_df = _fetch_data(years, tickers)

    if spy_df.empty or vix_df.empty:
        logger.error("Failed to fetch SPY/VIX data")
        return None

    engine = WalkForwardEngine(
        strategy=strategy,
        config=config,
        cost_model=cost_model,
    )

    try:
        result = engine.run(
            price_data=price_data,
            spy_df=spy_df,
            vix_df=vix_df,
            strategy_kwargs={"tickers": tickers},
        )
    except Exception as e:
        logger.error("Backtest execution failed for %s: %s", strategy_name, e)
        return None

    # Generate tear sheet
    tear_sheet = generate_tear_sheet(result)
    perf = to_performance_stats(result)

    # Print summary
    print(f"\n{'─' * 50}")
    print(f"  {strategy_name.upper()} — Walk-Forward Results")
    print(f"{'─' * 50}")
    summary = tear_sheet.get("summary", {})
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:30s}: {v:>10.4f}")
        else:
            print(f"  {k:30s}: {v!s:>10}")

    # Statistical validation
    trade_returns = [t.pnl_pct for t in result.trades]
    if trade_returns:
        validation = run_validation(
            trade_returns=trade_returns,
            sharpe=result.sharpe_ratio,
            win_rate=summary.get("win_rate", 0),
            profit_factor=summary.get("profit_factor", 0),
        )
        print(f"\n  {'VALIDATION':30s}")
        print(f"  {'passes_all_gates':30s}: {validation.get('passes_all_gates', False)}")
        for gate_name, gate_result in validation.get("gates", {}).items():
            status = "PASS" if gate_result.get("passed") else "FAIL"
            print(f"  {gate_name:30s}: {status}")
    else:
        validation = {"passes_all_gates": False, "reason": "No trades generated"}
        print("\n  WARNING: No trades generated — strategy may need a longer lookback or different tickers")

    print(f"{'─' * 50}\n")

    return {
        "strategy": strategy_name,
        "config": config.model_dump(),
        "tear_sheet": tear_sheet,
        "validation": validation,
        "n_trades": len(result.trades),
        "timestamp": datetime.utcnow().isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward backtest runner")
    parser.add_argument(
        "--strategy", type=str, default=None,
        choices=list(STRATEGY_MAP.keys()),
        help="Strategy to backtest (omit for --all)",
    )
    parser.add_argument("--all", action="store_true", help="Backtest all strategies")
    parser.add_argument("--years", type=int, default=3, help="Years of historical data (default: 3)")
    parser.add_argument("--train-days", type=int, default=504, help="Training window in trading days (default: 504 = 2y)")
    parser.add_argument("--test-days", type=int, default=126, help="Test window in trading days (default: 126 = 6mo)")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Slippage in decimal (default: 0.0005 = 5bps)")
    parser.add_argument("--commission", type=float, default=0.005, help="Commission per share (default: $0.005)")
    parser.add_argument("--short-borrow", type=float, default=0.005, help="Annual short borrow rate (default: 0.5%%)")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital (default: $100,000)")
    args = parser.parse_args()

    if not args.strategy and not args.all:
        parser.error("Specify --strategy NAME or --all")

    config = BacktestConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        initial_capital=args.capital,
        commission_per_share=args.commission,
        slippage_pct=args.slippage,
        short_borrow_rate=args.short_borrow,
    )

    cost_model = TransactionCostModel(
        commission_per_share=args.commission,
        base_slippage_pct=args.slippage,
        easy_borrow_rate=args.short_borrow,
    )

    strategies = list(STRATEGY_MAP.keys()) if args.all else [args.strategy]

    RESULTS_DIR.mkdir(exist_ok=True)
    all_results = {}

    for name in strategies:
        result = run_single_backtest(name, args.years, config, cost_model)
        if result:
            all_results[name] = result

            # Save individual result
            outfile = RESULTS_DIR / f"{name}_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
            with open(outfile, "w") as f:
                json.dump(result, f, indent=2, default=str)
            logger.info("Results saved to %s", outfile)

    # Summary across all strategies
    if len(all_results) > 1:
        print(f"\n{'=' * 60}")
        print("  CROSS-STRATEGY SUMMARY")
        print(f"{'=' * 60}")
        for name, res in all_results.items():
            ts = res.get("tear_sheet", {}).get("summary", {})
            validated = res.get("validation", {}).get("passes_all_gates", False)
            print(
                f"  {name:20s}  Sharpe={ts.get('sharpe_ratio', 0):.2f}  "
                f"WinRate={ts.get('win_rate', 0):.0%}  "
                f"Trades={res['n_trades']:4d}  "
                f"Valid={'YES' if validated else 'NO'}"
            )
        print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
