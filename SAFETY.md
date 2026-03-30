# Safety & Risk Architecture

How QuantPulse prevents catastrophic losses through defense-in-depth — the same principles that guide safe AI systems.

QuantPulse is advisory, not autonomous. The system generates signals. The human executes. This is the most important safety decision in the architecture.

---

## Layer 1: Per-Trade Stop-Loss

Every signal is generated with an explicit stop-loss price derived from ATR (Average True Range), regime context, and strategy-specific rules. The system will not emit a signal without a defined exit.

- Stat arb stops: based on spread z-score exceeding 3.5σ (spread has broken down, not mean-reverting)
- Catalyst stops: 1.5× ATR below entry, widened in high-VIX regimes
- Gap reversion stops: hard limit at 110% of gap size (gap is not filling, cut it)

## Layer 2: Strategy Circuit Breakers

Each strategy tracks its own rolling performance via the Shadow Book (phantom trades auto-logged for every signal). If a strategy's recent equity curve deteriorates:

- Rolling 20-day drawdown > **-5%** → strategy pauses for 10 days (warning state)
- Rolling 20-day drawdown > **-10%** → strategy shuts down for 20 days (requires manual review to re-enable)

No manual intervention needed to trigger the pause. The scheduler checks this condition before running each strategy's scan.

## Layer 3: Position Sizing (Quarter-Kelly)

QuantPulse uses **quarter-Kelly** (Kelly/4) as the default position sizing method.

- **Why not full Kelly?** Full Kelly maximizes long-run geometric growth but produces severe drawdowns (50%+ swings are mathematically expected). No human psychology tolerates that.
- **Why not half-Kelly?** Half-Kelly is the academic recommendation but still requires high confidence in win rate and edge estimates. We're in the track-record-building phase — our estimates have wide confidence intervals.
- **Why not equal-weight?** Equal-weight ignores signal quality. A high-conviction pairs trade with a tight z-score and long cointegration history should get more capital than a marginal catalyst signal.
- **Why quarter-Kelly?** Preserves 93-95% of the Kelly growth rate while reducing variance by 75%. As the shadow book accumulates evidence, the system can graduate to half-Kelly per strategy.

Kelly fraction is recalibrated from a rolling 100-trade window per strategy. It is capped at 8% of portfolio per position regardless of Kelly output.

## Layer 4: Portfolio-Level Exposure Caps

Even if every individual signal is sound, correlated exposure can create systemic risk. The risk manager enforces:

| Constraint | Limit |
|---|---|
| Max single position | 8% of portfolio |
| Max sector concentration | 30% of gross exposure |
| Max correlated position pairs (ρ > 0.70) | 3 simultaneous |
| Max gross exposure | 150% |
| Max net exposure | 80% long / 20% short |
| Portfolio VaR (95%, 10-day) | 5% of portfolio |
| Max portfolio drawdown before full pause | 15% |

When VaR exceeds the threshold, the portfolio builder reduces position sizes proportionally across all strategies — no single strategy gets cut, all get trimmed.

## Layer 5: Regime-Aware Capital Allocation

The regime detector classifies the market into five states. Each state controls how much capital the strategies are allowed to deploy:

| Regime | Description | Capital Allocation |
|---|---|---|
| Bull Trending | Low VIX, strong breadth, high ADX | Full deployment |
| Bull Choppy | Low VIX, weak breadth, low ADX | 60% deployment |
| Mean Reverting | Medium VIX, range-bound | Stat arb only at full, others at 40% |
| Bear Trending | High VIX, weak breadth, downtrend | 25% deployment, long bias removed |
| Crisis | VIX spike, breadth collapse | 0-10% deployment, mostly cash |

In Crisis regime, the system does not generate new long signals. It may generate short signals or suggest moving to cash. The regime check runs every 2 minutes.

## Layer 6: Human-in-the-Loop (Advisory Architecture)

QuantPulse deliberately does not connect to any brokerage API. There is no order execution, no automated position management, no automated stop-loss placement.

**Why?**

1. **Model uncertainty**: Signal quality estimates, Kelly fractions, and regime classifications all have uncertainty bounds. Automating on uncertain estimates scales mistakes.
2. **Tail risk**: The scenarios that matter most — flash crashes, earnings surprises, liquidity crises — are exactly the scenarios where automated systems fail in correlated ways.
3. **Accountability**: If the human places the trade, the human understands the trade. Advisory systems build understanding; automated systems build dependency.
4. **Alignment**: This maps directly to the Constitutional AI philosophy — the system proposes, the human ratifies. Scalable oversight requires a human in the loop until the system has demonstrated sufficient reliability to warrant increased autonomy.

The dashboard presents signals as recommendations with confidence levels, supporting evidence, and explicit risk/reward. The human decides what to execute and when.

---

## Parallels to AI Safety

| QuantPulse Mechanism | AI Safety Analog |
|---|---|
| Circuit breakers | Constitutional AI guardrails — hard limits that activate before catastrophic outcomes |
| Regime detection | Context-aware routing — system behavior changes based on environmental state |
| Human-in-the-loop execution | Scalable oversight — human ratification before irreversible actions |
| Adaptive parameters, no hardcoded thresholds | Avoiding brittle rule-following; generalizing to distributional shift |
| Shadow book + morning scorecard | Evaluation-first culture; measure actual outcomes, not just predicted ones |
| Quarter-Kelly with graduation path | Corrigibility — start conservative, earn autonomy through demonstrated reliability |

---

## What This Architecture Does Not Prevent

Honest disclosure of known limitations:

- **Regime misclassification**: The detector has ~2-bar lag. Fast transitions (e.g., March 2020 type selloffs) may not be caught in time.
- **Cointegration breakdown**: Pairs that were cointegrated can structurally decouple. The Hurst exponent monitor catches slow breakdowns; sudden ones (merger, bankruptcy) are not fully addressed.
- **Data source failure**: 11 external APIs. If multiple fail simultaneously, the pipeline runs on stale data. The staleness TTLs are conservative but not zero.
- **Black swan events**: No quant model handles truly unprecedented events. The Crisis regime reduces exposure but does not eliminate it.
