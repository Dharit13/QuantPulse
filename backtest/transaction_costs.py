"""Transaction cost model for realistic backtest simulation.

All costs are adaptive — slippage widens with volatility, market impact
scales with position size relative to average daily volume.

Cost components:
  1. Commission: per-share (IBKR rate)
  2. Slippage: percentage of trade value, scaled by vol
  3. Short borrow: annualized fee pro-rated to hold period
  4. Market impact: simplified Almgren-Chriss for large positions
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CostBreakdown:
    commission: float
    slippage: float
    borrow_cost: float
    market_impact: float

    @property
    def total(self) -> float:
        return self.commission + self.slippage + self.borrow_cost + self.market_impact


class TransactionCostModel:
    """Adaptive transaction cost model.

    Parameters are defaults from the spec (Section 15) and scale
    with the provided volatility multiplier at call time.
    """

    def __init__(
        self,
        commission_per_share: float = 0.005,
        base_slippage_pct: float = 0.0005,
        easy_borrow_rate: float = 0.005,
        hard_borrow_rate: float = 0.05,
        hard_borrow_tickers: set[str] | None = None,
    ):
        self.commission_per_share = commission_per_share
        self.base_slippage_pct = base_slippage_pct
        self.easy_borrow_rate = easy_borrow_rate
        self.hard_borrow_rate = hard_borrow_rate
        self.hard_borrow_tickers: set[str] = hard_borrow_tickers or set()

    def compute_entry_cost(
        self,
        price: float,
        shares: int,
        direction: str,
        vol_scale: float = 1.0,
        avg_daily_volume: float | None = None,
    ) -> CostBreakdown:
        """Compute costs incurred when entering a position."""
        notional = price * abs(shares)

        commission = self.commission_per_share * abs(shares)
        slippage = notional * self.base_slippage_pct * max(0.5, vol_scale)

        impact = 0.0
        if avg_daily_volume and avg_daily_volume > 0:
            adv_notional = price * avg_daily_volume
            participation_rate = notional / adv_notional
            if participation_rate > 0.01:
                impact = self._almgren_chriss_impact(
                    notional, adv_notional, vol_scale
                )

        return CostBreakdown(
            commission=commission,
            slippage=slippage,
            borrow_cost=0.0,
            market_impact=impact,
        )

    def compute_exit_cost(
        self,
        price: float,
        shares: int,
        direction: str,
        hold_days: int,
        ticker: str = "",
        vol_scale: float = 1.0,
        avg_daily_volume: float | None = None,
    ) -> CostBreakdown:
        """Compute costs incurred when exiting a position."""
        notional = price * abs(shares)

        commission = self.commission_per_share * abs(shares)
        slippage = notional * self.base_slippage_pct * max(0.5, vol_scale)

        borrow = 0.0
        if direction == "short":
            rate = (
                self.hard_borrow_rate
                if ticker in self.hard_borrow_tickers
                else self.easy_borrow_rate
            )
            borrow = notional * rate * (hold_days / 252)

        impact = 0.0
        if avg_daily_volume and avg_daily_volume > 0:
            adv_notional = price * avg_daily_volume
            participation_rate = notional / adv_notional
            if participation_rate > 0.01:
                impact = self._almgren_chriss_impact(
                    notional, adv_notional, vol_scale
                )

        return CostBreakdown(
            commission=commission,
            slippage=slippage,
            borrow_cost=borrow,
            market_impact=impact,
        )

    def compute_round_trip(
        self,
        entry_price: float,
        exit_price: float,
        shares: int,
        direction: str,
        hold_days: int,
        ticker: str = "",
        vol_scale: float = 1.0,
        avg_daily_volume: float | None = None,
    ) -> CostBreakdown:
        """Total round-trip cost (entry + exit)."""
        entry = self.compute_entry_cost(
            entry_price, shares, direction, vol_scale, avg_daily_volume
        )
        exit_ = self.compute_exit_cost(
            exit_price, shares, direction, hold_days, ticker, vol_scale, avg_daily_volume
        )
        return CostBreakdown(
            commission=entry.commission + exit_.commission,
            slippage=entry.slippage + exit_.slippage,
            borrow_cost=entry.borrow_cost + exit_.borrow_cost,
            market_impact=entry.market_impact + exit_.market_impact,
        )

    @staticmethod
    def _almgren_chriss_impact(
        notional: float,
        adv_notional: float,
        vol_scale: float,
    ) -> float:
        """Simplified Almgren-Chriss temporary market impact.

        impact ≈ sigma * sqrt(notional / ADV)
        where sigma proxied by base_vol * vol_scale.
        """
        base_daily_vol = 0.015
        sigma = base_daily_vol * vol_scale
        participation = notional / adv_notional
        return notional * sigma * math.sqrt(participation)


default_cost_model = TransactionCostModel()
