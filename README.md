# QuantPulse v3 — Multi-Strategy Quantitative Trading Advisory System

QuantPulse is a signal-generation and decision-support system for quantitative equity trading. It does **not** place trades, connect to brokers, or move money. It is a human-in-the-loop advisory cockpit: the system generates high-conviction trade ideas backed by math, and the human decides what to execute.

## What we are trying to achieve

Most retail trading tools rely on indicators like RSI, MACD, and Bollinger Bands. These signals have zero alpha — everyone computes the same thing, so there is no informational edge. Institutions don't trade this way. They find **structural edges**: mispricings that exist for a mathematical reason (behavioral bias, information lag, mechanical flow, regulatory constraint) and persist because of capacity constraints or execution difficulty.

QuantPulse targets **risk-adjusted alpha** — portfolio Sharpe > 1.5, max drawdown < 15%, positive net returns after transaction costs over full evaluation cycles, with controlled drawdowns and explicit regime-aware de-risking in unfavorable environments. It combines multiple complementary signal engines: two core alpha strategies, one specialist tactical module, and two overlay/confirmation layers — each with a documented structural reason for why the edge exists. No single strategy carries the system. The return comes from diversification across complementary alpha streams, regime-aware capital allocation, and conservative position sizing that scales with validated edge strength.

Every signal in the system must answer three questions before it's allowed in:

1. **Why does this edge exist?** (structural reason, not pattern-matching)
2. **Why hasn't it been arbitraged away?** (capacity constraint, holding period, execution difficulty)
3. **What kills this edge?** (regime change, crowding, data disappearing)

## Signal engines

### Strategy 1: Statistical Arbitrage (Pairs/Baskets) — core alpha

Two stocks in the same sector share common risk factors. When their price spread diverges beyond what fundamentals justify, it mean-reverts. We find cointegrated pairs using three statistical tests (ADF, Engle-Granger, Johansen — require 2-of-3 to pass at p < 0.01), compute the half-life of mean reversion via the Ornstein-Uhlenbeck process, and trade the z-score of the spread. Pairs are filtered for minimum 252-day correlation > 0.70, liquidity > $5M daily volume, and ongoing Hurst exponent monitoring (H must stay < 0.5). The edge exists because of behavioral overreaction to single-stock news, ETF arbitrage mechanics, and institutional rebalancing flows.

### Strategy 2: Catalyst-Driven Event Trading — core alpha

Markets systematically misprice the magnitude and timing of catalysts. Post-Earnings Announcement Drift (PEAD) is one of the most well-documented anomalies in finance — stocks that beat earnings continue drifting in the same direction for 60+ days because analysts update estimates slowly and institutional mandates prevent immediate rebalancing. We score earnings surprises, analyst revision momentum, management guidance detection, insider buying clusters, and institutional options flow sweeps, with sector context from the regime engine. The edge persists because information diffusion is structurally slow.

### Strategy 3: Cross-Asset Regime Signals — allocation overlay

Equity sectors respond to macro signals (yields, VIX, commodities, credit, dollar, market breadth) with a lag. We track 9 cross-asset indicators, compute rolling z-scores against their 60-day distributions, and use the results to **tilt capital allocation and validate other strategies' signals** rather than generate direct trades. The specific sector mappings are treated as hypotheses to validate via walk-forward testing, not embedded truths. This strategy feeds the regime detection engine and provides advisory context on the dashboard.

### Strategy 4: Microstructure & Flow Imbalance — confirmation signal

When institutions need to move large blocks, they create temporary supply/demand imbalances invisible to retail. We detect institutional direction through options sweep flow (large call/put sweeps via SteadyAPI) and dark pool accumulation patterns (FINRA ATS weekly data showing persistent institutional buying). Note: FINRA ATS data is published with a 2-4 week delay, so dark pool signals are used as **swing-timeframe confirmation**, not real-time urgency triggers. Options sweep flow from SteadyAPI is near-real-time and more actionable for 3-10 day holds.

### Strategy 5: Overnight Gap Mean Reversion — specialist module

Overnight gaps are driven by futures and pre-market trading with thin liquidity. Gaps between 1-5% revert 60-65% of the time within the first 90 minutes of regular trading. We filter for non-catalyst gaps (earnings-driven gaps are continuation, not reversion), require historical fill rates above 60% per ticker, and gate on VIX < 30 (high-vol environments trend instead of reverting). The edge is structural: the liquidity differential between overnight and intraday sessions creates systematic overreaction.

## Evidence-enriched signal cards

Every signal goes through a three-layer enrichment pipeline before reaching the user. The system doesn't just say "this looks like a good trade" — it proves tradability, cites shadow evidence, and monitors strategy health. The enrichment framework is implemented; the evidence layer reaches full maturity once 90+ days of phantom history accumulate per active strategy.

```
Strategy generates TradeSignal
        │
        ▼
┌─────────────────────┐
│  Tradability Gate   │  %ADV check, slippage estimate,
│                     │  borrow heuristic, spread width
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Shadow Evidence    │  Similar phantom trades in last 90d:
│                     │  win rate, avg hold, realized Sharpe
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Strategy Health    │  Rolling 60d Sharpe, degradation
│                     │  detection, regime alignment
└────────┬────────────┘
         ▼
    EnrichedSignal
    final_recommendation: trade / conditional / do_not_trade
```

A signal card includes:

- **Tradability**: projected slippage (bps), position as % of daily volume, borrow availability for shorts, spread width check
- **Shadow evidence**: count of similar phantom trades, win rate, average P&L, average hold time, realized Sharpe — all from the last 90 days in the same regime
- **Strategy health**: rolling 60-day Sharpe from phantom outcomes, whether performance is deteriorating, regime alignment (favorable/neutral/unfavorable), automatic size reduction when conditions worsen
- **Final recommendation**: `trade` (all checks pass), `conditional_trade` (insufficient shadow data or degraded health), or `do_not_trade` (tradability fails or strategy paused)

## How it all fits together

```
                        ┌─────────────────────┐
                        │   Regime Detection   │
                        │ VIX + Breadth + ADX  │
                        │ + Cross-Asset Conf.  │
                        └────────┬────────────┘
                                 │ weights
          ┌──────────┬───────────┼───────────┐
          ▼          ▼           ▼           ▼
      Stat Arb   Catalyst     Flow    Gap Revert
       (core)    (core)     (confirm)  (specialist)
          │          │           │          │
          └──────────┴───────────┴──────────┘
                         ▼
              ┌────────────────────┐
              │  Enrichment Layer  │
              │  Tradability +     │
              │  Shadow Evidence + │
              │  Strategy Health   │
              └────────┬───────────┘
                       ▼
              ┌────────────────────┐
              │  Position Sizing   │
              │  Quarter-Kelly     │
              │  (regime-aware,    │
              │   vol-adjusted)    │
              └────────┬───────────┘
                       ▼
              ┌────────────────────┐
              │  Risk Management   │
              │  4-layer gate:     │
              │  Position →        │
              │  Strategy →        │
              │  Portfolio → Tail  │
              └────────┬───────────┘
                       ▼
              EnrichedSignal Card
              to Human Dashboard
```

The **Regime Detection Engine** classifies the market into one of five states (bull trending, bull choppy, bear trending, crisis, mean-reverting) using four indicator pillars. The regime determines how much capital each strategy receives — core alpha strategies receive larger allocations in favorable regimes, while specialist and tactical modules are reduced or disabled in crisis conditions, with cash allocation rising from 5% to 70%.

**Position Sizing** defaults to quarter-Kelly (conservative) until strategies are validated through paper trading. After 6+ months of shadow-book evidence, it can be upgraded to half-Kelly. It recalibrates from a rolling 100-trade window and is capped per-strategy to prevent concentration. An equal-risk budgeting mode is also available for maximum conservatism.

**Risk Management** runs four layers of checks before every trade: position limits (8% max), strategy circuit breakers (pause at -5% drawdown, shutdown at -10%), portfolio limits (gross exposure, net exposure, sector concentration, VaR, correlation, drawdown), and optional tail-risk overlays that may be activated in stress regimes subject to carry-cost constraints.

**Shadow Book** automatically logs every generated signal and creates phantom trades. The daily scheduler tracks what would have happened (stop hit, target hit, or timed out). This builds the evidence base needed to validate edges before increasing sizing, and feeds directly into the shadow evidence and strategy health modules.

## Validation infrastructure

- **Walk-forward backtesting**: rolling train/test windows with transaction costs (slippage, commission, short borrow via Almgren-Chriss model), statistical validation (Bonferroni correction, bootstrap Sharpe CI, permutation tests)
- **Paper-trade shadow book**: every signal auto-logged with regime/VIX/ATR context, phantom outcomes tracked daily, similar-signal lookups for evidence-based sizing
- **Strategy health monitoring**: rolling Sharpe from phantom outcomes, slippage deterioration detection, automatic pause when performance degrades
- **Backtest CLI**: `python scripts/run_backtest.py --strategy stat_arb --years 3` runs walk-forward backtests with tear sheets and statistical validation

## Stack

- **Backend**: Python 3.11+ / FastAPI
- **Frontend**: Streamlit
- **Data**: yfinance (free), FMP, SteadyAPI, FINRA ATS, SEC EDGAR (paid sources feature-flagged)
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **Live scan universe**: Dynamic S&P 500 from Wikipedia (cached weekly), no hardcoded watchlists
- **Backtest universe**: Must use point-in-time membership snapshots to avoid survivorship bias (live scan universe is NOT safe for backtesting)
- **No broker integration**: advisory only, human executes trades
