"""Abstract base class for all trading strategies."""

from abc import ABC, abstractmethod

from backend.adaptive.vol_context import VolContext
from backend.models.schemas import TradeSignal


class BaseStrategy(ABC):
    """All strategies must implement this interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier matching StrategyName enum."""
        ...

    @abstractmethod
    def generate_signals(
        self,
        vol: VolContext,
        **kwargs,
    ) -> list[TradeSignal]:
        """Generate trade signals given current market context.

        Must use VolContext for all adaptive parameters.
        Returns empty list if no signals meet criteria.
        """
        ...

    @abstractmethod
    def get_params(self, vol: VolContext) -> dict:
        """Return current adaptive parameters for this strategy."""
        ...

    def validate_signal(self, signal: TradeSignal) -> bool:
        """Validate that a signal meets minimum quality standards."""
        if signal.conviction < 0.3:
            return False
        if signal.kelly_size_pct <= 0:
            return False
        if not signal.edge_reason:
            return False
        if not signal.kill_condition:
            return False
        return True
