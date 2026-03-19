"""AI-powered summaries for Market Overview, Scanner, and Swing Picks tabs.

Each function sends a focused prompt to Claude and returns a dict of
plain-English text fields, or None on failure (caller keeps existing UI).
"""

from __future__ import annotations

import json
import logging

from backend.config import settings

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-20250514"


def _call_claude(system: str, user: str, max_tokens: int = 800) -> dict | None:
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed")
        return None
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        prompt_hint = system[:60].replace("\n", " ")
        logger.warning("AI JSON parse failed for [%s...]: response was not valid JSON", prompt_hint)
        return None
    except Exception as e:
        prompt_hint = system[:60].replace("\n", " ")
        logger.warning("AI call failed for [%s...]: %s", prompt_hint, e)
        return None


# ── Market Overview ──────────────────────────────────────────

_MARKET_SYSTEM = """\
You are a senior trader at Jane Street giving a morning market briefing to a \
friend who invests long-term (6-12 months, targeting 30%+ returns).

You will receive current market regime data. Give a concise, opinionated \
briefing that helps them decide how to position today.

Rules:
- Write for a non-professional. No unexplained jargon.
- Be direct and opinionated. "The market is..." not "The data suggests..."
- Reference specific numbers (VIX level, breadth %, confidence %).
- Do NOT mention you are an AI.
- Dollar amounts use $, percentages use %.

Respond with valid JSON:
{
  "market_summary": "<3-5 sentences: what's happening, what it means, what to do>",
  "strategy_advice": "<1-2 sentences: which approach works best right now>"
}"""


def ai_market_summary(regime_data: dict) -> dict | None:
    regime = regime_data.get("regime", "unknown")
    confidence = regime_data.get("confidence", 0)
    vix = regime_data.get("vix", 0)
    breadth = regime_data.get("breadth_pct", 0)
    adx = regime_data.get("adx", 0)
    weights = regime_data.get("strategy_weights", {})
    probs = regime_data.get("regime_probabilities", {})

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Confidence: {confidence:.0%}\n"
        f"VIX: {vix:.1f}\n"
        f"Breadth (% above 200-SMA): {breadth:.1f}%\n"
        f"ADX (trend strength): {adx:.1f}\n"
        f"Regime Probabilities: {json.dumps(probs)}\n"
        f"Strategy Weights: {json.dumps(weights)}"
    )
    return _call_claude(_MARKET_SYSTEM, user, max_tokens=500)


# ── Market Timing Tip ─────────────────────────────────────────

_TIMING_TIP_SYSTEM = """\
You are a friendly trading coach giving a short, practical tip about WHEN to \
trade right now, based on the current market session and conditions.

You will receive:
- The current time and market session (open, pre-market, after-hours, closed)
- Current market regime data (VIX, breadth, trend)
- Day of week

Write 1-2 sentences of actionable timing advice for a beginner investor. \
Combine the time-of-day context with what the market is actually doing.

Examples of good tips:
- "Market opens in 2 hours. VIX is elevated at 25 — expect a choppy open. \
Wait until 10 AM for prices to settle before buying anything."
- "Afternoon session and the market is trending down today. Not the best time \
to buy — set alerts and wait for a green day."
- "Market is closed. Futures are calm, so tomorrow's open should be smooth. \
Good night to plan your trades."
- "Morning session in a strong bull trend — this is a great window to enter \
positions. Volume is high and momentum is on your side."

Rules:
- Plain English only. No jargon.
- Reference specific data: VIX level, market direction, time.
- Be honest — if it's a bad time to trade, say so.
- Keep it to 1-2 sentences max.
- Do NOT mention AI.

Respond with valid JSON:
{
  "tip": "<1-2 sentences of timing advice>"
}"""


def ai_market_timing_tip(data: dict) -> dict | None:
    """Generate a contextual trading tip based on time + market conditions."""
    session = data.get("session", "closed")
    time_et = data.get("time_et", "")
    day = data.get("day_of_week", "")
    regime = data.get("regime", "unknown")
    vix = data.get("vix", 0)
    breadth = data.get("breadth_pct", 0)

    user = (
        f"Current time: {time_et} ET, {day}\n"
        f"Market session: {session}\n"
        f"Market regime: {regime.replace('_', ' ')}\n"
        f"VIX (fear level): {vix:.1f}\n"
        f"Breadth (% stocks above 200-SMA): {breadth:.1f}%"
    )
    return _call_claude(_TIMING_TIP_SYSTEM, user, max_tokens=200)


# ── Market Action Banner ──────────────────────────────────────

_ACTION_BANNER_SYSTEM = """\
You are a no-nonsense trading coach giving ONE bold, clear action call to a \
retail investor checking their dashboard. Think of it as the single most \
important thing they need to hear right now.

You will receive current market regime data. Based on the data, decide the \
overall market tone and give a short, punchy recommendation.

Pick exactly ONE of these tones based on the data:
- "bullish" — strong buying opportunity, market looks great
- "cautious" — mixed signals, be selective, don't go all-in
- "bearish" — pull back, protect capital, avoid new buys
- "crisis" — sell or hedge, capital preservation is priority

Rules:
- headline: 6-10 words max. Bold, direct. Examples: "Great buying window — load up today", \
  "Take a break — sit this week out", "Red alert — protect your cash now"
- detail: 1-2 sentences explaining WHY in plain English. Reference specific numbers.
- Do NOT mention AI or models. Write as if you're a friend texting them.
- Be dramatic but honest. This is the banner they see FIRST.

Respond with valid JSON:
{
  "tone": "bullish|cautious|bearish|crisis",
  "headline": "<6-10 word bold action call>",
  "detail": "<1-2 sentences explaining why, referencing specific numbers>"
}"""


def ai_market_action_banner(regime_data: dict) -> dict | None:
    """Generate a bold one-liner market action banner for the dashboard."""
    regime = regime_data.get("regime", "unknown")
    confidence = regime_data.get("confidence", 0)
    vix = regime_data.get("vix", 0)
    breadth = regime_data.get("breadth_pct", 0)
    adx = regime_data.get("adx", 0)
    weights = regime_data.get("strategy_weights", {})
    probs = regime_data.get("regime_probabilities", {})
    cash_weight = weights.get("cash", 0)

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Confidence: {confidence:.0%}\n"
        f"VIX: {vix:.1f}\n"
        f"Breadth (% above 200-SMA): {breadth:.1f}%\n"
        f"ADX (trend strength): {adx:.1f}\n"
        f"Cash allocation: {cash_weight:.0%}\n"
        f"Regime Probabilities: {json.dumps(probs)}\n"
        f"Strategy Weights: {json.dumps(weights)}"
    )
    return _call_claude(_ACTION_BANNER_SYSTEM, user, max_tokens=300)


# ── AI Stock Picker for Dashboard ─────────────────────────────

_STOCK_PICKER_SYSTEM = """\
You are a senior long-term investment analyst. You will receive a list of \
stock candidates with their price data, and the current market regime. \
Your job is to pick the TOP 5 best stocks for a 6-12 month investment.

For each pick, explain in 1 sentence WHY this stock is worth buying right now, \
in plain English that a non-investor would understand. No jargon.

How to evaluate:
- Stocks that dropped recently but are in strong sectors = buying opportunity
- Low RSI (under 40) = the stock is "on sale"
- Price above long-term average (SMA 200) = healthy company in a dip
- Diverse sectors = don't put all picks in one industry
- Prefer well-known companies a regular person would recognize

Respond with valid JSON:
{
  "picks": [
    {
      "ticker": "AAPL",
      "reason": "Apple dropped 5% this month even though their business is fine — good chance to buy a great company at a discount."
    }
  ]
}

Return exactly 5 tickers. Each reason must be 1 sentence, plain English."""


def ai_pick_dashboard_stocks(regime: str, candidates: list[dict]) -> list[str] | None:
    """Ask Claude to pick the best 5 stocks from scored candidates."""
    if not candidates:
        return None

    lines = []
    for c in candidates[:30]:
        lines.append(
            f"  {c['ticker']} ({c['name']}): "
            f"${c['price']:.0f}, "
            f"sector={c['sector']}, "
            f"monthly return={c.get('return_20d', 0):+.1f}%, "
            f"RSI={c.get('rsi', 50):.0f}, "
            f"score={c.get('score', 50)}"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n\n"
        f"Stock candidates ({len(candidates)} total, showing top {len(lines)}):\n"
        + "\n".join(lines)
    )
    result = _call_claude(_STOCK_PICKER_SYSTEM, user, max_tokens=500)
    if result and "picks" in result:
        picked = []
        ticker_reasons = {}
        for p in result["picks"]:
            picked.append(p["ticker"])
            ticker_reasons[p["ticker"]] = p.get("reason", "")
        return picked, ticker_reasons
    return None


# ── Strategy Allocation Explanation ───────────────────────────

_ALLOCATION_SYSTEM = """\
You are explaining investment strategy allocations to someone who has NEVER \
invested before. They see percentage bars on a dashboard and need to understand \
what each strategy does and WHY it got its percentage.

You will receive the current market regime, VIX, and the strategy weights. \
For each strategy, write 2-3 sentences explaining:
1. What it does in everyday language (use an analogy)
2. Why it got THIS specific percentage right now given the market

Strategy names and what they actually do:
- stat_arb: Finds two stocks that normally move together but temporarily \
  diverged, and bets they'll come back. Like noticing Coke and Pepsi usually \
  trade similarly, but Pepsi dropped 5% for no reason — buy Pepsi, it'll recover.
- catalyst: Buys stocks where something specific happened — executives bought \
  their own shares, the company beat earnings expectations, or analysts upgraded it. \
  Like following what the smart money does.
- momentum: Rides sectors that are already going up. Like surfing — catch the \
  wave while it's still moving. Works best when markets have a clear direction.
- flow: Watches what big institutions (hedge funds, pension funds) are secretly \
  buying. When billions of dollars move into a stock, the price usually follows.
- intraday/gap_reversion: When a stock opens way higher or lower than it closed \
  yesterday (a "gap"), it usually fills that gap during the day. Quick in-and-out trades.
- cash: Money not invested, sitting safely on the sideline.

Rules:
- ZERO finance jargon. No "mean reversion", "alpha", "volatility", "RSI".
- Use everyday analogies and examples with real company names when helpful.
- Explain WHY the percentage is high or low given the current market.
- If cash is high, explain that keeping money safe IS a strategy.
- Do NOT mention you are an AI.

Respond with valid JSON — one entry per strategy that has > 0% allocation:
{
  "strategies": [
    {
      "key": "catalyst",
      "name": "Insider & Earnings Moves",
      "explanation": "2-3 sentences in plain English"
    }
  ]
}"""


def ai_allocation_explain(regime_data: dict) -> dict | None:
    regime = regime_data.get("regime", "unknown")
    vix = regime_data.get("vix", 0)
    weights = regime_data.get("strategy_weights", {})
    breadth = regime_data.get("breadth_pct", 0)

    weight_lines = []
    for k, v in sorted(weights.items(), key=lambda x: -x[1]):
        if v >= 0.01:
            weight_lines.append(f"  {k}: {v:.0%}")

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"VIX: {vix:.1f}\n"
        f"Market Breadth: {breadth:.1f}%\n\n"
        f"Current strategy allocations:\n" + "\n".join(weight_lines)
    )
    return _call_claude(_ALLOCATION_SYSTEM, user, max_tokens=800)


# ── Regime Probabilities ─────────────────────────────────────

_REGIME_PROBS_SYSTEM = """\
You are a senior trader at Jane Street. You see the current market regime \
probabilities, indicators, and recent market news headlines. Give a short, \
specific action with timing, plus a quick sentiment read from the news.

Rules:
- One sentence for what to do right now.
- One sentence for WHEN to buy — be specific (e.g. "wait for SPY to drop below $540" \
  or "buy this week while RSI is below 30" or "wait 5-7 days for the dip to finish").
- Use the VIX, breadth, and ADX to determine timing. High VIX = wait. Low RSI = buy now.
- Read the news headlines and give a 2-3 sentence market mood summary. What are \
  investors worried about? What's driving the market? Any catalysts coming up?
- Keep it dead simple. No jargon. Write like you're texting a friend.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "action": "<1 sentence: what to do right now>",
  "timing": "<1 sentence: specific timeframe and condition for buying>",
  "news_sentiment": "<2-3 sentences: what's happening in the market based on the news, overall mood, key risks or catalysts>"
}"""


_TICKER_PICKER_SYSTEM = """\
You are a senior long-term investment analyst. Given the current market \
conditions, recent news, and the full S&P 500 list, pick the 50 stocks \
MOST WORTH investigating for a 6-12 month investment.

This is NOT for short-term trades. Focus on stocks where:
1. Insider buying is likely — company executives buying their own stock is \
   the strongest long-term signal. Look for beaten-down quality companies, \
   stocks near 52-week lows, companies with recent bad news that's overdone.
2. Strong earnings — companies that just reported great results and are \
   still reasonably priced for long-term growth.
3. Analyst upgrades — Wall Street is getting more bullish, which often \
   precedes 6-12 month price moves.
4. Sector tailwinds — sectors benefiting from macro trends (AI, energy \
   transition, reshoring, healthcare innovation, etc).
5. Undervalued quality — great companies temporarily cheap due to market \
   fear, rotation, or one-time events.

IMPORTANT:
- Spread across at least 8 different sectors.
- Include a mix of large-cap stability AND mid-cap growth potential.
- Prefer companies with strong balance sheets that can weather downturns.
- Consider the current market regime when picking.

Respond with valid JSON:
{
  "tickers": ["AAPL", "MSFT", ...],
  "reasoning": "1 sentence on the overall thesis for these picks"
}

Return EXACTLY 50 tickers from the provided S&P 500 list. No duplicates."""


def _get_market_movers_data(all_tickers: list[str]) -> str:
    """Quickly get today's biggest movers, drops, and volume spikes from yfinance.
    
    Uses batch download for speed — one HTTP call for all tickers.
    """
    try:
        import yfinance as yf

        top_tickers = all_tickers[:100]
        data = yf.download(
            top_tickers, period="5d", group_by="ticker",
            threads=True, progress=False,
        )
        if data.empty:
            return ""

        movers: list[str] = []
        for ticker in top_tickers:
            try:
                if ticker in data.columns.get_level_values(0):
                    close = data[ticker]["Close"].dropna()
                elif len(top_tickers) == 1:
                    close = data["Close"].dropna()
                else:
                    continue
                if len(close) < 2:
                    continue
                ret_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100
                ret_5d = (close.iloc[-1] / close.iloc[0] - 1) * 100 if len(close) >= 5 else ret_1d
                price = close.iloc[-1]
                movers.append(f"{ticker}: ${price:.0f}, 1d={ret_1d:+.1f}%, 5d={ret_5d:+.1f}%")
            except Exception:
                continue

        if not movers:
            return ""

        movers_sorted = sorted(movers, key=lambda x: abs(float(x.split("5d=")[1].rstrip("%"))), reverse=True)
        return "\n\nBiggest movers (last 5 days):\n" + "\n".join(movers_sorted[:30])
    except Exception as e:
        logger.debug("Failed to get movers data: %s", e)
        return ""


def ai_pick_scan_tickers(
    regime: str, all_tickers: list[str], vix: float = 0, breadth_pct: float = 0,
) -> list[str] | None:
    """Ask Claude to pick the 50 most interesting S&P 500 tickers to scan,
    using real-time market data: regime, VIX, and news."""
    news = _fetch_market_news()
    news_block = ""
    if news:
        news_block = "\n\nRecent Market News:\n" + "\n".join(f"- {h}" for h in news[:8])

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"VIX: {vix:.1f}\n"
        f"Market Breadth: {breadth_pct:.1f}% of stocks above 200-day MA\n"
        f"{news_block}\n\n"
        f"Pick 50 S&P 500 tickers. Use the news headlines and market conditions "
        f"to guide your picks. Focus on stocks likely to have insider buying, "
        f"earnings surprises, or analyst revisions right now."
    )
    result = _call_claude(_TICKER_PICKER_SYSTEM, user, max_tokens=800)
    if result and "tickers" in result:
        valid_set = set(all_tickers)
        picked = [t for t in result["tickers"] if t in valid_set]
        if len(picked) >= 20:
            logger.info("AI picked %d scan tickers: %s", len(picked), result.get("reasoning", ""))
            return picked[:50]
    return None


def _fetch_market_news() -> list[str]:
    """Grab recent market news from yfinance across multiple tickers for broad coverage."""
    headlines: list[str] = []
    seen: set[str] = set()
    try:
        import yfinance as yf
        for ticker in ["SPY", "^VIX", "QQQ", "DIA"]:
            try:
                t = yf.Ticker(ticker)
                for item in (t.news or [])[:8]:
                    content = item.get("content", item)
                    title = content.get("title", "") or item.get("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        headlines.append(title)
            except Exception:
                continue
    except Exception:
        pass
    return headlines[:12]


def ai_regime_probs(data: dict) -> dict | None:
    probs = data.get("probabilities", {})
    vix = data.get("vix", 0)
    adx = data.get("adx", 0)
    breadth = data.get("breadth_pct", 0)

    news = _fetch_market_news()
    news_block = ""
    if news:
        news_block = "\n\nRecent Market News:\n" + "\n".join(f"  - {h}" for h in news[:8])

    user = (
        f"Regime Probabilities: {json.dumps(probs)}\n"
        f"VIX: {vix:.1f}\n"
        f"ADX: {adx:.1f}\n"
        f"Breadth: {breadth:.1f}%"
        f"{news_block}"
    )
    return _call_claude(_REGIME_PROBS_SYSTEM, user, max_tokens=400)


# ── Scanner ──────────────────────────────────────────────────

_SCAN_SYSTEM = """\
You are a senior portfolio manager at Jane Street with 20 years of experience. \
Your friend trusts you completely with their money. They invest long-term \
(6-12 months, targeting 30%+ returns).

You will receive the current regime and the top signals from a scanner. \
Give a DEEP, specific analysis — not surface-level observations.

Rules for scan_summary:
- Don't just say "insider buying across N names." That's what the data already shows.
- ANALYZE the pattern: Are these insiders buying because of sector rotation? \
  Upcoming earnings? Regulatory changes? Tax-loss harvesting recovery? \
  Contrarian bottom-fishing in a bear market?
- Compare the signals: Which sectors dominate? Is there a theme? \
  Are the insiders right historically (insider buying in bear markets has 65%+ hit rate)?
- Be specific about the regime: In a bear trend, what does concentrated insider buying \
  actually mean? When did this pattern last appear and what happened?
- Give a concrete recommendation: Should the user act now or wait? \
  How much of their portfolio? Which signals are strongest vs which to skip?

Rules for top_pick:
- Don't just say "XYZ leads with $X in purchases." That's restating the data.
- EXPLAIN the thesis: What is the company? What do they do? What's the catalyst? \
  Why are insiders buying NOW specifically? What's the likely timeline?
- Compare to alternatives: Why is this #1 and not the others?
- Give a specific trade idea: Entry price, how long to hold, what would make you sell.
- Quantify the opportunity: What's the realistic upside? What's the risk?

For each field, provide BOTH a technical version AND a simple version.
The "simple" versions are for someone who knows NOTHING about finance. \
No jargon. Use everyday language and analogies.

Do NOT mention you are an AI.

Respond with valid JSON:
{
  "scan_summary": "<4-6 sentences: deep technical analysis — patterns, historical context, regime implications, concrete recommendation>",
  "scan_summary_simple": "<3-4 sentences: plain English — what this means for a regular person, should they buy, what's the risk>",
  "top_pick": "<4-6 sentences: deep analysis — the company, the catalyst, the thesis, specific trade idea with entry/hold/risk>",
  "top_pick_simple": "<2-3 sentences: plain English — why this one company, what could happen, what's the risk in simple terms>"
}"""


def ai_scan_summary(regime: str, signals: list[dict]) -> dict | None:
    if not signals:
        return None

    top = signals[:10]
    sig_lines = []
    for s in top:
        sig = s.get("signal", s)
        entry = sig.get("entry_price", 0)
        stop = sig.get("stop_loss", 0)
        target = sig.get("target", 0)
        risk = abs(entry - stop) if entry and stop else 0
        reward = abs(target - entry) if target and entry else 0
        rr = f"{reward/risk:.1f}" if risk > 0 else "?"
        sig_lines.append(
            f"  {sig.get('ticker')} {sig.get('direction')} "
            f"({sig.get('strategy')}, score {sig.get('signal_score', 0):.0f}, "
            f"conviction {sig.get('conviction', 0):.2f}): "
            f"entry=${entry:.2f}, stop=${stop:.2f}, target=${target:.2f}, R/R={rr}:1 — "
            f"{sig.get('edge_reason', '')}"
        )

    user = (
        f"Regime: {regime.replace('_', ' ')}\n"
        f"Total signals found: {len(signals)}\n\n"
        f"Signals (ranked by conviction):\n" + "\n".join(sig_lines)
    )
    return _call_claude(_SCAN_SYSTEM, user, max_tokens=1200)


# ── Signal Explanations ──────────────────────────────────────

_SIGNAL_EXPLAIN_SYSTEM = """\
You are explaining stock trading signals to someone who knows NOTHING about finance.

You will receive a list of signals with their technical edge reasons. For each signal, \
write a 1-2 sentence plain English explanation of why this stock is interesting.

Rules:
- NO jargon. No RSI, no R/R, no "cointegration", no "mean reversion."
- Use everyday analogies. Think of how you'd explain it to your grandmother.
- For insider buying: "The company's own executives are buying the stock with their own money — they know something."
- For earnings: "The company made more money than everyone expected."
- For technical setups: "The stock dropped for no real reason and is likely to bounce back."
- For sector strength: "This whole industry is doing well and this stock is leading the pack."
- Keep each explanation SHORT — 1-2 sentences max.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "explanations": [
    {
      "ticker": "AAPL",
      "simple": "Apple's executives just bought a lot of company stock with their own money — a strong sign they believe the price is going up."
    }
  ]
}

Return one object per signal in the "explanations" array."""


def ai_signal_explain(signals: list[dict]) -> dict | None:
    if not signals:
        return None

    lines = []
    for s in signals[:10]:
        sig = s.get("signal", s)
        lines.append(
            f"  {sig.get('ticker')} ({sig.get('strategy', 'unknown')}): "
            f"{sig.get('edge_reason', 'no reason')}"
        )

    user = "Explain these signals in plain English:\n" + "\n".join(lines)
    return _call_claude(_SIGNAL_EXPLAIN_SYSTEM, user, max_tokens=800)


# ── Swing Picks ──────────────────────────────────────────────

_SWING_SYSTEM = """\
You are explaining short-term stock bets to a friend who knows NOTHING about \
finance. These are 3-10 day trades targeting big returns.

You will receive the current regime and the top swing picks. The picks are \
already ranked — the FIRST pick is #1 (the best one). Your "top pick" advice \
MUST be about the FIRST pick in the list, not a different one you like better.

Rules:
- ZERO jargon. No "RSI", "mean reversion", "oversold", "counter-trend", \
  "regime", "ATR", "breadth", "momentum", "risk/reward ratio", "volatility". \
  None. Ever.
- Write like you're texting a friend who has never bought a stock before.
- Use everyday comparisons: "like buying something on clearance sale", \
  "like betting on a horse race", "the stock got hammered and might bounce back".
- Be blunt about risk. "You could lose 15% in a day" is better than \
  "elevated downside risk in a bearish environment".
- Use dollar examples when possible: "If you put in $100, you could make $40 \
  or lose $15."
- The simple versions should be understandable by a high school student.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "swing_summary": "<2-3 sentences: what's happening with these stocks, should your friend bet on them>",
  "swing_summary_simple": "<2-3 sentences: even simpler — like explaining to your grandmother>",
  "top_pick_advice": "<2-3 sentences: why the #1 pick is interesting, what could go wrong>",
  "top_pick_advice_simple": "<1-2 sentences: dead simple — what it is, what could happen>"
}"""


_PICKS_SYSTEM = """\
You are a senior trader at Jane Street recommending stocks to a friend who \
wants to invest long-term (6-12 months) targeting 30%+ returns.

You will receive the current market regime and the system's top stock picks \
with entry points, stop losses, targets, and analyst targets.

Rules:
- Lead with the #1 pick and why it's the best bet right now.
- For each recommended stock, mention the entry price and how long to hold.
- Be specific: "Buy NVDA at $182, hold for at least 6 months, target $237."
- If analyst target implies 30%+ upside, highlight it.
- If no picks look strong enough, say so honestly.
- Keep it to 4-6 sentences. Be actionable and specific.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "picks_summary": "<4-6 sentences: which stocks to buy, at what price, hold how long>"
}"""


def ai_picks_summary(regime: str, picks: list[dict]) -> dict | None:
    if not picks:
        return None

    pick_lines = []
    for p in picks[:5]:
        analyst = p.get('analyst_target')
        analyst_str = f", analyst target=${analyst:.2f}" if analyst else ""
        pick_lines.append(
            f"  {p.get('ticker')} ({p.get('name', '')}): "
            f"price=${p.get('price', 0):.2f}, entry=${p.get('entry', 0):.2f}, "
            f"stop=${p.get('stop_loss', 0):.2f}, target(30%)=${p.get('target', 0):.2f}"
            f"{analyst_str}, "
            f"RSI={p.get('rsi', 50):.0f}, score={p.get('score', 0)}, "
            f"reason: {p.get('why', '')}"
        )

    user = (
        f"Regime: {regime.replace('_', ' ')}\n\n"
        f"Top stock picks:\n" + "\n".join(pick_lines)
    )
    return _call_claude(_PICKS_SYSTEM, user, max_tokens=400)


_PORTFOLIO_REVIEW_SYSTEM = """\
You are a senior trader at Jane Street reviewing a portfolio a system built \
for your friend. They want to invest long-term (6-12 months) targeting 30%+ returns.

Review the picks and give your honest expert opinion. Are these good picks? \
Any concerns? What's the strategy behind them?

Rules:
- Be specific. Name each stock and say if you agree or disagree with the pick.
- Explain WHY the system picked these (insider buying, oversold, sector strength, etc).
- If a pick looks weak, say so. Suggest what to watch for.
- Mention the hold period for each — how long to hold based on the setup.
- Keep it to 4-6 sentences. Actionable and direct.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "review": "<4-6 sentences: honest review of the portfolio picks, strategy rationale, hold periods, any concerns>"
}"""


def ai_portfolio_review(data: dict) -> dict | None:
    regime = data.get("regime", "unknown")
    capital = data.get("capital", 0)
    picks = data.get("picks", [])
    if not picks:
        return None

    pick_lines = []
    for p in picks:
        pick_lines.append(
            f"  {p.get('ticker')}: {p.get('allocation_pct', 0):.0f}% allocation, "
            f"entry=${p.get('entry', 0):.2f}, stop=${p.get('stop_loss', 0):.2f}, "
            f"target=${p.get('target', 0):.2f}, reason: {p.get('why', '')}"
        )

    user = (
        f"Regime: {regime.replace('_', ' ')}\n"
        f"Capital: ${capital:,.0f}\n\n"
        f"Portfolio picks:\n" + "\n".join(pick_lines)
    )
    return _call_claude(_PORTFOLIO_REVIEW_SYSTEM, user, max_tokens=500)


_ENTRY_TIMING_SYSTEM = """\
You are a senior trader at Jane Street. Your friend just got a list of stock \
picks from the system. For each stock, tell them whether NOW is a good time \
to enter based on where the current price sits relative to the suggested entry, \
the RSI, the stop-loss, and the target.

You will receive the current regime and a list of picks with price, entry, \
stop, target, RSI, and reason.

For each stock, decide:
- "green" = good to enter now (price near/below entry, or oversold even if slightly above)
- "amber" = proceed with caution (price above entry but still has upside, or mixed signals)
- "red" = don't enter now (price too far above entry, overbought, or R/R ruined)

Rules:
- Be specific. Reference the actual price vs entry gap.
- Factor in RSI heavily: RSI < 35 = oversold (favor entry), RSI > 70 = overbought (caution).
- If price is below the suggested entry, that's ALWAYS green.
- Consider the regime: in a bear/crisis regime, be more cautious.
- The "detail" field is the technical reasoning (1 sentence, references RSI, R/R, gap%).
- The "simple" field explains the same thing in plain English for someone who knows \
  NOTHING about finance. No jargon. Use everyday analogies. Examples:
  - "This stock is on sale right now. The price dropped more than expected — good time to buy."
  - "The price already went up past where we wanted to buy. Wait for it to come back down."
  - "It's like buying something at full price when a sale is coming. Better to wait."
  - "The stock is cheap right now and the potential reward is much bigger than the risk."
  - "Too late — the train already left the station. Wait for the next one."
- Do NOT mention you are an AI.

Respond with valid JSON. The "variant" field MUST be exactly one of these three strings: "green", "amber", "red".

{
  "entries": [
    {
      "ticker": "AAPL",
      "label": "Good price",
      "detail": "Only 1.5% above entry and RSI 32 is oversold — enter now.",
      "simple": "This stock is on sale right now. It dipped more than usual — good time to buy.",
      "variant": "green"
    }
  ]
}

Return one object per stock in the "entries" array."""


def ai_entry_timing(regime: str, picks: list[dict]) -> dict | None:
    if not picks:
        return None

    pick_lines = []
    for p in picks:
        entry = p.get("entry") or p.get("price", 0)
        stop = p.get("stop_loss") or p.get("stop", 0)
        target = p.get("target", 0)
        price = p.get("price", 0)
        rsi = p.get("rsi")
        risk = abs(entry - stop) if stop else 0
        reward = abs(target - entry) if target else 0
        rr = f"{reward / risk:.1f}" if risk > 0 else "?"
        pct_above = ((price - entry) / entry * 100) if entry > 0 else 0
        pct_to_target = ((target - price) / price * 100) if price > 0 and target > 0 else 0

        pick_lines.append(
            f"  {p.get('ticker')}: price=${price:.2f}, entry=${entry:.2f} "
            f"({pct_above:+.1f}% from entry), stop=${stop:.2f}, "
            f"target=${target:.2f} ({pct_to_target:.0f}% upside), "
            f"R/R={rr}:1"
            + (f", RSI={rsi:.0f}" if rsi else "")
            + f", reason: {p.get('why', '')}"
        )

    user = (
        f"Regime: {regime.replace('_', ' ')}\n\n"
        f"Stock picks to evaluate entry timing:\n" + "\n".join(pick_lines)
    )
    return _call_claude(_ENTRY_TIMING_SYSTEM, user, max_tokens=900)


def ai_swing_summary(regime: str, picks: list[dict]) -> dict | None:
    if not picks:
        return None

    top = picks[:5]
    pick_lines = []
    for i, p in enumerate(top):
        price = p.get("price", 0)
        target = p.get("target", 0)
        stop = p.get("stop", 0)
        gain_pct = p.get("return_pct", 0)
        loss_pct = abs(price - stop) / price * 100 if price > 0 and stop > 0 else 0
        rank_label = "BEST PICK" if i == 0 else f"Pick #{i + 1}"
        pick_lines.append(
            f"  [{rank_label}] {p.get('ticker')}: "
            f"stock price is ${price:.2f}, "
            f"could go up to ${target:.2f} (+{gain_pct:.0f}% gain), "
            f"sell if it drops to ${stop:.2f} (-{loss_pct:.0f}% loss), "
            f"risk level: {p.get('risk_level', '?')}, "
            f"why: {p.get('catalyst', 'none')}"
        )

    regime_plain = regime.replace("_", " ")
    user = (
        f"Market is currently in a {regime_plain} phase.\n"
        f"We found {len(picks)} stocks worth looking at.\n\n"
        f"Here are the top {len(top)} (already ranked, #1 is the best):\n"
        + "\n".join(pick_lines)
    )
    return _call_claude(_SWING_SYSTEM, user, max_tokens=600)


# ── Swing Pick Ranking ────────────────────────────────────────

_SWING_RANK_SYSTEM = """\
You are a senior swing trader at Jane Street with 20 years of experience. \
You are ranking short-term trade candidates (3-10 day holds) for a friend \
who wants aggressive returns but needs to manage risk carefully.

You will receive the current market regime and a batch of candidate swing \
picks with their technical data. Your job is to RANK them from best to worst \
and assign a quality score (0-100).

How to evaluate each pick — weigh ALL of these:
1. SETUP QUALITY: Is this a clean technical setup? Oversold bounces with \
   volume confirmation are better than random high-ATR plays. RSI 25-40 \
   near support is ideal for longs.
2. CATALYST STRENGTH: Volume surges and momentum breakouts are stronger \
   than generic "high ATR" setups. Insider buying is a strong bonus.
3. RISK/REWARD: Higher R/R ratios are better. Anything above 2:1 is good, \
   above 3:1 is excellent.
4. REGIME ALIGNMENT: In a bear trend, oversold bounces work well. In a bull \
   trend, momentum continuation is better. In crisis, only extreme oversold \
   plays with high R/R.
5. REALISTIC RETURN: A stock moving 5% daily can realistically hit a 30% \
   target. A stock moving 2% daily targeting 30% is a stretch.
6. TREND ALIGNMENT: For longs, price above SMA-20/50 is better. Near 20d \
   support means tighter stop and better entry.

For the analysis field, write 2-3 sentences that a high school student would \
understand. ZERO jargon — no RSI, no mean reversion, no oversold, no \
cointegration, no ATR, no breadth, no regime, no momentum. If you can't \
explain it without those words, use an everyday comparison instead.

BANNED WORDS in analysis: RSI, oversold, overbought, mean reversion, \
momentum, volatility, ATR, breadth, regime, bearish, bullish, support, \
resistance, breakout, reversal, consolidation, R/R, risk/reward ratio.

Examples of good analysis:
- "SOFI's stock price crashed to its lowest point this month, but the \
   company's own executives just bought a bunch of shares with their own \
   money. When the people who run the company are buying, it usually means \
   the stock is about to go back up. Risk: the whole market is dropping \
   right now and could drag this down too."
- "TSLA shot up 5% today and way more people are trading it than normal — \
   big money is pouring in. When a stock gets this kind of attention, it \
   usually keeps climbing for a few more days. The risk is it's already \
   gone up a lot so you might be buying near the top."

Do NOT mention you are an AI.

Respond with valid JSON:
{
  "ranked": [
    {
      "ticker": "SOFI",
      "rank": 1,
      "score": 82,
      "analysis": "2-3 sentence plain-English explanation"
    }
  ]
}

Return ALL tickers from the input, ranked from best (rank 1) to worst. \
Every ticker must appear exactly once."""


def ai_rank_swing_picks(regime: str, picks: list[dict]) -> dict | None:
    """Send all qualifying swing candidates to Claude for ranking."""
    if not picks:
        return None

    pick_lines = []
    for p in picks:
        pick_lines.append(
            f"  {p.get('ticker')}: price=${p.get('price', 0):.2f}, "
            f"entry=${p.get('entry', 0):.2f}, stop=${p.get('stop', 0):.2f}, "
            f"target=${p.get('target', 0):.2f} (+{p.get('return_pct', 0):.0f}%), "
            f"R/R={p.get('risk_reward', 0):.1f}:1, "
            f"ATR%={p.get('atr_pct', 0):.1f}, RSI={p.get('rsi', 0):.0f}, "
            f"vol_ratio={p.get('volume_ratio', 0):.1f}x, "
            f"ret_1d={p.get('ret_1d', 0):+.1f}%, ret_5d={p.get('ret_5d', 0):+.1f}%, "
            f"catalyst={p.get('catalyst', 'none')}, "
            f"risk={p.get('risk_level', '?')}, "
            f"hold={p.get('hold_days', '?')}d"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Total candidates: {len(picks)}\n\n"
        f"Swing trade candidates to rank:\n" + "\n".join(pick_lines)
    )

    token_budget = min(300 + len(picks) * 120, 4000)
    return _call_claude(_SWING_RANK_SYSTEM, user, max_tokens=token_budget)


# ── Swing Investment Research ─────────────────────────────────

_SWING_INVEST_SYSTEM = """\
You are a senior portfolio manager at Jane Street. Your friend has real money \
to invest and wants your personal advice on 3 specific stocks. They invest \
long-term (6-12 months, targeting 30%+ returns).

You will receive: the market regime, their total capital, and the top 3 stock \
picks with full technical data.

Your job:
1. ALLOCATE the capital across the 3 picks. Put more money in the strongest \
   conviction pick. Never put more than 50% in one stock. Keep 10-20% in cash \
   if the regime is bearish or volatile.
2. For each pick, calculate: exact number of shares to buy (round down), \
   dollar amount to invest, dollar amount at risk (if stop is hit), and \
   dollar gain at target.
3. Write a THESIS for each pick — 3-4 sentences in PLAIN ENGLISH. No jargon. \
   Explain: what the company does, why NOW is the time to buy, what catalyst \
   could drive 30%+, and the main risk. Write like you're texting a friend.
4. Write a RISK WARNING for each — 1-2 sentences, plain English. What's the \
   worst case? When should they sell?
5. Write an ENTRY STRATEGY — 1 sentence. Buy now, or wait for a dip? Be specific.
6. Write a PORTFOLIO NOTE — 1-2 sentences on how the 3 picks complement each \
   other (sector diversification, risk balance, etc).

Examples of good thesis writing:
- "SoFi is basically becoming a real bank — they got their charter last year \
   and deposits are growing 40% per quarter. The stock got crushed with \
   everything else but the business is accelerating. If they keep this growth \
   rate, $20+ is easy within a year."
- "AMD is stealing market share from Intel in data centers, which is a $50B \
   market. They just guided revenue up 20% and the stock barely moved. The \
   AI chip wave hasn't fully priced in their server GPU lineup."

MATH RULES:
- shares = floor(invest_amount / price)
- invest_amount = capital * (allocation_pct / 100)
- max_loss = shares * (price - stop)
- max_gain = shares * (target - price)
- All dollar amounts must be realistic given the capital provided.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "picks": [
    {
      "ticker": "SOFI",
      "rank": 1,
      "allocation_pct": 40,
      "shares": 25,
      "invest_amount": 400,
      "entry_strategy": "Buy now at $15.80 — near monthly low, good entry",
      "stop_dollars": "-$355 if it drops to $14.60",
      "target_dollars": "+$520 if it hits $21.00",
      "hold_period": "6-12 months",
      "thesis": "3-4 sentence plain-English investment case",
      "risk": "1-2 sentence plain-English risk warning"
    }
  ],
  "portfolio_note": "1-2 sentences on how the 3 picks work together"
}"""


def ai_swing_invest(regime: str, capital: float, picks: list[dict]) -> dict | None:
    """Generate personalized investment research for top 3 picks."""
    if not picks:
        return None

    pick_lines = []
    for i, p in enumerate(picks[:3]):
        pick_lines.append(
            f"  #{i+1} {p.get('ticker')}: "
            f"price=${p.get('price', 0):.2f}, "
            f"entry=${p.get('entry', 0):.2f}, "
            f"stop=${p.get('stop', 0):.2f} (-{p.get('stop_pct', 0):.1f}%), "
            f"target=${p.get('target', 0):.2f} (+{p.get('return_pct', 0):.0f}%), "
            f"R/R={p.get('risk_reward', 0):.1f}:1, "
            f"ATR%={p.get('atr_pct', 0):.1f}, RSI={p.get('rsi', 0):.0f}, "
            f"vol={p.get('volume_ratio', 0):.1f}x avg, "
            f"1d={p.get('ret_1d', 0):+.1f}%, 5d={p.get('ret_5d', 0):+.1f}%, "
            f"catalyst: {p.get('catalyst', 'none')}, "
            f"risk_level: {p.get('risk_level', '?')}, "
            f"hold: {p.get('hold_days', '?')}d"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Capital to invest: ${capital:,.0f}\n\n"
        f"Top 3 picks:\n" + "\n".join(pick_lines)
    )
    return _call_claude(_SWING_INVEST_SYSTEM, user, max_tokens=1500)


# ── AI Investment Research (Long-Term 6-12 Month) ────────────

_INVEST_RESEARCH_SYSTEM = """\
You are a senior portfolio manager at Jane Street with 20 years of experience. \
Your friend has real capital to invest and wants your PERSONAL recommendation \
for the top 3 long-term stocks (6-12 month hold, targeting 30%+ returns).

You will receive: the market regime, their total capital, recent market news, \
and the top 3 stock picks from the system with technicals and fundamentals.

This is NOT a short-term swing trade. This is a serious, long-term investment \
where they will hold for 6-12 months. Think like Warren Buffett meets a \
quantitative analyst.

Your job:
1. ALLOCATE the capital across the 3 picks. Put more money in the strongest \
   conviction pick. Never put more than 50% in one stock. Keep 10-20% in cash \
   as a reserve if the regime is bearish or volatile.
2. For each pick, calculate: exact number of shares to buy (round down to whole \
   shares), dollar amount to invest, dollar amount at risk (if stop is hit), \
   and dollar gain at target.
3. Write a THESIS for each pick — 4-6 sentences in PLAIN ENGLISH. No jargon. \
   Explain: what the company does in one sentence, why NOW is the time to buy \
   (what's the catalyst?), what could drive 30%+ over 6-12 months, and what \
   the bear case is. Write like you're explaining to a smart friend over dinner.
4. Write a RISK WARNING for each — 2-3 sentences, plain English. What's the \
   worst realistic scenario? At what price should they cut losses? What macro \
   event could derail this?
5. Write an ENTRY STRATEGY — 2 sentences. Buy all at once, or split into 2-3 \
   tranches? Is today a good entry point based on RSI and price vs support? \
   Be specific with prices.
6. Write a PORTFOLIO NOTE — 2-3 sentences on how the 3 picks work together. \
   Are they diversified across sectors? Do they have correlated risks? What's \
   the overall portfolio risk level?

Examples of good thesis writing:
- "SoFi is basically becoming a real bank — they got their charter last year \
   and deposits are growing 40% per quarter. The stock got hammered with the \
   rest of fintech but the underlying business is accelerating. Management is \
   guiding for profitability this year, which would be a massive re-rating \
   catalyst. If deposits keep compounding at this rate, the stock could \
   easily double from here."
- "AMD is stealing Intel's lunch in the data center market, which is worth \
   $50B+ annually. Their new server chips benchmarks are beating Intel by 30% \
   at lower power consumption. The AI wave hasn't fully priced in their MI300 \
   GPU lineup yet. The main risk is NVIDIA's dominance, but AMD only needs a \
   small slice of this massive market to justify 30%+ upside."

MATH RULES:
- shares = floor(invest_amount / price)  (whole shares only!)
- invest_amount = capital * (allocation_pct / 100)
- max_loss = shares * (price - stop_loss)  (negative number as string with $ sign)
- max_gain = shares * (target - price)  (positive number as string with $ sign)
- All dollar amounts must be realistic given the capital provided.
- Do NOT mention you are an AI.

Respond with valid JSON:
{
  "picks": [
    {
      "ticker": "SOFI",
      "company_name": "SoFi Technologies",
      "rank": 1,
      "allocation_pct": 40,
      "shares": 25,
      "invest_amount": 400.00,
      "entry_strategy": "Buy 60% now at $15.80, add remaining 40% if it dips to $14.50. RSI at 35 signals oversold — decent entry.",
      "stop_dollars": "-$85 if it drops to $12.40",
      "target_dollars": "+$250 if it hits $25.80",
      "hold_period": "6-12 months",
      "thesis": "4-6 sentence plain-English investment case",
      "risk": "2-3 sentence plain-English risk warning"
    }
  ],
  "portfolio_note": "2-3 sentences on how the picks work together",
  "market_context": "1-2 sentences on what the current market regime means for these picks"
}"""


def _fetch_stock_fundamentals(ticker: str) -> dict:
    """Grab key fundamentals for a stock via yfinance."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return {
            "company_name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin": info.get("profitMargins"),
            "analyst_target": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey"),
            "eps_trailing": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
        }
    except Exception:
        return {"company_name": ticker}


def ai_investment_research(
    regime: str, capital: float, picks: list[dict]
) -> dict | None:
    """Generate deep, personalized long-term investment research for top 3 picks.

    Fetches fundamentals and news in parallel before sending to Claude.
    """
    if not picks:
        return None

    from concurrent.futures import ThreadPoolExecutor

    tickers = [p.get("ticker", "???") for p in picks[:3]]

    with ThreadPoolExecutor(max_workers=4) as pool:
        news_future = pool.submit(_fetch_market_news)
        fund_futures = {t: pool.submit(_fetch_stock_fundamentals, t) for t in tickers}

        news = news_future.result()
        fundamentals = {t: f.result() for t, f in fund_futures.items()}

    news_block = ""
    if news:
        news_block = "\nRecent Market News:\n" + "\n".join(f"  - {h}" for h in news[:6])

    pick_lines = []
    for i, p in enumerate(picks[:3]):
        ticker = tickers[i]
        fund = fundamentals.get(ticker, {"company_name": ticker})

        price = p.get("price", 0)
        entry = p.get("entry", price)
        stop = p.get("stop_loss", price * 0.85)
        target = p.get("target", price * 1.30)
        rsi = p.get("rsi")

        mc = fund.get("market_cap")
        mc_str = ""
        if mc:
            if mc >= 1e12:
                mc_str = f"${mc / 1e12:.1f}T"
            elif mc >= 1e9:
                mc_str = f"${mc / 1e9:.1f}B"
            elif mc >= 1e6:
                mc_str = f"${mc / 1e6:.0f}M"

        analyst = fund.get("analyst_target")
        analyst_str = f", analyst target=${analyst:.2f}" if analyst else ""
        pe_str = f", P/E={fund['pe_ratio']:.1f}" if fund.get("pe_ratio") else ""
        fwd_pe_str = f", Fwd P/E={fund['forward_pe']:.1f}" if fund.get("forward_pe") else ""
        rev_str = f", rev growth={fund['revenue_growth']:.0%}" if fund.get("revenue_growth") else ""
        margin_str = f", profit margin={fund['profit_margin']:.0%}" if fund.get("profit_margin") else ""

        pick_lines.append(
            f"  #{i + 1} {ticker} ({fund.get('company_name', ticker)})\n"
            f"      Sector: {fund.get('sector', p.get('sector', 'Unknown'))} / "
            f"{fund.get('industry', 'Unknown')}\n"
            f"      Price: ${price:.2f}, Entry: ${entry:.2f}, "
            f"Stop: ${stop:.2f}, Target(30%): ${target:.2f}"
            f"{analyst_str}\n"
            f"      Market Cap: {mc_str or 'N/A'}{pe_str}{fwd_pe_str}"
            f"{rev_str}{margin_str}\n"
            f"      Score: {p.get('score', 0)}, Why: {p.get('why', 'N/A')}"
            + (f", RSI: {rsi:.0f}" if rsi else "")
            + (f"\n      52W Range: ${fund.get('52w_low', 0):.2f} — ${fund.get('52w_high', 0):.2f}" if fund.get("52w_high") else "")
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Capital to invest: ${capital:,.0f}\n\n"
        f"Top 3 long-term stock picks:\n" + "\n\n".join(pick_lines)
        + news_block
    )
    return _call_claude(_INVEST_RESEARCH_SYSTEM, user, max_tokens=2000)


# ── DCF Valuation Explanation ─────────────────────────────────

_DCF_EXPLAIN_SYSTEM = """\
You are a patient investment teacher explaining a DCF (Discounted Cash Flow) \
valuation result to someone who has NEVER done stock valuation before.

You will receive the DCF output (intrinsic value, current price, upside %, \
verdict, assumptions) and the company's fundamentals.

Write 2-3 sentences in plain English explaining:
1. Whether the stock looks cheap, expensive, or fairly priced based on its cash flow
2. WHY — reference specific numbers (cash flow amount, growth rate) in everyday terms
3. One caveat the user should know (DCF assumptions are estimates, not guarantees)

Rules:
- Do NOT mention "DCF" or "discounted cash flow" — the user doesn't know what that means
- Say "based on what this company earns" or "based on its cash flow"
- Use $ and % with actual numbers
- Be direct: "This stock looks cheap" or "You'd be overpaying"
- Do NOT mention you are an AI

Respond with valid JSON:
{
  "explanation": "<2-3 sentences>"
}"""


def ai_dcf_explain(dcf_data: dict, fundamentals: dict) -> dict | None:
    """Plain-English explanation of a DCF valuation result."""
    assumptions = dcf_data.get("assumptions", {})
    fcf = assumptions.get("fcf_latest", 0)
    if fcf >= 1_000_000_000:
        fcf_str = f"${fcf / 1_000_000_000:.1f}B"
    elif fcf >= 1_000_000:
        fcf_str = f"${fcf / 1_000_000:.0f}M"
    else:
        fcf_str = f"${fcf:,.0f}"

    user = (
        f"Ticker: {fundamentals.get('sector', 'Unknown')} sector\n"
        f"Current price: ${dcf_data['current_price']:.2f}\n"
        f"Fair value (based on cash flow): ${dcf_data['intrinsic_value']:.2f}\n"
        f"Upside/downside: {dcf_data['upside_pct']:+.1f}%\n"
        f"Verdict: {dcf_data['verdict'].replace('_', ' ')}\n"
        f"Annual free cash flow: {fcf_str}\n"
        f"Assumed growth rate: {assumptions.get('growth_rate', 0):.1%}\n"
        f"P/E ratio: {fundamentals.get('pe_ratio', 'N/A')}\n"
        f"Revenue growth: {fundamentals.get('revenue_growth', 'N/A')}\n"
        f"Profit margin: {fundamentals.get('profit_margin', 'N/A')}"
    )
    return _call_claude(_DCF_EXPLAIN_SYSTEM, user, max_tokens=300)
