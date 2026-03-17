"""Multi-layer risk management — the survival layer.

Layer 1: Position-level limits
Layer 2: Strategy-level limits + circuit breakers
Layer 3: Portfolio-level limits (exposure, sector, correlation, VaR, drawdown)
Layer 4: Black swan protection (tail hedges)
"""

import logging
from datetime import datetime, timedelta

from backend.adaptive.risk_scaling import get_adaptive_risk_limits
from backend.adaptive.vol_context import VolContext
from backend.models.schemas import TradeSignal

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces all risk limits before trade entry and during monitoring."""

    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital = initial_capital
        self.peak_capital = initial_capital
        self.current_capital = initial_capital
        self.strategy_drawdowns: dict[str, float] = {}
        self.strategy_pause_until: dict[str, datetime] = {}

    def check_trade(
        self,
        signal: TradeSignal,
        vol: VolContext,
        active_trades: list[TradeSignal],
        sector_exposures: dict[str, float],
        portfolio_correlation: float = 0.0,
    ) -> dict:
        """Run all risk checks before allowing a trade entry.

        Returns: {"approved": bool, "reasons": list[str], "adjusted_size": float}
        """
        limits = get_adaptive_risk_limits(vol)
        reasons = []
        adjusted_size = signal.kelly_size_pct / 100

        # Layer 1: Position-level
        if adjusted_size > limits["max_position_pct"]:
            adjusted_size = limits["max_position_pct"]
            reasons.append(f"Position capped at {limits['max_position_pct']:.1%}")

        if signal.stop_loss <= 0 and signal.direction == "long":
            reasons.append("REJECTED: No stop-loss set")
            return {"approved": False, "reasons": reasons, "adjusted_size": 0}

        # Layer 2: Strategy-level circuit breaker
        strategy = signal.strategy.value
        if strategy in self.strategy_pause_until:
            if datetime.utcnow() < self.strategy_pause_until[strategy]:
                reasons.append(f"REJECTED: Strategy {strategy} is paused until {self.strategy_pause_until[strategy]}")
                return {"approved": False, "reasons": reasons, "adjusted_size": 0}

        # Layer 3: Portfolio-level
        # Gross exposure check
        current_gross = sum(abs(t.kelly_size_pct / 100) for t in active_trades)
        if current_gross + adjusted_size > limits["max_gross_exposure"]:
            adjusted_size = max(0, limits["max_gross_exposure"] - current_gross)
            reasons.append(f"Gross exposure capped at {limits['max_gross_exposure']:.0%}")

        # Sector check
        ticker_sector = signal.ticker[:3]  # Simplified; real impl uses GICS mapping
        sector_exp = sector_exposures.get(ticker_sector, 0.0)
        if sector_exp + adjusted_size > limits["max_sector_pct"]:
            adjusted_size = max(0, limits["max_sector_pct"] - sector_exp)
            reasons.append(f"Sector exposure capped at {limits['max_sector_pct']:.0%}")

        # Correlation check
        if portfolio_correlation > limits["max_position_correlation"]:
            adjusted_size *= 0.5
            reasons.append(f"Position halved due to high portfolio correlation ({portfolio_correlation:.2f})")

        # Drawdown check
        current_dd = self._compute_drawdown()
        if current_dd <= limits["flatten_at_drawdown_pct"]:
            reasons.append(f"REJECTED: Portfolio at {current_dd:.1%} drawdown — flatten mode")
            return {"approved": False, "reasons": reasons, "adjusted_size": 0}

        if current_dd <= limits["reduce_at_drawdown_pct"]:
            adjusted_size *= 0.3
            reasons.append(f"Position reduced 70% — drawdown at {current_dd:.1%}")

        approved = adjusted_size > 0.001  # At least 0.1% of capital

        if not reasons:
            reasons.append("All risk checks passed")

        return {
            "approved": approved,
            "reasons": reasons,
            "adjusted_size": round(adjusted_size, 4),
            "original_size": signal.kelly_size_pct / 100,
            "risk_limits": limits,
        }

    def update_capital(self, new_capital: float) -> None:
        self.current_capital = new_capital
        self.peak_capital = max(self.peak_capital, new_capital)

    def record_strategy_pnl(self, strategy: str, pnl_20d: float) -> None:
        """Check strategy drawdown circuit breakers."""
        self.strategy_drawdowns[strategy] = pnl_20d

        if pnl_20d < -0.10:
            self.strategy_pause_until[strategy] = datetime.utcnow() + timedelta(days=20)
            logger.warning("Strategy %s SHUTDOWN: 20-day drawdown %.1f%% — paused 20 days", strategy, pnl_20d * 100)
        elif pnl_20d < -0.05:
            self.strategy_pause_until[strategy] = datetime.utcnow() + timedelta(days=5)
            logger.warning("Strategy %s PAUSED: 20-day drawdown %.1f%% — paused 5 days", strategy, pnl_20d * 100)

    def _compute_drawdown(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return (self.current_capital - self.peak_capital) / self.peak_capital


risk_manager = RiskManager()
