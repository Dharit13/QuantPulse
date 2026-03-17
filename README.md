# QuantPulse v2 — Multi-Strategy Quantitative Trading Advisory System

QuantPulse is a signal-generation and decision-support system for quantitative equity trading. It does **not** place trades, connect to brokers, or move money. It is a human-in-the-loop advisory cockpit: the system generates high-conviction trade ideas backed by math, and the human decides what to execute.

## What we are trying to achieve

Most retail trading tools rely on indicators like RSI, MACD, and Bollinger Bands. These signals have zero alpha — everyone computes the same thing, so there is no informational edge. Institutions don't trade this way. They find **structural edges**: mispricings that exist for a mathematical reason (behavioral bias, information lag, mechanical flow, regulatory constraint) and persist because of capacity constraints or execution difficulty.

QuantPulse targets **50%+ annual returns** by combining five independent, uncorrelated strategies — each with a documented structural reason for why the edge exists. No single strategy carries the target. The return comes from diversification across alpha streams, regime-aware capital allocation, and mathematically optimal position sizing.

Every signal in the system must answer three questions before it's allowed in:

1. **Why does this edge exist?** (structural reason, not pattern-matching)
2. **Why hasn't it been arbitraged away?** (capacity constraint, holding period, execution difficulty)
3. **What kills this edge?** (regime change, crowding, data disappearing)

## The five strategies

### Strategy 1: Statistical Arbitrage (Pairs/Baskets) — 8-15% contribution

Two stocks in the same sector share common risk factors. When their price spread diverges beyond what fundamentals justify, it mean-reverts. We find cointegrated pairs using three statistical tests (ADF, Engle-Granger, Johansen — require 2-of-3 to pass at p < 0.01), compute the half-life of mean reversion via the Ornstein-Uhlenbeck process, and trade the z-score of the spread. The edge exists because of behavioral overreaction to single-stock news, ETF arbitrage mechanics, and institutional rebalancing flows.

### Strategy 2: Catalyst-Driven Event Trading — 10-18% contribution

Markets systematically misprice the magnitude and timing of catalysts. Post-Earnings Announcement Drift (PEAD) is one of the most well-documented anomalies in finance — stocks that beat earnings continue drifting in the same direction for 60+ days because analysts update estimates slowly and institutional mandates prevent immediate rebalancing. We score earnings surprises, analyst revision momentum, insider buying clusters, and institutional options flow sweeps. The edge persists because information diffusion is structurally slow.

### Strategy 3: Cross-Asset Regime Momentum — 8-12% contribution

Equity sectors respond predictably to macro signals, but with a 1-5 day lag. When the 10Y yield rises sharply, financials outperform. When oil spikes, energy leads while airlines lag. When the VIX term structure inverts, equities sell off within days. We track 9 cross-asset indicators (yields, VIX, oil, gold, copper/gold ratio, dollar, credit spreads, market breadth), compute rolling z-scores against their 60-day distributions, and rotate into the sectors that historically benefit. Most equity-only traders ignore these signals entirely.

### Strategy 4: Microstructure & Flow Imbalance — 5-10% contribution

When institutions need to move large blocks, they create temporary supply/demand imbalances invisible to retail. We detect institutional urgency through options sweep flow (large call/put sweeps hitting multiple exchanges simultaneously via SteadyAPI) and dark pool accumulation patterns (FINRA ATS data showing persistent institutional buying). The edge exists because retail doesn't see this data, and the signal decays within 3-10 days as the information diffuses.

### Strategy 5: Overnight Gap Mean Reversion — 5-10% contribution

Overnight gaps are driven by futures and pre-market trading with thin liquidity. Gaps between 1-5% revert 60-65% of the time within the first 90 minutes of regular trading. We filter for non-catalyst gaps (earnings-driven gaps are continuation, not reversion), require historical fill rates above 60% per ticker, and gate on VIX < 30 (high-vol environments trend instead of reverting). The edge is structural: the liquidity differential between overnight and intraday sessions creates systematic overreaction.

## How it all fits together

```
                        ┌─────────────────────┐
                        │   Regime Detection   │
                        │ VIX + Breadth + ADX  │
                        │ + Cross-Asset Conf.  │
                        └────────┬────────────┘
                                 │ weights
          ┌──────────┬───────────┼───────────┬──────────┐
          ▼          ▼           ▼           ▼          ▼
      Stat Arb   Catalyst   Cross-Asset   Flow    Gap Revert
          │          │           │           │          │
          └──────────┴───────────┼───────────┴──────────┘
                                 ▼
                     ┌───────────────────────┐
                     │    Kelly Criterion     │
                     │  Half-Kelly Sizing     │
                     │  (regime-aware, vol-   │
                     │   adjusted, capped)    │
                     └───────────┬───────────┘
                                 ▼
                     ┌───────────────────────┐
                     │   Risk Management     │
                     │  4-layer gate:         │
                     │  Position → Strategy   │
                     │  → Portfolio → Tail    │
                     └───────────┬───────────┘
                                 ▼
                        Trade Signals to
                        Human Dashboard
```

The **Regime Detection Engine** classifies the market into one of five states (bull trending, bull choppy, bear trending, crisis, mean-reverting) using four indicator pillars. The regime determines how much capital each strategy receives — momentum gets 35% in a bull trend but 5% in crisis, while cash goes from 5% to 70%.

**Kelly Criterion** sizes each position optimally based on win rate and win/loss ratio, using half-Kelly for safety (sacrifices ~25% return for ~50% less variance). It recalibrates weekly from a rolling 100-trade window and is capped per-strategy to prevent concentration.

**Risk Management** runs four layers of checks before every trade: position limits (8% max), strategy circuit breakers (pause at -5% drawdown, shutdown at -10%), portfolio limits (gross exposure, net exposure, sector concentration, VaR, correlation, drawdown), and tail hedging (VIX calls + SPY puts for black swan protection).

## Stack

- **Backend**: Python 3.11+ / FastAPI
- **Frontend**: Streamlit
- **Data**: yfinance (free), FMP, SteadyAPI, FINRA ATS, SEC EDGAR (paid sources feature-flagged)
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **No broker integration**: advisory only, human executes trades
