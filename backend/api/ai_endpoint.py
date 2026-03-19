"""Lightweight AI summarization endpoint for frontend tabs."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from backend.ai.market_ai import ai_allocation_explain, ai_dcf_explain, ai_entry_timing, ai_investment_research, ai_market_action_banner, ai_market_summary, ai_market_timing_tip, ai_picks_summary, ai_portfolio_review, ai_regime_probs, ai_scan_summary, ai_signal_explain, ai_swing_invest, ai_swing_summary

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger(__name__)


class AISummarizeRequest(BaseModel):
    type: str
    data: dict


@router.post("/summarize")
async def summarize(req: AISummarizeRequest) -> dict:
    result = None

    if req.type == "market":
        result = ai_market_summary(req.data)
    elif req.type == "regime_probs":
        result = ai_regime_probs(req.data)
    elif req.type == "scan":
        regime = req.data.get("regime", "unknown")
        signals = req.data.get("signals", [])
        result = ai_scan_summary(regime, signals)
    elif req.type == "picks":
        regime = req.data.get("regime", "unknown")
        picks = req.data.get("picks", [])
        result = ai_picks_summary(regime, picks)
    elif req.type == "portfolio_review":
        result = ai_portfolio_review(req.data)
    elif req.type == "swing":
        regime = req.data.get("regime", "unknown")
        picks = req.data.get("picks", [])
        result = ai_swing_summary(regime, picks)
    elif req.type == "entry_timing":
        regime = req.data.get("regime", "unknown")
        picks = req.data.get("picks", [])
        result = ai_entry_timing(regime, picks)
    elif req.type == "signal_explain":
        signals = req.data.get("signals", [])
        result = ai_signal_explain(signals)
    elif req.type == "swing_invest":
        regime = req.data.get("regime", "unknown")
        capital = req.data.get("capital", 1000)
        picks = req.data.get("picks", [])
        result = ai_swing_invest(regime, capital, picks)
    elif req.type == "investment_research":
        regime = req.data.get("regime", "unknown")
        capital = req.data.get("capital", 1000)
        picks = req.data.get("picks", [])
        result = ai_investment_research(regime, capital, picks)
    elif req.type == "allocation_explain":
        result = ai_allocation_explain(req.data)
    elif req.type == "market_action":
        result = ai_market_action_banner(req.data)
    elif req.type == "market_timing":
        result = ai_market_timing_tip(req.data)
    elif req.type == "dcf_explain":
        dcf = req.data.get("dcf", {})
        fundamentals = req.data.get("fundamentals", {})
        result = ai_dcf_explain(dcf, fundamentals)

    return {"result": result}
