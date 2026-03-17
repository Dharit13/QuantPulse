# CLAUDE.md — QuantPulse v2: Institutional-Grade Alpha Engine

> **Ambition**: 50%+ annual return target. This is not a retail screener — it is a multi-strategy quantitative trading system that thinks in terms of edge, expected value, regime awareness, and capital efficiency.
> **Philosophy**: Jane Street doesn't use RSI. They find **structural edges** — mispricings that exist for a mathematical reason, not a pattern-matching reason. Every signal in this system must answer: **why does this edge exist, and why hasn't it been arbitraged away?**
> **Owner**: Dharit — Senior Data Scientist, strong Python/ML, production systems experience
> **Stack**: Python (FastAPI) + Streamlit (MVP) + PostgreSQL (production) / SQLite (dev)

---

## Table of Contents

1. [Why the Previous Spec Fails at 50%](#1-why-the-previous-spec-fails)
2. [Core Philosophy: How Alpha Actually Works](#2-core-philosophy)
3. [Multi-Strategy Architecture](#3-multi-strategy-architecture)
4. [Strategy 1: Statistical Arbitrage (Pairs/Baskets)](#4-strategy-1-statistical-arbitrage)
5. [Strategy 2: Catalyst-Driven Event Trading](#5-strategy-2-catalyst-driven-event-trading)
6. [Strategy 3: Cross-Asset Regime Momentum](#6-strategy-3-cross-asset-regime-momentum)
7. [Strategy 4: Microstructure & Flow Imbalance](#7-strategy-4-microstructure--flow-imbalance)
8. [Strategy 5: Overnight Gap & Intraday Mean Reversion](#8-strategy-5-overnight-gap--intraday-mean-reversion)
9. [The Regime Detection Engine](#9-regime-detection-engine)
10. [Position Sizing: Kelly Criterion](#10-position-sizing-kelly-criterion)
11. [Risk Management: The Survival Layer](#11-risk-management)
12. [Signal Combination & Portfolio Construction](#12-signal-combination--portfolio-construction)
13. [Alpha Decay & Signal Freshness](#13-alpha-decay--signal-freshness)
14. [Data Infrastructure](#14-data-infrastructure)
15. [Backtesting: Walk-Forward Optimization](#15-backtesting)
16. [Full Directory Structure](#16-directory-structure)
17. [Pydantic Schemas](#17-schemas)
18. [Implementation Sprints](#18-implementation-sprints)
19. [Configuration & Environment](#19-configuration)
20. [The Math Appendix](#20-math-appendix)

---

## 1. Why the Previous Spec Fails at 50%

The v1 spec was a stock screener with RSI, MACD, and Bollinger Bands. Here is why it will never make 50%:

**Problem 1: Signals with no structural edge.** RSI > 70 means "overbought" to retail traders. To institutions it means "strong momentum, likely to continue." Everyone can compute RSI. If everyone has the same signal, it has zero alpha. The signal must be derived from information asymmetry or structural market mechanics.

**Problem 2: Single strategy, single timeframe.** One strategy has one equity curve. In bad regimes, it bleeds. A 50% target requires multiple uncorrelated strategies so when one is flat, another is printing.

**Problem 3: Equal position sizing.** Putting the same amount in every trade is the dumbest possible capital allocation. A 90% confidence signal should get 5x the capital of a 55% confidence signal. Kelly criterion or bust.

**Problem 4: No regime awareness.** A momentum strategy that works in a bull market will destroy you in a choppy market. The system must detect the current regime (trending, mean-reverting, crisis) and dynamically shift strategy weights.

**Problem 5: No statistical rigor.** "RSI < 30 = buy" has never been validated with proper out-of-sample testing, walk-forward optimization, or correction for multiple hypothesis testing. Every signal must survive p < 0.01 after Bonferroni correction.

**What changes in v2:**
- 5 independent strategies, each with a structural reason for existing
- Regime detection that shifts capital allocation dynamically
- Kelly criterion position sizing with half-Kelly safety margin
- Walk-forward backtesting with proper statistical validation
- Cross-asset signals (bonds, VIX, commodities predict equities)
- Market microstructure signals (order flow imbalance, dark pool)
- Proper risk decomposition and portfolio-level drawdown controls

---

## 2. Core Philosophy

### The Three Questions Every Signal Must Answer

Before adding ANY signal to the system, it must pass this test:

1. **Why does this edge exist?** (Structural reason: behavioral bias, information lag, mechanical flow, regulatory constraint)
2. **Why hasn't it been arbitraged away?** (Capacity constraint, capital requirement, holding period, execution difficulty)
3. **What kills this edge?** (Regime change, crowding, data source disappearing, regulatory change)

If you can't answer all three, the signal is noise.

### Return Decomposition Target

```
Target annual return: 50%+
Decomposition:
├── Strategy 1: Stat Arb (pairs/baskets)      →  8-15% contribution
├── Strategy 2: Catalyst/Event Trading         → 10-18% contribution
├── Strategy 3: Cross-Asset Regime Momentum    →  8-12% contribution
├── Strategy 4: Microstructure/Flow Imbalance  →  5-10% contribution
├── Strategy 5: Overnight Gap / Intra-day MR   →  5-10% contribution
├── Kelly Sizing Alpha (vs equal sizing)       →  5-8% boost
└── Regime Timing Alpha (avoiding drawdowns)   →  3-5% saved
                                         Total → ~50-70% gross
                                  Minus costs  → ~45-55% net
```

No single strategy carries the target. Diversification across uncorrelated alpha streams is the path.

### Capital Allocation by Regime

| Regime | Stat Arb | Catalyst | Momentum | Flow | Intraday | Cash |
|--------|---------|----------|----------|------|----------|------|
| **Bull trending** | 15% | 25% | 35% | 10% | 10% | 5% |
| **Bull choppy** | 30% | 20% | 10% | 15% | 20% | 5% |
| **Bear trending** | 20% | 15% | 25% (short) | 10% | 10% | 20% |
| **Crisis/vol spike** | 10% | 5% | 5% | 5% | 5% | 70% |
| **Mean-reverting** | 35% | 15% | 5% | 15% | 25% | 5% |

---

## 3. Multi-Strategy Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     REGIME DETECTION ENGINE                          │
│  VIX level + term structure │ Yield curve │ Breadth │ Correlation    │
│  Output: {bull_trend, bull_chop, bear_trend, crisis, mean_revert}   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ regime weights
        ┌───────────┬───────────┼───────────┬───────────┐
        ▼           ▼           ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Stat Arb │ │ Catalyst │ │ Cross-   │ │ Micro-   │ │ Intraday │
│ Pairs &  │ │ Event    │ │ Asset    │ │ structure│ │ Gap &    │
│ Baskets  │ │ Trading  │ │ Regime   │ │ & Flow   │ │ Mean Rev │
│          │ │          │ │ Momentum │ │ Imbalance│ │          │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
     │             │            │             │             │
     └─────────────┴────────────┴─────────────┴─────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  PORTFOLIO            │
                    │  CONSTRUCTION         │
                    │  Kelly sizing ×       │
                    │  regime weight ×      │
                    │  correlation adj      │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  RISK MANAGEMENT      │
                    │  Max drawdown: -15%   │
                    │  Position limit: 8%   │
                    │  Sector limit: 25%    │
                    │  Correlation check    │
                    │  VaR: 2% daily        │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  EXECUTION ENGINE     │
                    │  Smart routing        │
                    │  Slippage model       │
                    │  Transaction cost     │
                    └───────────────────────┘
```

---

## 4. Strategy 1: Statistical Arbitrage (Pairs/Baskets)

### Why This Edge Exists
Two stocks in the same sector share common risk factors. When they diverge beyond what fundamentals justify, the spread mean-reverts. This works because: (a) behavioral overreaction to single-stock news, (b) ETF arbitrage forces keep sector relationships anchored, (c) institutional rebalancing creates predictable flows.

### Implementation

```python
# backend/strategies/stat_arb.py

"""
Statistical Arbitrage — Pairs & Basket Trading

FINDING PAIRS:
1. Universe: S&P 500 stocks, grouped by GICS sub-industry
2. For each pair within same sub-industry:
   a. Run Augmented Dickey-Fuller (ADF) test on price spread
   b. Run Engle-Granger cointegration test
   c. Run Johansen cointegration test (for baskets of 3+)
   d. Require: p-value < 0.01 on at least 2 of 3 tests
   e. Compute half-life of mean reversion using Ornstein-Uhlenbeck process:
      half_life = -ln(2) / ln(β) where β is AR(1) coefficient of spread
   f. Require: 3 days < half-life < 30 days (too fast = noise, too slow = no edge)
3. Re-validate pairs monthly. Pairs that lose cointegration are dropped.

TRADING SIGNALS:
- Compute z-score of current spread vs rolling 60-day mean and std:
    z = (spread_t - mean_60d) / std_60d
- Entry: |z| > 2.0 (2-sigma divergence)
- Exit: |z| < 0.5 (spread reverted near mean)
- Stop-loss: |z| > 3.5 (divergence worsening, cointegration may be breaking)
- Direction: if z > 2.0 → short the outperformer, long the underperformer

POSITION SIZING:
- Size inversely proportional to half-life (faster mean-reversion = larger position)
- Apply Kelly criterion based on historical win rate and avg win/loss for this pair
- Max 4% of capital per pair, max 20% total in stat arb

EDGE DECAY MONITORING:
- Track rolling 60-day Hurst exponent of each pair's spread
  H < 0.5 → mean-reverting (good), H > 0.5 → trending (bad, reduce/exit)
- If a pair's Sharpe drops below 0.5 over trailing 60 days, pause it

EXPECTED: 15-25 active pairs at any time, 60-70% win rate, avg hold 5-12 days
"""

PAIR_SELECTION_CRITERIA = {
    "min_adf_pvalue": 0.01,
    "min_coint_pvalue": 0.01,
    "min_half_life_days": 3,
    "max_half_life_days": 30,
    "min_correlation": 0.70,       # Minimum rolling 252-day correlation
    "min_avg_dollar_volume": 5e6,  # Both legs must be liquid
    "entry_z": 2.0,
    "exit_z": 0.5,
    "stop_z": 3.5,
    "max_position_pct": 0.04,      # 4% per pair
    "max_strategy_pct": 0.20,      # 20% total allocation to stat arb
    "revalidation_interval_days": 30,
}
```

### Key Libraries
- `statsmodels.tsa.stattools.adfuller` — ADF test
- `statsmodels.tsa.stattools.coint` — Engle-Granger cointegration
- `statsmodels.tsa.vector_ar.vecm.coint_johansen` — Johansen test
- `hurst` package — Hurst exponent for mean-reversion detection

---

## 5. Strategy 2: Catalyst-Driven Event Trading

### Why This Edge Exists
Markets systematically misprice the magnitude and timing of catalysts. Earnings drift (PEAD — Post-Earnings Announcement Drift) is one of the most well-documented anomalies in finance. Stocks that beat earnings continue to drift in the same direction for 60+ days. Similarly, analyst upgrades/downgrades have predictable follow-through that the market prices in too slowly.

### Implementation

```python
# backend/strategies/catalyst_event.py

"""
Catalyst-Driven Event Trading

SUB-STRATEGY A: Earnings Drift (PEAD)
1. After earnings, compute: EPS surprise % = (actual - estimate) / |estimate|
2. If surprise > +5% AND stock gapped up > 2% on earnings day:
   → Enter LONG at next day's open
   → Target: +8-12% over 20-40 trading days
   → Stop: -5% from entry
   → WHY: Post-earnings drift is the most persistent anomaly, documented since 1968.
     It exists because: (a) analysts update estimates slowly, (b) institutional
     mandate constraints prevent immediate rebalancing, (c) retail under-reacts to
     magnitude of surprise.

3. If surprise < -5% AND stock gapped down > 2%:
   → Enter SHORT (if shortable and borrowable)
   → Same parameters, inverted

SCORING EARNINGS TRADES:
- surprise_magnitude: |surprise %| — bigger = stronger drift
- estimate_revision_trend: Were estimates being revised up before the beat? Continuation signal.
- guidance: Did management raise guidance? Strongest signal when surprise + guidance raise.
- sector_context: Is the sector in a positive regime? (from regime engine)
- historical_drift: Does this stock historically have strong PEAD? (backtest per-ticker)

SUB-STRATEGY B: Analyst Revision Momentum
1. Track all analyst estimate revisions daily (via FMP or Finnhub)
2. Compute: revision_breadth = (upgrades - downgrades) / total_analysts over trailing 30 days
3. Compute: revision_acceleration = current 15-day breadth - previous 15-day breadth
4. Entry: breadth > 0.3 AND acceleration > 0.1 AND stock not yet moved > 5%
   → The estimates are being revised up, but the stock hasn't fully priced it in yet
5. Expected hold: 2-6 weeks until next earnings or price target adjustment

SUB-STRATEGY C: Institutional Flow Events
(Requires paid data — Unusual Whales / similar)
1. Detect: large call sweeps (>$500K premium) in short-dated options (< 14 DTE)
2. This signals: institution is making a time-sensitive directional bet
3. Entry: follow the sweep direction, enter stock within 1 trading day
4. Expected hold: 3-10 days (match the option expiry window)
5. Stop: -3% from entry (these are high-conviction, tight-stop trades)
"""

EARNINGS_DRIFT_PARAMS = {
    "min_eps_surprise_pct": 5.0,
    "min_earnings_day_gap_pct": 2.0,
    "target_return_pct": 10.0,
    "stop_loss_pct": 5.0,
    "max_hold_days": 40,
    "min_hold_days": 5,
    "max_position_pct": 0.06,      # 6% per trade (higher conviction)
    "max_strategy_pct": 0.25,
}

REVISION_MOMENTUM_PARAMS = {
    "min_breadth": 0.3,
    "min_acceleration": 0.1,
    "max_price_moved_pct": 5.0,    # Don't chase if already moved
    "max_hold_days": 30,
    "stop_loss_pct": 4.0,
    "max_position_pct": 0.04,
}
```

---

## 6. Strategy 3: Cross-Asset Regime Momentum

### Why This Edge Exists
Equity sectors respond predictably to macro signals, but with a lag. When the 10Y yield rises sharply, financials outperform with a 1-3 day lag. When oil spikes, energy leads while airlines lag. When VIX term structure inverts, the S&P sells off within 1-5 days. Most equity-only traders ignore these cross-asset signals entirely.

### Implementation

```python
# backend/strategies/cross_asset_momentum.py

"""
Cross-Asset Regime Momentum

CROSS-ASSET SIGNAL MAP (empirically validated relationships):
┌─────────────────────────────┬──────────────────────────────────────┐
│ Signal                      │ Equity Impact (with lag)             │
├─────────────────────────────┼──────────────────────────────────────┤
│ 10Y yield rising fast       │ Long financials, short utilities     │
│ 10Y yield falling fast      │ Long utilities/REITs, short banks   │
│ Yield curve steepening      │ Long small caps, long cyclicals      │
│ Yield curve inverting       │ Risk-off: long defensive, short beta │
│ Oil > 2σ move up            │ Long energy, short airlines/transpo  │
│ Oil > 2σ move down          │ Short energy, long consumer disc     │
│ Dollar (DXY) strengthening  │ Short EM, short multinationals       │
│ Dollar weakening            │ Long EM, long materials/commodities  │
│ VIX term structure invert   │ Hedge: long VIX calls, reduce equity │
│ VIX crush (post-event)      │ Sell vol, go long equity             │
│ Credit spreads widening     │ Risk-off: short HY, long quality     │
│ Gold breakout               │ Inflation hedge: long miners, TIPS   │
│ Copper/Gold ratio rising    │ Risk-on: long cyclicals              │
│ Copper/Gold ratio falling   │ Risk-off: long defensives            │
└─────────────────────────────┴──────────────────────────────────────┘

IMPLEMENTATION:
1. Track these cross-asset indicators daily:
   - Treasury yields: ^TNX (10Y), ^FVX (5Y), ^IRX (13W) → compute curve slope
   - Volatility: ^VIX, VIX futures (VX1, VX2) → compute term structure
   - Commodities: CL=F (oil), GC=F (gold), HG=F (copper)
   - Dollar: DX-Y.NYB (DXY)
   - Credit: HYG, LQD → compute HY spread via HYG/LQD ratio
   - Breadth: % stocks above 200 SMA, advance/decline ratio

2. For each signal, compute z-score vs trailing 60-day distribution
3. When a cross-asset signal fires (|z| > 1.5):
   → Apply the corresponding sector rotation via sector ETFs or top liquid stocks
   → Size based on signal z-score and regime context
   → Expected hold: 3-15 days (until z-score normalizes)

POSITION SIZING:
- Sector ETF trades: 3-5% per position
- Individual stock expression of macro theme: 2-3% per position
- Max 15% total in cross-asset trades
"""

CROSS_ASSET_INSTRUMENTS = {
    "yields": {"10y": "^TNX", "5y": "^FVX", "2y": "^IRX"},
    "volatility": {"vix": "^VIX"},
    "commodities": {"oil": "CL=F", "gold": "GC=F", "copper": "HG=F"},
    "dollar": {"dxy": "DX-Y.NYB"},
    "credit": {"hy": "HYG", "ig": "LQD"},
    "breadth": {"sp500_above_200sma": None},  # Computed from constituent data
}
```

---

## 7. Strategy 4: Microstructure & Flow Imbalance

### Why This Edge Exists
When institutions need to move large blocks, they create temporary supply/demand imbalances. Dark pool prints at specific price levels create support/resistance that doesn't show on public charts. Options market makers must delta-hedge, creating predictable stock buying/selling at specific price levels (gamma exposure). Retail doesn't see any of this.

```python
# backend/strategies/flow_imbalance.py

"""
Microstructure & Flow Imbalance
(Requires paid data: Unusual Whales + Polygon)

SUB-STRATEGY A: GEX (Gamma Exposure) Pin Risk
1. Compute net gamma exposure at each strike price from open interest data
2. Large positive GEX at a strike → price will be "pinned" near that strike
   (because market makers hedge by buying dips and selling rallies)
3. Large negative GEX → price will be "repelled" from that level
   (market makers amplify moves, creating acceleration)
4. Trade: Mean-revert when near positive GEX strikes, momentum when near negative GEX
5. Re-compute daily after options data refresh

SUB-STRATEGY B: Dark Pool Level Trading
1. Track significant dark pool prints (>$1M notional) via Unusual Whales
2. Cluster prints by price level
3. Heavy print clusters → institutional support/resistance
4. Trade: Buy when price pulls back to a heavy buy-side cluster
         Short when price rallies to a heavy sell-side cluster
5. Confirm with public volume at the same level

SUB-STRATEGY C: Unusual Options Volume
1. Detect stocks with options volume > 3x 20-day average
2. Filter: call/put ratio skew AND premium weighted direction
3. If net call premium > $5M in a single day AND no known catalyst:
   → Something is happening that isn't public yet
   → Enter long, tight stop (-3%), hold up to 10 days
4. Win rate historically: 55-60%, but winners are 2-3x losers
"""
```

---

## 8. Strategy 5: Overnight Gap & Intraday Mean Reversion

### Why This Edge Exists
Overnight gaps are driven by futures/pre-market with thin liquidity. Gaps > 1σ revert 60-65% of the time within the first 90 minutes of trading. This is one of the most mechanically reliable short-term signals because it exploits the structural difference between overnight and intraday liquidity.

```python
# backend/strategies/gap_reversion.py

"""
Overnight Gap Mean Reversion

LOGIC:
1. At 9:25 AM EST (pre-market), compute for each stock in universe:
   gap_pct = (premarket_price - prev_close) / prev_close

2. Filter: |gap_pct| > 1.0% AND |gap_pct| < 5.0%
   (Gaps > 5% are usually catalyst-driven and DON'T revert)

3. Additional filters for gap-fill trades:
   - No earnings/catalyst in last 24 hours (catalyst gaps = continuation, not reversion)
   - Volume in first 5 min must exceed 1.5x avg first-5-min volume (confirms liquidity)
   - VIX < 30 (high-VIX environments = trends, not reversions)
   - Stock must have historical gap-fill rate > 60% (backtest per-ticker)

4. Entry: At market open (9:31 AM)
   - Gap UP → Short (betting on gap fill)
   - Gap DOWN → Long (betting on gap fill)

5. Target: Previous close (full gap fill) — or 50% gap fill for partial target
6. Stop: 50% of gap size in the WRONG direction
   (e.g., stock gapped up 2%, stop if it goes up another 1% → total 3% gap expansion)
7. Time stop: Close any open position at 11:00 AM regardless (don't hold through lunch)

SIZING: Small positions (1-2% each) because these are high-frequency, low-hold-time trades.
Expect 3-8 trades per day, 60% win rate, 1.3:1 avg win/loss.
"""
```

---

## 9. The Regime Detection Engine

This is the brain that tells every strategy how much capital to use.

```python
# backend/regime/detector.py

"""
Regime Detection Engine

Classifies the current market into one of 5 regimes using a combination of
quantitative indicators. The regime determines strategy capital allocation.

INDICATORS (weighted equally):

1. VIX Level + Term Structure (25%)
   - VIX < 15 AND term structure in contango → "bull_trend"
   - VIX 15-25 AND term structure flat → "bull_choppy"
   - VIX 25-35 AND term structure in backwardation → "bear_trend"
   - VIX > 35 → "crisis"

2. Market Breadth (25%)
   - % S&P 500 stocks above 200-day SMA
   - > 70% → "bull_trend"
   - 50-70% → "bull_choppy"
   - 30-50% → "bear_trend" or "mean_reverting" (check other indicators)
   - < 30% → "crisis"

3. Trend Strength — ADX of SPY (25%)
   - ADX > 30 AND DI+ > DI- → "bull_trend"
   - ADX > 30 AND DI- > DI+ → "bear_trend"
   - ADX < 20 → "mean_reverting"
   - ADX 20-30 → "bull_choppy" or "mean_reverting"

4. Cross-Asset Confirmation (25%)
   - Yield curve slope (10Y - 2Y)
   - Credit spreads (HYG - LQD)
   - If yields normal + spreads tight → risk-on environment
   - If curve inverting + spreads widening → risk-off

REGIME PERSISTENCE:
- Regime must hold for 3 consecutive days to trigger a switch
- This prevents whipsawing on single-day volatility spikes
- Exception: VIX > 40 triggers immediate "crisis" mode (1-day override)

REGIME TRANSITION MATRIX:
- bull_trend ↔ bull_choppy: gradual, adjust weights over 5 days
- bull_* → bear_trend: aggressive de-risk over 2 days
- any → crisis: IMMEDIATE. Cut equity exposure to 30% within 1 day.
- crisis → any: gradual re-entry over 10 days (don't rush back in)
"""

REGIMES = ["bull_trend", "bull_choppy", "bear_trend", "crisis", "mean_reverting"]

STRATEGY_WEIGHTS = {
    "bull_trend":    {"stat_arb": 0.15, "catalyst": 0.25, "momentum": 0.35, "flow": 0.10, "intraday": 0.10, "cash": 0.05},
    "bull_choppy":   {"stat_arb": 0.30, "catalyst": 0.20, "momentum": 0.10, "flow": 0.15, "intraday": 0.20, "cash": 0.05},
    "bear_trend":    {"stat_arb": 0.20, "catalyst": 0.15, "momentum": 0.25, "flow": 0.10, "intraday": 0.10, "cash": 0.20},
    "crisis":        {"stat_arb": 0.10, "catalyst": 0.05, "momentum": 0.05, "flow": 0.05, "intraday": 0.05, "cash": 0.70},
    "mean_reverting":{"stat_arb": 0.35, "catalyst": 0.15, "momentum": 0.05, "flow": 0.15, "intraday": 0.25, "cash": 0.05},
}
```

---

## 10. Position Sizing: Kelly Criterion

This is the single biggest alpha generator after signal quality. Equal sizing leaves 30-40% of potential return on the table.

```python
# backend/risk/kelly.py

"""
Kelly Criterion Position Sizing

For each trade, compute the optimal fraction of capital to risk:

    Full Kelly: f* = (p × b - q) / b

    where:
        p = probability of winning (from backtest or model confidence)
        q = 1 - p = probability of losing
        b = win/loss ratio (avg win size / avg loss size)

CRITICAL: We use HALF-KELLY (f*/2) in production.
- Full Kelly maximizes geometric growth but has brutal drawdowns
- Half-Kelly sacrifices ~25% of return for ~50% less drawdown volatility
- This is what Ed Thorp, the godfather of quant trading, recommends

IMPLEMENTATION:
1. For each strategy, maintain a rolling window of last 100 trades
2. Compute p (win rate) and b (win/loss ratio) from this window
3. Compute f* = (p*b - q) / b
4. Apply half-Kelly: position_size = (f* / 2) × total_capital
5. Cap at per-trade maximum (see risk limits below)
6. If f* is negative → the strategy has negative expected value → DO NOT TRADE

PER-STRATEGY KELLY PARAMETERS (bootstrapped from backtests):
- Stat arb pairs:    Expected p=0.65, b=1.2  → f*=0.28, half-Kelly=0.14
- Earnings drift:    Expected p=0.58, b=1.8  → f*=0.34, half-Kelly=0.17
- Revision momentum: Expected p=0.55, b=1.5  → f*=0.18, half-Kelly=0.09
- Cross-asset:       Expected p=0.52, b=2.0  → f*=0.14, half-Kelly=0.07
- Flow imbalance:    Expected p=0.55, b=2.0  → f*=0.22, half-Kelly=0.11
- Gap reversion:     Expected p=0.62, b=1.3  → f*=0.24, half-Kelly=0.12

These are initial estimates. The system recalibrates f* weekly using rolling trade results.
"""
```

---

## 11. Risk Management: The Survival Layer

50% returns mean nothing if you blow up once. Survival comes first.

```python
# backend/risk/manager.py

"""
Multi-Layer Risk Management

LAYER 1: POSITION-LEVEL LIMITS
- Max position size: 8% of capital (even if Kelly says more)
- Mandatory stop-loss on every trade (no exceptions)
- Time stops: every strategy has a max hold period

LAYER 2: STRATEGY-LEVEL LIMITS
- Max allocation per strategy: set by regime engine (see table above)
- Strategy drawdown circuit breaker:
  If a strategy draws down > 5% in a rolling 20-day window → PAUSE for 5 days
  If drawdown > 10% → PAUSE for 20 days and re-validate signals

LAYER 3: PORTFOLIO-LEVEL LIMITS
- Max gross exposure: 200% (allows 2x leverage in high-conviction regimes)
- Max net exposure: +80% to -30% (always maintain some directionality control)
- Max sector concentration: 25% of capital in any single sector
- Max correlation: No two positions with > 0.8 trailing 60-day correlation
  (if adding a correlated trade, reduce existing position first)
- Daily VaR limit: 2% of capital at 95% confidence
  (if VaR exceeds 2%, de-risk the portfolio proportionally)
- Max portfolio drawdown: -15% from peak
  → At -10%: reduce all positions by 30%, shift to crisis weights
  → At -15%: flatten to 80% cash, only keep highest-conviction trades

LAYER 4: BLACK SWAN PROTECTION
- Maintain 2-5% of capital in long VIX calls or SPY puts at all times (tail hedge)
- This costs ~3-5% per year in premium decay but protects against -20% days
- Rebalance monthly: buy 30-delta puts, 60-90 DTE, on SPY

IMPLEMENTATION:
- Risk checks run BEFORE every trade entry
- Real-time P&L monitoring during market hours
- Hard circuit breakers cannot be overridden by any strategy
"""

RISK_LIMITS = {
    "max_position_pct": 0.08,
    "max_gross_exposure": 2.00,
    "max_net_exposure_long": 0.80,
    "max_net_exposure_short": -0.30,
    "max_sector_pct": 0.25,
    "max_correlation_between_positions": 0.80,
    "daily_var_limit_pct": 0.02,
    "max_portfolio_drawdown_pct": -0.15,
    "reduce_at_drawdown_pct": -0.10,
    "flatten_at_drawdown_pct": -0.15,
    "tail_hedge_pct": 0.03,          # 3% of capital in puts
    "strategy_pause_drawdown_pct": -0.05,
    "strategy_shutdown_drawdown_pct": -0.10,
}
```

---

## 12. Signal Combination & Portfolio Construction

```python
# backend/portfolio/constructor.py

"""
Portfolio Construction

STEP 1: Collect all active trade signals from all 5 strategies
STEP 2: For each signal, compute:
  - Kelly-optimal position size (half-Kelly)
  - Strategy weight from regime engine
  - Adjusted size = kelly_size × regime_weight
STEP 3: Check correlation matrix of proposed portfolio
  - If two proposed trades have >0.7 correlation → keep the one with higher Sharpe
STEP 4: Apply risk limits (position, sector, VaR caps)
STEP 5: Compute expected portfolio Sharpe:
  portfolio_sharpe = sum(weight_i × sharpe_i) / sqrt(sum(weight_i² × var_i + cross_terms))
  Target: portfolio Sharpe > 2.0
STEP 6: If portfolio Sharpe < 1.5, the overall signal quality is too weak → increase cash

REBALANCING:
- Strategy signals are evaluated: stat_arb (hourly), catalyst (daily),
  momentum (daily), flow (hourly during market), intraday (real-time)
- Portfolio-level rebalance: daily at 9:00 AM before market open
- Emergency rebalance: triggered by risk limit breach
"""
```

---

## 13. Alpha Decay & Signal Freshness

```python
# backend/signals/decay.py

"""
Alpha Decay Monitoring

Every signal decays over time as more market participants discover it.
Track the rolling Sharpe ratio of each signal over multiple windows:

- 30-day rolling Sharpe
- 90-day rolling Sharpe
- 252-day rolling Sharpe

ALERT SYSTEM:
- If 30-day Sharpe drops below 0.5 → WARNING: signal may be decaying
- If 90-day Sharpe drops below 0.3 → CRITICAL: reduce allocation by 50%
- If 252-day Sharpe is negative → KILL: disable the signal, investigate

SIGNAL CROWDING DETECTION:
- Track correlation of our strategy returns with popular ETFs (MTUM, VLUE, QUAL)
- If correlation > 0.6 → our signals are crowded, reduce sizing
- Track short interest and borrow costs for our short positions
- Rising borrow costs = crowded short, risk of squeeze

NEW SIGNAL RESEARCH:
- Reserve 5% of capital for "paper trading" new signal candidates
- Run them in shadow mode for 60 days before allocating real capital
- Require: positive Sharpe, > 50 trades, p < 0.05 after multiple testing correction
"""
```

---

## 14. Data Infrastructure

### Required Data (with upgrade tiers from previous spec)

| Data | Free Source | Paid Source | Refresh | Used By |
|------|-----------|-------------|---------|---------|
| Daily OHLCV | yfinance | Polygon ($29) | 1hr | All strategies |
| 1-min intraday bars | — | Polygon ($79) | Real-time | Gap reversion, flow |
| Fundamentals | yfinance + FMP | FMP paid ($14) | 24hr | Catalyst, stat arb |
| Earnings calendar | FMP | FMP paid | 24hr | Catalyst |
| Analyst revisions | Finnhub | Finnhub paid ($50) | 4hr | Catalyst |
| News + sentiment | Finnhub + FinBERT | Finnhub paid | 4hr | All strategies |
| Options chain + OI | — | Polygon ($79) | 1hr | GEX, flow |
| Options flow | — | Unusual Whales ($50) | 30min | Flow imbalance |
| Dark pool prints | — | Unusual Whales | 30min | Flow imbalance |
| 13F institutional | — | Unusual Whales | Quarterly | Catalyst |
| Congress trades | — | Unusual Whales / Quiver ($25) | Daily | Catalyst |
| Treasury yields | yfinance (^TNX) | — | 1hr | Regime, cross-asset |
| VIX + futures | yfinance (^VIX) | Polygon | 15min | Regime |
| Commodities | yfinance (CL=F, GC=F) | — | 1hr | Cross-asset |
| S&P constituents | Wikipedia/GitHub | — | Weekly | Universe |

### Minimum Viable Paid Stack: ~$130/mo
Polygon Starter ($29) + FMP Starter ($14) + Finnhub paid ($50) + Unusual Whales ($50)

This gives you: real-time prices, fundamentals, news sentiment, options flow, dark pool, and institutional holdings — enough to run all 5 strategies.

---

## 15. Backtesting: Walk-Forward Optimization

```python
# backend/backtest/walk_forward.py

"""
Walk-Forward Optimization (WFO)

NEVER use simple backtest (train on all data, test on all data). It overfits.

WALK-FORWARD PROTOCOL:
1. Split data into N windows (e.g., 24 months train + 6 months test, rolling)
2. For each window:
   a. TRAIN: Optimize signal parameters on in-sample data
   b. TEST: Run the strategy with frozen parameters on out-of-sample data
   c. Record out-of-sample returns
3. Final performance = concatenation of ALL out-of-sample periods
4. This gives you a realistic estimate of live performance

MULTIPLE HYPOTHESIS CORRECTION:
- If testing N different signal variants, apply Bonferroni correction:
  Required p-value = 0.05 / N
- Or use the Holm-Bonferroni step-down procedure (less conservative)
- A signal that "works" at p=0.03 with N=20 variants is NOT significant

TRANSACTION COST MODEL:
- Commission: $0.005/share (Interactive Brokers rate)
- Slippage: 0.05% per trade (conservative for liquid large-caps)
- Short borrow cost: 0.5% annualized for easy-to-borrow, 5%+ for hard-to-borrow
- Market impact: for positions > 1% of ADV, apply Almgren-Chriss model

REQUIRED MINIMUM STATS FOR A LIVE SIGNAL:
- Sharpe ratio > 1.5 (out-of-sample)
- Win rate > 50% (or win rate > 40% with win/loss ratio > 2.0)
- Profit factor > 1.5
- Max drawdown < 15%
- > 100 trades in out-of-sample period
- p-value < 0.01 after multiple testing correction
- Positive performance in at least 60% of rolling 6-month windows
"""
```

---

## 16. Full Directory Structure

```
quantpulse/
├── CLAUDE.md
├── .env / .env.example
├── requirements.txt
├── pyproject.toml
│
├── backend/
│   ├── main.py                        # FastAPI app
│   ├── config.py                      # All settings and constants
│   ├── scheduler.py                   # APScheduler jobs
│   │
│   ├── api/
│   │   ├── router.py
│   │   ├── analyzer.py                # Single stock analysis
│   │   ├── scanner.py                 # Swing picks / trade ideas
│   │   ├── portfolio.py               # Current portfolio state
│   │   ├── regime.py                  # Current regime + history
│   │   └── journal.py                 # Trade log endpoints
│   │
│   ├── data/
│   │   ├── fetcher.py                 # Multi-source orchestrator
│   │   ├── cache.py                   # PostgreSQL/SQLite cache
│   │   ├── universe.py                # S&P 500 constituent management
│   │   ├── sources/
│   │   │   ├── yfinance_src.py
│   │   │   ├── polygon_src.py
│   │   │   ├── fmp_src.py
│   │   │   ├── finnhub_src.py
│   │   │   ├── unusual_whales_src.py
│   │   │   └── quiver_src.py
│   │   └── cross_asset.py             # Bonds, VIX, commodities, DXY
│   │
│   ├── regime/
│   │   ├── detector.py                # Regime classification engine
│   │   ├── indicators.py              # VIX, breadth, yield curve, credit
│   │   └── transitions.py             # Regime transition logic + hysteresis
│   │
│   ├── strategies/
│   │   ├── base.py                    # Abstract strategy interface
│   │   ├── stat_arb.py                # Pairs/basket cointegration
│   │   ├── catalyst_event.py          # PEAD, analyst revisions, flow events
│   │   ├── cross_asset_momentum.py    # Macro theme rotation
│   │   ├── flow_imbalance.py          # GEX, dark pool, unusual options
│   │   └── gap_reversion.py           # Overnight gap mean reversion
│   │
│   ├── signals/
│   │   ├── cointegration.py           # ADF, Engle-Granger, Johansen tests
│   │   ├── earnings.py                # EPS surprise, guidance, PEAD scoring
│   │   ├── revisions.py               # Analyst revision breadth/acceleration
│   │   ├── sentiment.py               # FinBERT + VADER pipeline
│   │   ├── microstructure.py          # GEX, dark pool levels, sweep detection
│   │   ├── cross_asset_signals.py     # Yield, VIX, commodity z-scores
│   │   └── decay_monitor.py           # Rolling Sharpe, crowding detection
│   │
│   ├── risk/
│   │   ├── kelly.py                   # Kelly criterion position sizing
│   │   ├── manager.py                 # Multi-layer risk limits + circuit breakers
│   │   ├── var.py                     # Historical VaR + Monte Carlo VaR
│   │   ├── correlation.py             # Portfolio correlation monitoring
│   │   └── tail_hedge.py              # VIX call / SPY put hedge management
│   │
│   ├── portfolio/
│   │   ├── constructor.py             # Signal aggregation → portfolio
│   │   ├── rebalancer.py              # Daily rebalance logic
│   │   └── execution.py               # Order generation + slippage model
│   │
│   ├── tracker/
│   │   ├── trade_journal.py           # Trade logging + P&L
│   │   ├── strategy_performance.py    # Per-strategy attribution
│   │   └── signal_audit.py            # Why did we enter/exit this trade?
│   │
│   └── models/
│       ├── schemas.py                 # Pydantic models
│       └── database.py                # DB models (trades, regimes, cache)
│
├── backtest/
│   ├── walk_forward.py                # Walk-forward optimization engine
│   ├── transaction_costs.py           # Slippage + commission + borrow model
│   ├── statistical_tests.py           # Bonferroni, bootstrap, permutation tests
│   └── reports.py                     # Generate backtest tear sheets
│
├── nlp/
│   └── finbert_sentiment.py           # FinBERT wrapper
│
├── frontend/
│   └── app.py                         # Streamlit dashboard
│
├── scripts/
│   ├── seed_universe.py
│   ├── find_pairs.py                  # Run cointegration scan
│   ├── calibrate_kelly.py             # Estimate Kelly params from history
│   └── regime_backtest.py             # Backtest regime detection accuracy
│
└── tests/
    ├── test_strategies/
    ├── test_risk/
    ├── test_regime/
    └── test_signals/
```

---

## 17. Key Pydantic Schemas

```python
# backend/models/schemas.py

class Regime(str, Enum):
    BULL_TREND = "bull_trend"
    BULL_CHOPPY = "bull_choppy"
    BEAR_TREND = "bear_trend"
    CRISIS = "crisis"
    MEAN_REVERTING = "mean_reverting"

class StrategyName(str, Enum):
    STAT_ARB = "stat_arb"
    CATALYST = "catalyst"
    CROSS_ASSET = "cross_asset"
    FLOW = "flow"
    INTRADAY = "intraday"

class TradeSignal(BaseModel):
    strategy: StrategyName
    ticker: str
    direction: Literal["long", "short"]
    conviction: float                # 0.0 to 1.0
    kelly_size_pct: float            # Half-Kelly optimal size
    entry_price: float
    stop_loss: float
    target: float
    max_hold_days: int
    edge_reason: str                 # WHY does this edge exist
    kill_condition: str              # What would invalidate this trade
    expected_sharpe: float           # Per-trade expected Sharpe

class PortfolioState(BaseModel):
    regime: Regime
    regime_confidence: float
    gross_exposure: float
    net_exposure: float
    daily_var: float
    current_drawdown_pct: float
    active_trades: list[TradeSignal]
    strategy_pnl: dict[StrategyName, float]
    total_pnl_ytd: float
    portfolio_sharpe_30d: float
```

---

## 18. Implementation Sprints

### Sprint 1 (Week 1-2): Stat Arb + Regime Foundation
1. Data layer: yfinance + cache + cross-asset instruments
2. `signals/cointegration.py` — ADF, Engle-Granger, half-life computation
3. `strategies/stat_arb.py` — pair finding, z-score trading logic
4. `regime/detector.py` — VIX + breadth + ADX regime classification
5. `risk/kelly.py` — half-Kelly sizing
6. `risk/manager.py` — position + portfolio limits
7. **Backtest stat arb on 2 years of data. Target: Sharpe > 1.5**

### Sprint 2 (Week 3-4): Catalyst + Earnings Drift
1. `data/sources/fmp_src.py` + `finnhub_src.py` — earnings, analyst data
2. `signals/earnings.py` — EPS surprise scoring, PEAD detection
3. `signals/revisions.py` — analyst revision breadth + acceleration
4. `strategies/catalyst_event.py` — PEAD + revision momentum
5. `nlp/finbert_sentiment.py` — local FinBERT for news scoring
6. **Backtest PEAD strategy. Target: 58%+ win rate, 1.5+ profit factor**

### Sprint 3 (Week 5-6): Cross-Asset Momentum + Flow
1. `data/cross_asset.py` — yields, VIX, commodities, credit spreads
2. `signals/cross_asset_signals.py` — z-score computation + signal map
3. `strategies/cross_asset_momentum.py` — sector rotation on macro signals
4. `data/sources/unusual_whales_src.py` — options flow, dark pool
5. `signals/microstructure.py` — GEX, sweep detection, dark pool levels
6. `strategies/flow_imbalance.py` — institutional flow trading
7. **Backtest cross-asset signals. Target: positive returns in 60%+ of months**

### Sprint 4 (Week 7-8): Portfolio Construction + Intraday
1. `strategies/gap_reversion.py` — overnight gap mean reversion
2. `portfolio/constructor.py` — multi-strategy signal aggregation
3. `portfolio/rebalancer.py` — daily rebalance with regime weights
4. `risk/var.py` — VaR computation
5. `risk/correlation.py` — position correlation monitoring
6. `signals/decay_monitor.py` — rolling Sharpe, crowding detection
7. **Full portfolio backtest with all 5 strategies. Target: 50%+ CAGR, max DD < 15%**

### Sprint 5 (Week 9-10): Dashboard + Paper Trading
1. `frontend/app.py` — full Streamlit dashboard
2. `tracker/trade_journal.py` — trade logging
3. `tracker/strategy_performance.py` — attribution
4. `backtest/walk_forward.py` — proper WFO validation
5. `backtest/statistical_tests.py` — significance testing
6. Paper trade live for 30 days before real capital

---

## 19. Configuration

### .env.example

```bash
# ── API Keys ──
FINNHUB_API_KEY=
FMP_API_KEY=
POLYGON_API_KEY=
UW_API_KEY=
QUIVER_API_KEY=

# ── Feature Flags ──
ENABLE_POLYGON=false
ENABLE_SMART_MONEY=false
ENABLE_QUIVER=false
ENABLE_INTRADAY=false
PAPER_TRADE_MODE=true        # ALWAYS start in paper trade mode

# ── Risk Parameters ──
INITIAL_CAPITAL=100000
MAX_POSITION_PCT=0.08
MAX_GROSS_EXPOSURE=2.0
MAX_DRAWDOWN_PCT=0.15
KELLY_FRACTION=0.5           # Half-Kelly (0.5 = half, 1.0 = full Kelly)
TAIL_HEDGE_PCT=0.03

# ── Strategy Enable/Disable ──
ENABLE_STAT_ARB=true
ENABLE_CATALYST=true
ENABLE_CROSS_ASSET=true
ENABLE_FLOW=false            # Requires paid data
ENABLE_GAP_REVERSION=false   # Requires intraday data

# ── Database ──
DATABASE_URL=sqlite:///./quantpulse.db

# ── Alerts ──
SLACK_WEBHOOK_URL=
ALERT_EMAIL=
```

---

## 20. The Math Appendix

### Cointegration (Stat Arb)
- Augmented Dickey-Fuller: H₀ = unit root (no mean reversion). Reject at p < 0.01.
- Half-life: `hl = -ln(2) / ln(β)` where `β` from `ΔS_t = β × S_{t-1} + ε_t`
- Hurst exponent: H < 0.5 = mean-reverting, H = 0.5 = random walk, H > 0.5 = trending

### Kelly Criterion
- `f* = (p × b - q) / b` where p = win prob, q = 1-p, b = avg_win / avg_loss
- Half-Kelly: `f = f* / 2` (reduces variance by 50%, sacrifices ~25% geometric growth)
- Multi-asset Kelly: `f = Σ⁻¹ × μ` where Σ = covariance matrix, μ = expected returns vector

### Value at Risk
- Historical VaR (95%): sort daily returns, VaR = 5th percentile
- Parametric VaR: `VaR = μ - z_{0.95} × σ × √t` where z = 1.645
- Monte Carlo VaR: simulate 10,000 portfolio paths using bootstrapped returns

### Sharpe Ratio
- `Sharpe = (R_p - R_f) / σ_p × √252` (annualized from daily returns)
- Target: > 2.0 at portfolio level, > 1.5 per strategy

### Post-Earnings Announcement Drift (PEAD)
- Documented by Ball & Brown (1968), still persistent
- Stocks in top decile of earnings surprise outperform bottom decile by ~8% over 60 days
- Effect is stronger for smaller stocks (less analyst coverage = slower information diffusion)

---

## Final Note for Claude Code

**Build order matters.** Start with stat arb + regime detection. These two together form the foundation that everything else plugs into. Stat arb is the most mathematically rigorous strategy and will teach you the most about the codebase architecture. Regime detection determines capital allocation for every other strategy.

**Paper trade for 30 days minimum** before allocating real money. Track every signal, every entry, every exit. Compare paper results to backtest expectations. If live results are > 30% worse than backtest, something is wrong — usually transaction costs, slippage, or data snooping in the backtest.

**The system should be uncomfortable.** If every trade feels safe and obvious, you don't have edge. Real alpha comes from trades that feel slightly wrong — shorting a stock making new highs because the spread says it's rich, buying a stock with terrible headlines because earnings drift says it's going higher. The math overrules the narrative.
# ADAPTIVE_PARAMETERS.md — Self-Tuning Market Parameter Engine

> **Append this to QUANTPULSE_V2_SPEC.md as Section 21**
> This is the most critical section. A static-parameter system dies the first time the market regime shifts. Every single number in the system must breathe with the market.

---

## 21. The Adaptive Parameter Engine

### The Core Problem

```
January 2024:  VIX = 13,  SPY daily range = 0.4%,  correlations = low
October 2008:  VIX = 80,  SPY daily range = 8.0%,  correlations = 1.0
August 2024:   VIX = 65 spike → 15 within 2 weeks (Yen carry unwind)

Using the same z-score threshold, stop-loss distance, hold period, and position
size across all three environments is financial suicide.
```

### The Solution: Everything Scales to Volatility

The single most important variable in all of finance is **realized volatility**. Every parameter in the system is expressed as a function of current volatility, not as a fixed number.

---

### 21.1 The Volatility Context Object

Every strategy, every signal, every risk calculation receives this object. It is recomputed every hour during market hours and once at 7 AM pre-market.

```python
# backend/adaptive/vol_context.py

"""
Volatility Context — the pulse of the market.

Computed from multiple instruments, multiple timeframes.
This object is passed to EVERY function that uses parameters.
Nothing in the system uses a hardcoded threshold.
"""

from dataclasses import dataclass
from enum import Enum

class VolRegime(str, Enum):
    ULTRA_LOW  = "ultra_low"    # VIX < 12 — compressed spring, breakout coming
    LOW        = "low"          # VIX 12-16 — normal bull, full risk on
    NORMAL     = "normal"       # VIX 16-22 — typical conditions
    ELEVATED   = "elevated"     # VIX 22-30 — caution, tighten everything
    HIGH       = "high"         # VIX 30-45 — fear, reduce exposure significantly
    EXTREME    = "extreme"      # VIX > 45 — crisis, survival mode

@dataclass
class VolContext:
    # ── Spot Volatility ──
    vix_current: float                    # Current VIX level
    vix_5d_avg: float                     # 5-day average (smoothed)
    vix_20d_avg: float                    # 20-day average (baseline)
    vix_percentile_1y: float              # Where current VIX sits vs last 252 days (0-100)

    # ── Volatility Regime ──
    vol_regime: VolRegime                 # Classified regime
    vol_regime_days: int                  # How many days in this regime

    # ── Term Structure ──
    vix_term_spread: float                # VX2 - VX1 (positive = contango = calm)
    term_structure: str                   # "contango", "flat", "backwardation"

    # ── Realized vs Implied ──
    realized_vol_20d: float               # SPY 20-day realized vol (annualized)
    vol_risk_premium: float               # VIX - realized_vol (positive = fear > reality)

    # ── Market Speed ──
    spy_atr_14d: float                    # SPY 14-day ATR in dollars
    spy_atr_pct: float                    # ATR as % of SPY price
    avg_intraday_range_5d: float          # Average (high-low)/close over 5 days

    # ── Correlation Environment ──
    avg_sp500_correlation_20d: float      # Average pairwise correlation of top 50 stocks
    correlation_regime: str               # "dispersed" (<0.3), "normal" (0.3-0.6), "herding" (>0.6)

    # ── Breadth ──
    pct_above_200sma: float              # % of S&P 500 above 200-day SMA
    pct_above_50sma: float               # % of S&P 500 above 50-day SMA
    advance_decline_ratio_10d: float     # 10-day avg advance/decline ratio

    # ── Cross-Asset Vol ──
    move_index: float                     # Bond market volatility (MOVE index proxy)
    fx_vol_index: float                   # Currency vol (CVIX or DXY ATR)
    oil_atr_pct: float                    # Crude oil ATR %

    # ── Computed Scaling Factors ──
    @property
    def vol_scale(self) -> float:
        """Master scaling factor. 1.0 = normal conditions.
        < 1.0 in low vol (tighter params), > 1.0 in high vol (wider params)."""
        return self.vix_current / self.vix_20d_avg

    @property
    def position_scale(self) -> float:
        """Inverse vol scale for position sizing. Smaller positions in high vol."""
        return min(2.0, max(0.3, self.vix_20d_avg / self.vix_current))

    @property
    def speed_scale(self) -> float:
        """How fast the market is moving relative to normal. Adjusts hold periods."""
        return self.spy_atr_pct / 0.01  # Normalize to 1.0 at 1% daily ATR
```

---

### 21.2 How Every Parameter Adapts

Here is the complete mapping. **No parameter in the system is static.**

#### A. Entry/Exit Thresholds Scale with Volatility

```python
# backend/adaptive/thresholds.py

"""
All entry/exit thresholds are expressed as:
    adaptive_threshold = base_threshold × vol_context.vol_scale

In low-vol environments (VIX = 12, vol_scale = 0.75):
    - Z-score entry tightens: 2.0 × 0.75 = 1.5 (catch smaller divergences)
    - Markets move less, so a 1.5σ move IS significant

In high-vol environments (VIX = 35, vol_scale = 2.0):
    - Z-score entry widens: 2.0 × 2.0 = 4.0 (only trade extreme divergences)
    - Markets are wild, 2σ moves are noise — need 4σ to signal real mispricing
"""

def get_stat_arb_params(vol: VolContext) -> dict:
    """Stat arb pair trading parameters, adapted to current vol."""
    vs = vol.vol_scale
    ps = vol.position_scale

    return {
        # ── Entry/Exit Z-Scores ──
        "entry_z": 2.0 * max(0.8, min(2.5, vs)),         # Range: 1.6 to 5.0
        "exit_z": 0.5 * max(0.8, min(1.5, vs)),           # Range: 0.4 to 0.75
        "stop_z": 3.5 * max(0.8, min(2.0, vs)),           # Range: 2.8 to 7.0

        # ── Position Sizing ──
        "max_position_pct": 0.04 * ps,                     # Smaller in high vol
        "max_strategy_pct": 0.20 * ps,

        # ── Hold Period ──
        # High vol = things mean-revert faster (or break faster)
        "max_hold_days": int(20 / max(0.5, vol.speed_scale)),  # 10-40 days

        # ── Pair Selection ──
        # Require stronger cointegration in high-vol (more noise to filter)
        "min_adf_pvalue": 0.01 if vs < 1.5 else 0.005,
        "min_half_life_days": max(2, int(3 / vol.speed_scale)),
        "max_half_life_days": int(30 / max(0.5, vol.speed_scale)),
    }


def get_catalyst_params(vol: VolContext) -> dict:
    """Earnings drift and event trading parameters."""
    vs = vol.vol_scale
    ps = vol.position_scale

    return {
        # ── Earnings Drift ──
        # In high vol, require BIGGER surprises (small ones get lost in noise)
        "min_eps_surprise_pct": 5.0 * max(1.0, vs * 0.8),  # 5% base, up to 10%
        "min_earnings_gap_pct": 2.0 * max(0.8, vs * 0.7),   # 2% base, up to 3.5%

        # ── Targets & Stops ──
        # Wider stops in high vol to avoid getting shaken out
        "stop_loss_pct": 5.0 * max(0.8, min(2.0, vs)),      # 4% to 10%
        "target_return_pct": 10.0 * max(0.8, min(1.5, vs)),  # 8% to 15%

        # ── Hold Period ──
        # High vol = drift happens faster (or reverses faster)
        "max_hold_days": int(40 / max(0.7, vol.speed_scale)),

        # ── Sizing ──
        "max_position_pct": 0.06 * ps,

        # ── Revision Momentum ──
        "min_breadth": 0.3 if vs < 1.3 else 0.4,  # Higher bar in noisy markets
        "min_acceleration": 0.1 if vs < 1.3 else 0.15,
    }


def get_cross_asset_params(vol: VolContext) -> dict:
    """Cross-asset regime momentum parameters."""
    vs = vol.vol_scale

    return {
        # ── Signal Threshold ──
        # In calm markets, smaller cross-asset moves are meaningful
        # In volatile markets, only large moves matter
        "signal_z_threshold": 1.5 * max(0.7, min(2.0, vs)),  # 1.05 to 3.0

        # ── Hold Period ──
        "max_hold_days": int(15 / max(0.5, vol.speed_scale)),

        # ── Which signals are active ──
        # In crisis: only trade VIX term structure and credit spread signals
        # In calm: trade the full signal map
        "active_signals": (
            ["vix_term", "credit_spread"] if vol.vol_regime == VolRegime.EXTREME
            else ["vix_term", "credit_spread", "yield_curve", "oil", "dollar", "copper_gold"]
            if vol.vol_regime in [VolRegime.HIGH, VolRegime.ELEVATED]
            else "all"
        ),
    }


def get_gap_reversion_params(vol: VolContext) -> dict:
    """Overnight gap mean reversion parameters."""
    vs = vol.vol_scale

    return {
        # ── Gap Size Filter ──
        # Low vol: gaps > 0.7% are tradeable (that's a big move in a quiet market)
        # High vol: only gaps > 2% are tradeable (smaller ones are normal noise)
        "min_gap_pct": max(0.7, 1.0 * vs),                # 0.7% to 2.5%
        "max_gap_pct": max(3.0, 5.0 * vs),                # 3% to 12.5%

        # ── Stops ──
        # Wider in high vol to avoid false stop-outs
        "stop_pct_of_gap": 0.5 * max(0.8, min(1.5, vs)),  # 40% to 75% of gap

        # ── Time Stop ──
        "close_by_time": "11:00" if vs < 1.3 else "10:30",  # Faster exit in vol

        # ── VIX Gate ──
        # DISABLE gap reversion entirely when VIX > 35 (gaps don't fill in panic)
        "max_vix_for_trading": 35,

        # ── Sizing ──
        "max_position_pct": 0.02 * vol.position_scale,     # Tiny in high vol
    }


def get_flow_params(vol: VolContext) -> dict:
    """Microstructure and flow imbalance parameters."""
    vs = vol.vol_scale

    return {
        # ── Sweep Detection ──
        # In high vol, there's more large flow — need higher threshold to filter signal
        "min_sweep_premium": 100_000 * max(1.0, vs),      # $100K to $250K
        "min_dark_pool_notional": 1_000_000 * max(1.0, vs),

        # ── Hold Period ──
        "max_hold_days": int(10 / max(0.5, vol.speed_scale)),

        # ── Stops ──
        "stop_loss_pct": 3.0 * max(0.8, min(2.0, vs)),

        # ── GEX Thresholds ──
        # In high vol, GEX levels matter MORE (dealers hedging amplifies)
        "gex_significance_threshold": "auto",  # Scaled to open interest distribution
    }
```

#### B. Stop-Losses Are ALWAYS ATR-Based, Never Fixed %

```python
# backend/adaptive/stops.py

"""
The #1 mistake in trading systems: fixed percentage stops.

A 5% stop on a stock with 1% daily ATR gives you 5 days of breathing room.
A 5% stop on a stock with 4% daily ATR gives you 1.25 days — you'll get
stopped out by normal noise.

EVERY stop-loss in the system is expressed in ATR multiples:

    stop_price = entry_price - (atr_multiple × ATR_14d × direction)

The ATR multiple itself scales with vol regime:
"""

def compute_stop(
    entry_price: float,
    direction: str,          # "long" or "short"
    atr_14d: float,          # Stock's 14-day ATR in dollars
    strategy: str,           # Which strategy
    vol: "VolContext",       # Current vol context
) -> dict:
    """Compute adaptive stop-loss."""

    # Base ATR multiples per strategy (in normal vol)
    BASE_ATR_MULTIPLES = {
        "stat_arb": 2.0,       # Tight — mean reversion should work quickly
        "catalyst": 2.5,       # Medium — give drift room to develop
        "cross_asset": 3.0,    # Wide — macro trades need space
        "flow": 1.5,           # Tight — high conviction, fail fast
        "gap_reversion": 1.0,  # Very tight — gap fills or it doesn't
    }

    base_mult = BASE_ATR_MULTIPLES[strategy]

    # Scale ATR multiple by vol environment
    # High vol → wider stops (don't get shaken out by noise)
    # Low vol → tighter stops (less noise, if it moves against you it's real)
    vol_adjusted_mult = base_mult * max(0.7, min(2.0, vol.vol_scale))

    # Compute stop distance
    stop_distance = vol_adjusted_mult * atr_14d

    # Compute stop price
    if direction == "long":
        stop_price = entry_price - stop_distance
    else:
        stop_price = entry_price + stop_distance

    # Compute risk % (for Kelly sizing input)
    risk_pct = stop_distance / entry_price

    return {
        "stop_price": round(stop_price, 2),
        "stop_distance_dollars": round(stop_distance, 2),
        "atr_multiple_used": round(vol_adjusted_mult, 2),
        "risk_pct": round(risk_pct * 100, 2),
        "atr_14d": round(atr_14d, 2),
    }
```

#### C. Targets Are Volatility-Scaled Too

```python
# backend/adaptive/targets.py

"""
Targets scale with volatility AND reward/risk ratio constraint.

Principle: In high vol, moves are bigger → targets should be further out.
But stops are also wider → the R/R ratio must stay > 2.0.
"""

def compute_targets(
    entry_price: float,
    stop_info: dict,          # Output from compute_stop()
    strategy: str,
    vol: "VolContext",
    resistance_levels: list[float] = None,
    analyst_target: float = None,
) -> list[dict]:
    """Compute adaptive price targets."""

    risk_distance = stop_info["stop_distance_dollars"]

    # Minimum reward = 2.0 × risk (non-negotiable)
    min_target_distance = risk_distance * 2.0

    # Preferred reward = 2.5-3.5× risk, scaled by vol
    # In high vol, aim for larger multiples (moves are bigger)
    preferred_rr = 2.5 * max(1.0, min(1.5, vol.vol_scale))
    preferred_target_distance = risk_distance * preferred_rr

    targets = []

    # Target 1: Technical (risk-based)
    target_1_price = entry_price + preferred_target_distance
    targets.append({
        "price": round(target_1_price, 2),
        "label": f"Risk-based ({preferred_rr:.1f}:1 R/R)",
        "exit_pct": 50,  # Sell 50% at target 1
    })

    # Target 2: Resistance or analyst target (if available)
    if resistance_levels:
        # Find the nearest resistance above entry that gives > 2:1 R/R
        valid = [r for r in resistance_levels if (r - entry_price) > min_target_distance]
        if valid:
            targets.append({
                "price": round(valid[0], 2),
                "label": "Resistance level",
                "exit_pct": 30,
            })

    if analyst_target and (analyst_target - entry_price) > min_target_distance:
        targets.append({
            "price": round(analyst_target, 2),
            "label": "Analyst consensus",
            "exit_pct": 20,
        })

    # If no secondary targets, trail the remainder
    if len(targets) == 1:
        targets.append({
            "price": None,
            "label": "Trailing stop (2× ATR)",
            "exit_pct": 50,
        })

    return targets
```

#### D. Kelly Sizing Adapts to Vol and Regime

```python
# backend/adaptive/kelly_adaptive.py

"""
Adaptive Kelly Criterion

Standard Kelly uses fixed p (win rate) and b (win/loss ratio).
Adaptive Kelly adjusts these based on:
1. Trailing performance IN THE CURRENT REGIME (not all-time)
2. Vol-scaled position cap
3. Correlation adjustment (reduce if portfolio is already correlated)
"""

def compute_adaptive_kelly(
    strategy: str,
    vol: "VolContext",
    regime: str,
    trailing_trades: list[dict],     # Last N trades from this strategy
    portfolio_correlation: float,     # Current avg portfolio correlation
) -> dict:
    """Compute regime-aware, vol-adjusted Kelly fraction."""

    # 1. Compute p and b from RECENT trades in CURRENT regime
    # Only use trades from the same regime (bull trades don't inform bear sizing)
    regime_trades = [t for t in trailing_trades if t["regime"] == regime]

    if len(regime_trades) < 20:
        # Not enough data — use conservative defaults
        # Fall back to full-history stats with a penalty
        all_wins = [t for t in trailing_trades if t["pnl_pct"] > 0]
        p = len(all_wins) / max(1, len(trailing_trades))
        avg_win = sum(t["pnl_pct"] for t in all_wins) / max(1, len(all_wins))
        avg_loss = abs(sum(t["pnl_pct"] for t in trailing_trades if t["pnl_pct"] <= 0)
                       / max(1, len(trailing_trades) - len(all_wins)))
        confidence_penalty = 0.5  # Halve the size when we don't have regime data
    else:
        wins = [t for t in regime_trades if t["pnl_pct"] > 0]
        p = len(wins) / len(regime_trades)
        avg_win = sum(t["pnl_pct"] for t in wins) / max(1, len(wins))
        losses = [t for t in regime_trades if t["pnl_pct"] <= 0]
        avg_loss = abs(sum(t["pnl_pct"] for t in losses) / max(1, len(losses)))
        confidence_penalty = 1.0

    q = 1 - p
    b = avg_win / max(0.001, avg_loss)  # Win/loss ratio

    # 2. Compute raw Kelly
    if (p * b - q) <= 0:
        # Negative edge in this regime — DO NOT TRADE
        return {"kelly_fraction": 0.0, "reason": "Negative expected value in current regime"}

    full_kelly = (p * b - q) / b

    # 3. Apply half-Kelly safety margin
    half_kelly = full_kelly / 2.0

    # 4. Apply confidence penalty (if insufficient regime data)
    adjusted_kelly = half_kelly * confidence_penalty

    # 5. Apply volatility scaling
    # In high vol: reduce further (wider stops = same Kelly fraction = more $ at risk)
    vol_adjusted = adjusted_kelly * vol.position_scale

    # 6. Apply correlation haircut
    # If portfolio is already highly correlated, adding more positions
    # concentrates risk — reduce sizing
    if portfolio_correlation > 0.6:
        corr_haircut = 1.0 - (portfolio_correlation - 0.6) * 1.5  # Up to 60% reduction
        vol_adjusted *= max(0.4, corr_haircut)

    # 7. Cap at absolute limits
    STRATEGY_CAPS = {
        "stat_arb": 0.06,
        "catalyst": 0.08,
        "cross_asset": 0.05,
        "flow": 0.04,
        "gap_reversion": 0.03,
    }
    final_size = min(vol_adjusted, STRATEGY_CAPS.get(strategy, 0.05))

    return {
        "kelly_fraction": round(final_size, 4),
        "full_kelly": round(full_kelly, 4),
        "half_kelly": round(half_kelly, 4),
        "win_rate": round(p, 3),
        "win_loss_ratio": round(b, 3),
        "vol_scale_applied": round(vol.position_scale, 3),
        "corr_haircut_applied": round(portfolio_correlation, 3),
        "regime_trades_count": len(regime_trades),
        "confidence_penalty": confidence_penalty,
    }
```

#### E. Regime Detection Thresholds Are Self-Calibrating

```python
# backend/adaptive/regime_calibration.py

"""
Regime Detection Thresholds Auto-Calibrate

Problem: VIX = 20 meant "elevated" in 2017. It meant "calm" in 2022.
The absolute VIX number changes meaning over time.

Solution: All regime thresholds are percentile-based, not absolute.

Instead of:  VIX > 25 → elevated
We use:      VIX > 75th percentile of trailing 252 days → elevated
"""

def calibrate_regime_thresholds(
    vix_history_252d: list[float],
    breadth_history_252d: list[float],
    adx_history_252d: list[float],
) -> dict:
    """Compute regime thresholds from trailing 1-year distributions."""

    import numpy as np

    vix_arr = np.array(vix_history_252d)
    breadth_arr = np.array(breadth_history_252d)

    return {
        "vix_thresholds": {
            "ultra_low":  float(np.percentile(vix_arr, 10)),    # Bottom 10%
            "low":        float(np.percentile(vix_arr, 25)),    # 10-25th
            "normal":     float(np.percentile(vix_arr, 50)),    # 25-50th
            "elevated":   float(np.percentile(vix_arr, 75)),    # 50-75th
            "high":       float(np.percentile(vix_arr, 90)),    # 75-90th
            "extreme":    float(np.percentile(vix_arr, 97)),    # Top 3%
        },
        "breadth_thresholds": {
            "crisis":     float(np.percentile(breadth_arr, 10)),
            "bear":       float(np.percentile(breadth_arr, 30)),
            "neutral":    float(np.percentile(breadth_arr, 50)),
            "bull":       float(np.percentile(breadth_arr, 70)),
            "strong_bull": float(np.percentile(breadth_arr, 90)),
        },
        "calibrated_at": "datetime.utcnow()",
        "lookback_days": 252,
    }

    # Recalibrate weekly (Sunday night)
    # This means a VIX of 20 is "elevated" in a 2017-like year (when VIX averaged 11)
    # but "normal" in a 2022-like year (when VIX averaged 25)
```

#### F. Hold Periods Scale with Market Speed

```python
# backend/adaptive/hold_periods.py

"""
Hold Period Adaptation

In fast markets (high ATR, high vol):
  - Mean reversion happens in 3-5 days instead of 8-12
  - Earnings drift plays out in 15 days instead of 40
  - Macro rotations complete in 5 days instead of 15

In slow markets (low ATR, low vol):
  - Everything takes longer
  - Patience is required — don't close trades too early

Formula:
    adaptive_hold = base_hold_days / speed_scale

Where speed_scale = current_atr_pct / normal_atr_pct (normalized to 1.0)
"""

BASE_HOLD_PERIODS = {
    "stat_arb":       {"min": 3, "max": 20, "typical": 10},
    "catalyst_pead":  {"min": 5, "max": 40, "typical": 25},
    "catalyst_rev":   {"min": 5, "max": 30, "typical": 15},
    "cross_asset":    {"min": 3, "max": 15, "typical": 8},
    "flow":           {"min": 2, "max": 10, "typical": 5},
    "gap_reversion":  {"min": 0.1, "max": 0.5, "typical": 0.25},  # Intraday (fraction of day)
}

def get_adaptive_hold(strategy: str, vol: "VolContext") -> dict:
    base = BASE_HOLD_PERIODS[strategy]
    ss = max(0.5, vol.speed_scale)  # Floor at 0.5 to prevent infinite holds

    return {
        "min_days": max(1, int(base["min"] / ss)),
        "max_days": max(2, int(base["max"] / ss)),
        "typical_days": max(1, int(base["typical"] / ss)),
        "speed_scale_used": round(ss, 2),
    }
```

#### G. Strategy Weights Interpolate Smoothly Between Regimes

```python
# backend/adaptive/weight_interpolation.py

"""
Strategy Weight Smooth Transitions

Problem: Hard regime switches cause violent portfolio rebalancing.
Going from bull_trend to bear_trend in one day means selling 25% of
momentum and buying 20% of stat arb — that's a lot of turnover and slippage.

Solution: Weights interpolate smoothly based on regime confidence scores.

Instead of: regime = "bull_trend" → weights = BULL_TREND_WEIGHTS
We use:     regime_probs = {bull_trend: 0.6, bull_choppy: 0.3, bear: 0.1}
            weights = 0.6 × BULL_TREND_WEIGHTS + 0.3 × CHOPPY_WEIGHTS + 0.1 × BEAR_WEIGHTS
"""

from backend.regime.detector import STRATEGY_WEIGHTS

def compute_blended_weights(regime_probabilities: dict[str, float]) -> dict[str, float]:
    """
    Blend strategy weights based on regime probability distribution.

    Args:
        regime_probabilities: {"bull_trend": 0.6, "bull_choppy": 0.3, "bear_trend": 0.1}
                              Must sum to 1.0

    Returns:
        Blended strategy weights: {"stat_arb": 0.21, "catalyst": 0.23, ...}
    """
    strategies = list(STRATEGY_WEIGHTS["bull_trend"].keys())
    blended = {s: 0.0 for s in strategies}

    for regime, prob in regime_probabilities.items():
        regime_weights = STRATEGY_WEIGHTS[regime]
        for strategy in strategies:
            blended[strategy] += prob * regime_weights[strategy]

    # Normalize (should already sum to ~1.0, but ensure precision)
    total = sum(blended.values())
    return {s: round(w / total, 4) for s, w in blended.items()}


def compute_regime_transition_weights(
    prev_weights: dict[str, float],
    target_weights: dict[str, float],
    transition_speed: float,           # 0.0 to 1.0 (how fast to transition)
    vol: "VolContext",
) -> dict[str, float]:
    """
    Smooth weight transition over multiple days.

    transition_speed is set by regime severity:
    - Normal regime change: 0.2 (takes ~5 days to fully transition)
    - Urgent (into bear/crisis): 0.5 (takes ~2 days)
    - CRISIS OVERRIDE: 1.0 (immediate, one day)
    """
    # In crisis: override speed to 1.0 (immediate de-risk)
    if vol.vol_regime == "extreme":
        transition_speed = 1.0

    new_weights = {}
    for strategy in prev_weights:
        prev = prev_weights[strategy]
        target = target_weights[strategy]
        # Exponential moving toward target
        new_weights[strategy] = round(prev + transition_speed * (target - prev), 4)

    # Normalize
    total = sum(new_weights.values())
    return {s: round(w / total, 4) for s, w in new_weights.items()}
```

#### H. Cointegration Parameters Adapt to Pair-Specific Vol

```python
# backend/adaptive/pair_params.py

"""
Each pair has its OWN volatility profile. A tech pair (NVDA/AMD) moves 3x
faster than a utility pair (NEE/DUK). The same z-score and hold period
make no sense for both.

Solution: Per-pair parameter calibration using the pair's spread statistics.
"""

def calibrate_pair_params(
    spread_series: "pd.Series",        # Historical spread values
    half_life: float,                   # Pre-computed OU half-life
    spread_vol: float,                  # Standard deviation of spread
    vol: "VolContext",                  # Current market vol context
) -> dict:
    """Compute pair-specific adaptive parameters."""

    # Entry z-score: inversely proportional to half-life
    # Fast mean-reverting pairs → enter at lower z (1.5σ)
    # Slow mean-reverting pairs → need bigger divergence to justify hold time (2.5σ)
    base_entry_z = 1.5 + (half_life / 30)  # 1.5 for hl=0, 2.5 for hl=30

    # Scale by market vol
    entry_z = base_entry_z * max(0.8, min(2.0, vol.vol_scale))

    # Max hold: 2× half-life (if it hasn't reverted by then, something broke)
    max_hold = int(half_life * 2.0 / max(0.5, vol.speed_scale))

    # Position size: inversely proportional to spread vol
    # High-vol spreads → smaller positions (more risk per unit)
    normal_spread_vol = 0.02  # Assume 2% is "normal" spread volatility
    vol_ratio = spread_vol / normal_spread_vol
    size_adjustment = 1.0 / max(0.5, vol_ratio)

    return {
        "entry_z": round(entry_z, 2),
        "exit_z": round(entry_z * 0.25, 2),    # Exit at 25% of entry threshold
        "stop_z": round(entry_z * 1.75, 2),     # Stop at 175% of entry (break)
        "max_hold_days": max(3, min(60, max_hold)),
        "size_adjustment": round(size_adjustment, 3),
    }
```

---

### 21.3 Risk Limits Scale with Volatility

```python
# backend/adaptive/risk_scaling.py

"""
Even risk limits aren't fixed. In a crisis, tighter limits. In calm, looser.

The principle: keep the DOLLAR VAR approximately constant across regimes.
If vol doubles, position sizes halve → same dollar risk.
"""

def get_adaptive_risk_limits(vol: "VolContext") -> dict:
    vs = vol.vol_scale
    ps = vol.position_scale

    return {
        # Position limits scale inversely with vol
        "max_position_pct": round(0.08 * ps, 3),          # 4% in 2× vol, 12% in 0.5× vol
        "max_gross_exposure": round(min(2.5, 2.0 * ps), 2),  # Less leverage in high vol

        # Drawdown limits are TIGHTER in high vol (losses accelerate)
        "reduce_at_drawdown_pct": round(-0.10 * min(1.0, ps), 3),   # -10% normally, -5% in high vol
        "flatten_at_drawdown_pct": round(-0.15 * min(1.0, ps), 3),  # -15% normally, -7.5% in high vol

        # Daily VaR limit (approximately constant in dollar terms)
        "daily_var_limit_pct": round(0.02 * ps, 3),        # ~constant dollar risk

        # Sector concentration (tighter when correlations are high)
        "max_sector_pct": (
            0.15 if vol.correlation_regime == "herding"
            else 0.20 if vol.correlation_regime == "normal"
            else 0.30  # dispersed correlations → can concentrate more safely
        ),

        # Tail hedge sizing (MORE when vol is cheap, i.e., low VIX)
        "tail_hedge_pct": (
            0.05 if vol.vol_regime in ["ultra_low", "low"]     # Cheap vol: buy more
            else 0.03 if vol.vol_regime == "normal"
            else 0.02 if vol.vol_regime == "elevated"
            else 0.01  # Already in high vol: hedges are expensive, reduce
        ),

        # Correlation limit between positions
        "max_position_correlation": (
            0.60 if vol.correlation_regime == "herding"
            else 0.75 if vol.correlation_regime == "normal"
            else 0.85
        ),
    }
```

---

### 21.4 The Recalibration Schedule

```python
# backend/adaptive/scheduler.py

"""
When does each parameter recalibrate?

REAL-TIME (every price tick / 1-second, during market hours):
  - Stop-loss levels (trailing stops adjust continuously)
  - Intraday gap reversion entry/exit

EVERY 15 MINUTES (market hours):
  - VolContext refresh (VIX, ATR, correlation)
  - Risk limit check (VaR, exposure, drawdown)
  - Exit trigger check (stop hit? target hit? time stop?)

HOURLY:
  - Strategy-specific parameter refresh (entry thresholds, hold periods)
  - Portfolio correlation matrix update
  - Stat arb z-score refresh for all active pairs

DAILY (7:00 AM EST):
  - Full regime detection recalibration
  - Strategy weight rebalance
  - Kelly fraction recalculation per strategy
  - Universe filter re-run (swing scanner)
  - Sector rotation ranking refresh
  - New pair cointegration scan (weekly, but prep daily)

WEEKLY (Sunday night):
  - Regime threshold recalibration (percentile-based from trailing 252d)
  - Pair re-validation (cointegration tests on all active pairs)
  - Strategy-level Sharpe recalculation + alpha decay check
  - Kelly parameter re-estimation (p, b) from trailing 100 trades
  - Signal crowding check (correlation with factor ETFs)

MONTHLY:
  - Full universe refresh (index reconstitution)
  - Backtest re-run on trailing 6 months to validate parameter stability
  - Signal decay audit (kill signals with negative rolling Sharpe)
"""

CALIBRATION_SCHEDULE = {
    "vol_context":         {"interval": "15min", "market_hours_only": True},
    "risk_limits":         {"interval": "15min", "market_hours_only": True},
    "strategy_params":     {"interval": "1h",    "market_hours_only": True},
    "correlation_matrix":  {"interval": "1h",    "market_hours_only": True},
    "regime_detection":    {"interval": "daily",  "time": "07:00 EST"},
    "kelly_fractions":     {"interval": "daily",  "time": "07:00 EST"},
    "strategy_weights":    {"interval": "daily",  "time": "07:00 EST"},
    "regime_thresholds":   {"interval": "weekly",  "day": "sunday"},
    "pair_revalidation":   {"interval": "weekly",  "day": "sunday"},
    "alpha_decay_audit":   {"interval": "weekly",  "day": "sunday"},
    "universe_refresh":    {"interval": "monthly"},
    "full_backtest":       {"interval": "monthly"},
}
```

---

### 21.5 Updated Directory Structure Additions

```
quantpulse/
├── backend/
│   ├── adaptive/                          # ★ NEW — THE ADAPTIVE ENGINE
│   │   ├── __init__.py
│   │   ├── vol_context.py                 # VolContext dataclass + computation
│   │   ├── thresholds.py                  # All entry/exit threshold adaptation
│   │   ├── stops.py                       # ATR-based adaptive stop-losses
│   │   ├── targets.py                     # Volatility-scaled profit targets
│   │   ├── kelly_adaptive.py              # Regime-aware Kelly sizing
│   │   ├── hold_periods.py                # Speed-adjusted hold durations
│   │   ├── weight_interpolation.py        # Smooth regime weight transitions
│   │   ├── pair_params.py                 # Per-pair parameter calibration
│   │   ├── risk_scaling.py                # Vol-scaled risk limits
│   │   ├── regime_calibration.py          # Self-calibrating regime thresholds
│   │   └── scheduler.py                   # Recalibration schedule definitions
```

---

### 21.6 The Golden Rule

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   EVERY number in the system is a FUNCTION, not a CONSTANT.     │
│                                                                  │
│   ✗  stop_loss = entry_price × 0.95                             │
│   ✓  stop_loss = entry_price - (atr_multiple(vol) × ATR_14d)    │
│                                                                  │
│   ✗  entry_z = 2.0                                              │
│   ✓  entry_z = 2.0 × vol_scale(vix / vix_20d_avg)              │
│                                                                  │
│   ✗  position_size = capital × 0.05                             │
│   ✓  position_size = capital × half_kelly(p, b, regime) × ps    │
│                                                                  │
│   ✗  max_hold = 20 days                                         │
│   ✓  max_hold = 20 / speed_scale(atr_pct / normal_atr_pct)     │
│                                                                  │
│   ✗  regime = "bull" if VIX < 20                                │
│   ✓  regime = "bull" if VIX < percentile_25(vix_trailing_252d)  │
│                                                                  │
│   If you find a hardcoded number anywhere in the trading logic,  │
│   it's a bug. Wrap it in an adaptive function.                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```
# EXECUTION_PHILOSOPHY.md — Human-in-the-Loop Advisory System

> **Append this to QUANTPULSE_COMPLETE_SPEC.md as Section 22**
> This overrides all references to "execution engine", "broker API", and "automated trading" in previous sections.

---

## 22. Execution Philosophy: You Are the Final Layer

### What This System IS

```
┌───────────────────────────────────────────────────────────────┐
│                                                               │
│   This system is a SIGNAL GENERATOR + DECISION COCKPIT.      │
│                                                               │
│   It does NOT place trades.                                   │
│   It does NOT connect to any broker.                          │
│   It does NOT move money.                                     │
│                                                               │
│   It tells you:                                               │
│     → WHAT to trade and WHY                                   │
│     → WHEN to enter and at what price                         │
│     → WHERE to set your stop and target                       │
│     → HOW MUCH to risk (as % of capital)                      │
│     → WHEN to exit and why                                    │
│                                                               │
│   YOU decide whether to pull the trigger.                     │
│   YOU execute on your own broker (Schwab, IBKR, Public, etc)  │
│   YOU log the trade back into the system for tracking.        │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### Why This Is Actually Better

1. **Regulatory simplicity.** No broker API integration = no compliance issues, no API key security risk, no accidental fat-finger orders from a bug.

2. **Broker-agnostic.** You can execute on Public.com, Schwab, IBKR, Robinhood, Zerodha — whatever you want. The system doesn't care.

3. **You develop intuition.** By reviewing every signal before trading, you learn which signals FEEL right and which don't. After 6 months, your judgment + the model > the model alone.

4. **Override bad signals.** The model doesn't know about breaking news from 30 seconds ago. You do. You're the circuit breaker.

5. **No catastrophic bugs.** An automated system with a bug can lose your entire account in minutes. A signal system with a bug shows you a bad recommendation — you just don't take it.

---

### 22.1 The Information Flow

```
  DATA SOURCES                    YOUR SYSTEM                      YOU
  ───────────                    ───────────                      ───
  Polygon                  ┌──────────────────┐
  Finnhub          ───────►│ Signal Engine     │
  FMP                      │ (5 strategies)    │
  Unusual Whales           │                   │
  Polymarket               │ Regime Detection  │
                           │                   │
                           │ Adaptive Params   │         ┌──────────────┐
                           │                   │────────►│ DASHBOARD    │
                           │ Kelly Sizing      │         │              │
                           │                   │         │ You see:     │
                           │ Risk Checks       │         │ • Picks      │
                           └──────────────────┘         │ • Trade plans│
                                                         │ • Risk       │
                           ┌──────────────────┐         │ • Alerts     │
                           │ ALERTS           │────────►│              │
                           │ • Morning brief  │         └──────┬───────┘
                           │ • Signal fired   │                │
                           │ • Exit trigger   │                │ YOU DECIDE
                           │ • Regime changed │                │
                           └──────────────────┘                ▼
                                                         ┌──────────────┐
                                                         │ Your broker  │
                                                         │ (manual)     │
                                                         │              │
                                                         │ Schwab/IBKR/ │
                                                         │ Public/Robin │
                                                         └──────┬───────┘
                                                                │
                                                                │ YOU LOG
                                                                ▼
                           ┌──────────────────┐         ┌──────────────┐
                           │ TRADE JOURNAL    │◄────────│ Log entry:   │
                           │ Tracks P&L       │         │ ticker, side │
                           │ Win rate         │         │ entry price  │
                           │ Strategy perf    │         │ shares, stop │
                           └──────────────────┘         └──────────────┘
```

---

### 22.2 What the Dashboard Shows You

The dashboard is your **trading terminal**. It replaces Bloomberg for your personal use.

#### Screen 1: Morning Command Center (what you see first at 7:30 AM)

```
┌─────────────────────────────────────────────────────────────────────┐
│  REGIME: Bull Choppy (68% confidence)     VIX: 17.3 (normal)      │
│  SPY: +0.2% pre-market    Sector lead: Tech (+1.1%)               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ★ TODAY'S TOP SIGNALS (sorted by conviction)                      │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 1. LONG MSFT — Catalyst (Earnings Drift)     Score: 84     │   │
│  │    Entry: $428-432 │ Stop: $418 │ Target: $458 │ R/R: 2.8  │   │
│  │    Size: 5.2% of capital (Half-Kelly)                       │   │
│  │    WHY: Beat EPS by 8%, guidance raised, RSI 52 pullback    │   │
│  │    [Take Trade ↗] [Pass] [Remind Later]                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 2. LONG XLE — Cross-Asset (Oil breakout)     Score: 71     │   │
│  │    Entry: $89-91 │ Stop: $86 │ Target: $97 │ R/R: 2.2      │   │
│  │    Size: 3.1% of capital                                    │   │
│  │    WHY: Oil +4% (2σ), energy sector rotating in             │   │
│  │    [Take Trade ↗] [Pass] [Remind Later]                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 3. PAIR: Long AMD / Short INTC — Stat Arb    Score: 68     │   │
│  │    Spread z-score: 2.3σ │ Half-life: 8 days                 │   │
│  │    Long AMD at $165 │ Short INTC at $24 │ Size: 3.8% each   │   │
│  │    WHY: Spread diverged beyond 2σ, cointegrated (p<0.005)   │   │
│  │    [Take Trade ↗] [Pass] [Remind Later]                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ... (up to 5-8 signals per day)                                   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  ACTIVE TRADES (ones you took)                                     │
│  NVDA long │ Day 4/14 │ +3.2% │ Stop: $133 (safe) │ Target: $152  │
│  GS long   │ Day 2/10 │ -0.8% │ Stop: $580 (safe) │ Target: $625  │
│                                                                     │
│  ⚠ EXIT ALERTS                                                     │
│  AMZN long │ Approaching Target 1 ($198, currently $196) │ [Exit?] │
├─────────────────────────────────────────────────────────────────────┤
│  SECTOR HEATMAP │ NEWS FEED │ REGIME HISTORY                       │
└─────────────────────────────────────────────────────────────────────┘
```

#### The Action Buttons

Every signal card has three buttons:

**[Take Trade ↗]** — You clicked this = you're taking the trade.
- Opens a pre-filled trade log form: ticker, direction, entry price, shares, stop, target
- You manually enter your ACTUAL entry price (may differ from system's suggested entry)
- The system starts tracking this as an active trade
- Monitors stop/target/time-stop and alerts you when action is needed

**[Pass]** — You're skipping this one.
- Logs the pass with optional reason ("too correlated with existing position", "don't trust the catalyst", "bad timing")
- System still tracks what would have happened (phantom P&L) so you can review your judgment vs the model

**[Remind Later]** — Not ready to decide yet.
- Sets a reminder alert in 1 hour (or custom time)
- Useful for: waiting for market open confirmation, waiting for a pullback to entry zone

---

### 22.3 Alert System (Your Notification Layer)

Since you're trading manually, alerts are CRITICAL. The system needs to tap you on the shoulder at the right moments.

#### Alert Types

```python
# backend/alerts/types.py

ALERT_TYPES = {
    # ── Morning (pre-market) ──
    "morning_brief": {
        "time": "7:30 AM EST",
        "channel": ["email", "slack", "push"],
        "content": "Today's top signals, regime status, active trade updates",
        "priority": "high",
    },

    # ── New Signal Fired ──
    "new_signal": {
        "trigger": "Any strategy generates a signal with score > 65",
        "channel": ["push", "slack"],
        "content": "Quick summary: ticker, direction, score, entry zone",
        "priority": "high",
        "throttle": "Max 1 per strategy per hour (avoid alert fatigue)",
    },

    # ── Entry Zone Reached ──
    "entry_zone_hit": {
        "trigger": "A signal you marked [Remind Later] — stock hits the entry zone",
        "channel": ["push"],
        "content": "MSFT just hit $428 — your entry zone. Signal still valid?",
        "priority": "high",
    },

    # ── Active Trade Alerts ──
    "approaching_stop": {
        "trigger": "Active trade price is within 1% of stop-loss",
        "channel": ["push", "slack"],
        "content": "⚠ NVDA at $134.50 — stop at $133.50 (0.7% away). Review now.",
        "priority": "urgent",
    },
    "stop_hit": {
        "trigger": "Active trade price breaches stop-loss level",
        "channel": ["push", "slack", "email"],
        "content": "🔴 NVDA hit stop at $133.50. EXIT NOW. Current: $133.20",
        "priority": "urgent",
    },
    "target_hit": {
        "trigger": "Active trade price reaches target",
        "channel": ["push", "slack"],
        "content": "🟢 NVDA hit Target 1 at $152. Take profit on 50%?",
        "priority": "high",
    },
    "time_stop": {
        "trigger": "Active trade exceeds max hold period",
        "channel": ["push", "slack"],
        "content": "⏰ NVDA Day 14/14. Max hold reached. Reassess or close.",
        "priority": "high",
    },

    # ── Regime Change ──
    "regime_shift": {
        "trigger": "Regime classification changes (held for 3+ days)",
        "channel": ["slack", "email"],
        "content": "Regime shifted: Bull Choppy → Bear Trend. Strategy weights adjusting. Review active trades.",
        "priority": "high",
    },

    # ── Risk Alerts ──
    "drawdown_warning": {
        "trigger": "Portfolio drawdown exceeds -7%",
        "channel": ["push", "slack", "email"],
        "content": "⚠ Portfolio down 7% from peak. Consider reducing exposure.",
        "priority": "urgent",
    },
    "correlation_spike": {
        "trigger": "Portfolio avg correlation > 0.6",
        "channel": ["slack"],
        "content": "Your positions are highly correlated. Sector concentration risk.",
        "priority": "medium",
    },

    # ── Signal Invalidation ──
    "signal_invalidated": {
        "trigger": "A pending signal's conditions changed (e.g., pair lost cointegration)",
        "channel": ["push"],
        "content": "AMD/INTC pair signal CANCELLED — cointegration broke (ADF p > 0.05)",
        "priority": "medium",
    },

    # ── Weekly Summary ──
    "weekly_review": {
        "time": "Sunday 6 PM EST",
        "channel": ["email"],
        "content": "Week recap: trades taken, P&L, model accuracy, signals passed (phantom P&L), strategy performance, upcoming catalysts",
        "priority": "medium",
    },
}

# Alert delivery channels
CHANNELS = {
    "push":  "Mobile push notification (via Pushover or ntfy.sh — free)",
    "slack": "Slack webhook to a private #trading channel",
    "email": "Email via SendGrid free tier (100/day) or SMTP",
}
```

---

### 22.4 Trade Logging (Manual Entry)

When you take a trade, you log it. This is how the system tracks performance and recalibrates Kelly parameters.

```python
# backend/tracker/trade_log.py

"""
Trade Log — Manual Entry Interface

When user clicks [Take Trade]:
1. Pre-filled form appears with system's recommended values
2. User adjusts to ACTUAL execution values (price may differ, size may differ)
3. System starts monitoring this trade for alerts

When user exits a trade:
1. User clicks [Close Trade] on the active trades panel
2. Enters actual exit price and reason
3. System computes P&L and logs everything
"""

# ── What gets logged per trade ──

TRADE_LOG_SCHEMA = {
    # Pre-filled from signal (user can modify)
    "ticker": "NVDA",
    "direction": "long",
    "strategy": "catalyst",           # Which strategy generated this
    "signal_score": 84,               # Score at time of signal
    "regime_at_entry": "bull_choppy",

    # User enters (actual execution values)
    "entry_date": "2026-03-17",
    "entry_price": 139.50,            # Actual fill price
    "shares": 72,                     # Actual shares bought
    "position_size_pct": 5.2,         # % of capital used

    # System-set (from adaptive params at time of entry)
    "stop_loss": 133.50,
    "target_1": 152.00,
    "target_2": 158.00,
    "max_hold_days": 14,
    "atr_at_entry": 3.85,
    "vix_at_entry": 17.3,
    "vol_regime_at_entry": "normal",
    "kelly_fraction_used": 0.052,

    # Filled on exit
    "exit_date": None,
    "exit_price": None,
    "exit_reason": None,              # "target_hit", "stop_hit", "time_stop",
                                      # "manual_close", "signal_invalidated"
    "pnl_dollars": None,
    "pnl_percent": None,
    "hold_days": None,

    # User notes (optional but valuable)
    "entry_notes": "Liked the earnings beat, sector strong",
    "exit_notes": "",
}

# ── Phantom Trades (signals you passed on) ──

PHANTOM_TRADE_SCHEMA = {
    "ticker": "AMZN",
    "direction": "long",
    "strategy": "cross_asset",
    "signal_score": 71,
    "signal_date": "2026-03-17",
    "entry_price_suggested": 198.00,
    "stop_suggested": 191.00,
    "target_suggested": 212.00,
    "pass_reason": "Already have too much tech exposure",

    # System tracks what WOULD have happened
    "phantom_exit_date": None,        # When stop/target/time-stop would have hit
    "phantom_exit_price": None,
    "phantom_pnl_pct": None,
    "phantom_outcome": None,          # "would_have_won", "would_have_lost"
}
```

---

### 22.5 Performance Dashboard (Your Report Card)

```python
# frontend/pages/performance.py

"""
Performance Page Layout

SECTION 1: Overall Stats
┌────────────┬────────────┬─────────────┬────────────┬──────────────┐
│ Total P&L  │ Win Rate   │ Avg Win     │ Avg Loss   │ Profit Factor│
│ +$12,340   │ 62%        │ +4.8%       │ -2.1%      │ 2.3          │
│ +12.3%     │ (38/61)    │             │            │              │
└────────────┴────────────┴─────────────┴────────────┴──────────────┘

SECTION 2: Per-Strategy Breakdown
┌──────────────┬────────┬──────────┬────────┬───────────┬───────────┐
│ Strategy     │ Trades │ Win Rate │ Avg P&L│ Sharpe    │ Contrib % │
├──────────────┼────────┼──────────┼────────┼───────────┼───────────┤
│ Stat Arb     │ 15     │ 67%      │ +2.1%  │ 1.8       │ 22%       │
│ Catalyst     │ 12     │ 58%      │ +3.5%  │ 1.6       │ 28%       │
│ Cross-Asset  │ 18     │ 56%      │ +1.8%  │ 1.4       │ 20%       │
│ Flow         │ 9      │ 67%      │ +2.8%  │ 2.1       │ 18%       │
│ Gap Revert   │ 7      │ 71%      │ +0.9%  │ 1.9       │ 12%       │
└──────────────┴────────┴──────────┴────────┴───────────┴───────────┘

SECTION 3: Your Judgment vs The Model
┌───────────────────────────────────────────────────────────────────┐
│ Signals you TOOK:     38 trades, 62% win rate, +$12,340          │
│ Signals you PASSED:   23 signals, phantom 57% win rate, +$4,120  │
│                                                                   │
│ INSIGHT: Your filtering added +5% win rate vs taking everything. │
│ BUT: You passed on $4,120 of profit. Net judgment alpha: +$1,200 │
│                                                                   │
│ Best override: Passed on TSLA short (would have lost -$890) ✓    │
│ Worst override: Passed on NVDA long (would have gained +$2,100) ✗│
└───────────────────────────────────────────────────────────────────┘

SECTION 4: Equity Curve
  Interactive chart showing:
  - Your actual P&L curve (trades you took)
  - Phantom P&L curve (all signals, no filtering)
  - SPY buy-and-hold benchmark
  - Regime shading (colored background bands)

SECTION 5: Trade Log
  Sortable/filterable table of all trades with full detail
  Export to CSV for your own analysis
"""
```

---

### 22.6 The Decision Support Extras

Things the system computes JUST to help your decision-making, not for automation:

```python
# backend/decision_support/

"""
CONVICTION METER
For each signal, show a visual breakdown of WHY the score is what it is:
  Technical:    ████████░░  78/100  "RSI 48 pullback to 20 SMA"
  Fundamental:  ██████░░░░  62/100  "P/E below sector, EPS growing 18%"
  Catalyst:     █████████░  91/100  "Earnings beat +8%, guidance raised"
  News:         ███████░░░  72/100  "84% positive sentiment, trending"
  Risk/Reward:  ████████░░  80/100  "2.8:1 R/R ratio"
  ─────────────────────────────────
  COMPOSITE:    ████████░░  84/100  → STRONG BUY

WHAT COULD GO WRONG (red team every signal)
  1. "Broad market near ATH — if SPY pulls back 2%, this trade loses regardless"
  2. "Earnings was good but revenue growth is slowing — drift may be weaker"
  3. "VIX term structure is flattening — possible vol expansion ahead"

SIMILAR HISTORICAL TRADES
  "The last 8 times this strategy fired with similar conditions:"
  "Win rate: 75%, Avg return: +5.2%, Avg hold: 8 days"
  "Worst case: -3.1%, Best case: +11.4%"

PORTFOLIO IMPACT PREVIEW
  "If you take this trade:"
  "  - Gross exposure: 142% → 147%"
  "  - Tech sector: 28% → 33% (⚠ approaching 35% limit)"
  "  - Portfolio correlation: 0.41 → 0.44"
  "  - Daily VaR: 1.6% → 1.8%"
"""
```

---

### 22.7 Updated Architecture (No Broker, No Automation)

**REMOVE from the spec:**
- `backend/portfolio/execution.py` — no auto-execution
- All references to Interactive Brokers, Alpaca, or broker APIs
- Any "auto-place order" logic
- Webhook-based order routing

**KEEP but rename:**
- `execution.py` → `decision_support.py` — computes portfolio impact previews
- Order generation → Signal generation (the system generates signals, not orders)

**ADD:**
- `backend/tracker/phantom_trades.py` — tracks signals you passed on
- `backend/decision_support/conviction.py` — visual conviction breakdown
- `backend/decision_support/red_team.py` — counter-arguments for each signal
- `backend/decision_support/historical_match.py` — similar past trade outcomes
- `backend/decision_support/portfolio_impact.py` — preview impact before you decide

---

### 22.8 Notification Stack (Free/Cheap)

Since alerts are your lifeline for manual trading, here are the delivery options:

```
Mobile push notifications:
  → ntfy.sh (free, self-hostable, instant push to phone)
  → Pushover ($5 one-time, reliable, iOS + Android)

Slack:
  → Free workspace, incoming webhook to #trading channel
  → Rich formatting, can include charts as image attachments

Email:
  → SendGrid free tier (100 emails/day — plenty for alerts)
  → Or use Gmail SMTP directly

Desktop:
  → Streamlit dashboard auto-refreshes during market hours
  → Browser push notifications via streamlit-autorefresh
```

Recommended setup: **ntfy.sh for urgent alerts** (stop approaching, target hit) + **Slack for daily signals** (morning brief, new picks) + **email for weekly review**.

---

### 22.9 Config Update

```bash
# Add to .env.example

# ── Execution Mode ──
EXECUTION_MODE=advisory          # "advisory" (manual) — only mode supported
                                 # No "auto" mode exists. By design.

# ── Alert Delivery ──
NTFY_TOPIC=quantpulse-alerts     # ntfy.sh topic (free push notifications)
NTFY_PRIORITY=high               # Default priority for push alerts

SLACK_WEBHOOK_URL=               # Slack incoming webhook
SLACK_CHANNEL=trading            # Channel name

SENDGRID_API_KEY=                # For email alerts (free tier: 100/day)
ALERT_EMAIL_TO=dharit@email.com

# ── Alert Preferences ──
ALERT_MARKET_HOURS_ONLY=true     # Don't wake me up at 2 AM
ALERT_THROTTLE_MINUTES=30        # Min time between alerts of same type
ALERT_MIN_SCORE_FOR_PUSH=65      # Only push-notify for high-conviction signals
```
