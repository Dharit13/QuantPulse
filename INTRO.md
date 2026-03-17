# QuantPulse — Plain English Introduction

## What is QuantPulse?

QuantPulse is a tool that helps find good stock trades. It doesn't buy or sell anything on its own — it looks at the market every day and says "here's a trade worth considering, here's why, and here's the risk." The human makes the final decision on every trade.

Think of it like a really smart research assistant that never sleeps, never gets emotional, and checks hundreds of stocks at once using math instead of gut feeling. It's a cockpit, not an autopilot.

## Why not just use the same tools everyone else uses?

Most people who trade stocks use the same basic indicators — things like RSI or MACD that you see on every trading app. The problem is: if everyone is looking at the same signals, there's no advantage. It's like everyone showing up to the same sale — the deals are already gone.

QuantPulse looks for something different. It looks for situations where the market is temporarily wrong for a specific, explainable reason — not just because a line crossed another line on a chart.

## What kinds of trades does it find?

It has two main trade-finding engines and a few supporting tools:

### 1. Pairs Trading (Statistical Arbitrage)

Imagine two oil companies — say ExxonMobil and Chevron. They normally move together because they're in the same business, affected by the same oil prices. But sometimes one stock drops while the other doesn't, for no real fundamental reason — maybe a fund had to sell one to raise cash, or traders overreacted to a headline.

QuantPulse detects when two stocks that should move together have drifted apart. The bet is simple: buy the cheap one, short the expensive one, and wait for them to come back together. It uses three different statistical tests to make sure the relationship is real, not random.

### 2. Earnings Drift (Catalyst Trading)

When a company reports earnings that are much better than expected, the stock usually jumps. But here's the thing most people don't know: it keeps drifting in the same direction for weeks afterward. This has been documented by academics since 1968 and it still works — because analysts are slow to update their estimates and big funds can't rebalance instantly.

QuantPulse watches for earnings surprises, checks if analysts are revising their targets upward, looks for insider buying (when the CEO is buying their own stock, that's a strong signal), and combines all of that into a single score.

### 3. Cross-Asset Signals (Market Weather)

This one doesn't generate trades directly. Instead, it watches bonds, oil, gold, the dollar, and volatility to figure out what kind of market we're in — is it calm and trending up? Choppy? Crashing? Based on that, it decides how aggressive or conservative the other strategies should be. In a crisis, it tells the system to mostly sit in cash. In a calm bull market, it lets the strategies run.

### 4. Institutional Flow (Confirmation)

Big hedge funds and institutions can't buy millions of shares quietly. When they make large, urgent trades — especially through options — it leaves traces. QuantPulse picks up these traces and uses them to confirm signals from the other strategies. If the math says "buy this stock" AND big money is flowing in the same direction, that's a stronger signal.

### 5. Gap Trading (Specialist)

Sometimes a stock opens the next morning significantly higher or lower than where it closed — that's called a gap. Most small gaps (1-3%) caused by overnight noise tend to fill back within the first hour of trading. QuantPulse identifies which gaps are likely to fill and which ones are driven by real news (those don't fill). It only recommends this in calm markets.

## How does it decide how much to risk?

Most people put the same amount of money into every trade, which is wasteful. QuantPulse uses a formula called the Kelly Criterion to suggest an optimal position size based on confidence level and risk/reward ratio. But we use a very conservative version (quarter-Kelly) because we don't fully trust our own estimates yet. As the system builds a track record, we can gradually increase it.

The system recommends a size — the human decides whether to follow it.

## How does it protect against losses?

QuantPulse doesn't execute anything. It recommends protective actions and the human decides whether to follow them. Four layers of recommendations:

1. **Every trade comes with a stop-loss price** — if the stock hits that price, the system says to exit. The human still has to place the order.
2. **Each strategy has a circuit breaker** — if a strategy's recent signals have been losing money, the system stops recommending new trades from that strategy for a cooling-off period. It flags this on the dashboard.
3. **The whole portfolio has limits** — if the portfolio is already heavily exposed to one sector or total risk is too high, the system warns not to add more. It might say "do not trade" or reduce the recommended size.
4. **In a crisis, the system says sit out** — when it detects a market crash, it shifts the recommended allocation to mostly cash and scales back all strategy signals.

None of this happens automatically. The system advises, the human executes.

## How does it know if it's actually working?

This is what separates it from most trading tools. Every signal the system generates is recorded — even the ones that aren't acted on. It tracks what would have happened if the trade had been taken. After 90 days, it can show: "out of the last 50 similar signals, 62% would have been winners, with an average return of 1.2%."

If a strategy's track record starts deteriorating, the system flags it as "degraded" or "paused" and stops recommending new trades from it. But again — the human can see the flag and make their own judgment. The system doesn't shut anything off; it says when it thinks you should.

## Before recommending a trade, it checks three things

Every signal goes through a three-step check before it reaches the dashboard:

1. **Can this trade actually be executed?** — Is there enough trading volume? Can we get in and out without moving the price? If it's a short trade, can the stock actually be borrowed? What's the estimated slippage?

2. **How have similar signals performed recently?** — The system looks at its own track record: "in the last 90 days, how did similar trades in the same market conditions do?" If there's not enough history yet, it says so honestly and flags the signal as "conditional."

3. **Is this strategy still healthy?** — Is the strategy's recent performance holding up, or is it degrading? Is the current market regime favorable for this type of trade? If things are deteriorating, the system automatically reduces the recommended size.

Based on these checks, every signal gets one of three labels:

- **Trade** — all checks pass, evidence supports it
- **Conditional trade** — the logic is sound but there isn't enough historical evidence yet, or conditions are uncertain
- **Do not trade** — something failed (can't execute cleanly, strategy is paused, or risk limits would be breached)

## What's the goal?

Not a specific return number. The goal is:

- Make money after costs over time
- Never have a drawdown worse than 15%
- Know when to be aggressive and when to sit out
- Build a track record of evidence, not just theories

It's designed to survive first and compound second. And the human always has the final say.
