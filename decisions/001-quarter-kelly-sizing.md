---
# ADR-001: Quarter-Kelly Position Sizing

## Status
Active

## Context
Position sizing has an outsized impact on long-run portfolio outcomes. Three common approaches exist: equal-weight (same dollar amount per trade), full Kelly (mathematically optimal for long-run growth), and fractional Kelly (a conservative scaling).

Full Kelly maximizes the geometric growth rate of the portfolio but requires precise estimates of win rate and edge — estimates that are only reliable after hundreds of trades. Using full Kelly on uncertain estimates produces severe drawdowns (50%+ swings are expected). Half-Kelly is the academic standard compromise but still amplifies estimation error.

We are in the track-record-building phase. The shadow book has been running for months, not years. Our Kelly estimates have wide confidence intervals.

## Decision
Use quarter-Kelly (Kelly fraction / 4) as the default sizing method. Cap at 8% of portfolio per position regardless of Kelly output. Recalibrate from a rolling 100-trade window per strategy.

## Reasoning
Quarter-Kelly preserves ~93-95% of the geometric growth rate of full Kelly while reducing variance by ~75%. It's the right tradeoff when edge estimates are uncertain: we lose little expected return but dramatically reduce drawdown risk.

Equal-weight was rejected because it ignores signal quality entirely — a high-confidence cointegrated pair should receive more capital than a marginal catalyst signal. The Kelly fraction encodes that confidence.

Full Kelly and half-Kelly were rejected because we haven't yet earned the track record that justifies them.

## Graduation Path
As the shadow book accumulates 200+ completed trades per strategy with stable win rates, individual strategies can graduate to half-Kelly. This requires passing a statistical significance test on rolling Sharpe (bootstrap CI must exclude 0 at 95% confidence).

## Consequences
- Lower expected returns in the short term vs half-Kelly
- Significantly reduced max drawdown
- System naturally becomes more aggressive as it builds a track record (graduation path)
- Each strategy has its own Kelly fraction — strategies with more phantom trade history can graduate independently
