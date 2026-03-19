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
You are a senior equity analyst at Jane Street performing a rigorous intrinsic \
value assessment using a two-stage discounted cash flow model.

You will receive: FCF history, fundamentals, balance sheet, analyst estimates, \
and FCF growth metrics. Use ALL of this data — do not ignore any field.

== YOUR DCF MODEL ==

Stage 1 (Years 1-5): High-growth phase
- Growth rate MUST be anchored to the data. Use this priority:
  1. Forward EPS growth (if available) — this reflects analyst consensus
  2. FCF CAGR from history — this is the actual cash flow trajectory
  3. Revenue growth (if plausible, i.e., between -20% and +50%)
  4. Your sector-informed judgment as a last resort
- If FCF is flat or declining, the growth rate should be LOW (2-5%), not zero.
- If Forward EPS >> Trailing EPS, analysts expect acceleration — reflect that.

Stage 2 (Years 6-10): Fade phase
- Growth fades linearly from Stage 1 rate toward terminal growth (2.5%).

Terminal Value: Gordon Growth Model at 2.5% perpetual growth.

== DISCOUNT RATE (WACC) ==
Compute a proper weighted average cost of capital:
- Cost of equity = Risk-free rate (4.5%) + Beta × Equity risk premium (5.5%)
- Cost of debt ≈ 4% pre-tax, apply 21% tax shield
- Weight by market cap vs total debt
- Typical range: 7% (stable utility) to 14% (speculative growth)

== EQUITY VALUE ==
Enterprise Value = PV of projected FCFs + PV of terminal value
Equity Value = Enterprise Value - Net Debt + Excess Cash
Fair Value Per Share = Equity Value / Shares Outstanding

== CRITICAL RULES ==
- The analyst consensus target price is a STRONG anchor. Your fair value should \
  be within 20% of it unless you have a specific reason to disagree.
- If Forward P/E is lower than Trailing P/E, earnings are GROWING — factor this in.
- Net debt reduces equity value but does NOT mean the company is bad. IBM has \
  $47B debt but generates $11B+ FCF annually — it can service the debt easily.
- Do NOT be excessively conservative. Wall Street consensus exists for a reason.
- Your valuation should match what a Bloomberg terminal DCF would produce.

Respond with valid JSON:
{
  "intrinsic_value": <fair value per share, float>,
  "growth_rate": <Stage 1 growth rate, float like 0.08 for 8%>,
  "discount_rate": <WACC you computed, float like 0.09 for 9%>,
  "reasoning": "<3-4 sentences: what growth rate and why (cite the data point), \
WACC calculation, how debt/cash affected it, and how it compares to analyst target>",
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


def _simple_dcf(
    fcf_history: list[float],
    fundamentals: dict,
    balance: dict,
    price: float,
    shares: int,
) -> dict | None:
    """Deterministic DCF fallback when AI is unavailable.

    10-year two-stage projection + terminal value using Gordon Growth Model.
    Uses FCF CAGR from history as primary growth signal, with revenue growth
    as a cross-check. Discount rate uses CAPM-based WACC.
    """
    try:
        base_fcf = fcf_history[0]
        if base_fcf <= 0:
            return None

        # ── Growth rate: prefer FCF CAGR from history over revenue_growth ──
        fcf_cagr = None
        if len(fcf_history) >= 2 and fcf_history[-1] > 0:
            years = len(fcf_history) - 1
            fcf_cagr = (fcf_history[0] / fcf_history[-1]) ** (1 / years) - 1

        rev_growth = fundamentals.get("revenue_growth")
        if isinstance(rev_growth, (int, float)) and (rev_growth > 1.0 or rev_growth < -0.5):
            rev_growth = None

        if fcf_cagr is not None:
            growth_rate = fcf_cagr
            if rev_growth is not None and 0 < rev_growth < 0.5:
                growth_rate = (fcf_cagr * 0.6 + rev_growth * 0.4)
        elif rev_growth is not None and 0 < rev_growth < 0.5:
            growth_rate = rev_growth
        else:
            growth_rate = 0.04

        growth_rate = max(0.02, min(growth_rate, 0.20))

        # ── Discount rate: CAPM-based WACC ──
        # Risk-free rate ~4.5% (10Y Treasury), equity risk premium ~5.5%
        RISK_FREE = 0.045
        EQUITY_PREMIUM = 0.055
        beta = fundamentals.get("beta")
        if isinstance(beta, (int, float)) and beta > 0:
            cost_of_equity = RISK_FREE + beta * EQUITY_PREMIUM
        else:
            cost_of_equity = RISK_FREE + 1.0 * EQUITY_PREMIUM

        # Approximate WACC: blend equity and debt cost based on debt/equity mix
        total_debt = balance.get("total_debt", 0) or 0
        market_cap = price * shares
        if market_cap > 0 and total_debt > 0:
            debt_weight = total_debt / (market_cap + total_debt)
            equity_weight = 1 - debt_weight
            cost_of_debt = 0.04  # ~4% pre-tax, assume BBB-rated
            tax_rate = 0.21
            discount_rate = equity_weight * cost_of_equity + debt_weight * cost_of_debt * (1 - tax_rate)
        else:
            discount_rate = cost_of_equity

        discount_rate = max(0.07, min(discount_rate, 0.16))

        terminal_growth = 0.025

        # ── Two-stage model: high growth for 5 years, fade to terminal ──
        stage1_years = 5
        stage2_years = 5
        fade_growth = (growth_rate + terminal_growth) / 2

        projection_years = stage1_years + stage2_years
        pv_fcfs = 0.0
        projected_fcf = base_fcf
        for yr in range(1, projection_years + 1):
            if yr <= stage1_years:
                projected_fcf *= (1 + growth_rate)
            else:
                projected_fcf *= (1 + fade_growth)
            pv_fcfs += projected_fcf / (1 + discount_rate) ** yr

        terminal_value = (projected_fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
        pv_terminal = terminal_value / (1 + discount_rate) ** projection_years

        enterprise_value = pv_fcfs + pv_terminal

        net_cash = 0.0
        if balance.get("total_cash") is not None:
            cash = balance.get("total_cash", 0)
            debt = balance.get("total_debt", 0)
            net_cash = cash - debt

        equity_value = enterprise_value + net_cash
        intrinsic_value = round(equity_value / shares, 2)

        if intrinsic_value <= 0:
            return None

        upside_pct = round((intrinsic_value - price) / price * 100, 1)
        margin_of_safety = (
            round((intrinsic_value - price) / intrinsic_value * 100, 1)
            if intrinsic_value > price else 0.0
        )
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
            "reasoning": (
                f"Deterministic DCF: {growth_rate:.0%} FCF growth for {projection_years} years, "
                f"{discount_rate:.0%} discount rate, {terminal_growth:.1%} terminal growth. "
                f"Net cash/debt: {_fmt_big_number(net_cash)}."
            ),
            "method": "formula",
            "assumptions": {
                "fcf_latest": round(base_fcf),
                "growth_rate": round(growth_rate, 4),
                "discount_rate": round(discount_rate, 4),
                "terminal_growth": terminal_growth,
                "shares_outstanding": shares,
                "projection_years": projection_years,
                "net_cash": round(net_cash) if net_cash else None,
            },
        }
    except Exception:
        logger.exception("Simple DCF fallback failed")
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

        # Compute FCF growth metrics for the AI
        fcf_cagr_str = "N/A"
        if len(fcf_history) >= 2 and fcf_history[-1] > 0:
            years = len(fcf_history) - 1
            cagr = (fcf_history[0] / fcf_history[-1]) ** (1 / years) - 1
            fcf_cagr_str = f"{cagr:.1%}"

        # Forward earnings growth (implied from EPS)
        eps_trailing = fundamentals.get("eps_trailing")
        eps_forward = fundamentals.get("eps_forward")
        fwd_growth_str = "N/A"
        if eps_trailing and eps_forward and isinstance(eps_trailing, (int, float)) and isinstance(eps_forward, (int, float)) and eps_trailing > 0:
            fwd_growth = (eps_forward - eps_trailing) / abs(eps_trailing) * 100
            fwd_growth_str = f"{fwd_growth:+.1f}%"

        # Debt serviceability
        debt_to_fcf_str = "N/A"
        total_debt = balance.get("total_debt", 0)
        if total_debt and fcf_history[0] > 0:
            debt_to_fcf = total_debt / fcf_history[0]
            debt_to_fcf_str = f"{debt_to_fcf:.1f}x"

        # Market cap for context
        market_cap = price * shares

        # Sanitize revenue growth — flag garbage data
        rev_growth_raw = fundamentals.get("revenue_growth", "N/A")
        if isinstance(rev_growth_raw, (int, float)) and (rev_growth_raw > 1.0 or rev_growth_raw < -0.5):
            rev_growth_display = f"{rev_growth_raw} (WARNING: likely bad data, ignore this)"
        else:
            rev_growth_display = rev_growth_raw

        data_snapshot = (
            f"Company: {ticker}\n"
            f"Current price: ${price:.2f}\n"
            f"Shares outstanding: {shares:,.0f}\n"
            f"Market cap: {_fmt_big_number(market_cap)}\n\n"
            f"== FREE CASH FLOW HISTORY ==\n"
            + "\n".join(fcf_lines) + "\n"
            f"  FCF CAGR ({len(fcf_history)-1}yr): {fcf_cagr_str}\n\n"
            f"== GROWTH METRICS ==\n"
            f"  FCF CAGR: {fcf_cagr_str}\n"
            f"  Forward EPS growth: {fwd_growth_str}\n"
            f"  Revenue growth: {rev_growth_display}\n"
            f"  EPS (TTM): {fundamentals.get('eps_trailing', 'N/A')}\n"
            f"  EPS (FWD): {fundamentals.get('eps_forward', 'N/A')}\n\n"
            f"== VALUATION MULTIPLES ==\n"
            f"  P/E (TTM): {fundamentals.get('pe_ratio', 'N/A')}\n"
            f"  Forward P/E: {fundamentals.get('forward_pe', 'N/A')}\n"
            f"  PEG ratio: {fundamentals.get('peg_ratio', 'N/A')}\n"
            f"  Analyst consensus target: ${fundamentals.get('analyst_target', 'N/A')}\n\n"
            f"== COMPANY PROFILE ==\n"
            f"  Sector: {fundamentals.get('sector', 'Unknown')}\n"
            f"  Industry: {fundamentals.get('industry', 'Unknown')}\n"
            f"  Profit margin: {fundamentals.get('profit_margin', 'N/A')}\n"
            f"  Beta: {fundamentals.get('beta', 'N/A')}\n\n"
            f"== BALANCE SHEET ==\n"
            f"  Total cash: {_fmt_big_number(balance['total_cash']) if balance.get('total_cash') else 'N/A'}\n"
            f"  Total debt: {_fmt_big_number(balance['total_debt']) if balance.get('total_debt') else 'N/A'}\n"
            f"  Net debt: {_fmt_big_number(balance['net_debt']) if balance.get('net_debt') else 'N/A'}\n"
            f"  Debt / FCF: {debt_to_fcf_str}\n"
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
                "method": "ai",
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

        return _simple_dcf(
            fcf_history, fundamentals, balance, price, shares,
        )
    except Exception:
        logger.exception("DCF computation failed for %s", ticker)
        return None
