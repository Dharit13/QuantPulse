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
from backend.prompts import load_prompt

logger = logging.getLogger(__name__)

VALID_BIASES = [
    "bullish",
    "lean bullish",
    "cautiously bullish",
    "neutral",
    "lean bearish",
    "bearish",
]

SYSTEM_PROMPT = load_prompt("stock_analysis")


def _build_user_prompt(
    ticker: str,
    technicals: dict,
    fundamentals: dict,
    regime: str,
    signals: list[dict],
    dcf: dict | None = None,
    short_interest: list | None = None,
    institutional: dict | None = None,
    sentiment: dict | None = None,
    sentiment_context: str = "",
) -> str:
    sections = [f"Stock: {ticker}\n"]

    sections.append("== PRICE ACTION & TECHNICALS ==")
    for key in [
        "current_price",
        "return_1d",
        "return_5d",
        "return_20d",
        "return_60d",
        "trend",
        "rsi_14",
        "atr_14",
        "atr_pct",
        "sma_20",
        "sma_50",
        "sma_200",
        "high_52w",
        "low_52w",
        "pct_from_52w_high",
        "volume_latest",
        "volume_avg_20d",
        "volume_ratio",
        "support_20d",
        "resistance_20d",
    ]:
        val = technicals.get(key)
        if val is not None:
            label = key.replace("_", " ").title()
            sections.append(f"  {label}: {val}")

    sections.append("\n== FUNDAMENTALS ==")
    for key in [
        "sector",
        "industry",
        "market_cap",
        "pe_ratio",
        "forward_pe",
        "peg_ratio",
        "eps_trailing",
        "eps_forward",
        "revenue_growth",
        "profit_margin",
        "debt_to_equity",
        "beta",
        "dividend_yield",
        "short_ratio",
        "analyst_target",
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

    if sentiment and sentiment.get("article_count", 0) > 0:
        sections.append("\n== NEWS SENTIMENT (FinBERT) ==")
        sections.append(f"  Articles analyzed: {sentiment['article_count']}")
        sections.append(
            f"  Sentiment: {sentiment['sentiment_label'].upper()} (score {sentiment['composite_score']:.0f}/100)"
        )
        sections.append(f"  Avg compound: {sentiment['avg_compound']:+.3f}")
        sections.append(
            f"  Positive/Negative/Neutral: {sentiment['pct_positive']:.0%} / {sentiment['pct_negative']:.0%} / {sentiment['pct_neutral']:.0%}"
        )
        if sentiment.get("strongest_positive"):
            sections.append(f"  Most positive headline: {sentiment['strongest_positive'][:120]}")
        if sentiment.get("strongest_negative"):
            sections.append(f"  Most negative headline: {sentiment['strongest_negative'][:120]}")

    sections.append("\n== MACRO REGIME ==")
    sections.append(f"  Current regime: {regime.replace('_', ' ')}")

    if signals:
        sections.append("\n== STRATEGY SIGNALS ==")
        for sig in signals:
            direction = sig.get("direction", "?")
            strategy = sig.get("strategy", "?")
            score = sig.get("signal_score", 0)
            edge = sig.get("edge_reason", "")
            sections.append(f"  [{strategy}] {direction} (score {score}): {edge}")

    if sentiment_context:
        sections.append(f"\n== UNIVERSE SENTIMENT ==\n{sentiment_context}")

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
    sentiment: dict | None = None,
    sentiment_context: str = "",
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
        ticker,
        technicals,
        fundamentals,
        regime,
        signals,
        dcf=dcf,
        short_interest=short_interest,
        institutional=institutional,
        sentiment=sentiment,
        sentiment_context=sentiment_context,
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
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
