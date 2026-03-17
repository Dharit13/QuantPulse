"""QuantPulse v2 — Streamlit Dashboard.

Your trading command center: signals, active trades, regime, performance.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

logger = logging.getLogger(__name__)


def _d(value: float, fmt: str = ",.2f") -> str:
    """Format a dollar value without the $ sign triggering LaTeX.

    Streamlit markdown interprets $...$ as LaTeX. Using the unicode
    full-width dollar sign or escaping avoids this.
    """
    return f"\\${value:{fmt}}"


def _dp(value: float, fmt: str = ",.2f") -> str:
    """Dollar value for st.metric (no escaping needed there)."""
    return f"${value:{fmt}}"

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="QuantPulse v2",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """<style>
    div[data-testid="stSidebar"] { background: #0f0f23; }
    .stMetric label { font-size: 13px !important; }
    </style>""",
    unsafe_allow_html=True,
)


# ── API Helpers ─────────────────────────────────────────────

def _api_get(path: str, params: dict | None = None, timeout: float = 10) -> dict | list | None:
    try:
        resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("API %s: %s", path, e)
        return None


def _api_post(path: str, json_data: dict) -> dict | None:
    try:
        resp = httpx.post(f"{API_BASE}{path}", json=json_data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("API POST %s: %s", path, e)
        return None


@st.cache_data(ttl=120)
def _cached_regime() -> dict | None:
    return _api_get("/regime/current", timeout=15)


# ── Page Functions ──────────────────────────────────────────

def page_market_overview():
    st.header("Market Overview")

    regime_data = _cached_regime()

    if not regime_data:
        st.warning("Could not connect to API. Start the backend with `uvicorn backend.main:app`")
        return

    c1, c2, c3, c4 = st.columns(4)
    regime_name = regime_data.get("regime", "unknown").replace("_", " ").title()
    c1.metric("Regime", regime_name, f"{regime_data.get('confidence', 0):.0%} conf")
    c2.metric("VIX", f"{regime_data.get('vix', 0):.1f}")
    c3.metric("Breadth", f"{regime_data.get('breadth_pct', 0):.1f}%")
    c4.metric("ADX", f"{regime_data.get('adx', 0):.1f}")

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        probs = regime_data.get("regime_probabilities", {})
        if probs:
            st.subheader("Regime Probabilities")
            prob_df = pd.DataFrame(
                [{"Regime": k.replace("_", " ").title(), "Probability": v} for k, v in probs.items()]
            ).sort_values("Probability", ascending=True)
            fig = go.Figure(go.Bar(
                x=prob_df["Probability"], y=prob_df["Regime"], orientation="h",
                marker_color=["#e94560" if p > 0.3 else "#0f3460" for p in prob_df["Probability"]],
            ))
            fig.update_layout(
                height=280, margin=dict(l=0, r=0, t=0, b=0),
                xaxis_title="Probability", yaxis_title="",
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e0e0e0"),
            )
            st.plotly_chart(fig, width="stretch")

    with col_right:
        weights = regime_data.get("strategy_weights", {})
        if weights:
            st.subheader("Strategy Weights")
            for name, w in weights.items():
                st.progress(min(w, 1.0), text=f"{name.replace('_', ' ').title()}: {w:.0%}")

        st.subheader("What This Means")
        regime_val = regime_data.get("regime", "")
        if "bull_trend" in regime_val:
            st.info("Strong bull market. Favor momentum and breakout strategies. Full position sizing.")
        elif "bull_choppy" in regime_val:
            st.info("Bullish but choppy. Be selective, use tighter stops. Mean reversion works here.")
        elif "bear_trend" in regime_val:
            st.warning("Bear trend detected. Reduce exposure, favor defensive sectors, hedge with puts.")
        elif "crisis" in regime_val:
            st.error("Crisis mode. Minimize new positions, raise cash, let hedges work.")
        elif "mean_reverting" in regime_val:
            st.info("Sideways/mean-reverting. Pairs trading and stat arb strategies work best.")

    st.divider()

    # ── Sector & Stock Recommendations
    st.subheader("Where To Invest (Next 30 Days + Long-Term)")

    if st.button("Generate Recommendations", type="primary"):
        with st.spinner("Analyzing all sectors and picking top stocks..."):
            recs = _api_get("/sectors/recommendations", timeout=1200)

        if not recs:
            st.error("Failed to generate recommendations. Try again.")
            return

        sectors = recs.get("sectors", [])
        buy_sectors = [s for s in sectors if s["verdict"] == "BUY"]
        hold_sectors = [s for s in sectors if s["verdict"] == "HOLD"]
        avoid_sectors = [s for s in sectors if s["verdict"] in ("REDUCE", "AVOID")]

        # Clear verdict at the top
        if buy_sectors:
            names = ", ".join(s["sector"] for s in buy_sectors)
            st.success(f"**BUY these sectors:** {names}")
        if hold_sectors:
            names = ", ".join(s["sector"] for s in hold_sectors)
            st.info(f"**HOLD if you own:** {names}")
        if avoid_sectors:
            names = ", ".join(s["sector"] for s in avoid_sectors)
            st.error(f"**AVOID / REDUCE:** {names}")

        st.divider()

        # Sector details
        st.markdown("#### Sector Breakdown")
        for s in sectors:
            verdict = s["verdict"]
            colors = {"BUY": "success", "HOLD": "info", "REDUCE": "warning", "AVOID": "error"}
            icons = {"BUY": "🟢", "HOLD": "🟡", "REDUCE": "🟠", "AVOID": "🔴"}

            getattr(st, colors.get(verdict, "info"))(
                f"{icons.get(verdict, '⚪')} **{s['sector']}** ({s['etf']}) — **{verdict}** (score: {s['score']})\n\n"
                f"5d: {s['return_5d']:+.1f}% | 20d: {s['return_20d']:+.1f}% | "
                f"60d: {s['return_60d']:+.1f}% | RSI: {s['rsi']:.0f}\n\n"
                f"6-12 month outlook: {s.get('long_term_outlook', 'N/A')}"
            )

        st.divider()

        # Top stock picks
        picks = recs.get("stock_picks", [])
        if picks:
            st.markdown("#### Top Stock Picks")
            pick_rows = []
            for p in picks:
                pick_rows.append({
                    "Ticker": p["ticker"],
                    "Company": p["name"],
                    "Sector": p["sector"],
                    "Price": _dp(p['price']),
                    "20d Return": f"{p['return_20d']:+.1f}%",
                    "RSI": f"{p['rsi']:.0f}",
                    "Score": p["score"],
                    "Why": p["why"],
                })
            st.dataframe(pd.DataFrame(pick_rows), width="stretch", hide_index=True)
            st.caption("Go to Stock Analysis for full trade plans on any of these tickers.")
        else:
            st.info("No strong stock picks in current conditions.")


def page_scanner():
    st.header("Universe Scanner")
    col_a, col_b = st.columns(2)
    max_sigs = col_a.slider("Max signals", 5, 50, 15)
    min_score = col_b.slider("Min score", 0.0, 100.0, 60.0)

    if st.button("Run Scan", type="primary"):
        with st.spinner("Scanning watchlist (50 tickers)..."):
            data = _api_get("/scan/", params={"max_signals": max_sigs, "min_score": min_score}, timeout=1200)
            if data and data.get("signals"):
                st.success(f"Found {len(data['signals'])} signals (of {data.get('total_signals', 0)} total)")
                df = pd.DataFrame(data["signals"])
                display_cols = ["ticker", "direction", "strategy", "signal_score", "conviction", "entry_price", "stop_loss", "target", "kelly_size_pct"]
                available = [c for c in display_cols if c in df.columns]
                st.dataframe(df[available], width="stretch", hide_index=True)
            elif data:
                st.info("No signals found. Try lowering the minimum score.")
            else:
                st.error("Scan timed out or API unavailable. The scanner fetches live data for ~50 tickers — try again.")


def page_stock_analysis():
    st.header("Single Stock Analysis")
    col_in1, col_in2 = st.columns([2, 1])
    ticker_input = col_in1.text_input("Enter ticker symbol", "AAPL").upper()
    capital_input = col_in2.number_input("Your capital ($)", min_value=10, value=10000, step=100)

    if st.button("Analyze", type="primary"):
        with st.spinner(f"Analyzing {ticker_input}..."):
            data = _api_get(f"/analyze/{ticker_input}", params={"capital": capital_input}, timeout=30)

        if not data:
            st.error(f"Could not analyze {ticker_input}. Check that the backend is running.")
            return

        tech = data.get("technicals", {})
        fund = data.get("fundamentals", {})
        take = data.get("system_take", {})
        plan = data.get("trade_plan", {})
        signals = data.get("signals", [])

        # ── Plain-English Summary (top of the page)
        summary_text = take.get("summary", "")
        if summary_text:
            st.markdown(f"**What's Happening**\n\n{summary_text.replace('$', chr(92) + '$')}")
            st.divider()

        # ── THE VERDICT — What should I do?
        action = plan.get("action", "HOLD OFF")
        override = plan.get("signal_override")
        action_colors = {
            "BUY": "success", "WAIT FOR BETTER ENTRY": "warning",
            "HOLD OFF — NO EDGE": "info", "AVOID": "error",
        }

        sizing = plan.get("sizing", {})
        shares = sizing.get("shares", 0)
        pos_val = sizing.get("position_value", 0)

        if action == "BUY":
            st.success(
                f"**{action}: {ticker_input}**\n\n"
                f"**Entry:** {_d(plan.get('entry_price', 0))} — {plan.get('entry_note', '')}\n\n"
                f"**Stop Loss:** {_d(plan.get('stop_loss', 0))} ({plan.get('stop_pct', 0):.1f}% risk)\n\n"
                f"**Target 1:** {_d(plan.get('target_1', 0))} (+{plan.get('target_1_pct', 0):.1f}%) | "
                f"**Target 2:** {_d(plan.get('target_2', 0))} (+{plan.get('target_2_pct', 0):.1f}%)\n\n"
                f"**Risk/Reward:** {plan.get('risk_reward', 0):.1f} : 1\n\n"
                f"**Hold Period:** {plan.get('hold_period', 'N/A')}"
            )
        elif action == "WAIT FOR BETTER ENTRY":
            st.warning(
                f"**{action}**\n\n"
                f"Set an alert at **{_d(plan.get('entry_price', 0))}** — {plan.get('entry_note', '')}\n\n"
                f"If it gets there: Stop {_d(plan.get('stop_loss', 0))} | Target {_d(plan.get('target_1', 0))}"
            )
        elif override and override.get("has_conflict"):
            st.warning(
                f"**CONFLICTING SIGNALS**\n\n"
                f"Technicals say: **{action}** — price is below key moving averages\n\n"
                f"Strategy signal says: **{override['signal_direction'].upper()}** "
                f"(score {override['signal_score']:.0f}, {override['signal_strategy']})\n\n"
                f"{override['note'].replace('$', chr(92) + '$')}"
            )
        else:
            st.error(f"**{action}**\n\nConditions aren't favorable for this stock right now.")

        # ── Position Sizing Box
        if shares > 0:
            st.subheader(f"Position Sizing ({_d(capital_input, ',.0f')} capital)")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Buy", f"{shares} shares")
            s2.metric("Position", _dp(pos_val), f"{sizing.get('position_pct', 0):.0f}% of capital")
            s3.metric("Max Loss", _dp(sizing.get('max_loss', 0)))
            s4.metric("Gain at T1", _dp(sizing.get('gain_at_target_1', 0)))

        # ── If you already own it
        own = plan.get("if_you_own_it", {})
        if own:
            st.subheader("Already Own This Stock?")
            own_action = own.get("action", "HOLD")
            own_colors = {
                "BUY MORE": "success", "HOLD": "info", "HOLD — TIGHTEN STOP": "warning",
                "HOLD — INSIDER CONVICTION": "warning", "HOLD — PREPARE TO SELL": "warning",
                "SELL": "error", "SELL PARTIAL — TAKE PROFITS": "warning",
            }
            own_fn = getattr(st, own_colors.get(own_action, "info"))
            own_fn(f"**{own_action}**\n\n{own.get('reason', '').replace('$', chr(92) + '$')}")

            hold_dur = own.get("hold_duration")
            if hold_dur:
                st.caption(f"**Hold duration:** {hold_dur.replace('$', chr(92) + '$')}")

            if own.get("stop_loss") or own.get("target"):
                oc1, oc2, oc3, oc4 = st.columns(4)
                if own.get("stop_loss"):
                    oc1.metric("Stop Loss", _dp(own['stop_loss']))
                    oc2.metric("Days to Stop", own.get("days_to_stop", "—"))
                if own.get("target"):
                    oc3.metric("Target", _dp(own['target']))
                    oc4.metric("Days to Target", own.get("days_to_target", "—"))

            # Sell window — only show if it adds information beyond what "already own" said
            sw = own.get("sell_window", {})
            own_already_covers_sell = own_action in ("SELL", "HOLD — INSIDER CONVICTION")
            if sw and sw.get("urgency") not in ("none", None) and not own_already_covers_sell:
                st.subheader("Sell Window")
                urg = sw.get("urgency", "")
                urg_colors = {"NOW": "error", "ALREADY LATE": "error", "SOON": "warning", "NEAR TERM": "warning", "WATCH": "info", "NOT YET": "success"}
                sw_fn = getattr(st, urg_colors.get(urg, "info"))
                sw_fn(f"**{urg}** — {sw.get('reason', '').replace('$', '\\$')}")
                sw1, sw2 = st.columns(2)
                if sw.get("sell_at"):
                    sw1.metric("Sell At", _dp(sw['sell_at']))
                sw2.metric("When", sw.get("sell_by", "—"))

        # ── 50% return question
        time_50 = plan.get("time_to_50pct")
        if time_50:
            st.subheader("Can I get 50% return?")
            st.markdown(f"Estimated time to 50% return: **{time_50}**")

        st.divider()

        # ── Header metrics
        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Price", _dp(tech.get('current_price', 0)), f"{tech.get('return_1d', 0):+.2f}% today")
        h2.metric("Sector", data.get("sector", "Unknown"))
        h3.metric("Regime", data.get("regime", "?").replace("_", " ").title())
        bias = take.get("bias", "neutral").title()
        h4.metric("System Bias", bias, f"Score: {take.get('score', 50)}")

        # ── System Assessment
        notes = take.get("notes", [])
        if notes:
            st.subheader("System Assessment")
            for note in notes:
                st.markdown(f"- {note}")

        st.divider()

        # ── Signals (if any)
        if signals:
            st.subheader("Active Strategy Signals")
            for sig in signals:
                sig_ticker = sig.get("ticker", ticker_input)
                rr = "N/A"
                entry = sig.get("entry_price", 0)
                stop = sig.get("stop_loss", 0)
                target = sig.get("target", 0)
                if entry and stop and target:
                    risk = abs(entry - stop)
                    reward = abs(target - entry)
                    rr = f"{reward / risk:.1f}" if risk > 0 else "N/A"

                # Color based on whether signal conflicts with the trade plan
                sig_color = "success" if action in ("BUY", "WAIT FOR BETTER ENTRY") else "warning"
                edge_text = sig.get('edge_reason', '').replace('$', '\\$')
                getattr(st, sig_color)(
                    f"**{sig['direction'].upper()} {sig_ticker}** — {sig.get('strategy', '')} | "
                    f"Score: {sig.get('signal_score', 0):.0f} | R/R: {rr}\n\n"
                    f"Entry: {_d(entry)} | Stop: {_d(stop)} | Target: {_d(target)} | "
                    f"Size: {sig.get('kelly_size_pct', 0):.1f}%\n\n"
                    f"Edge: {edge_text}"
                )

        # ── Two-column: Technicals + Fundamentals
        col_tech, col_fund = st.columns(2)

        with col_tech:
            st.subheader("Technical Levels")
            st.metric("Trend", tech.get("trend", "N/A"))
            t1, t2, t3 = st.columns(3)
            t1.metric("RSI (14)", f"{tech.get('rsi_14', 0):.1f}")
            t2.metric("ATR (14)", _dp(tech.get('atr_14', 0)), f"{tech.get('atr_pct', 0):.1f}%")
            t3.metric("Vol Ratio", f"{tech.get('volume_ratio', 1):.1f}x")

            st.markdown("**Moving Averages**")
            ma_data = []
            for label, key in [("20-day", "sma_20"), ("50-day", "sma_50"), ("200-day", "sma_200")]:
                val = tech.get(key)
                if val:
                    pct = (tech["current_price"] / val - 1) * 100
                    ma_data.append({"MA": label, "Price": _dp(val), "vs Price": f"{pct:+.1f}%"})
            if ma_data:
                st.dataframe(pd.DataFrame(ma_data), width="stretch", hide_index=True)

            st.markdown("**Key Levels**")
            lv1, lv2 = st.columns(2)
            lv1.metric("20d Support", _dp(tech.get('support_20d', 0)))
            lv2.metric("20d Resistance", _dp(tech.get('resistance_20d', 0)))
            lv1.metric("52W Low", _dp(tech.get('low_52w', 0)))
            lv2.metric("52W High", _dp(tech.get('high_52w', 0)), f"{tech.get('pct_from_52w_high', 0):+.1f}%")

        with col_fund:
            st.subheader("Fundamentals")
            if fund:
                f1, f2 = st.columns(2)
                mc = fund.get("market_cap")
                mc_str = "N/A"
                if mc:
                    mc_str = _dp(mc/1e12, ".1f") + "T" if mc >= 1e12 else (_dp(mc/1e9, ".1f") + "B" if mc >= 1e9 else _dp(mc/1e6, ".0f") + "M")
                f1.metric("Market Cap", mc_str)
                f2.metric("Beta", f"{fund.get('beta', 0):.2f}" if fund.get("beta") else "N/A")

                f3, f4 = st.columns(2)
                f3.metric("P/E (TTM)", f"{fund['pe_ratio']:.1f}" if fund.get("pe_ratio") else "N/A")
                f4.metric("Fwd P/E", f"{fund['forward_pe']:.1f}" if fund.get("forward_pe") else "N/A")

                f5, f6 = st.columns(2)
                f5.metric("EPS (TTM)", _dp(fund['eps_trailing']) if fund.get("eps_trailing") else "N/A")
                f6.metric("EPS (Fwd)", _dp(fund['eps_forward']) if fund.get("eps_forward") else "N/A")

                f7, f8 = st.columns(2)
                f7.metric("Rev Growth", f"{fund['revenue_growth']:.0%}" if fund.get("revenue_growth") else "N/A")
                f8.metric("Profit Margin", f"{fund['profit_margin']:.0%}" if fund.get("profit_margin") else "N/A")

                at = fund.get("analyst_target")
                if at and tech.get("current_price"):
                    upside = (at - tech["current_price"]) / tech["current_price"] * 100
                    st.metric("Analyst Target", _dp(at), f"{upside:+.1f}% from current")
            else:
                st.info("Fundamentals unavailable.")

        st.divider()
        st.subheader("Recent Performance")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("1 Day", f"{tech.get('return_1d', 0):+.2f}%")
        p2.metric("1 Week", f"{tech.get('return_5d', 0):+.2f}%")
        p3.metric("1 Month", f"{tech.get('return_20d', 0):+.2f}%")
        p4.metric("3 Month", f"{tech.get('return_60d', 0):+.2f}%")


def page_swing_picks():
    st.header("Swing Picks — 30%+ Setups")
    st.caption(
        "Aggressive, high-risk setups targeting 30%+ returns in 1-10 days. "
        "These are volatile stocks — biotech, small-cap, high-beta. "
        "Size small: 1-2% of capital max per trade."
    )

    col_s1, col_s2 = st.columns(2)
    min_return = col_s1.slider("Minimum target return %", 10, 100, 30, step=5)
    max_days = col_s2.slider("Maximum hold days", 1, 30, 10)

    # Check if a scan is already running or has results
    status_data = _api_get("/swing/status")
    scan_status = status_data.get("status", "idle") if status_data else "idle"

    if scan_status == "scanning":
        progress = status_data.get("progress", 0)
        total = status_data.get("total", 0)
        pct = int(progress / total * 100) if total > 0 else 0
        st.info(f"Scan in progress: {progress}/{total} tickers ({pct}%). You can navigate away — it keeps running.")
        st.progress(pct / 100)
        import time
        time.sleep(5)
        st.rerun()

    if scan_status == "done" and status_data.get("result"):
        st.success("Previous scan results available below. Click 'Scan' to run a fresh one.")

    if st.button("Scan for Swing Picks", type="primary"):
        try:
            r = httpx.post(
                f"{API_BASE}/swing/start-scan",
                params={"min_return_pct": min_return, "max_hold_days": max_days},
                timeout=10,
            )
            r.raise_for_status()
            resp = r.json()
        except Exception as e:
            logger.warning("Swing scan start: %s", e)
            resp = None

        if resp and resp.get("status") in ("started", "already_scanning"):
            st.info("Scan started in the background. You can navigate to other pages — results will be here when you come back.")
            import time
            time.sleep(3)
            st.rerun()
        else:
            st.error("Failed to start scan.")
            return

    # Show results if available
    if scan_status == "done" and status_data.get("result"):
        data = status_data["result"]
        quick = data.get("quick_trades", [])
        swing = data.get("swing_trades", [])
        stats = data.get("scan_stats", {})
    elif scan_status == "error":
        st.error(f"Scan failed: {status_data.get('error', 'Unknown error')}")
        return
    else:
        return

    st.success(
        f"Scanned {stats.get('tickers_scanned', 0)} tickers. "
        f"Found **{len(quick)} quick trades** (1-3 days) and **{len(swing)} swing trades** (3-10 days)."
    )

    tab_quick, tab_swing = st.tabs([
        f"Quick Trades — 1-3 Days ({len(quick)})",
        f"Swing Trades — 3-10 Days ({len(swing)})",
    ])

    with tab_quick:
        if quick:
            _render_swing_trades(quick)
        else:
            st.info(f"No stocks found with {min_return}%+ potential in 1-3 days. Try lowering the target.")

    with tab_swing:
        if swing:
            _render_swing_trades(swing)
        else:
            st.info(f"No stocks found with {min_return}%+ potential in 3-10 days. Try lowering the target.")


def _render_swing_trades(trades: list[dict]):
    """Render a list of swing trade picks as cards."""
    for t in trades:
        risk_colors = {"EXTREME": "error", "VERY HIGH": "error", "HIGH": "warning"}
        risk_fn = getattr(st, risk_colors.get(t.get("risk_level", "HIGH"), "warning"))

        direction_icon = "LONG" if t.get("direction") == "long" else "SHORT"
        risk_fn(
            f"**{direction_icon} {t['ticker']}** — Score: {t.get('score', 0):.0f} | "
            f"Risk: {t.get('risk_level', 'HIGH')}\n\n"
            f"**Entry:** {_d(t['entry'])} | "
            f"**Target:** {_d(t['target'])} (+{t['return_pct']:.0f}%) | "
            f"**Stop:** {_d(t['stop'])} (-{t['stop_pct']:.0f}%) | "
            f"**R/R:** {t['risk_reward']:.1f}:1\n\n"
            f"**Hold:** {t['hold_days']} | **Exit:** {t['exit_window']}"
        )
        analysis = t.get("analysis", "")
        if analysis:
            st.caption(analysis.replace("$", "\\$"))

    if trades:
        st.divider()
        rows = []
        for t in trades:
            rows.append({
                "Ticker": t["ticker"],
                "Dir": t["direction"].upper(),
                "Price": _dp(t['price']),
                "Target": _dp(t['target']),
                "Return": f"+{t['return_pct']:.0f}%",
                "Stop": _dp(t['stop']),
                "R/R": f"{t['risk_reward']:.1f}",
                "Hold": t["hold_days"],
                "ATR%": f"{t['atr_pct']:.1f}%",
                "Score": t["score"],
                "Catalyst": t["catalyst"],
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ── Routing ─────────────────────────────────────────────────

PAGES = {
    "Swing Picks": page_swing_picks,
    "Stock Analysis": page_stock_analysis,
    "Scanner": page_scanner,
    "Market Overview": page_market_overview,
}

with st.sidebar:
    st.title("QuantPulse v2")
    st.caption("Multi-Strategy Trading Advisory")
    page = st.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    st.caption(f"Session: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

PAGES[page]()
