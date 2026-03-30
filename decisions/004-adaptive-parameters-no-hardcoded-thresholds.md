# ADR-004: Adaptive Parameters via VolContext, No Hardcoded Thresholds

## Status
Active

## Context
Quantitative strategies require dozens of parameters: z-score entry thresholds, lookback windows, stop distances, position sizing multipliers, and more. The conventional approach is to backtest and hardcode the optimal values (e.g., "enter when z-score > 2.0, exit at 0.5").

The problem is that optimal thresholds in a low-volatility regime are wrong in a high-volatility regime. A z-score of 2.0 in a VIX-12 environment is very different from a z-score of 2.0 in a VIX-35 environment.

## Decision
All strategy parameters are functions of `VolContext`, not hardcoded constants. `VolContext` is a dataclass computed fresh from market data before each scan, containing: VIX level, VIX term structure slope, ATR of SPY, average pairwise correlation, and market breadth score.

Parameters scale continuously with market conditions. There are no hardcoded thresholds anywhere in the strategy layer.

## Reasoning
**Hardcoded thresholds go stale**: A system backtested on 2015-2022 data has never seen a VIX-80 environment. Hardcoded thresholds calibrated on that history will either be too tight (generate no signals in a volatile regime) or too loose (generate too many false signals in a calm regime).

**Adaptive parameters generalize**: If the z-score threshold scales with ATR (tighter in low-vol, wider in high-vol), the strategy works across regimes without manual retuning. The system adapts; the operator doesn't intervene.

**Avoids overfitting**: A system with 50 hardcoded parameters is overfit to historical data. A system with 5 parameters that each have a principled, monotonic relationship with a volatility measure is generalizable.

## Implementation
`VolContext` is computed every 2 minutes by the scheduler and stored in Redis. Every strategy call reads the current `VolContext` and computes its parameters from it. Example:

```python
z_score_threshold = vol_context.base_z + (vol_context.vix_level / 20) * 0.5
lookback = int(vol_context.base_lookback * vol_context.vol_scalar)
stop_distance = vol_context.atr_spy * strategy_atr_multiplier
```

The `vol_scalar` is a number between 0.5 and 2.0 that compresses parameters in crisis regimes and expands them in calm regimes.

## Consequences
- Harder to backtest: backtests must reconstruct historical `VolContext` values, not just apply fixed parameters
- Strategy behavior is harder to explain to a non-technical observer ("the threshold changes based on market conditions")
- Eliminates an entire class of maintenance burden: no parameter re-optimization after regime shifts
- The system handles 2020 and 2023 with the same code without manual intervention
