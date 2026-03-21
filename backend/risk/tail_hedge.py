"""Tail hedge management — VIX calls and SPY puts for black swan protection.

The system allocates a small percentage of capital (TAIL_HEDGE_PCT from config,
default 3%) to protective positions that profit during market dislocations.

Hedge logic (spec §11 Layer 4):
  - When VIX < 15: buy cheap VIX calls (30-60 DTE, 25-delta OTM)
  - When VIX > 30: consider rolling or monetizing existing hedges
  - SPY puts: 5% OTM, 30-60 DTE, sized to offset 50% of portfolio delta

This module generates RECOMMENDATIONS for hedges. The user executes them
manually on their broker, consistent with the advisory-only architecture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.adaptive.vol_context import VolContext
from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class HedgeRecommendation:
    """A single hedge recommendation for the user to consider."""

    instrument: str  # "VIX_CALL", "SPY_PUT", "UVXY_CALL"
    action: str  # "buy", "roll", "monetize", "hold"
    ticker: str  # "VIX", "SPY", "UVXY"
    strike_pct_otm: float  # e.g., 0.25 = 25% OTM
    dte_target: int  # target days to expiration
    allocation_pct: float  # fraction of capital to allocate
    rationale: str
    priority: str  # "high", "medium", "low"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class HedgePortfolio:
    """Current state of the tail hedge portfolio."""

    total_allocation_pct: float
    target_allocation_pct: float
    recommendations: list[HedgeRecommendation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    vix_current: float = 18.0
    regime: str = "normal"


class TailHedgeManager:
    """Generates hedge recommendations based on current market conditions."""

    def __init__(self, capital: float | None = None):
        self.capital = capital or settings.initial_capital
        self.target_allocation = settings.tail_hedge_pct

    def evaluate(
        self,
        vol: VolContext,
        current_hedge_pct: float = 0.0,
        portfolio_delta: float = 1.0,
    ) -> HedgePortfolio:
        """Evaluate current conditions and generate hedge recommendations.

        Args:
            vol: current volatility context
            current_hedge_pct: fraction of capital currently in hedges
            portfolio_delta: portfolio net delta (1.0 = 100% long)
        """
        portfolio = HedgePortfolio(
            total_allocation_pct=current_hedge_pct,
            target_allocation_pct=self.target_allocation,
            vix_current=vol.vix_current,
        )

        vix = vol.vix_current

        if vix < 15:
            portfolio.regime = "low_vol"
            portfolio.recommendations.extend(self._low_vol_hedges(vol, current_hedge_pct, portfolio_delta))
        elif vix < 22:
            portfolio.regime = "normal"
            portfolio.recommendations.extend(self._normal_hedges(vol, current_hedge_pct, portfolio_delta))
        elif vix < 30:
            portfolio.regime = "elevated"
            portfolio.recommendations.extend(self._elevated_vol_hedges(vol, current_hedge_pct))
        else:
            portfolio.regime = "crisis"
            portfolio.recommendations.extend(self._crisis_hedges(vol, current_hedge_pct))

        if current_hedge_pct < self.target_allocation * 0.5:
            portfolio.notes.append(
                f"Hedge allocation ({current_hedge_pct:.1%}) is below target "
                f"({self.target_allocation:.1%}). Consider adding protection."
            )

        return portfolio

    def _low_vol_hedges(
        self,
        vol: VolContext,
        current_pct: float,
        delta: float,
    ) -> list[HedgeRecommendation]:
        """VIX < 15: cheap insurance. Load up on VIX calls and SPY puts."""
        recs = []
        remaining = max(0, self.target_allocation - current_pct)

        if remaining > 0.005:
            vix_alloc = remaining * 0.6
            recs.append(
                HedgeRecommendation(
                    instrument="VIX_CALL",
                    action="buy",
                    ticker="VIX",
                    strike_pct_otm=0.25,
                    dte_target=45,
                    allocation_pct=round(vix_alloc, 4),
                    rationale=(
                        f"VIX at {vol.vix_current:.1f} (low vol regime). "
                        f"Buy 25-delta OTM calls ~45 DTE while vol is cheap. "
                        f"Historically, VIX < 15 precedes spikes within 60 days."
                    ),
                    priority="high",
                )
            )

            spy_alloc = remaining * 0.4
            recs.append(
                HedgeRecommendation(
                    instrument="SPY_PUT",
                    action="buy",
                    ticker="SPY",
                    strike_pct_otm=0.05,
                    dte_target=45,
                    allocation_pct=round(spy_alloc, 4),
                    rationale=(f"Portfolio delta = {delta:.2f}. Buy 5% OTM SPY puts to offset ~50% of downside risk."),
                    priority="medium",
                )
            )

        return recs

    def _normal_hedges(
        self,
        vol: VolContext,
        current_pct: float,
        delta: float,
    ) -> list[HedgeRecommendation]:
        """VIX 15-22: maintain existing hedges, roll approaching expiry."""
        recs = []
        remaining = max(0, self.target_allocation - current_pct)

        if remaining > 0.01:
            recs.append(
                HedgeRecommendation(
                    instrument="SPY_PUT",
                    action="buy",
                    ticker="SPY",
                    strike_pct_otm=0.05,
                    dte_target=30,
                    allocation_pct=round(remaining * 0.5, 4),
                    rationale="Normal vol — maintain baseline SPY put protection.",
                    priority="medium",
                )
            )

        if current_pct > 0.005:
            recs.append(
                HedgeRecommendation(
                    instrument="SPY_PUT",
                    action="roll",
                    ticker="SPY",
                    strike_pct_otm=0.05,
                    dte_target=30,
                    allocation_pct=0.0,
                    rationale="Roll any hedges with < 14 DTE to maintain coverage.",
                    priority="low",
                )
            )

        return recs

    def _elevated_vol_hedges(
        self,
        vol: VolContext,
        current_pct: float,
    ) -> list[HedgeRecommendation]:
        """VIX 22-30: hedges are expensive. Consider monetizing partial VIX gains."""
        recs = []

        if current_pct > self.target_allocation:
            monetize_pct = (current_pct - self.target_allocation) * 0.5
            recs.append(
                HedgeRecommendation(
                    instrument="VIX_CALL",
                    action="monetize",
                    ticker="VIX",
                    strike_pct_otm=0.0,
                    dte_target=0,
                    allocation_pct=round(monetize_pct, 4),
                    rationale=(
                        f"VIX at {vol.vix_current:.1f} — hedges in profit. "
                        f"Take partial profits on VIX calls to lock in gains."
                    ),
                    priority="high",
                )
            )

        recs.append(
            HedgeRecommendation(
                instrument="SPY_PUT",
                action="hold",
                ticker="SPY",
                strike_pct_otm=0.05,
                dte_target=0,
                allocation_pct=0.0,
                rationale="Elevated vol — hold existing SPY puts, don't add (premium expensive).",
                priority="low",
            )
        )

        return recs

    def _crisis_hedges(
        self,
        vol: VolContext,
        current_pct: float,
    ) -> list[HedgeRecommendation]:
        """VIX > 30: crisis mode. Aggressively monetize VIX hedges."""
        recs = []

        if current_pct > 0.01:
            recs.append(
                HedgeRecommendation(
                    instrument="VIX_CALL",
                    action="monetize",
                    ticker="VIX",
                    strike_pct_otm=0.0,
                    dte_target=0,
                    allocation_pct=round(current_pct * 0.7, 4),
                    rationale=(
                        f"VIX at {vol.vix_current:.1f} — crisis mode. "
                        f"Monetize 70% of VIX call hedges while they're at peak value. "
                        f"Retain 30% in case of further deterioration."
                    ),
                    priority="high",
                )
            )

        recs.append(
            HedgeRecommendation(
                instrument="SPY_PUT",
                action="hold",
                ticker="SPY",
                strike_pct_otm=0.0,
                dte_target=0,
                allocation_pct=0.0,
                rationale="Crisis — hold all SPY puts. Do not sell downside protection.",
                priority="medium",
            )
        )

        return recs
