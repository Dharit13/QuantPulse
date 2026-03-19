"""Regime detection endpoint — current regime + history."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query

from backend.data.cache import data_cache
from backend.models.database import RegimeRecord, SessionLocal
from backend.models.schemas import Regime, RegimeSnapshot

router = APIRouter(prefix="/regime", tags=["regime"])
logger = logging.getLogger(__name__)


@router.get("/current")
async def get_current_regime(
    refresh: bool = Query(False, description="Force live computation, bypass pipeline cache"),
) -> dict:
    """Return the current market regime from pipeline cache (instant) or live."""
    if not refresh:
        cached = data_cache.get("pipeline:regime")
        if cached and isinstance(cached, dict):
            return cached

    from backend.pipeline import refresh_regime
    result = refresh_regime()
    if result:
        return result

    return {"error": "Regime detection failed", "regime": "unknown"}


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
