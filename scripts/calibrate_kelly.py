#!/usr/bin/env python3
"""Calibrate Kelly parameters from historical trade data.

Reads closed trades from the journal and estimates per-strategy
win rate and payoff ratio for Kelly sizing.

Usage:
    python -m scripts.calibrate_kelly [--min-trades 10]
"""

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate Kelly parameters")
    parser.add_argument("--min-trades", type=int, default=10, help="Min trades per strategy for calibration")
    args = parser.parse_args()

    from backend.models.schemas import StrategyName
    from backend.risk.kelly import compute_kelly_fraction
    from backend.tracker.trade_journal import TradeJournal

    journal = TradeJournal()

    print("\n" + "=" * 65)
    print("  KELLY PARAMETER CALIBRATION — from live trade history")
    print("=" * 65)

    for strategy in StrategyName:
        trades = journal.get_closed_trades(strategy=strategy)
        if len(trades) < args.min_trades:
            print(f"\n  {strategy.value:20s}  — insufficient trades ({len(trades)}/{args.min_trades})")
            continue

        wins = [t for t in trades if t.pnl_percent and t.pnl_percent > 0]
        losses = [t for t in trades if t.pnl_percent and t.pnl_percent <= 0]

        win_rate = len(wins) / len(trades)
        avg_win = sum(t.pnl_percent for t in wins if t.pnl_percent) / max(len(wins), 1) / 100
        avg_loss = abs(sum(t.pnl_percent for t in losses if t.pnl_percent) / max(len(losses), 1)) / 100

        if avg_loss > 0:
            payoff_ratio = avg_win / avg_loss
        else:
            payoff_ratio = float("inf")

        kelly = compute_kelly_fraction(win_rate, payoff_ratio)
        half_kelly = kelly * 0.5

        print(f"\n  {strategy.value:20s}")
        print(f"    Trades:       {len(trades)}")
        print(f"    Win rate:     {win_rate:.1%}")
        print(f"    Avg win:      {avg_win:.2%}")
        print(f"    Avg loss:     {avg_loss:.2%}")
        print(f"    Payoff ratio: {payoff_ratio:.2f}")
        print(f"    Full Kelly:   {kelly:.1%}")
        print(f"    Half Kelly:   {half_kelly:.1%}  ← recommended")

    print("\n" + "=" * 65)
    print("  NOTE: Half-Kelly is the default. Full Kelly is too aggressive")
    print("  for real trading. Use these numbers to update config.py.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
