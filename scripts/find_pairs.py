#!/usr/bin/env python3
"""Find cointegrated pairs across the S&P 500 universe.

Scans all same-sector pairs for cointegration using ADF + Engle-Granger
tests.  Outputs validated pairs with half-life and Hurst exponent.

Usage:
    python -m scripts.find_pairs [--sector "Information Technology"] [--max-pairs 20]
"""

import argparse
import logging
import sys
from itertools import combinations

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find cointegrated pairs")
    parser.add_argument("--sector", type=str, default=None, help="Limit to a specific GICS sector")
    parser.add_argument("--max-pairs", type=int, default=20, help="Maximum pairs to output")
    parser.add_argument("--period", type=str, default="2y", help="Data lookback period")
    args = parser.parse_args()

    from backend.data.fetcher import DataFetcher
    from backend.data.universe import fetch_sp500_constituents
    from backend.signals.cointegration import validate_pair

    fetcher = DataFetcher()
    universe = fetch_sp500_constituents()

    if universe.empty:
        logger.error("Failed to fetch universe")
        sys.exit(1)

    sector_col = "sector" if "sector" in universe.columns else "GICS Sector"
    symbol_col = "ticker" if "ticker" in universe.columns else "Symbol"

    if args.sector:
        if sector_col in universe.columns:
            universe = universe[universe[sector_col] == args.sector]
        logger.info("Filtered to sector '%s': %d stocks", args.sector, len(universe))

    symbols = universe[symbol_col].tolist() if symbol_col in universe.columns else []

    if len(symbols) < 2:
        logger.error("Need at least 2 symbols to find pairs")
        sys.exit(1)

    logger.info("Scanning %d symbols (%d possible pairs)...", len(symbols), len(symbols) * (len(symbols) - 1) // 2)

    sector_map = {}
    if sector_col in universe.columns and symbol_col in universe.columns:
        sector_map = dict(zip(universe[symbol_col], universe[sector_col]))

    valid_pairs: list[dict] = []

    sectors_grouped: dict[str, list[str]] = {}
    for sym in symbols:
        sec = sector_map.get(sym, "Unknown")
        sectors_grouped.setdefault(sec, []).append(sym)

    total_tested = 0
    for sector, sector_syms in sectors_grouped.items():
        if len(sector_syms) < 2:
            continue
        pairs_to_test = list(combinations(sector_syms[:30], 2))
        logger.info("Testing %d pairs in %s...", len(pairs_to_test), sector)

        for sym_a, sym_b in pairs_to_test:
            total_tested += 1
            try:
                df_a = fetcher.get_daily_ohlcv(sym_a, period=args.period)
                df_b = fetcher.get_daily_ohlcv(sym_b, period=args.period)

                if df_a.empty or df_b.empty:
                    continue
                if len(df_a) < 100 or len(df_b) < 100:
                    continue

                result = validate_pair(df_a["Close"], df_b["Close"])

                if result.get("valid", False):
                    valid_pairs.append({
                        "pair": f"{sym_a}/{sym_b}",
                        "sector": sector,
                        "half_life": result.get("half_life", 0),
                        "hurst": result.get("hurst", 0),
                        "adf_pvalue": result.get("adf_pvalue", 1),
                        "eg_pvalue": result.get("eg_pvalue", 1),
                    })
                    logger.info("  VALID: %s/%s (half-life=%.1f, hurst=%.3f)", sym_a, sym_b, result.get("half_life", 0), result.get("hurst", 0))

            except Exception as e:
                logger.debug("Error testing %s/%s: %s", sym_a, sym_b, e)

            if len(valid_pairs) >= args.max_pairs:
                break
        if len(valid_pairs) >= args.max_pairs:
            break

    logger.info("\nResults: %d valid pairs out of %d tested", len(valid_pairs), total_tested)

    if valid_pairs:
        df_results = pd.DataFrame(valid_pairs).sort_values("half_life")
        print("\n" + df_results.to_string(index=False))
    else:
        logger.info("No valid pairs found. Try a different sector or longer period.")


if __name__ == "__main__":
    main()
