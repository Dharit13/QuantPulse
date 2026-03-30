# ADR-002: Five Market Regimes, Not Three

## Status
Active

## Context
Regime detection is the core routing mechanism — it determines capital allocation, parameter scaling, and strategy activation. The simplest viable model uses three regimes: bull, bear, and neutral. Many commercial systems use this.

The question was whether three regimes was sufficient or whether the additional complexity of five regimes was justified.

## Decision
Use five regimes: Bull Trending, Bull Choppy, Bear Trending, Crisis, and Mean Reverting.

## Reasoning
Three regimes collapses two meaningfully different states:

1. **Bull Trending vs Bull Choppy**: In a bull trending market (high ADX, strong breadth), momentum strategies and stat arb both work well. In a bull choppy market (low ADX, weak breadth, low VIX), momentum strategies bleed slowly while mean-reversion dominates. Treating these as the same "bull" regime would over-allocate to momentum in choppy conditions.

2. **Bear Trending vs Crisis**: A bear trending market (rising VIX, weakening breadth, downtrend) is very different from a Crisis (VIX spike, breadth collapse, correlation breakdown). In a bear trend, stat arb still works — pairs relationships hold. In a Crisis, correlation goes to 1, stat arb breaks down entirely, and the only correct action is to reduce all exposure to near zero.

The fifth regime (Mean Reverting) captures range-bound markets where trend-following fails but mean-reversion strategies excel. Stat arb gets full allocation; catalyst and momentum strategies get reduced allocation.

Four indicators drive classification: VIX level, market breadth (advance/decline), ADX (trend strength), and cross-asset confirmation (yield curve, commodities, dollar). Requiring 3-of-4 agreement reduces false transitions.

## Consequences
- More complex regime logic (~200 lines vs ~50 for a three-regime model)
- Regime transitions require monitoring: the detector has ~2-bar lag, so fast transitions are a known weakness
- Each additional regime requires calibrating capital allocation weights per strategy — 5 strategies × 5 regimes = 25 allocation parameters
- More precise capital allocation: strategies only run in regimes where their edge is supported by theory
