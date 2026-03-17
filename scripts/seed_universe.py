#!/usr/bin/env python3
"""Seed the universe cache with S&P 500 constituents.

Run once after setup, then automatically refreshed monthly by the scheduler.

Usage:
    python -m scripts.seed_universe
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from backend.data.universe import fetch_sp500_constituents

    logger.info("Fetching S&P 500 constituents...")
    df = fetch_sp500_constituents()

    if df.empty:
        logger.error("Failed to fetch constituents")
        sys.exit(1)

    logger.info("Universe seeded: %d constituents", len(df))

    sector_col = "sector" if "sector" in df.columns else "GICS Sector"
    symbol_col = "ticker" if "ticker" in df.columns else "Symbol"

    sectors = df[sector_col].value_counts() if sector_col in df.columns else {}
    for sector, count in sectors.items():
        logger.info("  %s: %d stocks", sector, count)

    logger.info("Top 10 by weight (alphabetical):")
    symbols = sorted(df[symbol_col].tolist()[:10]) if symbol_col in df.columns else []
    for s in symbols:
        logger.info("  %s", s)

    logger.info("Done. Universe will auto-refresh monthly via scheduler.")


if __name__ == "__main__":
    main()
