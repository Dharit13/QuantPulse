"""Earnings signal — EPS surprise scoring and PEAD detection.

Implements Sub-Strategy A from the spec (Section 5):
  - Score the magnitude of EPS surprise
  - Detect Post-Earnings Announcement Drift (PEAD) candidates
  - Composite scoring from surprise, revision trend, guidance, sector, history

Data path:
  yfinance (free) → get_earnings_history()
  FMP (paid)      → get_eps_surprises()  (when API key set)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from backend.adaptive.thresholds import get_catalyst_params
from backend.adaptive.vol_context import VolContext
from backend.config import settings
from backend.data.fetcher import data_fetcher
from backend.data.sources.yfinance_src import yfinance_source
from backend.models.schemas import EarningsSignal

logger = logging.getLogger(__name__)


def get_recent_earnings(ticker: str) -> list[dict]:
    """Fetch earnings history, preferring paid source when available."""
    if settings.fmp_api_key:
        fmp_data = data_fetcher.get_earnings_data(ticker)
        if fmp_data:
            return [fmp_data] if isinstance(fmp_data, dict) else fmp_data

    return yfinance_source.get_earnings_history(ticker)


def score_earnings_surprise(
    eps_actual: float,
    eps_estimate: float,
) -> float:
    """Compute EPS surprise as a percentage.

    surprise_pct = (actual - estimate) / |estimate| * 100
    """
    if eps_estimate == 0:
        return 0.0
    return (eps_actual - eps_estimate) / abs(eps_estimate) * 100


def detect_pead(
    ticker: str,
    vol: VolContext,
    lookback_days: int = 5,
) -> EarningsSignal | None:
    """Check if ticker qualifies as a PEAD trade.

    Criteria (adaptive via VolContext):
      1. |EPS surprise| > min_eps_surprise_pct
      2. Earnings-day return > min_earnings_gap_pct (same direction as surprise)
      3. Earnings reported within lookback_days
    """
    params = get_catalyst_params(vol)
    earnings = get_recent_earnings(ticker)
    if not earnings:
        return None

    latest = earnings[0]
    report_date = latest["date"]
    if isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)

    today = date.today()
    if (today - report_date).days > lookback_days:
        return None

    surprise_pct = latest.get("surprise_pct")
    if surprise_pct is None:
        surprise_pct = score_earnings_surprise(
            latest["eps_actual"], latest["eps_estimate"]
        )

    if abs(surprise_pct) < params["min_eps_surprise_pct"]:
        return None

    earnings_day_return = yfinance_source.get_earnings_day_return(
        ticker, report_date.isoformat()
    )
    if earnings_day_return is None:
        return None

    # Surprise and gap must agree in direction
    if surprise_pct > 0 and earnings_day_return < params["min_earnings_gap_pct"]:
        return None
    if surprise_pct < 0 and earnings_day_return > -params["min_earnings_gap_pct"]:
        return None

    revision_trend = _estimate_revision_trend(ticker)
    historical_drift = _estimate_historical_drift(ticker)
    composite = _compute_composite_score(
        surprise_pct=surprise_pct,
        gap_pct=earnings_day_return,
        revision_trend=revision_trend,
        historical_drift=historical_drift,
    )

    return EarningsSignal(
        ticker=ticker,
        report_date=report_date,
        eps_actual=latest["eps_actual"],
        eps_estimate=latest["eps_estimate"],
        surprise_pct=round(surprise_pct, 2),
        earnings_day_gap_pct=round(earnings_day_return, 2),
        revision_trend_pre=round(revision_trend, 3),
        guidance_raised=False,
        historical_drift_avg=round(historical_drift, 3),
        composite_score=round(composite, 2),
    )


def scan_universe_for_pead(
    tickers: list[str],
    vol: VolContext,
    lookback_days: int = 5,
) -> list[EarningsSignal]:
    """Scan a list of tickers for recent PEAD opportunities."""
    signals: list[EarningsSignal] = []
    for ticker in tickers:
        try:
            sig = detect_pead(ticker, vol, lookback_days)
            if sig is not None:
                signals.append(sig)
        except Exception:
            logger.exception("PEAD scan failed for %s", ticker)
    return signals


# ── Private scoring helpers ──


def _estimate_revision_trend(ticker: str) -> float:
    """Estimate pre-earnings revision trend from recommendation data.

    Positive = analysts were raising estimates before earnings.
    Returns a value roughly in [-1, 1].
    """
    recs = yfinance_source.get_recommendation_trends(ticker)
    if not recs or len(recs) < 2:
        return 0.0

    recent = recs[0]
    older = recs[1] if len(recs) > 1 else recent

    recent_bullish = recent.get("strong_buy", 0) + recent.get("buy", 0)
    recent_bearish = recent.get("sell", 0) + recent.get("strong_sell", 0)
    recent_total = recent_bullish + recent_bearish + recent.get("hold", 0)

    older_bullish = older.get("strong_buy", 0) + older.get("buy", 0)
    older_bearish = older.get("sell", 0) + older.get("strong_sell", 0)
    older_total = older_bullish + older_bearish + older.get("hold", 0)

    if recent_total == 0 or older_total == 0:
        return 0.0

    recent_ratio = (recent_bullish - recent_bearish) / recent_total
    older_ratio = (older_bullish - older_bearish) / older_total

    return recent_ratio - older_ratio


def _estimate_historical_drift(ticker: str) -> float:
    """Average post-earnings drift over recent quarters.

    Looks at up to 8 past earnings and measures 20-day drift after each.
    """
    earnings = get_recent_earnings(ticker)
    if len(earnings) < 2:
        return 0.0

    drifts: list[float] = []
    for e in earnings[1:9]:
        report_date = e["date"]
        if isinstance(report_date, str):
            report_date = date.fromisoformat(report_date)

        start = (report_date + timedelta(days=1)).isoformat()
        end = (report_date + timedelta(days=35)).isoformat()

        try:
            df = yfinance_source.get_daily_ohlcv(ticker, start=start, end=end)
            if df.empty or len(df) < 5:
                continue
            entry_price = float(df["Open"].iloc[0])
            exit_price = float(df["Close"].iloc[min(19, len(df) - 1)])
            drift = (exit_price - entry_price) / entry_price
            surprise = e.get("surprise_pct", 0)
            if surprise > 0:
                drifts.append(drift)
            elif surprise < 0:
                drifts.append(-drift)
        except Exception:
            continue

    return float(sum(drifts) / len(drifts)) if drifts else 0.0


def _compute_composite_score(
    surprise_pct: float,
    gap_pct: float,
    revision_trend: float,
    historical_drift: float,
) -> float:
    """Weighted composite score for PEAD quality (0-100 scale).

    Weights:
      40% — surprise magnitude (capped at 20% = full marks)
      25% — earnings day gap (capped at 10% = full marks)
      20% — revision trend pre-earnings
      15% — historical drift tendency
    """
    surprise_score = min(1.0, abs(surprise_pct) / 20.0) * 40
    gap_score = min(1.0, abs(gap_pct) / 10.0) * 25
    revision_score = (0.5 + min(0.5, max(-0.5, revision_trend))) * 20
    drift_score = (0.5 + min(0.5, max(-0.5, historical_drift * 5))) * 15

    return min(100.0, surprise_score + gap_score + revision_score + drift_score)
