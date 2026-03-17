"""Universe scanner — generate today's top trade ideas across all strategies.

The scan runs strategies in a background thread to avoid blocking the
async event loop.  Catalyst and cross-asset scans are limited to a
manageable ticker subset so the endpoint responds in <30 seconds.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Query

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.config import settings
from backend.data.fetcher import DataFetcher
from backend.models.schemas import Regime, ScannerResult, StrategyName, TradeSignal
from backend.regime.detector import detect_regime

router = APIRouter(prefix="/scan", tags=["scanner"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=2)

SCAN_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "XOM", "PG", "MA", "HD", "COST", "ABBV",
    "CRM", "MRK", "CVX", "LLY", "PEP", "KO", "AVGO", "TMO", "MCD",
    "CSCO", "ACN", "ABT", "DHR", "NKE", "TXN", "WMT", "NEE", "PM",
    "UPS", "RTX", "LOW", "HON", "IBM", "GS", "CAT", "BA", "AMGN",
    "AMD", "INTC", "QCOM", "AMAT", "ADI",
]


def _run_scan(vol: VolContext, regime: Regime) -> list[TradeSignal]:
    """Execute all strategy scans synchronously (runs in thread pool)."""
    all_signals: list[TradeSignal] = []

    if settings.enable_catalyst:
        try:
            from backend.strategies.catalyst_event import CatalystEventStrategy
            catalyst = CatalystEventStrategy()
            all_signals.extend(catalyst.generate_signals(vol, tickers=SCAN_WATCHLIST, regime=regime.value))
        except Exception as e:
            logger.warning("Catalyst scan error: %s", e)

    if settings.enable_cross_asset:
        try:
            from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy
            cross = CrossAssetMomentumStrategy()
            all_signals.extend(cross.generate_signals(vol, tickers=SCAN_WATCHLIST, regime=regime.value))
        except Exception as e:
            logger.warning("CrossAsset scan error: %s", e)

    if settings.enable_gap_reversion:
        try:
            from backend.strategies.gap_reversion import GapReversionStrategy
            gap = GapReversionStrategy()
            all_signals.extend(gap.generate_signals(vol, tickers=SCAN_WATCHLIST, regime=regime.value))
        except Exception as e:
            logger.warning("GapReversion scan error: %s", e)

    return all_signals


@router.get("/", response_model=ScannerResult)
async def scan_universe(
    max_signals: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=60.0, ge=0, le=100),
) -> ScannerResult:
    """Scan the watchlist for today's top trade ideas."""
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y")
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y")
    regime_result = detect_regime(vix_df, spy_df)
    regime: Regime = regime_result["regime"]
    vol = compute_vol_context(spy_df, vix_df)

    loop = asyncio.get_event_loop()
    all_signals = await loop.run_in_executor(_executor, _run_scan, vol, regime)

    filtered = [s for s in all_signals if s.signal_score >= min_score]
    filtered.sort(key=lambda s: s.conviction, reverse=True)
    filtered = filtered[:max_signals]

    return ScannerResult(
        timestamp=datetime.utcnow(),
        regime=regime,
        signals=filtered,
        total_signals=len(all_signals),
    )
