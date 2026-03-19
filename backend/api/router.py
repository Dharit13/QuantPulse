"""Central API router — mounts all endpoint sub-modules."""

from fastapi import APIRouter

from backend.api.ai_endpoint import router as ai_router
from backend.api.analyzer import router as analyzer_router
from backend.api.journal import router as journal_router
from backend.api.pipeline_status import router as pipeline_router
from backend.api.portfolio import router as portfolio_router
from backend.api.regime import router as regime_router
from backend.api.scanner import router as scanner_router
from backend.api.sectors import router as sectors_router
from backend.api.swing_picks import router as swing_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(ai_router)
api_router.include_router(analyzer_router)
api_router.include_router(scanner_router)
api_router.include_router(swing_router)
api_router.include_router(portfolio_router)
api_router.include_router(regime_router)
api_router.include_router(journal_router)
api_router.include_router(sectors_router)
api_router.include_router(pipeline_router)
