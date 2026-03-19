"""AI-powered stock analysis using Anthropic Claude.

Replaces the rule-based system take with LLM-generated analysis that reasons
across technicals, fundamentals, macro regime, and strategy signals together.

Falls back to None (caller uses rule-based logic) when:
- API key is not set
- API call fails (timeout, rate limit, parse error)
"""

from __future__ import annotations

import json
import logging

from backend.config import settings

logger = logging.getLogger(__name__)

VALID_BIASES = [
    "bullish", "lean bullish", "cautiously bullish",
    "neutral",
    "lean bearish", "bearish",
]

SYSTEM_PROMPT = """\
You are a senior trader at Jane Street advising a friend on a stock. You give \
two pieces of advice: (1) should they BUY this stock for the long term, and \
(2) if they ALREADY OWN it, what should they do right now.

You will receive a structured data snapshot: price action, technicals, \
fundamentals, macro regime, and strategy signals. Synthesize everything into \
a decisive, expert assessment.

Your investor profile:
- NOT a day trader. Holds for 6-12 months minimum, targeting 30%+ returns.
- Has limited capital. Every dollar matters. Be protective of downside.
- Wants clear answers: "Should I buy?" and "I already own it — what now?"
- Needs specific guidance: "Hold at least X days" or "Sell if it drops below $Y."

Rules:
- Be brutally honest. If the stock is mediocre, say so. Don't sugarcoat.
- Think like Jane Street: what's the edge? What's the asymmetry?
- Write for someone who is NOT a finance professional. No jargon without explanation.
- Never invent data. Only reference numbers from the provided snapshot.
- If insiders are buying, that matters a LOT. Highlight it.
- Do NOT mention that you are an AI or that you received data.
- Dollar amounts use $ prefix. Percentages use % suffix.

CRITICAL for the "already_own_it" field:
- Analyze RSI, recent returns, support levels, volume, and trend to determine \
  if the stock is in a temporary dip or a real breakdown.
- If RSI is oversold (<35) or price is near strong support, advise HOLD with a \
  specific minimum hold period (e.g., "Hold at least 5-7 trading days").
- If the stock is down but fundamentals are strong, say "Don't panic sell. This \
  dip looks temporary because [reason]. Hold at least X days."
- If the stock is breaking down through 200-SMA with heavy volume, advise to \
  cut losses with a specific stop level.
- If the stock is up strongly and RSI is overbought (>70), advise taking partial \
  profits or setting a trailing stop.
- Always give a SPECIFIC action, a SPECIFIC price level, and a SPECIFIC time frame.
- The action must be one of: BUY MORE, HOLD, HOLD TIGHT, TAKE PARTIAL PROFITS, SELL.

You MUST respond with valid JSON matching this exact schema:
{
  "bias": "<one of: bullish, lean bullish, cautiously bullish, neutral, lean bearish, bearish>",
  "score": <integer 0-100, conviction score>,
  "notes": ["<observation 1>", "<observation 2>", ...],
  "summary": "<3-5 sentence plain-English analysis for someone considering buying>",
  "return_outlook": "<1-2 sentences: can this stock hit 30% in 6-12 months? Be specific.>",
  "already_own_it": {
    "action": "<BUY MORE | HOLD | HOLD TIGHT | TAKE PARTIAL PROFITS | SELL>",
    "headline": "<short 5-10 word directive, e.g. 'Hold tight — this dip is temporary'>",
    "reasoning": "<2-4 sentences explaining WHY with specific data points. Reference RSI, \
support levels, volume, insider activity, or earnings. Be specific about what you're watching.>",
    "simple": "<2-3 sentences explaining the same advice in everyday language for someone \
who knows NOTHING about finance. No jargon at all — no RSI, no SMA, no moving averages, \
no volume ratios. Use analogies. Example: 'The stock dropped but the company is still \
doing great — it's like a store having a bad week of weather but the business is fine. \
Don't sell in a panic. Give it 2 weeks to recover.'>",
    "hold_days": <minimum days to hold before reassessing, integer, 0 if SELL>,
    "stop_price": <price level where they should exit no matter what, float>,
    "target_price": <realistic price target for this hold period, float>
  }
}

Guidelines for each field:
- bias: your directional view for 6-12 months. Only say "bullish" if you'd bet \
  real money. "neutral" means "there are better opportunities elsewhere."
- score: 0 = strong avoid, 50 = meh/no edge, 70+ = worth betting on, 85+ = high conviction
- notes: 4-6 bullet points. Lead with the most important factor for the long-term \
  thesis. Include valuation, growth, insider activity, and macro headwinds/tailwinds.
- summary: talk like you're advising a friend considering BUYING. Be direct about \
  whether to buy or skip. Mention specific prices.
- return_outlook: specifically address the 30% return target. Reference analyst \
  targets, earnings growth rates, or historical patterns.
- already_own_it: expert advice for someone who ALREADY holds this stock and is \
  worried or unsure. Be the calm, data-driven voice. Give them a specific plan."""


def _build_user_prompt(
    ticker: str,
    technicals: dict,
    fundamentals: dict,
    regime: str,
    signals: list[dict],
    dcf: dict | None = None,
    short_interest: list | None = None,
    institutional: dict | None = None,
) -> str:
    sections = [f"Stock: {ticker}\n"]

    sections.append("== PRICE ACTION & TECHNICALS ==")
    for key in [
        "current_price", "return_1d", "return_5d", "return_20d", "return_60d",
        "trend", "rsi_14", "atr_14", "atr_pct",
        "sma_20", "sma_50", "sma_200",
        "high_52w", "low_52w", "pct_from_52w_high",
        "volume_latest", "volume_avg_20d", "volume_ratio",
        "support_20d", "resistance_20d",
    ]:
        val = technicals.get(key)
        if val is not None:
            label = key.replace("_", " ").title()
            sections.append(f"  {label}: {val}")

    sections.append("\n== FUNDAMENTALS ==")
    for key in [
        "sector", "industry", "market_cap", "pe_ratio", "forward_pe",
        "peg_ratio", "eps_trailing", "eps_forward",
        "revenue_growth", "profit_margin", "debt_to_equity",
        "beta", "dividend_yield", "short_ratio", "analyst_target",
    ]:
        val = fundamentals.get(key)
        if val is not None:
            label = key.replace("_", " ").title()
            sections.append(f"  {label}: {val}")

    if dcf:
        sections.append("\n== DCF VALUATION ==")
        sections.append(f"  Fair value: ${dcf.get('intrinsic_value', 'N/A')}")
        sections.append(f"  Upside/downside: {dcf.get('upside_pct', 'N/A')}%")
        sections.append(f"  Verdict: {dcf.get('verdict', 'N/A')}")
        sections.append(f"  Method: {dcf.get('method', 'N/A')}")
        if dcf.get("reasoning"):
            sections.append(f"  Reasoning: {dcf['reasoning']}")

    if short_interest and len(short_interest) >= 1:
        sections.append("\n== SHORT INTEREST ==")
        latest = short_interest[0]
        sections.append(f"  Days to cover: {latest.get('days_to_cover', 'N/A')}")
        sections.append(f"  Short shares: {latest.get('short_interest', 'N/A'):,}")
        if len(short_interest) >= 2:
            prev = short_interest[1]
            curr_si = latest.get("short_interest", 0)
            prev_si = prev.get("short_interest", 0)
            if prev_si > 0:
                change = (curr_si - prev_si) / prev_si * 100
                sections.append(f"  Change vs prior: {change:+.1f}%")

    if institutional and institutional.get("active_positions"):
        sections.append("\n== INSTITUTIONAL HOLDINGS ==")
        active = institutional["active_positions"]
        inc = active.get("increased_positions", {})
        dec = active.get("decreased_positions", {})
        if inc.get("holders"):
            sections.append(f"  Increased positions: {inc['holders']} holders")
        if dec.get("holders"):
            sections.append(f"  Decreased positions: {dec['holders']} holders")
        new_sold = institutional.get("new_sold_positions", {})
        new_p = new_sold.get("new_positions", {})
        sold_p = new_sold.get("sold_out_positions", {})
        if new_p.get("holders"):
            sections.append(f"  New positions: {new_p['holders']} holders")
        if sold_p.get("holders"):
            sections.append(f"  Sold out: {sold_p['holders']} holders")

    sections.append(f"\n== MACRO REGIME ==")
    sections.append(f"  Current regime: {regime.replace('_', ' ')}")

    if signals:
        sections.append("\n== STRATEGY SIGNALS ==")
        for sig in signals:
            direction = sig.get("direction", "?")
            strategy = sig.get("strategy", "?")
            score = sig.get("signal_score", 0)
            edge = sig.get("edge_reason", "")
            sections.append(f"  [{strategy}] {direction} (score {score}): {edge}")

    return "\n".join(sections)


def ai_system_take(
    ticker: str,
    technicals: dict,
    fundamentals: dict,
    regime: str,
    signals: list[dict],
    dcf: dict | None = None,
    short_interest: list | None = None,
    institutional: dict | None = None,
) -> dict | None:
    """Generate AI-powered system take using Claude.

    Returns dict with {bias, score, notes, summary} or None on failure.
    """
    if not settings.anthropic_api_key:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — pip install anthropic")
        return None

    user_prompt = _build_user_prompt(
        ticker, technicals, fundamentals, regime, signals,
        dcf=dcf, short_interest=short_interest, institutional=institutional,
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = response.content[0].text.strip()

        # Handle markdown-wrapped JSON
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)

        bias = result.get("bias", "neutral")
        if bias not in VALID_BIASES:
            bias = "neutral"

        score = result.get("score", 50)
        if not isinstance(score, (int, float)):
            score = 50
        score = max(0, min(100, int(score)))

        notes = result.get("notes", [])
        if not isinstance(notes, list) or not notes:
            return None

        summary = result.get("summary", "")
        if not isinstance(summary, str) or len(summary) < 20:
            return None

        return_outlook = result.get("return_outlook", "")

        already_own = result.get("already_own_it")
        if isinstance(already_own, dict):
            valid_actions = {"BUY MORE", "HOLD", "HOLD TIGHT", "TAKE PARTIAL PROFITS", "SELL"}
            if already_own.get("action") not in valid_actions:
                already_own["action"] = "HOLD"
            already_own.setdefault("headline", "")
            already_own.setdefault("reasoning", "")
            already_own.setdefault("simple", "")
            already_own.setdefault("hold_days", 5)
            already_own.setdefault("stop_price", 0)
            already_own.setdefault("target_price", 0)
        else:
            already_own = None

        logger.info("AI analysis for %s: bias=%s score=%d", ticker, bias, score)
        return {
            "bias": bias,
            "score": score,
            "notes": notes,
            "summary": summary,
            "return_outlook": return_outlook,
            "already_own_it": already_own,
        }

    except json.JSONDecodeError:
        logger.warning("AI analysis for %s: failed to parse JSON response", ticker)
        return None
    except Exception as e:
        logger.warning("AI analysis for %s failed: %s", ticker, e)
        return None
