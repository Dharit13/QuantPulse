"""Regime transition logic with persistence and hysteresis.

Rules:
- Regime must hold for 3 consecutive days to trigger a switch
- Exception: VIX > 40 triggers immediate crisis mode
- Transitions between regimes have different speeds
"""

import logging
from datetime import datetime

from backend.adaptive.vol_context import VolContext
from backend.adaptive.weight_interpolation import compute_regime_transition_weights
from backend.models.schemas import Regime

logger = logging.getLogger(__name__)

PERSISTENCE_DAYS = 3
CRISIS_VIX_OVERRIDE = 40

TRANSITION_SPEEDS = {
    ("bull_trend", "bull_choppy"): 0.2,
    ("bull_choppy", "bull_trend"): 0.2,
    ("bull_trend", "bear_trend"): 0.5,
    ("bull_choppy", "bear_trend"): 0.5,
    ("bear_trend", "bull_trend"): 0.2,
    ("bear_trend", "bull_choppy"): 0.2,
    ("crisis", "bull_trend"): 0.1,      # Slow recovery
    ("crisis", "bull_choppy"): 0.1,
    ("crisis", "bear_trend"): 0.2,
    ("crisis", "mean_reverting"): 0.15,
}
DEFAULT_TRANSITION_SPEED = 0.3


class RegimeTracker:
    """Tracks regime state with persistence and smooth transitions."""

    def __init__(self):
        self.current_regime: Regime = Regime.BULL_CHOPPY
        self.candidate_regime: Regime | None = None
        self.candidate_days: int = 0
        self.current_weights: dict[str, float] = {
            "stat_arb": 0.20, "catalyst": 0.20, "momentum": 0.20,
            "flow": 0.15, "intraday": 0.15, "cash": 0.10,
        }
        self.regime_start: datetime = datetime.utcnow()
        self.history: list[dict] = []

    def update(
        self,
        detected_regime: Regime,
        target_weights: dict[str, float],
        vol: VolContext,
    ) -> dict:
        """Process a new regime detection and return current effective state."""

        # Crisis VIX override — immediate switch
        if vol.vix_current >= CRISIS_VIX_OVERRIDE and detected_regime != Regime.CRISIS:
            detected_regime = Regime.CRISIS
            logger.warning("CRISIS OVERRIDE: VIX=%.1f >= %d", vol.vix_current, CRISIS_VIX_OVERRIDE)

        if detected_regime == self.current_regime:
            self.candidate_regime = None
            self.candidate_days = 0
        elif detected_regime == Regime.CRISIS and self.current_regime != Regime.CRISIS:
            # Immediate crisis transition
            self._switch_regime(detected_regime)
        elif detected_regime == self.candidate_regime:
            self.candidate_days += 1
            if self.candidate_days >= PERSISTENCE_DAYS:
                self._switch_regime(detected_regime)
        else:
            self.candidate_regime = detected_regime
            self.candidate_days = 1

        # Smooth weight transition
        speed_key = (self.current_regime.value, detected_regime.value)
        speed = TRANSITION_SPEEDS.get(speed_key, DEFAULT_TRANSITION_SPEED)

        self.current_weights = compute_regime_transition_weights(
            prev_weights=self.current_weights,
            target_weights=target_weights,
            transition_speed=speed,
            vol=vol,
        )

        return {
            "effective_regime": self.current_regime,
            "candidate_regime": self.candidate_regime,
            "candidate_days": self.candidate_days,
            "current_weights": self.current_weights,
            "days_in_regime": (datetime.utcnow() - self.regime_start).days,
        }

    def _switch_regime(self, new_regime: Regime) -> None:
        self.history.append({
            "from": self.current_regime.value,
            "to": new_regime.value,
            "timestamp": datetime.utcnow().isoformat(),
        })
        logger.info("Regime switch: %s -> %s", self.current_regime.value, new_regime.value)
        self.current_regime = new_regime
        self.candidate_regime = None
        self.candidate_days = 0
        self.regime_start = datetime.utcnow()
