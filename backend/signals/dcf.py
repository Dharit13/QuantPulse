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
from backend.prompts import load_prompt

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
        logger.debug("Balance sheet fetch failed for %s", ticker)
        return {}


def _fmt_big_number(n: float) -> str:
    if abs(n) >= 1e12:
        return f"${n / 1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"${n / 1e9:.1f}B"
    if abs(n) >= 1e6:
        return f"${n / 1e6:.0f}M"
    return f"${n:,.0f}"


_AI_VALUATION_SYSTEM = load_prompt("dcf_valuation")


def _ai_valuation(ticker: str, data_snapshot: str) -> dict | None:
    """Ask Claude to estimate intrinsic value from raw financial data."""
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=_AI_VALUATION_SYSTEM,
            messages=[{"role": "user", "content": data_snapshot}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if not raw or raw[0] not in ("{", "["):
            logger.warning("AI valuation for %s returned non-JSON: %.80s", ticker, raw)
            return None
        result = json.loads(raw)

        iv = result.get("intrinsic_value")
        if not iv or not isinstance(iv, (int, float)) or iv <= 0:
            return None

        return result
    except Exception:
        logger.exception("AI valuation failed for %s", ticker)
        return None


def _sector_growth_floor(sector: str) -> float:
    """Sector-aware minimum growth rate."""
    sector_lower = (sector or "").lower()
    if any(k in sector_lower for k in ("technology", "communication")):
        return 0.04
    if any(k in sector_lower for k in ("utilities", "consumer staples", "real estate")):
        return 0.02
    return 0.03


def _simple_dcf(
    fcf_history: list[float],
    fundamentals: dict,
    balance: dict,
    price: float,
    shares: int,
    sentiment_score: float | None = None,
) -> dict | None:
    """Deterministic DCF fallback when AI is unavailable.

    10-year two-stage projection + terminal value using Gordon Growth Model.
    Multi-signal growth blend: forward EPS (40%), revenue growth (30%),
    FCF CAGR (30%). Sector-aware floor + optional sentiment modifier.
    Discount rate uses CAPM-based WACC.
    """
    try:
        base_fcf = fcf_history[0]
        if base_fcf <= 0:
            return None

        sector = fundamentals.get("sector", "")
        floor = _sector_growth_floor(sector)

        # ── Multi-signal growth blend ──
        # Forward EPS growth (40% weight) — most forward-looking
        eps_trailing = fundamentals.get("eps_trailing")
        eps_forward = fundamentals.get("eps_forward")
        fwd_eps_growth = None
        if isinstance(eps_trailing, (int, float)) and isinstance(eps_forward, (int, float)) and eps_trailing > 0:
            raw = (eps_forward - eps_trailing) / abs(eps_trailing)
            if -0.5 < raw < 1.0:
                fwd_eps_growth = raw

        # Revenue growth (30% weight) — actual reported
        rev_growth = fundamentals.get("revenue_growth")
        if isinstance(rev_growth, (int, float)) and (rev_growth > 1.0 or rev_growth < -0.5):
            rev_growth = None

        # FCF CAGR (30% weight) — historical trend
        fcf_cagr = None
        if len(fcf_history) >= 2 and fcf_history[-1] > 0:
            years = len(fcf_history) - 1
            fcf_cagr = (fcf_history[0] / fcf_history[-1]) ** (1 / years) - 1

        signals: list[tuple[float, float]] = []
        if fwd_eps_growth is not None:
            signals.append((fwd_eps_growth, 0.40))
        if rev_growth is not None and 0 < rev_growth < 0.5:
            signals.append((rev_growth, 0.30))
        if fcf_cagr is not None:
            signals.append((fcf_cagr, 0.30))

        if signals:
            total_w = sum(w for _, w in signals)
            growth_rate = sum(g * w for g, w in signals) / total_w
        else:
            growth_rate = floor

        # Sentiment modifier: ±1-2% based on FinBERT composite
        if sentiment_score is not None:
            normalized = (sentiment_score - 50.0) / 50.0  # -1.0 to +1.0
            growth_rate += normalized * 0.02

        growth_rate = max(floor, min(growth_rate, 0.20))

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
                projected_fcf *= 1 + growth_rate
            else:
                projected_fcf *= 1 + fade_growth
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
            round((intrinsic_value - price) / intrinsic_value * 100, 1) if intrinsic_value > price else 0.0
        )
        verdict = "undervalued" if upside_pct > 15 else "overvalued" if upside_pct < -15 else "fairly_valued"

        return {
            "intrinsic_value": intrinsic_value,
            "current_price": round(price, 2),
            "upside_pct": upside_pct,
            "verdict": verdict,
            "margin_of_safety": margin_of_safety,
            "reasoning": (
                f"Deterministic DCF: {growth_rate:.0%} FCF growth (yrs 1-5) "
                f"fading to {fade_growth:.0%} (yrs 6-10), "
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


_DCF_CACHE_TTL_HOURS = 4.0


def _try_fmp_dcf(ticker: str, price: float) -> dict | None:
    """Try FMP's pre-computed DCF endpoint."""
    try:
        from backend.data.sources.fmp_src import fmp_source

        data = fmp_source.get_dcf(ticker)
        if not data or not data.get("dcf"):
            return None
        fair_value = round(data["dcf"], 2)
        current = data.get("stock_price") or price
        upside_pct = round((fair_value - current) / current * 100, 1)
        verdict = "undervalued" if upside_pct > 15 else "overvalued" if upside_pct < -15 else "fairly_valued"
        return {
            "intrinsic_value": fair_value,
            "current_price": round(current, 2),
            "upside_pct": upside_pct,
            "verdict": verdict,
            "margin_of_safety": round((fair_value - current) / fair_value * 100, 1) if fair_value > current else 0.0,
            "reasoning": (
                f"DCF valuation from Financial Modeling Prep. "
                f"Fair value ${fair_value:.2f} vs current ${current:.2f}."
            ),
            "method": "fmp_dcf",
            "assumptions": None,
        }
    except Exception:
        logger.debug("FMP DCF unavailable for %s", ticker)
        return None


def _try_polygon_consensus(ticker: str, price: float) -> dict | None:
    """Try Polygon/Benzinga analyst consensus target."""
    try:
        from backend.config import settings as _s

        if not _s.enable_polygon:
            return None
        from backend.data.sources.polygon_src import polygon_source

        data = polygon_source.get_consensus_target(ticker)
        if not data or not data.get("target_consensus"):
            return None
        target = round(data["target_consensus"], 2)
        n = data.get("num_analysts", 0)
        upside_pct = round((target - price) / price * 100, 1)
        verdict = "undervalued" if upside_pct > 15 else "overvalued" if upside_pct < -15 else "fairly_valued"
        return {
            "intrinsic_value": target,
            "current_price": round(price, 2),
            "upside_pct": upside_pct,
            "verdict": verdict,
            "margin_of_safety": round((target - price) / target * 100, 1) if target > price else 0.0,
            "reasoning": f"Analyst consensus target ${target:.2f} from {n} analysts (Benzinga via Polygon).",
            "method": "analyst_consensus",
            "assumptions": None,
        }
    except Exception:
        logger.debug("Polygon consensus unavailable for %s", ticker)
        return None


def _try_yfinance_target(fundamentals: dict, price: float) -> dict | None:
    """Use yfinance analyst target as fair value proxy."""
    target = fundamentals.get("analyst_target")
    if not target or not isinstance(target, (int, float)) or target <= 0:
        return None
    target = round(target, 2)
    upside_pct = round((target - price) / price * 100, 1)
    verdict = "undervalued" if upside_pct > 15 else "overvalued" if upside_pct < -15 else "fairly_valued"
    return {
        "intrinsic_value": target,
        "current_price": round(price, 2),
        "upside_pct": upside_pct,
        "verdict": verdict,
        "margin_of_safety": round((target - price) / target * 100, 1) if target > price else 0.0,
        "reasoning": f"Analyst consensus target ${target:.2f} from Yahoo Finance.",
        "method": "yfinance_target",
        "assumptions": None,
    }


def compute_dcf(ticker: str, fetcher, sentiment_score: float | None = None) -> dict | None:
    """Estimate intrinsic value per share.

    Priority waterfall:
      1. FMP pre-computed DCF (most reliable, professionally modeled)
      2. Polygon/Benzinga analyst consensus target
      3. yfinance analyst consensus target
      4. AI-powered DCF (Claude analyzes raw financials)
      5. Deterministic formula DCF (last resort)

    Results are cached for 4 hours so fair value stays stable across
    page refreshes.

    Returns None when there isn't enough data (ETFs, missing cashflow, etc.).
    """
    from backend.data.cache import data_cache

    cache_key = f"dcf:{ticker.upper()}"
    cached = data_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        price = fetcher.get_current_price(ticker)
        if not price or price <= 0:
            return None

        fundamentals = fetcher.get_fundamentals(ticker)

        # Layer 0: DB-stored fair value (pre-fetched by scheduler)
        db_dcf = fundamentals.get("dcf_fair_value")
        db_method = fundamentals.get("dcf_method")
        if db_dcf and isinstance(db_dcf, (int, float)) and db_dcf > 0:
            upside_pct = round((db_dcf - price) / price * 100, 1)
            verdict = "undervalued" if upside_pct > 15 else "overvalued" if upside_pct < -15 else "fairly_valued"
            result = {
                "intrinsic_value": round(db_dcf, 2),
                "current_price": round(price, 2),
                "upside_pct": upside_pct,
                "verdict": verdict,
                "margin_of_safety": round((db_dcf - price) / db_dcf * 100, 1) if db_dcf > price else 0.0,
                "reasoning": f"Fair value ${db_dcf:.2f} from {db_method or 'pre-computed DCF'}.",
                "method": db_method or "db_cached",
                "assumptions": None,
            }
            logger.info("DCF %s: using DB value ($%.2f, method=%s)", ticker, db_dcf, db_method)
            data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
            return result

        # Layer 0b: analyst_target from DB (already in fundamentals)
        db_target = fundamentals.get("analyst_target")
        if db_target and isinstance(db_target, (int, float)) and db_target > 0:
            result = _try_yfinance_target(fundamentals, price)
            if result:
                logger.info("DCF %s: using DB analyst target ($%.2f)", ticker, db_target)
                data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
                return result

        # Layer 1: FMP DCF (live API fallback)
        result = _try_fmp_dcf(ticker, price)
        if result:
            logger.info("DCF %s: using FMP (fair value $%.2f)", ticker, result["intrinsic_value"])
            data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
            return result

        # Layer 2: Polygon analyst consensus
        result = _try_polygon_consensus(ticker, price)
        if result:
            logger.info("DCF %s: using Polygon consensus ($%.2f)", ticker, result["intrinsic_value"])
            data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
            return result

        # Layer 3: yfinance analyst target
        result = _try_yfinance_target(fundamentals, price)
        if result:
            logger.info("DCF %s: using yfinance target ($%.2f)", ticker, result["intrinsic_value"])
            data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
            return result

        # Layer 4+5: AI or formula DCF (need cashflow data)
        cf = fetcher.get_cashflow(ticker)
        if cf is None or (isinstance(cf, pd.DataFrame) and cf.empty):
            return None

        fcf_history = _extract_fcf(cf)
        if not fcf_history or fcf_history[0] <= 0:
            return None

        shares = fetcher.get_shares_outstanding(ticker)
        if not shares or shares <= 0:
            return None

        balance = _extract_balance_sheet_items(ticker)

        fcf_lines = []
        for i, val in enumerate(fcf_history):
            label = "Latest year" if i == 0 else f"{i} year(s) ago"
            fcf_lines.append(f"  {label}: {_fmt_big_number(val)}")

        fcf_cagr_str = "N/A"
        if len(fcf_history) >= 2 and fcf_history[-1] > 0:
            years = len(fcf_history) - 1
            cagr = (fcf_history[0] / fcf_history[-1]) ** (1 / years) - 1
            fcf_cagr_str = f"{cagr:.1%}"

        eps_trailing = fundamentals.get("eps_trailing")
        eps_forward = fundamentals.get("eps_forward")
        fwd_growth_str = "N/A"
        if (
            eps_trailing
            and eps_forward
            and isinstance(eps_trailing, (int, float))
            and isinstance(eps_forward, (int, float))
            and eps_trailing > 0
        ):
            fwd_growth = (eps_forward - eps_trailing) / abs(eps_trailing) * 100
            fwd_growth_str = f"{fwd_growth:+.1f}%"

        debt_to_fcf_str = "N/A"
        total_debt = balance.get("total_debt", 0)
        if total_debt and fcf_history[0] > 0:
            debt_to_fcf = total_debt / fcf_history[0]
            debt_to_fcf_str = f"{debt_to_fcf:.1f}x"

        market_cap = price * shares

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
            f"== FREE CASH FLOW HISTORY ==\n" + "\n".join(fcf_lines) + "\n"
            f"  FCF CAGR ({len(fcf_history) - 1}yr): {fcf_cagr_str}\n\n"
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

        # Layer 4: AI valuation
        ai_result = _ai_valuation(ticker, data_snapshot)

        if ai_result:
            intrinsic_value = round(float(ai_result["intrinsic_value"]), 2)
            upside_pct = round((intrinsic_value - price) / price * 100, 1)
            margin_of_safety = (
                round((intrinsic_value - price) / intrinsic_value * 100, 1) if intrinsic_value > price else 0.0
            )
            verdict = ai_result.get("verdict", "fairly_valued")
            if verdict not in ("undervalued", "fairly_valued", "overvalued"):
                verdict = "undervalued" if upside_pct > 15 else "overvalued" if upside_pct < -15 else "fairly_valued"

            result = {
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
            data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
            return result

        # Layer 5: Deterministic formula DCF
        result = _simple_dcf(
            fcf_history,
            fundamentals,
            balance,
            price,
            shares,
            sentiment_score=sentiment_score,
        )
        if result:
            data_cache.set(cache_key, result, ttl_hours=_DCF_CACHE_TTL_HOURS)
        return result
    except Exception:
        logger.debug("DCF computation failed for %s", ticker)
        return None
