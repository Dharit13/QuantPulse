# Performance Summary

This document tracks system-level metrics rather than absolute P&L. The goal is to demonstrate that QuantPulse measures, evaluates, and learns systematically — not to report returns.

---

## System Uptime

| Metric | Value |
|---|---|
| Live since | [Month/Year] |
| Total operating days | [X] |
| Circuit breaker activations (strategy-level) | [Y] |
| Regime transitions detected | [Z] |
| Average regime detection lag | ~2 bars (10 min) |

---

## Shadow Book — Strategy Performance (Relative)

All figures are from phantom trades auto-logged by the shadow book. These are paper trades, not executed positions.

| Strategy | Phantom Trades | Win Rate | Avg Holding Period | Circuit Breaker Triggers | Notes |
|---|---|---|---|---|---|
| Statistical Arbitrage | [N] | [X]% | [X] days | [Y] | Best in Mean Reverting regime |
| Catalyst Event | [N] | [X]% | [X] days | [Y] | PEAD component strongest |
| Cross-Asset Momentum | [N] | [X]% | [X] days | [Y] | Regime confirmation role |
| Flow Imbalance | [N] | [X]% | [X] days | [Y] | Options sweep signal strongest |
| Gap Reversion | [N] | [X]% | [X] days | [Y] | Smallest sample size |

---

## Overnight AI Scanner — Scorecard

The morning scorecard auto-runs at 9:35 AM ET each trading day, comparing overnight picks to opening prices.

| Metric | Value |
|---|---|
| Total picks logged | [N] |
| Overall win rate | [X]% |
| Average return per pick | [+X]% |
| Best streak | [N] wins |
| Confidence 80+: win rate | [X]% |
| Confidence 60-79: win rate | [X]% |
| Best performing sector | [Sector] |
| Worst performing sector | [Sector] |

*Claude's prompt includes the last 7-day performance summary, allowing self-correction over time.*

---

## Regime Detection

| Metric | Value |
|---|---|
| Regime transitions detected (total) | [N] |
| False transitions (reversed within 2 bars) | [N] |
| Longest period in single regime | [X] days |
| Crisis regime activations | [N] |

---

## Infrastructure

| Metric | Value |
|---|---|
| API p95 latency | <[X]ms |
| Redis cache hit rate | [X]% |
| WebSocket uptime | [X]% |
| ARQ task failure rate | <[X]% |
| Claude API cost per overnight scan | ~$[X] |

---

## Key Learnings

1. **Adaptive parameters reduced false signals significantly.** Before VolContext, the stat arb strategy generated many false entries during the high-VIX period in [Date]. After adaptive z-score thresholds, those entries were filtered.

2. **Circuit breakers worked as designed.** [Strategy] triggered a circuit breaker during [regime/period]. Portfolio impact was -[X]% vs an estimated -[Y]% if signals had continued unfiltered.

3. **Overnight scanner confidence calibration improved after scorecard feedback.** Initial win rate for 80+ confidence picks was [X]%. After [N] weeks of performance memory in the prompt, it improved to [Y]%.

---

*Note: Absolute dollar returns are intentionally omitted. This system is in the track-record-building phase. The metrics above demonstrate the evaluation infrastructure and feedback loops, which are the foundation for any reliable performance claim.*
