"""AI-powered summaries for Market Overview, Scanner, and Swing Picks tabs.

Each function sends a focused prompt to Claude and returns a dict of
plain-English text fields, or None on failure (caller keeps existing UI).
"""

from __future__ import annotations

import json
import logging

from backend.config import settings
from backend.prompts import load_prompt

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
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        block = resp.content[0]
        raw = block.text.strip()
        return _extract_json(raw)
    except json.JSONDecodeError:
        prompt_hint = system[:60].replace("\n", " ")
        logger.warning("AI JSON parse failed for [%s...]: response was not valid JSON", prompt_hint)
        return None
    except Exception as e:
        prompt_hint = system[:60].replace("\n", " ")
        logger.warning("AI call failed for [%s...]: %s", prompt_hint, e)
        return None


def _extract_json(raw: str) -> dict:
    """Extract a JSON object from Claude's response, handling common formats:
    - Raw JSON
    - ```json ... ``` fenced blocks
    - Prose before/after the JSON object
    - Trailing commas, single-line comments
    """
    text = raw.strip()

    # Strip triple-backtick fences (```json ... ``` or ``` ... ```)
    if "```" in text:
        import re

        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    # Fast path: already valid JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the first { ... last } — handles prose before/after the JSON
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Clean up common Claude quirks: trailing commas, // comments
        import re

        cleaned = re.sub(r"//[^\n]*", "", candidate)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Try finding a JSON array [ ... ] if no object found
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = text[first_bracket : last_bracket + 1]
        try:
            arr = json.loads(candidate)
            if isinstance(arr, list):
                return {"items": arr}
        except json.JSONDecodeError:
            pass

    # Nothing worked
    raise json.JSONDecodeError("No valid JSON found in response", text, 0)


# ── Market Overview ──────────────────────────────────────────

_MARKET_SYSTEM = load_prompt("market_summary")


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

_TIMING_TIP_SYSTEM = load_prompt("timing_tip")


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

_ACTION_BANNER_SYSTEM = load_prompt("action_banner")


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

    sentiment_trend = ""
    try:
        from backend.data.ticker_intelligence import get_universe_sentiment

        univ = get_universe_sentiment()
        if univ.total_tickers > 0:
            net = univ.pct_bullish - univ.pct_bearish
            if net > 0:
                sentiment_trend = f"Sentiment trend: {univ.pct_bullish:.0f}% bullish, net +{net:.0f}% bullish bias"
            else:
                sentiment_trend = f"Sentiment trend: {univ.pct_bearish:.0f}% bearish, net {net:.0f}% bearish bias"
    except Exception as e:
        logger.debug("Universe sentiment unavailable for action banner: %s", e)

    sentiment_line = f"\n{sentiment_trend}" if sentiment_trend else ""

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Confidence: {confidence:.0%}\n"
        f"VIX: {vix:.1f}\n"
        f"Breadth (% above 200-SMA): {breadth:.1f}%\n"
        f"ADX (trend strength): {adx:.1f}\n"
        f"Cash allocation: {cash_weight:.0%}\n"
        f"Regime Probabilities: {json.dumps(probs)}\n"
        f"Strategy Weights: {json.dumps(weights)}"
        f"{sentiment_line}"
    )
    return _call_claude(_ACTION_BANNER_SYSTEM, user, max_tokens=300)


# ── AI Stock Picker for Dashboard ─────────────────────────────

_STOCK_PICKER_SYSTEM = load_prompt("stock_picker")


def ai_pick_dashboard_stocks(regime: str, candidates: list[dict]) -> tuple[list[str], dict[str, str]] | None:
    """Ask Claude to pick the best 5 stocks from scored candidates."""
    if not candidates:
        return None

    lines = []
    for c in candidates[:30]:
        sent = c.get("sentiment_score")
        sent_label = c.get("sentiment_label")
        sent_str = f", sentiment={sent:.0f}/100 ({sent_label})" if sent is not None else ""
        lines.append(
            f"  {c['ticker']} ({c['name']}): "
            f"${c['price']:.0f}, "
            f"sector={c['sector']}, "
            f"monthly return={c.get('return_20d', 0):+.1f}%, "
            f"RSI={c.get('rsi', 50):.0f}, "
            f"score={c.get('score', 50)}"
            f"{sent_str}"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n\n"
        f"Stock candidates ({len(candidates)} total, showing top {len(lines)}):\n" + "\n".join(lines)
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

_ALLOCATION_SYSTEM = load_prompt("allocation_explain")


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

_REGIME_PROBS_SYSTEM = load_prompt("regime_probs")


_TICKER_PICKER_SYSTEM = load_prompt("ticker_picker")


def _get_market_movers_data(all_tickers: list[str]) -> str:
    """Get today's biggest movers from a small set of tickers via individual calls."""
    try:
        import yfinance as yf

        sample = all_tickers[:30]
        movers: list[str] = []
        for ticker in sample:
            try:
                df = yf.Ticker(ticker).history(period="5d")
                if df.empty or len(df) < 2:
                    continue
                close = df["Close"]
                ret_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100
                ret_5d = (close.iloc[-1] / close.iloc[0] - 1) * 100 if len(close) >= 5 else ret_1d
                price = close.iloc[-1]
                movers.append(f"{ticker}: ${price:.0f}, 1d={ret_1d:+.1f}%, 5d={ret_5d:+.1f}%")
            except Exception:
                continue

        if not movers:
            return ""

        movers_sorted = sorted(movers, key=lambda x: abs(float(x.split("5d=")[1].rstrip("%"))), reverse=True)
        return "\n\nBiggest movers (last 5 days):\n" + "\n".join(movers_sorted[:15])
    except Exception as e:
        logger.debug("Failed to get movers data: %s", e)
        return ""


def ai_pick_scan_tickers(
    regime: str,
    all_tickers: list[str],
    vix: float = 0,
    breadth_pct: float = 0,
) -> list[str] | None:
    """Ask Claude to pick the 50 most interesting S&P 500 tickers to scan,
    using real-time market data: regime, VIX, and news."""
    news = _fetch_market_news()
    news_block = ""
    if news:
        news_block = "\n\nRecent Market News:\n" + "\n".join(f"- {h}" for h in news[:8])

    ticker_list = ", ".join(all_tickers)
    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"VIX: {vix:.1f}\n"
        f"Market Breadth: {breadth_pct:.1f}% of stocks above 200-day MA\n"
        f"{news_block}\n\n"
        f"Full S&P 500 ticker list ({len(all_tickers)} tickers):\n{ticker_list}\n\n"
        f"Pick 50 tickers FROM THE LIST ABOVE. Use the news headlines and market "
        f"conditions to guide your picks. Focus on stocks likely to have insider "
        f"buying, earnings surprises, or analyst revisions right now."
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

    sentiment_block = ""
    try:
        from backend.data.ticker_intelligence import format_sentiment_block, get_universe_sentiment

        univ = get_universe_sentiment()
        if univ.total_tickers > 0:
            sentiment_block = "\n\n" + format_sentiment_block(univ)
    except Exception as e:
        logger.debug("Universe sentiment unavailable for regime_probs: %s", e)

    user = (
        f"Regime Probabilities: {json.dumps(probs)}\n"
        f"VIX: {vix:.1f}\n"
        f"ADX: {adx:.1f}\n"
        f"Breadth: {breadth:.1f}%"
        f"{news_block}"
        f"{sentiment_block}"
    )
    return _call_claude(_REGIME_PROBS_SYSTEM, user, max_tokens=400)


# ── Scanner ──────────────────────────────────────────────────

_SCAN_SYSTEM = load_prompt("scan_summary")


def ai_scan_summary(regime: str, signals: list[dict], sentiment_block: str = "") -> dict | None:
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
        rr = f"{reward / risk:.1f}" if risk > 0 else "?"
        sig_lines.append(
            f"  {sig.get('ticker')} {sig.get('direction')} "
            f"({sig.get('strategy')}, score {sig.get('signal_score', 0):.0f}, "
            f"conviction {sig.get('conviction', 0):.2f}): "
            f"entry=${entry:.2f}, stop=${stop:.2f}, target=${target:.2f}, R/R={rr}:1 — "
            f"{sig.get('edge_reason', '')}"
        )

    sentiment_section = f"\n\n{sentiment_block}" if sentiment_block else ""

    user = (
        f"Regime: {regime.replace('_', ' ')}\n"
        f"Total signals found: {len(signals)}\n\n"
        f"Signals (ranked by conviction):\n" + "\n".join(sig_lines) + sentiment_section
    )
    return _call_claude(_SCAN_SYSTEM, user, max_tokens=1200)


# ── Signal Explanations ──────────────────────────────────────

_SIGNAL_EXPLAIN_SYSTEM = load_prompt("signal_explain")


def ai_signal_explain(signals: list[dict], sentiment_block: str = "") -> dict | None:
    if not signals:
        return None

    lines = []
    for s in signals[:10]:
        sig = s.get("signal", s)
        ticker = sig.get("ticker", "???")
        strategy = sig.get("strategy", "unknown")
        edge = sig.get("edge_reason", "no reason")

        rec = s.get("final_recommendation", "unknown")
        shadow = s.get("shadow_evidence", {}) or {}
        win_rate = shadow.get("win_rate")
        phantom_count = shadow.get("phantom_count", 0)
        has_data = shadow.get("has_enough_data", False)

        health = s.get("strategy_health", {}) or {}
        health_status = health.get("status", "unknown")

        rec_str = f"recommendation={rec}"
        if has_data and win_rate is not None:
            rec_str += f", win rate={win_rate * 100:.0f}% from {phantom_count} similar past trades"
        else:
            rec_str += ", not enough history to judge reliability"
        rec_str += f", strategy health={health_status}"

        lines.append(f"  {ticker} ({strategy}): {edge} [{rec_str}]")

    sentiment_section = f"\n\n{sentiment_block}" if sentiment_block else ""
    user = "Explain these signals in plain English:\n" + "\n".join(lines) + sentiment_section
    return _call_claude(_SIGNAL_EXPLAIN_SYSTEM, user, max_tokens=1200)


# ── Swing Picks ──────────────────────────────────────────────

_SWING_SYSTEM = load_prompt("swing_summary")


_PICKS_SYSTEM = load_prompt("picks_summary")


def ai_picks_summary(regime: str, picks: list[dict]) -> dict | None:
    if not picks:
        return None

    pick_lines = []
    for p in picks[:5]:
        analyst = p.get("analyst_target")
        analyst_str = f", analyst target=${analyst:.2f}" if analyst else ""
        pick_lines.append(
            f"  {p.get('ticker')} ({p.get('name', '')}): "
            f"price=${p.get('price', 0):.2f}, entry=${p.get('entry', 0):.2f}, "
            f"stop=${p.get('stop_loss', 0):.2f}, target(30%)=${p.get('target', 0):.2f}"
            f"{analyst_str}, "
            f"RSI={p.get('rsi', 50):.0f}, score={p.get('score', 0)}, "
            f"reason: {p.get('why', '')}"
        )

    user = f"Regime: {regime.replace('_', ' ')}\n\nTop stock picks:\n" + "\n".join(pick_lines)
    return _call_claude(_PICKS_SYSTEM, user, max_tokens=400)


_PORTFOLIO_REVIEW_SYSTEM = load_prompt("portfolio_review")


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

    user = f"Regime: {regime.replace('_', ' ')}\nCapital: ${capital:,.0f}\n\nPortfolio picks:\n" + "\n".join(pick_lines)
    return _call_claude(_PORTFOLIO_REVIEW_SYSTEM, user, max_tokens=500)


_ENTRY_TIMING_SYSTEM = load_prompt("entry_timing")


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
            f"R/R={rr}:1" + (f", RSI={rsi:.0f}" if rsi else "") + f", reason: {p.get('why', '')}"
        )

    user = f"Regime: {regime.replace('_', ' ')}\n\nStock picks to evaluate entry timing:\n" + "\n".join(pick_lines)
    return _call_claude(_ENTRY_TIMING_SYSTEM, user, max_tokens=900)


def ai_swing_summary(regime: str, picks: list[dict], sentiment_block: str = "") -> dict | None:
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
        name = p.get("name", "")
        sector = p.get("sector", "")
        earnings = p.get("earnings_warning", "")
        earnings_str = f" | WARNING: {earnings}" if earnings else ""
        sent_score = p.get("sentiment_score")
        sent_label = p.get("sentiment_label")
        sent_str = f", news sentiment: {sent_score:.0f}/100 ({sent_label})" if sent_score is not None else ""
        pick_lines.append(
            f"  [{rank_label}] {p.get('ticker')} ({name}, {sector}): "
            f"stock price is ${price:.2f}, "
            f"could go up to ${target:.2f} (+{gain_pct:.0f}% gain), "
            f"sell if it drops to ${stop:.2f} (-{loss_pct:.0f}% loss), "
            f"RSI={p.get('rsi', 50):.0f}, volume={p.get('volume_ratio', 1):.1f}x avg, "
            f"risk level: {p.get('risk_level', '?')}, "
            f"why: {p.get('catalyst', 'none')}{sent_str}{earnings_str}"
        )

    sentiment_section = f"\n\n{sentiment_block}" if sentiment_block else ""
    regime_plain = regime.replace("_", " ")
    user = (
        f"Market is currently in a {regime_plain} phase.\n"
        f"We found {len(picks)} stocks worth looking at.\n\n"
        f"Here are the top {len(top)} (already ranked, #1 is the best):\n" + "\n".join(pick_lines) + sentiment_section
    )
    return _call_claude(_SWING_SYSTEM, user, max_tokens=600)


# ── Swing Pick Ranking ────────────────────────────────────────

_SWING_RANK_SYSTEM = load_prompt("swing_rank")


def ai_rank_swing_picks(regime: str, picks: list[dict]) -> dict | None:
    """Send all qualifying swing candidates to Claude for ranking."""
    if not picks:
        return None

    pick_lines = []
    for p in picks:
        name = p.get("name", "")
        sector = p.get("sector", "")
        analyst = p.get("analyst_target")
        analyst_str = f", analyst target=${analyst:.2f}" if analyst else ""
        earnings = p.get("earnings_warning", "")
        earnings_str = f", WARNING: {earnings}" if earnings else ""
        sent_score = p.get("sentiment_score")
        sent_label = p.get("sentiment_label")
        sent_str = f", sentiment={sent_score:.0f}/100 ({sent_label})" if sent_score is not None else ""
        pick_lines.append(
            f"  {p.get('ticker')} ({name}, {sector}): "
            f"price=${p.get('price', 0):.2f}, "
            f"entry=${p.get('entry', 0):.2f}, stop=${p.get('stop', 0):.2f}, "
            f"target=${p.get('target', 0):.2f} (+{p.get('return_pct', 0):.0f}%){analyst_str}, "
            f"R/R={p.get('risk_reward', 0):.1f}:1, "
            f"ATR%={p.get('atr_pct', 0):.1f}, RSI={p.get('rsi', 0):.0f}, "
            f"vol_ratio={p.get('volume_ratio', 0):.1f}x, "
            f"ret_1d={p.get('ret_1d', 0):+.1f}%, ret_5d={p.get('ret_5d', 0):+.1f}%, "
            f"catalyst={p.get('catalyst', 'none')}, "
            f"risk={p.get('risk_level', '?')}, "
            f"hold={p.get('hold_days', '?')}d{sent_str}{earnings_str}"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Total candidates: {len(picks)}\n\n"
        f"Swing trade candidates to rank:\n" + "\n".join(pick_lines)
    )

    token_budget = min(300 + len(picks) * 120, 4000)
    return _call_claude(_SWING_RANK_SYSTEM, user, max_tokens=token_budget)


# ── Swing Investment Research ─────────────────────────────────

_SWING_INVEST_SYSTEM = load_prompt("swing_invest")


def ai_swing_invest(regime: str, capital: float, picks: list[dict]) -> dict | None:
    """Generate personalized investment research for top 3 picks."""
    if not picks:
        return None

    pick_lines = []
    for i, p in enumerate(picks[:3]):
        name = p.get("name", "")
        sector = p.get("sector", "")
        analyst = p.get("analyst_target")
        analyst_str = f", analyst target=${analyst:.2f}" if analyst else ""
        earnings = p.get("earnings_warning", "")
        earnings_str = f"\n      WARNING: {earnings}" if earnings else ""
        pick_lines.append(
            f"  #{i + 1} {p.get('ticker')} ({name}, {sector}): "
            f"price=${p.get('price', 0):.2f}, "
            f"entry=${p.get('entry', 0):.2f}, "
            f"stop=${p.get('stop', 0):.2f} (-{p.get('stop_pct', 0):.1f}%), "
            f"target=${p.get('target', 0):.2f} (+{p.get('return_pct', 0):.0f}%){analyst_str}, "
            f"R/R={p.get('risk_reward', 0):.1f}:1, "
            f"ATR%={p.get('atr_pct', 0):.1f}, RSI={p.get('rsi', 0):.0f}, "
            f"vol={p.get('volume_ratio', 0):.1f}x avg, "
            f"1d={p.get('ret_1d', 0):+.1f}%, 5d={p.get('ret_5d', 0):+.1f}%, "
            f"catalyst: {p.get('catalyst', 'none')}, "
            f"risk_level: {p.get('risk_level', '?')}, "
            f"hold: {p.get('hold_days', '?')}d{earnings_str}"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Capital to invest: ${capital:,.0f}\n\n"
        f"Top 3 picks:\n" + "\n".join(pick_lines)
    )
    return _call_claude(_SWING_INVEST_SYSTEM, user, max_tokens=1500)


# ── AI Investment Research (Medium-Term 1-6 Month) ────────────

_INVEST_RESEARCH_SYSTEM = load_prompt("invest_research")


def ai_investment_research(regime: str, capital: float, picks: list[dict]) -> dict | None:
    """Generate deep, personalized long-term investment research.

    Uses the unified TickerIntel layer for rich per-pick data and universe
    sentiment context. Each pick gets a full [TICKER INTEL] block and the
    prompt receives a [SENTIMENT CONTEXT] block for market mood.
    """
    if not picks:
        return None

    from concurrent.futures import ThreadPoolExecutor

    from backend.data.ticker_intelligence import (
        format_intel_block,
        format_sentiment_block,
        get_ticker_intel,
        get_universe_sentiment,
    )

    tickers = [p.get("ticker", "???") for p in picks[:5]]

    with ThreadPoolExecutor(max_workers=6) as pool:
        intel_futures = {t: pool.submit(get_ticker_intel, t, True) for t in tickers}
        sentiment_future = pool.submit(get_universe_sentiment)

        intel_map = {t: f.result() for t, f in intel_futures.items()}
        universe_sentiment = sentiment_future.result()

    sentiment_block = format_sentiment_block(universe_sentiment)

    pick_blocks: list[str] = []
    for i, p in enumerate(picks[:5]):
        ticker = tickers[i]
        intel = intel_map.get(ticker)
        if not intel:
            continue

        intel_block = format_intel_block(intel)

        price = p.get("price", 0) or intel.price
        entry = p.get("entry", price)
        stop = p.get("stop_loss", round(price * 0.92, 2))
        target = p.get("target", round(price * 1.15, 2))

        hold = p.get("hold_period", "1-6 months")

        pick_blocks.append(
            f"--- Pick #{i + 1} ---\n"
            f"{intel_block}\n"
            f"Trade levels: entry=${entry:.2f}, stop=${stop:.2f}, target=${target:.2f}\n"
            f"Hold period: {hold}\n"
            f"Source: {p.get('source', 'unknown')}, Score: {p.get('score', 0)}\n"
            f"Reason: {p.get('why', 'N/A')}"
        )

    user = (
        f"Market Regime: {regime.replace('_', ' ')}\n"
        f"Capital to invest: ${capital:,.0f}\n\n"
        f"{sentiment_block}\n\n"
        f"Stock picks with full data packages:\n\n" + "\n\n".join(pick_blocks)
    )
    result = _call_claude(_INVEST_RESEARCH_SYSTEM, user, max_tokens=3000)
    if result and "picks" in result:
        result["picks"] = [p for p in result["picks"] if p.get("invest_amount", 0) > 0 and p.get("shares", 0) > 0]
    return result


# ── DCF Valuation Explanation ─────────────────────────────────

_DCF_EXPLAIN_SYSTEM = load_prompt("dcf_explain")


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


# ── News Summary ───────────────────────────────────────────────

_NEWS_SUMMARY_SYSTEM = load_prompt("news_summary")


def ai_news_summary(ticker: str, news_items: list[dict]) -> dict | None:
    """AI briefing from a list of news headlines for a ticker."""
    if not news_items:
        return None
    lines = [f"- {item.get('title', '')} ({item.get('source', '')})" for item in news_items[:15]]
    user = f"Ticker: {ticker}\n\nRecent headlines:\n" + "\n".join(lines)
    return _call_claude(_NEWS_SUMMARY_SYSTEM, user, max_tokens=400)


# ── Overnight Swing Scanner ───────────────────────────────────

_OVERNIGHT_SYSTEM = load_prompt("overnight_scanner")


def ai_overnight_analysis(
    stock_data: dict,
    crypto_data: dict,
    macro_data: dict,
    current_positions: list[str] | None = None,
    performance_summary: str | None = None,
) -> dict | None:
    """Send pre-filtered, indicator-enriched market data to Claude.

    Returns structured picks (stocks + crypto) with cost tracking, or None.
    """
    from datetime import datetime as _dt

    now = _dt.now()

    sections = [
        "Here is today's pre-filtered market data with computed technical indicators.",
        "All RSI, Bollinger, volume ratios are pre-calculated — trust them.\n",
        f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S ET')}",
        f"Day of week: {now.strftime('%A')}",
    ]

    if current_positions:
        sections.append(f"\n=== CURRENT POSITIONS (do NOT recommend these) ===\n{', '.join(current_positions)}")

    if performance_summary:
        sections.append(f"\n=== YOUR TRACK RECORD (learn from these actual results) ===\n{performance_summary}")

    sections.append(f"\n=== MACRO REGIME DATA (FRED) ===\n{json.dumps(macro_data, indent=1, default=str)}")

    stock_count = len([k for k in stock_data if not k.startswith("_")])
    sections.append(
        f"\n=== STOCK DATA ({stock_count} tickers, pre-filtered for activity) ===\n"
        f"{json.dumps(stock_data, indent=1, default=str)}"
    )

    sections.append(f"\n=== CRYPTO DATA ===\n{json.dumps(crypto_data, indent=1, default=str)}")

    sections.append(
        "\nAnalyze all data. Find the best overnight swing trades. Check cross-asset correlations. Return JSON only."
    )

    user = "\n".join(sections)

    if len(user) > 180000:
        user = user[:180000] + "\n\n[DATA TRUNCATED — analyze what's available]"

    # Call Claude with cost tracking
    result = _call_claude_tracked(_OVERNIGHT_SYSTEM, user, max_tokens=8000)
    return result


def _call_claude_tracked(system: str, user: str, max_tokens: int = 8000) -> dict | None:
    """Like _call_claude but also logs token usage and cost."""
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed")
        return None
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0)
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        block = resp.content[0]
        raw = block.text.strip()

        # Log cost
        input_tokens = resp.usage.input_tokens
        output_tokens = resp.usage.output_tokens
        # Sonnet pricing: $3/M input, $15/M output
        cost_usd = (input_tokens * 3 + output_tokens * 15) / 1_000_000
        logger.info(
            "Overnight AI cost: %d input + %d output tokens = $%.4f",
            input_tokens,
            output_tokens,
            cost_usd,
        )

        from backend.data.cache import data_cache as _dc

        cost_log = _dc.get("overnight:cost_log") or []
        cost_log.append(
            {
                "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 4),
            }
        )
        _dc.set("overnight:cost_log", cost_log[-100:], ttl_hours=720.0)

        return _extract_json(raw)
    except json.JSONDecodeError:
        logger.warning("Overnight AI JSON parse failed")
        return None
    except Exception as e:
        logger.warning("Overnight AI call failed: %s", e)
        return None
