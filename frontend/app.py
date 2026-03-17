"""QuantPulse v2 — Streamlit Dashboard.

Institutional-grade trading command center: regime, signals, journal, performance.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# Theme
# ════════════════════════════════════════════════════════════════════

_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

/* ── Base ── */
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
[data-testid="stHeader"] { background: transparent !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d0d2b 0%, #080820 100%) !important;
    border-right: 1px solid #1a1a3e !important;
}
section[data-testid="stSidebar"] .stRadio > div {
    gap: 2px !important;
}
section[data-testid="stSidebar"] .stRadio label {
    font-size: 14px !important;
    padding: 10px 14px !important;
    border-radius: 8px !important;
    transition: background 0.15s !important;
}
section[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(79, 143, 234, 0.08) !important;
}
section[data-testid="stSidebar"] .stRadio label[data-checked="true"],
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked) {
    background: rgba(79, 143, 234, 0.12) !important;
}

/* ── Metrics ── */
[data-testid="stMetric"] {
    background: #12122e;
    border: 1px solid #1e2d4a;
    border-radius: 10px;
    padding: 12px 14px;
    overflow: visible !important;
    white-space: normal !important;
}
[data-testid="stMetric"] * {
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: normal !important;
}
[data-testid="stMetricLabel"] p {
    font-size: 11px !important;
    color: #6b7b8d !important;
    text-transform: uppercase !important;
    letter-spacing: 0.4px !important;
    font-weight: 600 !important;
}
[data-testid="stMetricValue"] div {
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 600 !important;
    min-width: 0 !important;
}
[data-testid="stMetricDelta"] div {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
}

/* ── Primary Buttons ── */
button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #4f8fea 0%, #6c5ce7 100%) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 8px 28px !important;
    letter-spacing: 0.3px !important;
    transition: all 0.2s !important;
}
button[data-testid="stBaseButton-primary"]:hover {
    box-shadow: 0 4px 18px rgba(79, 143, 234, 0.35) !important;
    transform: translateY(-1px);
}
button[data-testid="stBaseButton-secondary"] {
    border-radius: 8px !important;
    border-color: #1e2d4a !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background: #12122e;
    border-radius: 10px;
    padding: 4px;
    border: 1px solid #1e2d4a;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    color: #6b7b8d !important;
    font-weight: 500 !important;
    padding: 8px 18px !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(79, 143, 234, 0.12) !important;
    color: #4f8fea !important;
    font-weight: 600 !important;
}

/* ── Inputs ── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #12122e !important;
    border-color: #1e2d4a !important;
    border-radius: 8px !important;
    color: #e8eaed !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: #4f8fea !important;
    box-shadow: 0 0 0 1px #4f8fea !important;
}

/* ── Alerts ── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
}

/* ── Dividers ── */
hr { border-color: #1e2d4a !important; opacity: 0.5; }

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: #12122e;
    border: 1px solid #1e2d4a !important;
    border-radius: 10px !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    border-radius: 10px;
}

/* ── Custom Components ── */
.qp-title {
    font-size: 26px;
    font-weight: 700;
    color: #e8eaed;
    letter-spacing: -0.5px;
    margin-bottom: 2px;
}
.qp-subtitle {
    color: #6b7b8d;
    font-size: 13px;
    margin-bottom: 20px;
}
.qp-card {
    background: #12122e;
    border: 1px solid #1e2d4a;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 12px;
    overflow-wrap: break-word;
    word-break: break-word;
}
.qp-card h3 {
    color: #e8eaed;
    font-size: 15px;
    font-weight: 600;
    margin: 0 0 10px;
}
.qp-card p {
    color: #a0aab4;
    margin: 4px 0;
    line-height: 1.6;
    font-size: 14px;
}
.qp-accent-left {
    border-left: 4px solid;
}
.qp-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    vertical-align: middle;
}
.qp-badge.green  { background: rgba(0,210,106,0.15); color: #00d26a; }
.qp-badge.red    { background: rgba(233,69,96,0.15);  color: #e94560; }
.qp-badge.amber  { background: rgba(245,166,35,0.15); color: #f5a623; }
.qp-badge.blue   { background: rgba(79,143,234,0.15); color: #4f8fea; }
.qp-badge.purple { background: rgba(108,92,231,0.15); color: #6c5ce7; }
.qp-badge.gray   { background: rgba(107,123,141,0.15);color: #8899aa; }

.qp-verdict {
    border-radius: 12px;
    padding: 24px;
    margin: 12px 0;
}
.qp-verdict.buy {
    background: linear-gradient(135deg, rgba(0,210,106,0.12), rgba(0,210,106,0.03));
    border: 1px solid rgba(0,210,106,0.25);
}
.qp-verdict.sell, .qp-verdict.avoid {
    background: linear-gradient(135deg, rgba(233,69,96,0.12), rgba(233,69,96,0.03));
    border: 1px solid rgba(233,69,96,0.25);
}
.qp-verdict.wait, .qp-verdict.hold, .qp-verdict.conflict {
    background: linear-gradient(135deg, rgba(245,166,35,0.12), rgba(245,166,35,0.03));
    border: 1px solid rgba(245,166,35,0.25);
}
.qp-verdict h2 { margin: 0 0 12px; font-size: 20px; color: #e8eaed; }
.qp-verdict p  { margin: 4px 0; line-height: 1.6; color: #c0c8d0; font-size: 14px; overflow-wrap: break-word; word-break: break-word; }
.qp-verdict .detail { color: #8899aa; font-size: 13px; font-family: 'JetBrains Mono', monospace; overflow-wrap: break-word; word-break: break-word; }

.qp-trade-card {
    background: #12122e;
    border: 1px solid #1e2d4a;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 10px;
    transition: border-color 0.15s;
}
.qp-trade-card:hover { border-color: #4f8fea; }
.qp-trade-card .ticker {
    font-size: 18px;
    font-weight: 700;
    color: #e8eaed;
}
.qp-trade-card .meta {
    color: #6b7b8d;
    font-size: 12px;
    margin-top: 2px;
}
.qp-trade-card .stats {
    display: flex;
    gap: 16px;
    margin-top: 14px;
    flex-wrap: wrap;
}
.qp-trade-card .stat-val {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    font-size: 14px;
    color: #e8eaed;
    overflow-wrap: break-word;
    word-break: break-word;
    min-width: 0;
}
.qp-trade-card .stat-lbl {
    color: #6b7b8d;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-top: 2px;
}

.qp-kpi {
    background: #12122e;
    border: 1px solid #1e2d4a;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
}
.qp-kpi .kpi-label {
    color: #6b7b8d;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 600;
}
.qp-kpi .kpi-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 26px;
    font-weight: 700;
    margin: 6px 0 2px;
    color: #e8eaed;
}
.qp-kpi .kpi-delta {
    font-size: 12px;
    font-weight: 500;
}

.qp-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.qp-status-dot.on  { background: #00d26a; box-shadow: 0 0 6px rgba(0,210,106,0.5); }
.qp-status-dot.off { background: #e94560; box-shadow: 0 0 6px rgba(233,69,96,0.5); }

.mono { font-family: 'JetBrains Mono', monospace; }
.green { color: #00d26a; }
.red   { color: #e94560; }
.amber { color: #f5a623; }
.blue  { color: #4f8fea; }
.muted { color: #6b7b8d; }
</style>"""

PLOTLY_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#c0c8d0", family="Inter, sans-serif", size=13),
    margin=dict(l=10, r=10, t=30, b=10),
    hoverlabel=dict(bgcolor="#12122e", font_color="#e8eaed", bordercolor="#1e2d4a"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#8899aa")),
)

_AXIS_DEFAULTS = dict(gridcolor="rgba(30,45,74,0.4)", zerolinecolor="#1e2d4a")

CHART_COLORS = [
    "#4f8fea", "#00d26a", "#f5a623", "#e94560",
    "#6c5ce7", "#00cec9", "#fd79a8", "#636e72",
]

API_BASE = "http://localhost:8000/api/v1"


# ════════════════════════════════════════════════════════════════════
# Page Config & CSS Injection
# ════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="QuantPulse v2",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(_CSS, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════

def _d(value: float, fmt: str = ",.2f") -> str:
    """Dollar value safe for st.markdown (escapes $ to avoid LaTeX)."""
    return f"\\${value:{fmt}}"


def _dp(value: float, fmt: str = ",.2f") -> str:
    """Dollar value for st.metric (no escaping needed)."""
    return f"${value:{fmt}}"


def _pnl_color(val: float) -> str:
    if val > 0:
        return "#00d26a"
    if val < 0:
        return "#e94560"
    return "#8899aa"


def _badge(text: str, color: str = "blue") -> str:
    return f'<span class="qp-badge {color}">{text}</span>'


def _market_status() -> tuple[str, str, str]:
    """Return (status_label, dot_color, time_str) for US market hours."""
    ET = timezone(timedelta(hours=-4))
    now = datetime.now(ET)
    weekday = now.weekday()
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute
    time_str = now.strftime("%-I:%M %p ET")

    if weekday >= 5:
        return "Closed (Weekend)", "#e94560", time_str
    if t < 4 * 60:
        return "Closed", "#e94560", time_str
    if t < 9 * 60 + 30:
        return "Pre-Market", "#f5a623", time_str
    if t < 16 * 60:
        return "Market Open", "#00d26a", time_str
    if t < 20 * 60:
        return "After-Hours", "#6c5ce7", time_str
    return "Closed", "#e94560", time_str


def _page_header(title: str, subtitle: str = "") -> None:
    sub = f'<div class="qp-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="qp-title">{title}</div>{sub}', unsafe_allow_html=True)


# ── API ──

def _api_get(path: str, params: dict | None = None, timeout: float = 10) -> dict | list | None:
    try:
        resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("API %s: %s", path, e)
        return None


def _api_post(path: str, json_data: dict | None = None, params: dict | None = None) -> dict | None:
    try:
        resp = httpx.post(f"{API_BASE}{path}", json=json_data, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("API POST %s: %s", path, e)
        return None


@st.cache_data(ttl=120)
def _cached_regime() -> dict | None:
    return _api_get("/regime/current", timeout=15)


@st.cache_data(ttl=30)
def _check_health() -> bool:
    try:
        r = httpx.get(f"{API_BASE.rsplit('/api', 1)[0]}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════
# Page: Market Overview
# ════════════════════════════════════════════════════════════════════

def page_market_overview():
    _page_header("Market Overview", "Regime detection, strategy allocation & sector recommendations")

    regime_data = _cached_regime()
    if not regime_data:
        st.warning("Could not connect to API. Start the backend with `uvicorn backend.main:app`")
        return

    # ── Top metrics ──
    c1, c2, c3, c4 = st.columns(4)
    regime_name = regime_data.get("regime", "unknown").replace("_", " ").title()
    confidence = regime_data.get("confidence", 0)
    vix = regime_data.get("vix", 0)
    breadth = regime_data.get("breadth_pct", 0)
    adx = regime_data.get("adx", 0)

    c1.metric("Regime", regime_name, f"{confidence:.0%} confidence")
    vix_note = "Elevated" if vix > 25 else ("Low" if vix < 15 else "Normal")
    c2.metric("VIX", f"{vix:.1f}", vix_note)
    c3.metric("Breadth", f"{breadth:.1f}%")
    c4.metric("ADX", f"{adx:.1f}", "Trending" if adx > 25 else "Range-bound")

    # ── Metrics summary ──
    regime_plain = {
        "Bull Trend": "stocks are going up and it looks like they'll keep going up",
        "Bull Choppy": "stocks are going up overall, but with big ups and downs day-to-day",
        "Bear Trend": "stocks are falling — the market is in a downturn",
        "Crisis": "the market is in serious trouble — think 2008 or COVID crash",
        "Mean Reverting": "the market isn't really going anywhere — bouncing up and down in a range",
    }
    regime_desc = regime_plain.get(regime_name, "sending mixed signals")

    if vix > 30:
        vix_desc = (
            f"VIX is {vix:.1f} — that's high. Think of VIX as the market's \"fear meter.\" "
            f"Right now, investors are nervous and expect big price swings"
        )
    elif vix > 20:
        vix_desc = (
            f"VIX is {vix:.1f} — slightly elevated. There's some worry in the market, "
            f"but nothing extreme. Stay alert but don't panic"
        )
    elif vix < 13:
        vix_desc = (
            f"VIX is {vix:.1f} — very low. The market feels calm, maybe too calm. "
            f"When everyone is relaxed, surprises can hit harder"
        )
    else:
        vix_desc = (
            f"VIX is {vix:.1f} — normal range. No unusual fear or excitement. "
            f"The market is relatively calm"
        )

    if breadth > 65:
        breadth_desc = (
            f"Breadth is {breadth:.0f}% — that's good. It means most stocks are going up, "
            f"not just a few big names carrying the whole market"
        )
    elif breadth > 50:
        breadth_desc = (
            f"Breadth is {breadth:.0f}% — about half the stocks are doing well, half aren't. "
            f"The market is divided, no clear winner"
        )
    else:
        breadth_desc = (
            f"Breadth is {breadth:.0f}% — that's weak. Only a few stocks are holding up the market. "
            f"When the rally is this narrow, it can break down easily"
        )

    if adx > 40:
        adx_desc = (
            f"ADX is {adx:.0f} — very strong trend. The market is moving with conviction in one direction. "
            f"Don't try to fight it, go with the flow"
        )
    elif adx > 25:
        adx_desc = (
            f"ADX is {adx:.0f} — there is a trend happening. The market has picked a direction "
            f"and is sticking with it for now"
        )
    else:
        adx_desc = (
            f"ADX is {adx:.0f} — no real trend. The market is chopping around without a clear direction. "
            f"Trend-following won't work well here"
        )

    conf_desc = (
        "the system is fairly confident in this call"
        if confidence >= 0.5
        else "the system isn't very sure, so it's playing it safe and spreading bets"
    )

    st.markdown(
        f'<div class="qp-card">'
        f'<h3>What These Numbers Mean</h3>'
        f'<p><b>Regime = {regime_name}:</b> Right now, {regime_desc}. '
        f'The system is {confidence:.0%} confident — {conf_desc}.</p>'
        f'<p><b>VIX (Fear Meter):</b> {vix_desc}.</p>'
        f'<p><b>Breadth (How Many Stocks Are Going Up):</b> {breadth_desc}.</p>'
        f'<p><b>ADX (Is The Market Trending?):</b> {adx_desc}.</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Charts row ──
    col_left, col_right = st.columns(2)

    with col_left:
        probs = regime_data.get("regime_probabilities", {})
        if probs:
            st.markdown("##### Regime Probabilities")
            prob_df = pd.DataFrame(
                [{"Regime": k.replace("_", " ").title(), "Probability": v}
                 for k, v in probs.items()]
            ).sort_values("Probability", ascending=True)

            colors = []
            for p in prob_df["Probability"]:
                if p >= 0.35:
                    colors.append("#e94560")
                elif p >= 0.2:
                    colors.append("#f5a623")
                else:
                    colors.append("#4f8fea")

            fig = go.Figure(go.Bar(
                x=prob_df["Probability"], y=prob_df["Regime"], orientation="h",
                marker_color=colors,
                marker_line=dict(width=0),
                text=[f"{p:.0%}" for p in prob_df["Probability"]],
                textposition="auto",
                textfont=dict(color="#e8eaed", size=12, family="JetBrains Mono"),
            ))
            fig.update_layout(
                **PLOTLY_LAYOUT,
                height=260,
                xaxis=dict(showticklabels=False, showgrid=False),
                yaxis=dict(showgrid=False),
                bargap=0.3,
            )
            st.plotly_chart(fig, width="stretch")

            top_regime = prob_df.iloc[-1]
            second_regime = prob_df.iloc[-2] if len(prob_df) > 1 else None
            top_name = top_regime["Regime"]
            top_pct = top_regime["Probability"]

            regime_plain = {
                "Bull Trend": "stocks are going up steadily — a good time to buy and ride the wave",
                "Bull Choppy": "stocks are generally going up, but with a lot of bumps along the way — be picky about what you buy",
                "Bear Trend": "stocks are falling — be careful, consider selling weak positions and keeping more cash",
                "Crisis": "the market is in panic mode — protect what you have, don't try to be a hero",
                "Mean Reverting": "the market is going sideways, not really up or down — look for stocks that bounced too far in either direction",
            }
            top_meaning = regime_plain.get(top_name, "mixed signals")

            parts = [f"**What this chart is telling you:** The system thinks the market is most likely in "
                     f"**{top_name}** mode ({top_pct:.0%} chance). In plain terms: {top_meaning}."]
            if second_regime is not None and second_regime["Probability"] >= 0.2:
                second_meaning = regime_plain.get(second_regime["Regime"], "something different")
                parts.append(
                    f"But there's also a {second_regime['Probability']:.0%} chance it's actually "
                    f"**{second_regime['Regime']}** ({second_meaning}). "
                    f"Because it's not 100% sure, the system plays it safe and doesn't bet everything on one scenario."
                )
            if top_pct < 0.5:
                parts.append(
                    "Since no single scenario is above 50%, the system stays diversified — "
                    "it doesn't go all-in on any one approach."
                )

            st.caption(" ".join(parts))

    with col_right:
        weights = regime_data.get("strategy_weights", {})
        if weights:
            st.markdown("##### Strategy Allocation")
            labels = [k.replace("_", " ").title() for k in weights.keys()]
            values = list(weights.values())

            fig = go.Figure(go.Pie(
                labels=labels, values=values,
                hole=0.55,
                marker=dict(
                    colors=CHART_COLORS[:len(labels)],
                    line=dict(color="#0a0a1a", width=2),
                ),
                textinfo="label+percent",
                textfont=dict(size=11, color="#c0c8d0"),
                hoverinfo="label+percent+value",
            ))
            invested = sum(v for k, v in weights.items() if k != "cash")
            cash_pct = weights.get("cash", 0)
            fig.update_layout(
                **PLOTLY_LAYOUT,
                height=260,
                showlegend=False,
                annotations=[dict(
                    text=f"<b>{invested:.0%}</b><br><span style='font-size:11px'>Invested</span>",
                    x=0.5, y=0.5,
                    font=dict(size=18, color="#e8eaed"),
                    showarrow=False,
                )],
            )
            st.plotly_chart(fig, width="stretch")

            top_strat = max(
                ((k, v) for k, v in weights.items() if k != "cash"),
                key=lambda x: x[1],
            )
            strat_plain = {
                "stat_arb": "Stat Arb — betting that two related stocks will snap back to their normal relationship",
                "catalyst": "Catalyst — trading around big events like earnings reports or insider buying",
                "momentum": "Momentum — following which sectors are hot right now based on economic signals",
                "flow": "Flow — watching what big institutions are buying behind the scenes",
                "intraday": "Intraday — catching overnight price gaps that tend to fill back",
            }
            top_label = strat_plain.get(top_strat[0], top_strat[0].replace("_", " ").title())

            analysis = (
                f"**What this chart is telling you:** If you had \\$100 to invest, "
                f"put \\${invested * 100:.0f} to work and keep \\${cash_pct * 100:.0f} as cash on the side. "
                f"The **{invested:.0%}** in the center is how much of your money should be actively invested right now. "
                f"The biggest slice goes to **{top_label}** ({top_strat[1]:.0%} of your money) — "
                f"the system thinks this approach works best in the current market. "
            )
            if cash_pct >= 0.2:
                analysis += (
                    f"Keeping {cash_pct:.0%} in cash is a lot — the system is being cautious. "
                    "It's saying: don't put too much at risk right now, wait for better opportunities."
                )
            elif cash_pct <= 0.05:
                analysis += (
                    f"Only {cash_pct:.0%} cash means the system is very confident — "
                    "it wants almost all your money working. This happens when conditions look strong."
                )
            else:
                analysis += (
                    f"The {cash_pct:.0%} cash buffer is normal — "
                    "enough to jump on new opportunities if something good comes up."
                )

            st.caption(analysis)

    # ── Regime Insight callout ──
    regime_val = regime_data.get("regime", "")
    callout_map = {
        "bull_trend":     ("#00d26a", "Strong bull market. Favor momentum and breakout strategies. Full position sizing."),
        "bull_choppy":    ("#4f8fea", "Bullish but choppy. Be selective, use tighter stops. Mean reversion works."),
        "bear_trend":     ("#f5a623", "Bear trend detected. Reduce exposure, favor defensive sectors, hedge with puts."),
        "crisis":         ("#e94560", "Crisis mode. Minimize new positions, raise cash, let hedges work."),
        "mean_reverting": ("#6c5ce7", "Sideways / mean-reverting. Pairs trading and stat arb strategies work best."),
    }
    for key, (color, msg) in callout_map.items():
        if key in regime_val:
            st.markdown(
                f'<div class="qp-card qp-accent-left" style="border-left-color:{color}">'
                f'<h3>Regime Insight</h3>'
                f'<p>{msg}</p></div>',
                unsafe_allow_html=True,
            )
            break

    st.divider()

    # ── Sector & Stock Recommendations ──
    st.markdown("##### Where To Invest")
    st.caption("Next 30 days + long-term sector and stock recommendations")

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

        if buy_sectors:
            names = ", ".join(s["sector"] for s in buy_sectors)
            st.markdown(
                f'<div class="qp-card qp-accent-left" style="border-left-color:#00d26a">'
                f'<p style="color:#e8eaed;margin:0">{_badge("BUY", "green")} &nbsp;<b>{names}</b></p></div>',
                unsafe_allow_html=True,
            )
        if hold_sectors:
            names = ", ".join(s["sector"] for s in hold_sectors)
            st.markdown(
                f'<div class="qp-card qp-accent-left" style="border-left-color:#f5a623">'
                f'<p style="color:#e8eaed;margin:0">{_badge("HOLD", "amber")} &nbsp;<b>{names}</b></p></div>',
                unsafe_allow_html=True,
            )
        if avoid_sectors:
            names = ", ".join(s["sector"] for s in avoid_sectors)
            st.markdown(
                f'<div class="qp-card qp-accent-left" style="border-left-color:#e94560">'
                f'<p style="color:#e8eaed;margin:0">{_badge("AVOID", "red")} &nbsp;<b>{names}</b></p></div>',
                unsafe_allow_html=True,
            )

        st.divider()

        st.markdown("###### Sector Breakdown")
        for s in sectors:
            verdict = s["verdict"]
            badge_cls = {"BUY": "green", "HOLD": "amber", "REDUCE": "red", "AVOID": "red"}.get(verdict, "gray")
            v_color = {"BUY": "#00d26a", "HOLD": "#f5a623", "REDUCE": "#e94560", "AVOID": "#e94560"}.get(verdict, "#8899aa")
            st.markdown(
                f'<div class="qp-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
                f'<span style="font-size:15px;font-weight:600;color:#e8eaed">'
                f'{s["sector"]} <span class="muted">({s["etf"]})</span></span>'
                f'{_badge(f"{verdict} {s['score']}", badge_cls)}</div>'
                f'<div class="mono" style="color:#8899aa;font-size:13px">'
                f'5d: <span style="color:{_pnl_color(s["return_5d"])}">{s["return_5d"]:+.1f}%</span> '
                f'&nbsp;|&nbsp; 20d: <span style="color:{_pnl_color(s["return_20d"])}">{s["return_20d"]:+.1f}%</span> '
                f'&nbsp;|&nbsp; 60d: <span style="color:{_pnl_color(s["return_60d"])}">{s["return_60d"]:+.1f}%</span> '
                f'&nbsp;|&nbsp; RSI: {s["rsi"]:.0f}</div>'
                f'<div class="muted" style="font-size:13px;margin-top:6px">'
                f'6-12mo outlook: {s.get("long_term_outlook", "N/A")}</div></div>',
                unsafe_allow_html=True,
            )

        st.divider()

        picks = recs.get("stock_picks", [])
        if picks:
            st.markdown("###### Top Stock Picks")
            pick_rows = []
            for p in picks:
                pick_rows.append({
                    "Ticker": p["ticker"],
                    "Company": p["name"],
                    "Sector": p["sector"],
                    "Price": _dp(p["price"]),
                    "20d Return": f"{p['return_20d']:+.1f}%",
                    "RSI": f"{p['rsi']:.0f}",
                    "Score": p["score"],
                    "Why": p["why"],
                })
            st.dataframe(pd.DataFrame(pick_rows), width="stretch", hide_index=True)
            st.caption("Go to **Stock Analysis** for full trade plans on any ticker.")
        else:
            st.info("No strong stock picks in current conditions.")


# ════════════════════════════════════════════════════════════════════
# Page: Stock Analysis
# ════════════════════════════════════════════════════════════════════

def page_stock_analysis():
    _page_header("Stock Analysis", "Quick portfolio builder & single-stock deep dive")

    # ── Quick Portfolio Builder ──
    st.markdown("##### Quick Portfolio Builder")
    st.markdown(
        '<div class="qp-card qp-accent-left" style="border-left-color:#00d26a">'
        "<p style='margin:0'>Enter how much you want to invest and we'll pick the "
        "top 3 stocks to hold for <b>6-12 months</b>, targeting <b>30%+ returns</b>. "
        "Based on sector analysis, strategy signals, insider activity, and current market conditions.</p></div>",
        unsafe_allow_html=True,
    )

    qp_col1, qp_col2 = st.columns([2, 1])
    portfolio_amount = qp_col1.number_input(
        "How much do you want to invest?", min_value=10, value=1000, step=100,
        key="portfolio_amount",
    )
    qp_col2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    pf_status_data = _api_get("/portfolio/quick-allocate/status")
    pf_status = pf_status_data.get("status", "idle") if pf_status_data else "idle"

    if pf_status == "scanning":
        progress = pf_status_data.get("progress", 0)
        total = pf_status_data.get("total", 4)
        step = pf_status_data.get("step", "Working...")
        pct = progress / total if total > 0 else 0
        st.info(f"Building your portfolio... Step {progress}/{total}: {step}")
        st.progress(pct)
        time.sleep(3)
        st.rerun()

    if pf_status == "done" and pf_status_data.get("result"):
        st.success("Portfolio ready below. Click 'Build My Portfolio' to refresh with new amount.")

    if qp_col2.button("Build My Portfolio", type="primary", key="build_portfolio"):
        resp = _api_post("/portfolio/quick-allocate/start", params={"capital": portfolio_amount})
        if resp and resp.get("status") in ("started", "already_scanning"):
            st.info("Building portfolio in the background...")
            time.sleep(2)
            st.rerun()
        else:
            st.error("Failed to start portfolio build.")

    if pf_status == "done" and pf_status_data.get("result"):
        alloc_data = pf_status_data["result"]
        if not alloc_data.get("picks"):
            st.error("Could not generate portfolio. Make sure the backend is running.")
        else:
            picks = alloc_data["picks"]
            regime = alloc_data.get("regime", "unknown").replace("_", " ").title()

            result_capital = alloc_data.get("capital", portfolio_amount)
            st.success(f"Here's your **\\${result_capital:,.0f}** portfolio ({regime} market):")

            for p in picks:
                alloc = p.get("allocation_dollars", 0)
                alloc_pct = p.get("allocation_pct", 0)
                ticker = p.get("ticker", "")
                name = p.get("name", ticker)
                sector = p.get("sector", "")
                score = p.get("score", 0)
                price = p.get("price", 0)
                shares = p.get("shares", 0)
                why = p.get("why", "").replace("$", "\\$")
                entry = p.get("entry", price)
                stop = p.get("stop_loss", 0)
                target = p.get("target", 0)
                risk_pct = p.get("risk_pct", 0)
                reward_pct = p.get("reward_pct", 0)
                rr = p.get("risk_reward", 0)
                direction = p.get("direction", "long").upper()
                d_badge = "green" if direction == "LONG" else "red"

                hold = p.get("hold_period", "6-12 months")

                st.markdown(
                    f'<div class="qp-trade-card">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap">'
                    f'<div style="display:flex;align-items:center;gap:10px">'
                    f'<span class="ticker">{ticker}</span>'
                    f'{_badge(direction, d_badge)} '
                    f'{_badge(sector, "blue")} '
                    f'{_badge(hold, "gray")} '
                    f'{_badge(f"Score {score:.0f}", "purple")}</div>'
                    f'<div style="font-family:JetBrains Mono,monospace;font-size:20px;font-weight:700;color:#00d26a">'
                    f'\\${alloc:,.0f} <span style="font-size:13px;color:#6b7b8d">({alloc_pct:.0f}%)</span></div></div>'
                    f'<div class="stats">'
                    f'<div><div class="stat-lbl">Buy At</div><div class="stat-val">{_d(entry)}</div></div>'
                    f'<div><div class="stat-lbl">Shares</div><div class="stat-val">{shares:.1f}</div></div>'
                    f'<div><div class="stat-lbl">Stop Loss</div>'
                    f'<div class="stat-val" style="color:#e94560">{_d(stop)} (-{risk_pct:.1f}%)</div></div>'
                    f'<div><div class="stat-lbl">Target (30%)</div>'
                    f'<div class="stat-val" style="color:#00d26a">{_d(target)} (+{reward_pct:.1f}%)</div></div>'
                    f'<div><div class="stat-lbl">R/R</div><div class="stat-val">{rr:.1f}:1</div></div>'
                    f'</div>'
                    f'<div class="meta" style="margin-top:8px">{why}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            st.divider()

            st.markdown("##### Your Plan in Plain English")
            for i, p in enumerate(picks, 1):
                t = p["ticker"]
                a = p["allocation_dollars"]
                s = p.get("shares", 0)
                e = p.get("entry", p["price"])
                sl = p.get("stop_loss", 0)
                tgt = p.get("target", 0)
                hold = p.get("hold_period", "6-12 months")

                st.markdown(
                    f"**{i}. {t}** — Put **\\${a:,.0f}** in (~{s:.1f} shares) at {_d(e)}. "
                    f"Hold for **{hold}**. "
                    f"Target: {_d(tgt)} (+30%). "
                    f"If it drops below {_d(sl)} (-15%), consider selling to protect your capital."
                )

            st.divider()

            rows = []
            for p in picks:
                rows.append({
                    "Ticker": p["ticker"],
                    "Invest": f"${p['allocation_dollars']:,.0f}",
                    "%": f"{p['allocation_pct']:.0f}%",
                    "Shares": f"{p.get('shares', 0):.1f}",
                    "Entry": _dp(p.get("entry", 0)),
                    "Stop": _dp(p.get("stop_loss", 0)),
                    "Target": _dp(p.get("target", 0)),
                    "R/R": f"{p.get('risk_reward', 0):.1f}:1",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

            st.caption(
                "This is a suggestion based on current market conditions, sector strength, "
                "and strategy signals. It is NOT financial advice. Always do your own research."
            )

    st.divider()

    # ── Single Stock Analysis ──
    st.markdown("##### Single Stock Deep Dive")

    col_in1, col_in2 = st.columns([2, 1])
    ticker_input = col_in1.text_input("Ticker", "AAPL").upper()
    capital_input = col_in2.number_input("Capital ($)", min_value=10, value=10000, step=100)

    if not st.button("Analyze", type="primary"):
        return

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

    # ── Plain-English Summary ──
    summary_text = take.get("summary", "")
    if summary_text:
        st.markdown(
            f'<div class="qp-card qp-accent-left" style="border-left-color:#4f8fea">'
            f'<h3>What\'s Happening</h3>'
            f'<p>{summary_text.replace("$", chr(92) + "$")}</p></div>',
            unsafe_allow_html=True,
        )

    # ── Verdict Card ──
    action = plan.get("action", "HOLD OFF")
    override = plan.get("signal_override")
    sizing = plan.get("sizing", {})
    shares = sizing.get("shares", 0)
    pos_val = sizing.get("position_value", 0)

    if action == "BUY":
        st.markdown(
            f'<div class="qp-verdict buy">'
            f'<h2>{action}: {ticker_input}</h2>'
            f'<p class="detail">Entry: {_d(plan.get("entry_price", 0))} &mdash; {plan.get("entry_note", "")}</p>'
            f'<p class="detail">Stop: {_d(plan.get("stop_loss", 0))} ({plan.get("stop_pct", 0):.1f}% risk)</p>'
            f'<p class="detail">Target 1: {_d(plan.get("target_1", 0))} (+{plan.get("target_1_pct", 0):.1f}%) '
            f'&nbsp;|&nbsp; Target 2: {_d(plan.get("target_2", 0))} (+{plan.get("target_2_pct", 0):.1f}%)</p>'
            f'<p class="detail">R/R: {plan.get("risk_reward", 0):.1f} : 1 &nbsp;|&nbsp; '
            f'Hold: {plan.get("hold_period", "N/A")}</p></div>',
            unsafe_allow_html=True,
        )
    elif action == "WAIT FOR BETTER ENTRY":
        st.markdown(
            f'<div class="qp-verdict wait">'
            f'<h2>{action}</h2>'
            f'<p class="detail">'
            f'Set alert at {_d(plan.get("entry_price", 0))} &mdash; {plan.get("entry_note", "")}<br>'
            f'If it gets there: Stop {_d(plan.get("stop_loss", 0))} | Target {_d(plan.get("target_1", 0))}</p></div>',
            unsafe_allow_html=True,
        )
    elif override and override.get("has_conflict"):
        st.markdown(
            f'<div class="qp-verdict conflict">'
            f'<h2>Conflicting Signals</h2>'
            f'<p>Technicals say: <b>{action}</b> &mdash; price below key moving averages<br>'
            f'Strategy says: <b>{override["signal_direction"].upper()}</b> '
            f'(score {override["signal_score"]:.0f}, {override["signal_strategy"]})</p>'
            f'<p class="detail">{override["note"].replace("$", chr(92) + "$")}</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="qp-verdict avoid">'
            f'<h2>{action}</h2>'
            f'<p>Conditions aren\'t favorable for this stock right now.</p></div>',
            unsafe_allow_html=True,
        )

    # ── Position Sizing ──
    if shares > 0:
        st.markdown(f"##### Position Sizing ({_d(capital_input, ',.0f')} capital)")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Buy", f"{shares} shares")
        s2.metric("Position", _dp(pos_val), f"{sizing.get('position_pct', 0):.0f}% of capital")
        s3.metric("Max Loss", _dp(sizing.get("max_loss", 0)))
        s4.metric("Gain at T1", _dp(sizing.get("gain_at_target_1", 0)))

    # ── Already Own It? ──
    own = plan.get("if_you_own_it", {})
    if own:
        st.markdown("##### Already Own This Stock?")
        own_action = own.get("action", "HOLD")
        own_cls = {
            "BUY MORE": "buy", "HOLD": "hold", "HOLD — TIGHTEN STOP": "hold",
            "HOLD — INSIDER CONVICTION": "hold", "HOLD — PREPARE TO SELL": "hold",
            "SELL": "sell", "SELL PARTIAL — TAKE PROFITS": "sell",
        }
        vc = own_cls.get(own_action, "hold")
        reason = own.get("reason", "").replace("$", chr(92) + "$")
        st.markdown(
            f'<div class="qp-verdict {vc}">'
            f'<h2>{own_action}</h2>'
            f'<p>{reason}</p></div>',
            unsafe_allow_html=True,
        )

        hold_dur = own.get("hold_duration")
        if hold_dur:
            st.caption(f"**Hold duration:** {hold_dur.replace('$', chr(92) + '$')}")

        if own.get("stop_loss") or own.get("target"):
            if own.get("stop_loss"):
                oc1, oc2 = st.columns(2)
                oc1.metric("Stop Loss", _dp(own["stop_loss"]))
                oc2.metric("Days to Stop", own.get("days_to_stop", "—"))
            if own.get("target"):
                oc3, oc4 = st.columns(2)
                oc3.metric("Target", _dp(own["target"]))
                oc4.metric("Days to Target", own.get("days_to_target", "—"))

        sw = own.get("sell_window", {})
        own_already_covers_sell = own_action in ("SELL", "HOLD — INSIDER CONVICTION")
        if sw and sw.get("urgency") not in ("none", None) and not own_already_covers_sell:
            st.markdown("##### Sell Window")
            urg = sw.get("urgency", "")
            urg_cls = {"NOW": "sell", "ALREADY LATE": "sell", "SOON": "wait",
                       "NEAR TERM": "wait", "WATCH": "hold", "NOT YET": "buy"}
            st.markdown(
                f'<div class="qp-verdict {urg_cls.get(urg, "hold")}">'
                f'<h2>{urg}</h2>'
                f'<p>{sw.get("reason", "").replace("$", chr(92) + "$")}</p></div>',
                unsafe_allow_html=True,
            )
            if sw.get("sell_at"):
                st.metric("Sell At", _dp(sw["sell_at"]))
            sell_by = sw.get("sell_by", "—")
            if sell_by and sell_by != "—":
                sell_by_escaped = sell_by.replace("$", chr(92) + "$")
                st.markdown(f"**When:** {sell_by_escaped}")

    # ── 50% return ──
    time_50 = plan.get("time_to_50pct")
    if time_50:
        st.markdown("##### Can I Get 50% Return?")
        st.markdown(f"Estimated time: **{time_50}**")

    st.divider()

    # ── Header metrics ──
    h1, h2 = st.columns(2)
    h1.metric("Price", _dp(tech.get("current_price", 0)), f"{tech.get('return_1d', 0):+.2f}% today")
    h2.metric("Sector", data.get("sector", "Unknown"))
    h3, h4 = st.columns(2)
    h3.metric("Regime", data.get("regime", "?").replace("_", " ").title())
    bias = take.get("bias", "neutral").title()
    h4.metric("System Bias", bias, f"Score: {take.get('score', 50)}")

    # ── System Assessment ──
    notes = take.get("notes", [])
    if notes:
        st.markdown("##### System Assessment")
        for note in notes:
            st.markdown(f"- {note}")

    st.divider()

    # ── Active Signals ──
    if signals:
        st.markdown("##### Active Strategy Signals")
        for sig in signals:
            sig_ticker = sig.get("ticker", ticker_input)
            entry = sig.get("entry_price", 0)
            stop = sig.get("stop_loss", 0)
            target = sig.get("target", 0)
            rr = "N/A"
            if entry and stop and target:
                risk = abs(entry - stop)
                reward = abs(target - entry)
                rr = f"{reward / risk:.1f}" if risk > 0 else "N/A"

            direction = sig["direction"].upper()
            sig_badge = "green" if direction == "LONG" else "red"
            edge_text = sig.get("edge_reason", "").replace("$", "\\$")

            st.markdown(
                f'<div class="qp-trade-card">'
                f'<div style="display:flex;align-items:center;gap:10px">'
                f'<span class="ticker">{sig_ticker}</span>'
                f'{_badge(direction, sig_badge)} '
                f'{_badge(sig.get("strategy", ""), "blue")}</div>'
                f'<div class="stats">'
                f'<div><div class="stat-lbl">Score</div><div class="stat-val">{sig.get("signal_score", 0):.0f}</div></div>'
                f'<div><div class="stat-lbl">Entry</div><div class="stat-val">{_d(entry)}</div></div>'
                f'<div><div class="stat-lbl">Stop</div><div class="stat-val">{_d(stop)}</div></div>'
                f'<div><div class="stat-lbl">Target</div><div class="stat-val">{_d(target)}</div></div>'
                f'<div><div class="stat-lbl">R/R</div><div class="stat-val">{rr}</div></div>'
                f'<div><div class="stat-lbl">Size</div><div class="stat-val">{sig.get("kelly_size_pct", 0):.1f}%</div></div>'
                f'</div>'
                f'<div class="meta" style="margin-top:10px">Edge: {edge_text}</div></div>',
                unsafe_allow_html=True,
            )

    # ── Technicals / Fundamentals ──
    col_tech, col_fund = st.columns(2)

    with col_tech:
        st.markdown("##### Technicals")
        st.metric("Trend", tech.get("trend", "N/A"))
        t1, t2 = st.columns(2)
        t1.metric("RSI (14)", f"{tech.get('rsi_14', 0):.1f}")
        t2.metric("ATR (14)", _dp(tech.get("atr_14", 0)), f"{tech.get('atr_pct', 0):.1f}%")
        st.metric("Vol Ratio", f"{tech.get('volume_ratio', 1):.1f}x")

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
        lv1.metric("20d Support", _dp(tech.get("support_20d", 0)))
        lv2.metric("20d Resistance", _dp(tech.get("resistance_20d", 0)))
        lv1.metric("52W Low", _dp(tech.get("low_52w", 0)))
        lv2.metric("52W High", _dp(tech.get("high_52w", 0)), f"{tech.get('pct_from_52w_high', 0):+.1f}%")

    with col_fund:
        st.markdown("##### Fundamentals")
        if fund:
            f1, f2 = st.columns(2)
            mc = fund.get("market_cap")
            if mc:
                mc_str = (_dp(mc / 1e12, ".1f") + "T" if mc >= 1e12
                          else _dp(mc / 1e9, ".1f") + "B" if mc >= 1e9
                          else _dp(mc / 1e6, ".0f") + "M")
            else:
                mc_str = "N/A"
            f1.metric("Market Cap", mc_str)
            f2.metric("Beta", f"{fund['beta']:.2f}" if fund.get("beta") else "N/A")

            f3, f4 = st.columns(2)
            f3.metric("P/E (TTM)", f"{fund['pe_ratio']:.1f}" if fund.get("pe_ratio") else "N/A")
            f4.metric("Fwd P/E", f"{fund['forward_pe']:.1f}" if fund.get("forward_pe") else "N/A")

            f5, f6 = st.columns(2)
            f5.metric("EPS (TTM)", _dp(fund["eps_trailing"]) if fund.get("eps_trailing") else "N/A")
            f6.metric("EPS (Fwd)", _dp(fund["eps_forward"]) if fund.get("eps_forward") else "N/A")

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

    # ── Recent Performance bar chart ──
    st.markdown("##### Recent Performance")
    periods = ["1D", "1W", "1M", "3M"]
    returns = [
        tech.get("return_1d", 0), tech.get("return_5d", 0),
        tech.get("return_20d", 0), tech.get("return_60d", 0),
    ]
    colors = [_pnl_color(r) for r in returns]

    fig = go.Figure(go.Bar(
        x=periods, y=returns,
        marker_color=colors,
        text=[f"{r:+.2f}%" for r in returns],
        textposition="outside",
        textfont=dict(size=12, family="JetBrains Mono", color="#c0c8d0"),
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=200,
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=True, zerolinecolor="#1e2d4a"),
        xaxis=dict(showgrid=False),
        bargap=0.4,
    )
    st.plotly_chart(fig, width="stretch")


# ════════════════════════════════════════════════════════════════════
# Page: Scanner
# ════════════════════════════════════════════════════════════════════

def page_scanner():
    _page_header("Universe Scanner", "Scan the watchlist for actionable signals")

    st.markdown(
        '<div class="qp-card qp-accent-left" style="border-left-color:#4f8fea">'
        "<p style='margin:0'>Runs all 5 strategies (stat arb, catalyst, cross-asset momentum, "
        "flow, gap reversion) across a 41-ticker watchlist and returns the strongest signals "
        "ranked by conviction.</p></div>",
        unsafe_allow_html=True,
    )

    col_a, col_b = st.columns(2)
    max_sigs = col_a.slider(
        "Max signals", 5, 50, 15,
        help="Maximum results to return. Signals are ranked by conviction — this caps how many you see.",
    )
    min_score = col_b.slider(
        "Min score", 0.0, 100.0, 60.0,
        help="Minimum signal quality (0-100). Score is based on earnings surprise, revision breadth, "
             "z-score strength, etc. 60+ returns only high-quality signals.",
    )

    status_data = _api_get("/scan/status")
    scan_status = status_data.get("status", "idle") if status_data else "idle"

    if scan_status == "scanning":
        progress = status_data.get("progress", 0)
        total = status_data.get("total", 1)
        pct = int(progress / total * 100) if total > 0 else 0
        st.info(f"Scan in progress ({pct}%). You can navigate away — it keeps running.")
        st.progress(pct / 100)
        time.sleep(3)
        st.rerun()

    if scan_status == "done" and status_data.get("result"):
        st.success("Previous scan results available below. Click 'Run Scan' to run a fresh one.")

    if st.button("Run Scan", type="primary"):
        resp = _api_post("/scan/start-scan", params={"max_signals": max_sigs, "min_score": min_score})
        if resp and resp.get("status") in ("started", "already_scanning"):
            st.info("Scan started in the background. Results will appear here.")
            time.sleep(2)
            st.rerun()
        else:
            st.error("Failed to start scan.")
            return

    if scan_status == "done" and status_data.get("result"):
        data = status_data["result"]
        signals = data.get("signals", [])

        if signals:
            st.success(f"Found {len(signals)} signals (of {data.get('total_signals', 0)} total)")

            for sig in signals:
                direction = sig.get("direction", "long").upper()
                d_badge = "green" if direction == "LONG" else "red"
                entry = sig.get("entry_price", 0)
                stop = sig.get("stop_loss", 0)
                target = sig.get("target", 0)
                score = sig.get("signal_score", 0)
                strategy = sig.get("strategy", "").replace("_", " ").title()

                st.markdown(
                    f'<div class="qp-trade-card">'
                    f'<div style="display:flex;align-items:center;gap:10px">'
                    f'<span class="ticker">{sig.get("ticker", "")}</span>'
                    f'{_badge(direction, d_badge)} '
                    f'{_badge(strategy, "blue")} '
                    f'{_badge(sig.get("conviction", ""), "purple")}</div>'
                    f'<div class="stats">'
                    f'<div><div class="stat-lbl">Score</div><div class="stat-val">{score:.0f}</div></div>'
                    f'<div><div class="stat-lbl">Entry</div><div class="stat-val">{_d(entry)}</div></div>'
                    f'<div><div class="stat-lbl">Stop</div><div class="stat-val">{_d(stop)}</div></div>'
                    f'<div><div class="stat-lbl">Target</div><div class="stat-val">{_d(target)}</div></div>'
                    f'<div><div class="stat-lbl">Kelly Size</div><div class="stat-val">{sig.get("kelly_size_pct", 0):.1f}%</div></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            st.divider()
            df = pd.DataFrame(signals)
            display_cols = ["ticker", "direction", "strategy", "signal_score", "conviction",
                            "entry_price", "stop_loss", "target", "kelly_size_pct"]
            available = [c for c in display_cols if c in df.columns]
            st.dataframe(df[available], width="stretch", hide_index=True)
        else:
            st.info("No signals found. Try lowering the minimum score.")
    elif scan_status == "error":
        st.error(f"Scan failed: {status_data.get('error', 'Unknown error')}")


# ════════════════════════════════════════════════════════════════════
# Page: Swing Picks
# ════════════════════════════════════════════════════════════════════

def page_swing_picks():
    _page_header("Swing Picks", "Top 5 aggressive setups targeting 30%+ returns in 1-10 days")
    st.markdown(
        f'<div class="qp-card qp-accent-left" style="border-left-color:#e94560">'
        f'<p style="margin:0">Volatile stocks &mdash; biotech, small-cap, high-beta. '
        f'Size small: <b>1-2% of capital max</b> per trade.</p></div>',
        unsafe_allow_html=True,
    )

    col_s1, col_s2 = st.columns(2)
    min_return = col_s1.slider("Minimum target return %", 10, 100, 30, step=5)
    max_days = col_s2.slider("Maximum hold days", 1, 30, 10)

    status_data = _api_get("/swing/status")
    scan_status = status_data.get("status", "idle") if status_data else "idle"

    if scan_status == "scanning":
        progress = status_data.get("progress", 0)
        total = status_data.get("total", 0)
        pct = int(progress / total * 100) if total > 0 else 0
        st.info(f"Scan in progress: {progress}/{total} tickers ({pct}%).")
        st.progress(pct / 100)
        time.sleep(5)
        st.rerun()

    if scan_status == "done" and status_data.get("result"):
        st.success("Previous scan results available below. Click 'Scan' to run a fresh one.")

    if st.button("Scan for Swing Picks", type="primary"):
        resp = _api_post("/swing/start-scan", params={"min_return_pct": min_return, "max_hold_days": max_days})
        if resp and resp.get("status") in ("started", "already_scanning"):
            st.info("Scan started in the background. Results will appear here.")
            time.sleep(3)
            st.rerun()
        else:
            st.error("Failed to start scan.")
            return

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

    all_picks = quick + swing
    all_picks.sort(key=lambda t: t.get("score", 0), reverse=True)
    top_5 = all_picks[:5]

    st.success(
        f"Scanned {stats.get('tickers_scanned', 0)} tickers. "
        f"Showing the **top {len(top_5)}** picks by score."
    )

    if top_5:
        _render_swing_trades(top_5)
    else:
        st.info(f"No stocks found with {min_return}%+ potential. Try lowering the target.")


def _render_swing_trades(trades: list[dict]):
    for t in trades:
        direction = "LONG" if t.get("direction") == "long" else "SHORT"
        d_badge = "green" if direction == "LONG" else "red"
        risk_level = t.get("risk_level", "HIGH")
        risk_badge = "red" if risk_level in ("EXTREME", "VERY HIGH") else "amber"

        st.markdown(
            f'<div class="qp-trade-card">'
            f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
            f'<span class="ticker">{t["ticker"]}</span>'
            f'{_badge(direction, d_badge)} '
            f'{_badge(risk_level, risk_badge)} '
            f'{_badge(f"Score {t.get('score', 0):.0f}", "blue")}</div>'
            f'<div class="stats">'
            f'<div><div class="stat-lbl">Entry</div><div class="stat-val">{_d(t["entry"])}</div></div>'
            f'<div><div class="stat-lbl">Target</div>'
            f'<div class="stat-val" style="color:#00d26a">{_d(t["target"])} (+{t["return_pct"]:.0f}%)</div></div>'
            f'<div><div class="stat-lbl">Stop</div>'
            f'<div class="stat-val" style="color:#e94560">{_d(t["stop"])} (-{t["stop_pct"]:.0f}%)</div></div>'
            f'<div><div class="stat-lbl">R/R</div><div class="stat-val">{t["risk_reward"]:.1f}:1</div></div>'
            f'<div><div class="stat-lbl">Hold</div><div class="stat-val">{t["hold_days"]}</div></div>'
            f'<div><div class="stat-lbl">Exit</div><div class="stat-val">{t["exit_window"]}</div></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        analysis = t.get("analysis", "")
        if analysis:
            with st.expander("Analysis"):
                st.write(analysis.replace("$", "\\$"))

    if trades:
        st.divider()
        rows = []
        for t in trades:
            rows.append({
                "Ticker": t["ticker"],
                "Dir": t["direction"].upper(),
                "Price": _dp(t["price"]),
                "Target": _dp(t["target"]),
                "Return": f"+{t['return_pct']:.0f}%",
                "Stop": _dp(t["stop"]),
                "R/R": f"{t['risk_reward']:.1f}",
                "Hold": t["hold_days"],
                "ATR%": f"{t['atr_pct']:.1f}%",
                "Score": t["score"],
                "Catalyst": t["catalyst"],
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ════════════════════════════════════════════════════════════════════
# Sidebar & Routing
# ════════════════════════════════════════════════════════════════════

PAGES = {
    "📊  Market Overview": page_market_overview,
    "🔍  Stock Analysis": page_stock_analysis,
    "📡  Scanner": page_scanner,
    "⚡  Swing Picks": page_swing_picks,
}

with st.sidebar:
    # Logo
    st.markdown(
        '<div style="text-align:center;padding:8px 0 16px">'
        '<span style="font-size:28px">📊</span><br>'
        '<span style="font-size:22px;font-weight:700;color:#4f8fea;letter-spacing:-0.5px">QuantPulse</span>'
        '<span style="font-size:22px;font-weight:300;color:#6b7b8d"> v2</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Backend status
    healthy = _check_health()
    dot = "on" if healthy else "off"
    label = "API Connected" if healthy else "API Offline"
    st.markdown(
        f'<div style="text-align:center;margin-bottom:12px">'
        f'<span class="qp-status-dot {dot}"></span> '
        f'<span style="color:#6b7b8d;font-size:12px">{label}</span></div>',
        unsafe_allow_html=True,
    )

    # Market status
    mkt_label, mkt_color, mkt_time = _market_status()
    st.markdown(
        f'<div style="text-align:center;margin-bottom:12px">'
        f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
        f'background:{mkt_color};box-shadow:0 0 6px {mkt_color}80"></span> '
        f'<span style="color:#e8eaed;font-size:12px;font-weight:600">{mkt_label}</span> '
        f'<span style="color:#6b7b8d;font-size:11px">{mkt_time}</span></div>',
        unsafe_allow_html=True,
    )

    # Regime badge
    regime_data = _cached_regime()
    if regime_data:
        r_name = regime_data.get("regime", "unknown").replace("_", " ").title()
        r_conf = regime_data.get("confidence", 0)
        r_colors = {
            "bull_trend": "#00d26a", "bull_choppy": "#00cec9",
            "bear_trend": "#f5a623", "crisis": "#e94560", "mean_reverting": "#6c5ce7",
        }
        rc = r_colors.get(regime_data.get("regime", ""), "#4f8fea")
        st.markdown(
            f'<div style="text-align:center;margin-bottom:16px">'
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'padding:5px 12px;border-radius:8px;background:#12122e;border:1px solid #1e2d4a;'
            f'font-size:13px;font-weight:600;color:#e8eaed">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{rc};display:inline-block"></span>'
            f'{r_name} <span class="muted">({r_conf:.0%})</span></span></div>',
            unsafe_allow_html=True,
        )

    st.divider()
    page = st.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    ET = timezone(timedelta(hours=-4))
    now_et = datetime.now(ET)
    st.caption(f"{now_et.strftime('%A, %B %d, %Y')}")
    st.caption(f"{now_et.strftime('%-I:%M %p')} ET &nbsp;|&nbsp; {datetime.now().strftime('%-I:%M %p')} Local")

PAGES[page]()
