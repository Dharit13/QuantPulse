# What I Learned Building QuantPulse

Honest retrospective on v1 → v3. What worked, what didn't, and what v4 would look like.

---

## What Worked

**Adaptive parameters via VolContext eliminated manual tuning.** The biggest maintenance burden in v1 was recalibrating strategy thresholds after every volatility regime shift. Hardcoded thresholds that worked in a VIX-15 environment generated garbage signals in VIX-30. Moving to VolContext-derived parameters meant the system adjusted automatically. I haven't manually tuned a threshold since v2.

**Five regimes were worth the complexity.** The temptation was to use three (bull/bear/neutral). But the Bull Choppy vs Bull Trending distinction matters: momentum strategies bleed in choppy markets. And Crisis vs Bear Trending is critical — in a crisis, correlation goes to 1 and stat arb breaks down entirely. The extra complexity was justified.

**Circuit breakers caught strategy degradation before it compounded.** [Strategy] triggered a circuit breaker during [describe period]. The system paused automatically. This is exactly the behavior it was designed for — and it was unsettling how clearly the right call it was in retrospect.

**Prompt engineering for the overnight scanner required more iteration than the quantitative code.** Getting Claude to produce reliable, non-fabricated, properly-calibrated output required a 6-part prompt structure, explicit anti-hallucination rules, and a confidence rubric. The performance feedback loop (scorecard feeding back into the prompt) was the key insight — static prompts don't improve.

**Human-in-the-loop turned out to be a feature, not a limitation.** Originally conceived as a safety constraint, the advisory model actually produced better outcomes because the human review step caught several cases where the signal card looked right but the context was wrong (pending news event, sector-wide liquidity issue, etc.).

---

## What Didn't Work

**Gap reversion has insufficient sample size.** The strategy is sound — overnight gaps 1-5% fill 60-65% of the time. But the signal frequency is low and the filtering (non-catalyst, VIX < 30, historical fill rate > 60% per ticker) reduces the sample further. The shadow book has [N] completed trades for this strategy vs [M] for stat arb. Statistical conclusions are premature.

**Stat arb underperformed in low-correlation regimes.** When market-wide correlation drops (stocks moving independently rather than together), pairs that were historically cointegrated show more idiosyncratic behavior. The Hurst exponent monitoring catches slow breakdowns, but low-correlation regimes are a fundamentally harder environment for the strategy. The 20-bar lookback on the rolling correlation check may be too long to detect this quickly.

**Cross-asset signals are better as a filter than a strategy.** The cross-asset module works well for regime confirmation and as a veto on other strategies' signals. As a standalone signal generator for sector rotation, it underperformed — the lag from macro shift to equity sector repricing is too variable to time reliably.

**Data source reliability is a bigger operational issue than expected.** 11 external APIs means a meaningful chance of at least one being unavailable or rate-limited at any given time. The fallback logic is solid but the complexity of managing API key rotation, rate limits, and stale data TTLs across 11 sources is real ongoing overhead.

---

## What v4 Would Look Like

**Faster regime adaptation with exponential decay.** The current rolling-window approach for VolContext computation gives equal weight to all observations in the window. Exponential decay (recent data weighted more heavily) would detect regime transitions faster, reducing the ~2-bar detection lag.

**Strategy correlation monitoring at the portfolio level.** Currently each strategy monitors its own performance independently. But strategies can be correlated — if stat arb and gap reversion both rely on low-volatility conditions, a volatility spike hurts both simultaneously. v4 would monitor cross-strategy correlation and reduce total exposure when strategies become correlated.

**A/B testing framework for parameter changes.** Currently, a VolContext parameter change applies to all future signals. v4 would support running two parameter sets simultaneously in the shadow book, with statistical comparison of outcomes before promoting a change to production.

**MCP server for Claude to query portfolio state directly.** Currently Claude receives data as prompt context. A Model Context Protocol server exposing live portfolio state, strategy health, and regime data would allow Claude to ask questions of the system rather than receiving a static snapshot. This would enable richer analysis in the overnight scanner and better AI-assisted portfolio review.

**Shorter holding period for catalyst strategy, longer for stat arb.** Post-backtest analysis suggests the catalyst strategy's edge concentrates in days 2-5 post-earnings, not the 10-15 day window currently used. And stat arb mean reversion often requires more time than the current max hold allows. v4 would calibrate holding periods per strategy rather than using a shared default.

---

## Parallels to AI Systems Development

The problems in building QuantPulse are structurally similar to problems in building safe AI systems:

| QuantPulse Problem | AI Systems Analog |
|---|---|
| Strategies overfit to historical regimes | Models overfit to training distribution; fail on distributional shift |
| Circuit breakers catching strategy degradation | Constitutional AI guardrails; hard limits that activate before catastrophic outcomes |
| Adaptive parameters generalizing across regimes | Robustness to out-of-distribution inputs without manual intervention |
| Human-in-the-loop execution | Scalable oversight; human ratification before irreversible actions |
| Morning scorecard + performance feedback into prompt | RLHF / feedback loops; using outcome data to improve future behavior |
| Shadow book building evidence before graduating to half-Kelly | Corrigibility; earning autonomy through demonstrated reliability rather than assuming it |
| Prompt engineering for reliable structured output | Alignment; getting a capable system to behave in the specific constrained way you want |

The most surprising lesson: the hardest problems in quantitative finance and AI safety are not the capability problems. They're the alignment and evaluation problems — getting the system to do what you actually want, measuring whether it's doing it, and building feedback loops that improve behavior over time.
