"""Analyst revision breadth and acceleration signals.

Implements Sub-Strategy B from the spec (Section 5):
  - Revision breadth: (upgrades - downgrades) / total over trailing 30 days
  - Revision acceleration: current 15-day breadth minus previous 15-day breadth
  - Composite scoring with price-moved filter (don't chase)

Data path:
  yfinance (free) → get_recommendation_trends()
  Finnhub (paid)  → get_analyst_revisions() (when API key set)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from backend.adaptive.thresholds import get_catalyst_params
from backend.adaptive.vol_context import VolContext
from backend.config import settings
from backend.data.fetcher import data_fetcher
from backend.data.sources.yfinance_src import yfinance_source
from backend.models.schemas import RevisionSignal

logger = logging.getLogger(__name__)


def get_revision_data(ticker: str) -> list[dict]:
    """Fetch analyst revision data, preferring paid source."""
    if settings.finnhub_api_key:
        finnhub_data = data_fetcher.get_analyst_revisions(ticker)
        if finnhub_data:
            return [finnhub_data] if isinstance(finnhub_data, dict) else finnhub_data

    return yfinance_source.get_recommendation_trends(ticker)


def compute_revision_breadth(
    revisions: list[dict],
    window_days: int = 30,
) -> float:
    """Compute (upgrades - downgrades) / total over trailing window.

    Returns a value in [-1, 1].  +1 = all upgrades, -1 = all downgrades.
    """
    if not revisions:
        return 0.0

    cutoff = date.today() - timedelta(days=window_days)
    in_window = [r for r in revisions if _to_date(r.get("date")) >= cutoff]

    if not in_window:
        in_window = revisions[:2]

    total_bullish = 0
    total_bearish = 0
    total_all = 0
    for r in in_window:
        bullish = r.get("strong_buy", 0) + r.get("buy", 0)
        bearish = r.get("sell", 0) + r.get("strong_sell", 0)
        hold = r.get("hold", 0)
        total_bullish += bullish
        total_bearish += bearish
        total_all += bullish + bearish + hold

    if total_all == 0:
        return 0.0

    return (total_bullish - total_bearish) / total_all


def compute_revision_acceleration(
    revisions: list[dict],
) -> float:
    """Current 15-day breadth minus previous 15-day breadth.

    Positive acceleration = revisions are trending more bullish.
    """
    if len(revisions) < 2:
        return 0.0

    today = date.today()
    cutoff_recent = today - timedelta(days=15)
    cutoff_older = today - timedelta(days=30)

    recent = [r for r in revisions if _to_date(r.get("date")) >= cutoff_recent]
    older = [r for r in revisions if cutoff_older <= _to_date(r.get("date")) < cutoff_recent]

    if not recent and not older:
        if len(revisions) >= 2:
            recent = revisions[:1]
            older = revisions[1:2]
        else:
            return 0.0

    recent_breadth = _breadth_from_records(recent) if recent else 0.0
    older_breadth = _breadth_from_records(older) if older else 0.0

    return recent_breadth - older_breadth


def compute_price_moved_pct(ticker: str, days: int = 30) -> float:
    """How much the stock has already moved over the revision window.

    Used to avoid chasing — if the stock already moved >5%, the
    revision may be priced in.
    """
    try:
        df = data_fetcher.get_daily_ohlcv(ticker, period="3mo")
        if df.empty or len(df) < days:
            return 0.0

        recent_close = float(df["Close"].iloc[-1])
        past_close = float(df["Close"].iloc[-min(days, len(df))])
        if past_close <= 0:
            return 0.0
        return abs(recent_close - past_close) / past_close * 100
    except Exception:
        logger.exception("Failed to compute price move for %s", ticker)
        return 0.0


def detect_revision_momentum(
    ticker: str,
    vol: VolContext,
) -> RevisionSignal | None:
    """Check if ticker qualifies as a revision momentum trade.

    Criteria (adaptive via VolContext):
      1. breadth > min_breadth
      2. acceleration > min_acceleration
      3. price hasn't already moved > max_price_moved_pct (spec: 5%)
    """
    params = get_catalyst_params(vol)
    revisions = get_revision_data(ticker)
    if not revisions:
        return None

    breadth = compute_revision_breadth(revisions, window_days=30)
    acceleration = compute_revision_acceleration(revisions)
    price_moved = compute_price_moved_pct(ticker, days=30)

    if breadth < params["min_breadth"]:
        return None
    if acceleration < params["min_acceleration"]:
        return None
    if price_moved > 5.0:
        return None

    composite = _compute_composite_score(breadth, acceleration, price_moved)

    return RevisionSignal(
        ticker=ticker,
        as_of_date=date.today(),
        breadth_30d=round(breadth, 4),
        acceleration_15d=round(acceleration, 4),
        price_moved_pct=round(price_moved, 2),
        composite_score=round(composite, 2),
    )


def scan_universe_for_revisions(
    tickers: list[str],
    vol: VolContext,
) -> list[RevisionSignal]:
    """Scan a list of tickers for revision momentum opportunities."""
    signals: list[RevisionSignal] = []
    for ticker in tickers:
        try:
            sig = detect_revision_momentum(ticker, vol)
            if sig is not None:
                signals.append(sig)
        except Exception:
            logger.exception("Revision scan failed for %s", ticker)
    return signals


# ── Private helpers ──


def _to_date(d) -> date:
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        return date.fromisoformat(d)
    return date.min


def _breadth_from_records(records: list[dict]) -> float:
    total_b = 0
    total_br = 0
    total_all = 0
    for r in records:
        b = r.get("strong_buy", 0) + r.get("buy", 0)
        br = r.get("sell", 0) + r.get("strong_sell", 0)
        h = r.get("hold", 0)
        total_b += b
        total_br += br
        total_all += b + br + h
    if total_all == 0:
        return 0.0
    return (total_b - total_br) / total_all


def _compute_composite_score(
    breadth: float,
    acceleration: float,
    price_moved_pct: float,
) -> float:
    """Weighted composite score for revision momentum (0-100 scale).

    Weights:
      45% — breadth (capped at 0.8 = full marks)
      35% — acceleration (capped at 0.3 = full marks)
      20% — inverse price move (less move = better entry)
    """
    breadth_score = min(1.0, breadth / 0.8) * 45
    accel_score = min(1.0, acceleration / 0.3) * 35
    move_score = max(0.0, 1.0 - price_moved_pct / 5.0) * 20

    return min(100.0, breadth_score + accel_score + move_score)
