"""Smooth regime weight transitions.

Instead of hard switches (which cause violent rebalancing),
weights interpolate based on regime probability distributions.
"""

from backend.adaptive.vol_context import VolContext

STRATEGY_WEIGHTS = {
    "bull_trend":     {"stat_arb": 0.15, "catalyst": 0.25, "momentum": 0.35, "flow": 0.10, "intraday": 0.10, "cash": 0.05},
    "bull_choppy":    {"stat_arb": 0.30, "catalyst": 0.20, "momentum": 0.10, "flow": 0.15, "intraday": 0.20, "cash": 0.05},
    "bear_trend":     {"stat_arb": 0.20, "catalyst": 0.15, "momentum": 0.25, "flow": 0.10, "intraday": 0.10, "cash": 0.20},
    "crisis":         {"stat_arb": 0.10, "catalyst": 0.05, "momentum": 0.05, "flow": 0.05, "intraday": 0.05, "cash": 0.70},
    "mean_reverting": {"stat_arb": 0.35, "catalyst": 0.15, "momentum": 0.05, "flow": 0.15, "intraday": 0.25, "cash": 0.05},
}


def compute_blended_weights(regime_probabilities: dict[str, float]) -> dict[str, float]:
    """Blend strategy weights based on regime probability distribution.

    Args:
        regime_probabilities: e.g. {"bull_trend": 0.6, "bull_choppy": 0.3, "bear_trend": 0.1}
                              Must sum to ~1.0
    """
    strategies = list(STRATEGY_WEIGHTS["bull_trend"].keys())
    blended = {s: 0.0 for s in strategies}

    for regime, prob in regime_probabilities.items():
        if regime not in STRATEGY_WEIGHTS:
            continue
        regime_weights = STRATEGY_WEIGHTS[regime]
        for strategy in strategies:
            blended[strategy] += prob * regime_weights[strategy]

    total = sum(blended.values())
    if total > 0:
        return {s: round(w / total, 4) for s, w in blended.items()}
    return STRATEGY_WEIGHTS["bull_choppy"]


def compute_regime_transition_weights(
    prev_weights: dict[str, float],
    target_weights: dict[str, float],
    transition_speed: float,
    vol: VolContext,
) -> dict[str, float]:
    """Smooth weight transition over multiple days.

    transition_speed: 0.2 = gradual (~5 days), 0.5 = urgent (~2 days), 1.0 = immediate
    """
    if vol.vol_regime.value == "extreme":
        transition_speed = 1.0

    new_weights = {}
    for strategy in prev_weights:
        prev = prev_weights[strategy]
        target = target_weights.get(strategy, prev)
        new_weights[strategy] = round(prev + transition_speed * (target - prev), 4)

    total = sum(new_weights.values())
    if total > 0:
        return {s: round(w / total, 4) for s, w in new_weights.items()}
    return target_weights
