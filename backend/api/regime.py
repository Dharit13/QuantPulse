"""Regime detection endpoint — current regime + history."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Query

from backend.data.fetcher import DataFetcher
from backend.models.database import RegimeRecord, SessionLocal
from backend.models.schemas import Regime, RegimeSnapshot
from backend.regime.detector import detect_regime

router = APIRouter(prefix="/regime", tags=["regime"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()


@router.get("/current", response_model=RegimeSnapshot)
async def get_current_regime() -> RegimeSnapshot:
    """Detect and return the current market regime."""
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
    result = detect_regime(vix_df, spy_df)

    indicators = result.get("indicators", {})
    vix_val = indicators.get("vix", {}).get("vix", 18.0) if isinstance(indicators.get("vix"), dict) else 18.0
    breadth = indicators.get("breadth", {}).get("pct_above_200sma", 50.0) if isinstance(indicators.get("breadth"), dict) else 50.0
    adx = indicators.get("adx", {}).get("adx", 20.0) if isinstance(indicators.get("adx"), dict) else 20.0

    snapshot = RegimeSnapshot(
        timestamp=datetime.utcnow(),
        regime=result["regime"],
        confidence=result["confidence"],
        regime_probabilities=result["probabilities"],
        vix=vix_val,
        breadth_pct=breadth,
        adx=adx,
        strategy_weights=result.get("strategy_weights", {}),
    )

    _persist_regime(snapshot)
    return snapshot


@router.get("/history", response_model=list[RegimeSnapshot])
async def get_regime_history(limit: int = Query(default=30, ge=1, le=365)) -> list[RegimeSnapshot]:
    """Return recent regime snapshots from the database."""
    with SessionLocal() as db:
        rows = (
            db.query(RegimeRecord)
            .order_by(RegimeRecord.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            RegimeSnapshot(
                timestamp=r.timestamp,
                regime=Regime(r.regime),
                confidence=r.confidence,
                regime_probabilities=json.loads(r.regime_probabilities_json),
                vix=r.vix,
                breadth_pct=r.breadth_pct,
                adx=r.adx,
                strategy_weights=json.loads(r.strategy_weights_json),
            )
            for r in rows
        ]


def _persist_regime(snapshot: RegimeSnapshot) -> None:
    """Store a regime snapshot in the database."""
    try:
        with SessionLocal() as db:
            record = RegimeRecord(
                timestamp=snapshot.timestamp,
                regime=snapshot.regime.value,
                confidence=snapshot.confidence,
                vix=snapshot.vix,
                breadth_pct=snapshot.breadth_pct,
                adx=snapshot.adx,
                strategy_weights_json=json.dumps(snapshot.strategy_weights),
                regime_probabilities_json=json.dumps(snapshot.regime_probabilities),
            )
            db.add(record)
            db.commit()
    except Exception as e:
        logger.warning("Failed to persist regime: %s", e)
