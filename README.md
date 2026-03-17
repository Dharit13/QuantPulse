# QuantPulse v2 — Multi-Strategy Quantitative Trading Advisory System

QuantPulse is a signal-generation and decision-support system for quantitative equity trading. It does **not** place trades, connect to brokers, or move money. It is a human-in-the-loop advisory cockpit: the system generates high-conviction trade ideas backed by math, and the human decides what to execute.

## What we are trying to achieve

Most retail trading tools rely on indicators like RSI, MACD, and Bollinger Bands. These signals have zero alpha — everyone computes the same thing, so there is no informational edge. Institutions don't trade this way. They find **structural edges**: mispricings that exist for a mathematical reason (behavioral bias, information lag, mechanical flow, regulatory constraint) and persist because of capacity constraints or execution difficulty.

QuantPulse targets **risk-adjusted alpha** — portfolio Sharpe > 1.5, max drawdown < 15%, positive net returns after transaction costs across all regimes. It combines five independent, uncorrelated strategies, each with a documented structural reason for why the edge exists. No single strategy carries the system. The return comes from diversification across alpha streams, regime-aware capital allocation, and conservative position sizing that scales with validated edge strength.

Every signal in the system must answer three questions before it's allowed in:

1. **Why does this edge exist?** (structural reason, not pattern-matching)
2. **Why hasn't it been arbitraged away?** (capacity constraint, holding period, execution difficulty)
3. **What kills this edge?** (regime change, crowding, data disappearing)

## The five strategies

### Strategy 1: Statistical Arbitrage (Pairs/Baskets) — 8-15% contribution

Two stocks in the same sector share common risk factors. When their price spread diverges beyond what fundamentals justify, it mean-reverts. We find cointegrated pairs using three statistical tests (ADF, Engle-Granger, Johansen — require 2-of-3 to pass at p < 0.01), compute the half-life of mean reversion via the Ornstein-Uhlenbeck process, and trade the z-score of the spread. The edge exists because of behavioral overreaction to single-stock news, ETF arbitrage mechanics, and institutional rebalancing flows.

### Strategy 2: Catalyst-Driven Event Trading — 10-18% contribution

Markets systematically misprice the magnitude and timing of catalysts. Post-Earnings Announcement Drift (PEAD) is one of the most well-documented anomalies in finance — stocks that beat earnings continue drifting in the same direction for 60+ days because analysts update estimates slowly and institutional mandates prevent immediate rebalancing. We score earnings surprises, analyst revision momentum, insider buying clusters, and institutional options flow sweeps. The edge persists because information diffusion is structurally slow.

### Strategy 3: Cross-Asset Regime Signals — allocation overlay

Equity sectors respond to macro signals (yields, VIX, commodities, credit, dollar) with a lag. We track 9 cross-asset indicators, compute rolling z-scores against their 60-day distributions, and use the results to **tilt capital allocation and validate other strategies' signals** rather than generate direct trades. The specific sector mappings (e.g., "10Y up -> financials in 1-5 days") are treated as hypotheses to validate via walk-forward testing, not embedded truths. This strategy feeds the regime detection engine and provides advisory context on the dashboard.

### Strategy 4: Microstructure & Flow Imbalance — confirmation signal

When institutions need to move large blocks, they create temporary supply/demand imbalances invisible to retail. We detect institutional direction through options sweep flow (large call/put sweeps via SteadyAPI) and dark pool accumulation patterns (FINRA ATS weekly data showing persistent institutional buying). Note: FINRA ATS data is published with a 2-4 week delay, so dark pool signals are used as **swing-timeframe confirmation**, not real-time urgency triggers. Options sweep flow from SteadyAPI is near-real-time and more actionable for 3-10 day holds.

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
      Stat Arb   Catalyst     Flow    Gap Revert
       (core)    (core)     (confirm)  (specialist)
          │          │           │          │
          └──────────┴───────────┴──────────┘
                                 ▼
                     ┌───────────────────────┐
                     │  Position Sizing       │
                     │  Quarter-Kelly default │
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

**Position Sizing** defaults to quarter-Kelly (conservative) until strategies are validated through paper trading. After 6+ months of live shadow-book evidence, it can be upgraded to half-Kelly. It recalibrates from a rolling 100-trade window and is capped per-strategy to prevent concentration. An equal-risk budgeting mode is also available for maximum conservatism.

**Risk Management** runs four layers of checks before every trade: position limits (8% max), strategy circuit breakers (pause at -5% drawdown, shutdown at -10%), portfolio limits (gross exposure, net exposure, sector concentration, VaR, correlation, drawdown), and tail hedging (VIX calls + SPY puts for black swan protection).

## Stack

- **Backend**: Python 3.11+ / FastAPI
- **Frontend**: Streamlit
- **Data**: yfinance (free), FMP, SteadyAPI, FINRA ATS, SEC EDGAR (paid sources feature-flagged)
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **No broker integration**: advisory only, human executes trades
