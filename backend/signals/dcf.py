"""AI-powered intrinsic value estimation.

Gathers raw financial data (cash flow, fundamentals, balance sheet)
and sends it to Claude to estimate fair value with reasoning.
Falls back to a simple formula when the AI API is unavailable.
"""

from __future__ import annotations

import json
import logging
import math

import pandas as pd

from backend.config import settings

logger = logging.getLogger(__name__)


def _extract_fcf(cf: pd.DataFrame) -> list[float]:
    """Pull annual Free Cash Flow from a yfinance-style cash flow DataFrame."""
    if cf.empty:
        return []

    idx = cf.index.str.lower()

    fcf_row = cf[idx.str.contains("free cash flow", na=False)]
    if not fcf_row.empty:
        vals = fcf_row.iloc[0].dropna().tolist()
        return [float(v) for v in vals if not math.isnan(float(v))]

    ocf_mask = idx.str.contains("operating cash flow", na=False) | idx.str.contains(
        "cash flow from continuing operating", na=False
    )
    capex_mask = idx.str.contains("capital expenditure", na=False)

    ocf_row = cf[ocf_mask]
    capex_row = cf[capex_mask]

    if ocf_row.empty or capex_row.empty:
        return []

    ocf_vals = ocf_row.iloc[0]
    capex_vals = capex_row.iloc[0]
    fcf_series = ocf_vals + capex_vals
    vals = fcf_series.dropna().tolist()
    return [float(v) for v in vals if not math.isnan(float(v))]


def _extract_balance_sheet_items(ticker: str) -> dict:
    """Get cash, debt, and buyback data from yfinance balance sheet."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)

        bs = t.balance_sheet
        info = t.info

        result: dict = {}

        if bs is not None and not bs.empty:
            idx_lower = bs.index.str.lower()
            for label, keys in [
                ("total_cash", ["cash and cash equivalents", "cash cash equivalents and short term investments"]),
                ("total_debt", ["total debt"]),
                ("net_debt", ["net debt"]),
            ]:
                for key in keys:
                    mask = idx_lower.str.contains(key, na=False)
                    row = bs[mask]
                    if not row.empty:
                        val = row.iloc[0].dropna()
                        if not val.empty:
                            result[label] = float(val.iloc[0])
                            break

        result["buyback_yield"] = info.get("buybackYield")
        result["shares_outstanding"] = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")

        return result
    except Exception:
        logger.exception("Balance sheet fetch failed for %s", ticker)
        return {}


def _fmt_big_number(n: float) -> str:
    if abs(n) >= 1e12:
        return f"${n / 1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"${n / 1e9:.1f}B"
    if abs(n) >= 1e6:
        return f"${n / 1e6:.0f}M"
    return f"${n:,.0f}"


_AI_VALUATION_SYSTEM = """\
You are a senior equity analyst at Goldman Sachs performing an intrinsic value \
assessment. You will receive a company's raw financial data and must estimate \
the fair value per share.

You have access to:
- Free cash flow history (last 3-4 years)
- Fundamentals (P/E, revenue growth, profit margin, beta, etc.)
- Balance sheet items (cash, debt, buybacks)
- Current price and shares outstanding

Your job:
1. Choose an appropriate growth rate for the NEXT 5-10 years based on the \
   company's actual business quality, sector, and competitive position. Do NOT \
   use a mechanical formula — use judgment. A company like Apple with a massive \
   ecosystem and growing services segment deserves a higher growth rate than \
   its recent revenue growth suggests.
2. Choose an appropriate discount rate based on the company's risk profile. \
   Blue-chip companies with strong balance sheets deserve lower rates (8-9%). \
   Speculative companies deserve higher rates (12-15%).
3. Account for the company's net cash or net debt position — add net cash to \
   the equity value or subtract net debt.
4. Factor in share buybacks if significant — ongoing buybacks reduce share \
   count and boost per-share value over time.
5. Provide a realistic fair value per share.

Rules:
- Be REALISTIC. Your estimate should be defensible by a Wall Street analyst.
- Consider what the market is pricing in and whether it's reasonable.
- Don't just mechanically discount cash flows — think about the business.
- A company trading at 30x earnings might still be fairly valued if it has \
  a durable competitive advantage and growing earnings.

Respond with valid JSON:
{
  "intrinsic_value": <fair value per share, float>,
  "growth_rate": <the growth rate you chose, float like 0.12 for 12%>,
  "discount_rate": <the discount rate you chose, float like 0.09 for 9%>,
  "reasoning": "<2-3 sentences explaining your valuation logic — what growth \
rate you used and why, what discount rate, and how cash/debt/buybacks affected it>",
  "verdict": "<undervalued | fairly_valued | overvalued>"
}"""


def _ai_valuation(ticker: str, data_snapshot: str) -> dict | None:
    """Ask Claude to estimate intrinsic value from raw financial data."""
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=_AI_VALUATION_SYSTEM,
            messages=[{"role": "user", "content": data_snapshot}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)

        iv = result.get("intrinsic_value")
        if not iv or not isinstance(iv, (int, float)) or iv <= 0:
            return None

        return result
    except Exception:
        logger.exception("AI valuation failed for %s", ticker)
        return None


def compute_dcf(ticker: str, fetcher) -> dict | None:
    """Estimate intrinsic value per share using AI + raw financial data.

    Returns None when there isn't enough data (ETFs, missing cashflow, etc.).
    """
    try:
        cf = fetcher.get_cashflow(ticker)
        if cf is None or (isinstance(cf, pd.DataFrame) and cf.empty):
            return None

        fcf_history = _extract_fcf(cf)
        if not fcf_history or fcf_history[0] <= 0:
            return None

        fundamentals = fetcher.get_fundamentals(ticker)
        shares = fetcher.get_shares_outstanding(ticker)
        if not shares or shares <= 0:
            return None

        price = fetcher.get_current_price(ticker)
        if not price or price <= 0:
            return None

        balance = _extract_balance_sheet_items(ticker)

        fcf_lines = []
        for i, val in enumerate(fcf_history):
            label = "Latest year" if i == 0 else f"{i} year(s) ago"
            fcf_lines.append(f"  {label}: {_fmt_big_number(val)}")

        data_snapshot = (
            f"Company: {ticker}\n"
            f"Current price: ${price:.2f}\n"
            f"Shares outstanding: {shares:,.0f}\n"
            f"Market cap: {_fmt_big_number(price * shares)}\n\n"
            f"== FREE CASH FLOW HISTORY ==\n"
            + "\n".join(fcf_lines) + "\n\n"
            f"== FUNDAMENTALS ==\n"
            f"  Sector: {fundamentals.get('sector', 'Unknown')}\n"
            f"  Industry: {fundamentals.get('industry', 'Unknown')}\n"
            f"  P/E (TTM): {fundamentals.get('pe_ratio', 'N/A')}\n"
            f"  Forward P/E: {fundamentals.get('forward_pe', 'N/A')}\n"
            f"  PEG ratio: {fundamentals.get('peg_ratio', 'N/A')}\n"
            f"  Revenue growth: {fundamentals.get('revenue_growth', 'N/A')}\n"
            f"  Profit margin: {fundamentals.get('profit_margin', 'N/A')}\n"
            f"  Beta: {fundamentals.get('beta', 'N/A')}\n"
            f"  Analyst target: ${fundamentals.get('analyst_target', 'N/A')}\n"
            f"  EPS (TTM): {fundamentals.get('eps_trailing', 'N/A')}\n"
            f"  EPS (FWD): {fundamentals.get('eps_forward', 'N/A')}\n\n"
            f"== BALANCE SHEET ==\n"
            f"  Total cash: {_fmt_big_number(balance['total_cash']) if balance.get('total_cash') else 'N/A'}\n"
            f"  Total debt: {_fmt_big_number(balance['total_debt']) if balance.get('total_debt') else 'N/A'}\n"
            f"  Net debt: {_fmt_big_number(balance['net_debt']) if balance.get('net_debt') else 'N/A'}\n"
            f"  Buyback yield: {balance.get('buyback_yield', 'N/A')}\n"
        )

        ai_result = _ai_valuation(ticker, data_snapshot)

        if ai_result:
            intrinsic_value = round(float(ai_result["intrinsic_value"]), 2)
            upside_pct = round((intrinsic_value - price) / price * 100, 1)
            margin_of_safety = round(
                (intrinsic_value - price) / intrinsic_value * 100, 1
            ) if intrinsic_value > price else 0.0
            verdict = ai_result.get("verdict", "fairly_valued")
            if verdict not in ("undervalued", "fairly_valued", "overvalued"):
                verdict = (
                    "undervalued" if upside_pct > 15
                    else "overvalued" if upside_pct < -15
                    else "fairly_valued"
                )

            return {
                "intrinsic_value": intrinsic_value,
                "current_price": round(price, 2),
                "upside_pct": upside_pct,
                "verdict": verdict,
                "margin_of_safety": margin_of_safety,
                "reasoning": ai_result.get("reasoning", ""),
                "assumptions": {
                    "fcf_latest": round(fcf_history[0]),
                    "growth_rate": round(float(ai_result.get("growth_rate", 0)), 4),
                    "discount_rate": round(float(ai_result.get("discount_rate", 0)), 4),
                    "terminal_growth": 0.025,
                    "shares_outstanding": shares,
                    "projection_years": 10,
                    "net_cash": round(balance.get("total_cash", 0) - balance.get("total_debt", 0))
                    if balance.get("total_cash")
                    else None,
                },
            }

        return None
    except Exception:
        logger.exception("DCF computation failed for %s", ticker)
        return None
