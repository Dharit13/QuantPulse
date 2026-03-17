"""Microstructure & Flow Signals — GEX, sweeps, dark pool levels.

All sub-strategies require paid data (Unusual Whales + Polygon).
Gated behind ``enable_smart_money`` and ``enable_polygon`` feature flags.
When paid data is unavailable the functions return empty results so the
strategy degrades gracefully.

Sub-Strategy A: GEX (Gamma Exposure) Pin Risk
Sub-Strategy B: Dark Pool Level Trading
Sub-Strategy C: Unusual Options Volume / Sweep Detection

Reference: QUANTPULSE_FINAL_SPEC.md §7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.adaptive.vol_context import VolContext
from backend.config import settings
from backend.data.fetcher import data_fetcher

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────


@dataclass
class GEXLevel:
    """Net gamma exposure at a single strike price."""

    strike: float
    net_gex: float  # positive = pinning, negative = acceleration
    call_oi: int = 0
    put_oi: int = 0
    total_oi: int = 0
    notional: float = 0.0

    @property
    def is_pinning(self) -> bool:
        return self.net_gex > 0

    @property
    def is_repelling(self) -> bool:
        return self.net_gex < 0


@dataclass
class GEXProfile:
    """Full gamma exposure profile for a ticker."""

    ticker: str
    spot_price: float
    levels: list[GEXLevel] = field(default_factory=list)
    net_gex_total: float = 0.0
    flip_price: float | None = None  # price where GEX flips sign
    nearest_pin: float | None = None
    nearest_magnet: float | None = None

    @property
    def is_positive_gex_environment(self) -> bool:
        return self.net_gex_total > 0

    @property
    def regime(self) -> str:
        if self.net_gex_total > 0:
            return "pinned"  # MM dampens moves
        return "accelerating"  # MM amplifies moves


@dataclass
class DarkPoolLevel:
    """Clustered dark pool prints at a price level."""

    price_level: float
    total_notional: float
    print_count: int
    avg_print_size: float
    side: str  # "buy", "sell", or "mixed"
    significance: float = 0.0  # 0-1 score based on notional / ADV


@dataclass
class DarkPoolProfile:
    """Dark pool activity summary for a ticker."""

    ticker: str
    spot_price: float
    levels: list[DarkPoolLevel] = field(default_factory=list)
    total_dark_notional: float = 0.0
    nearest_support: float | None = None
    nearest_resistance: float | None = None


@dataclass
class SweepSignal:
    """Detected options sweep — institutional directional bet."""

    ticker: str
    direction: str  # "bullish" or "bearish"
    premium: float  # total premium of sweep
    contract_type: str  # "call" or "put"
    strike: float
    expiry_days: int
    volume: int
    avg_volume_20d: int = 0
    volume_ratio: float = 0.0  # volume / avg_volume_20d
    is_sweep: bool = True


@dataclass
class UnusualVolumeSignal:
    """Unusual options volume detection result."""

    ticker: str
    direction: str  # "bullish", "bearish", or "neutral"
    options_volume: int
    avg_volume_20d: int
    volume_ratio: float  # current / 20d avg
    call_put_ratio: float
    net_premium: float
    total_premium: float
    sweeps: list[SweepSignal] = field(default_factory=list)
    confidence: float = 0.0


# ── Sub-Strategy A: GEX Computation ──────────────────────────────────────


def compute_gex_profile(
    ticker: str,
    vol: VolContext,
) -> GEXProfile | None:
    """Compute net gamma exposure at each strike from options chain.

    Requires: enable_polygon=True (for options chain data).
    Falls back to None if data unavailable.
    """
    spot = data_fetcher.get_current_price(ticker)
    if spot is None or spot <= 0:
        return None

    chain = _fetch_options_chain(ticker)
    if not chain:
        return None

    levels: list[GEXLevel] = []
    for strike_price, data in chain.items():
        call_oi = data.get("call_oi", 0)
        put_oi = data.get("put_oi", 0)
        call_gamma = data.get("call_gamma", 0.0)
        put_gamma = data.get("put_gamma", 0.0)

        # Net GEX: calls contribute +gamma, puts contribute -gamma (MM hedge direction)
        net_gex = (call_gamma * call_oi - put_gamma * put_oi) * 100 * spot
        notional = (call_oi + put_oi) * 100 * spot

        levels.append(GEXLevel(
            strike=strike_price,
            net_gex=net_gex,
            call_oi=call_oi,
            put_oi=put_oi,
            total_oi=call_oi + put_oi,
            notional=notional,
        ))

    if not levels:
        return None

    net_total = sum(lv.net_gex for lv in levels)

    # Find the GEX flip price (where cumulative GEX changes sign)
    sorted_levels = sorted(levels, key=lambda lv: lv.strike)
    flip_price = None
    cum_gex = 0.0
    prev_sign = None
    for lv in sorted_levels:
        cum_gex += lv.net_gex
        current_sign = 1 if cum_gex >= 0 else -1
        if prev_sign is not None and current_sign != prev_sign:
            flip_price = lv.strike
        prev_sign = current_sign

    # Nearest pinning level (positive GEX closest to spot)
    pin_levels = [lv for lv in levels if lv.is_pinning]
    nearest_pin = None
    if pin_levels:
        nearest_pin = min(pin_levels, key=lambda lv: abs(lv.strike - spot)).strike

    # Nearest magnet/repel level
    repel_levels = [lv for lv in levels if lv.is_repelling and abs(lv.net_gex) > abs(net_total) * 0.1]
    nearest_magnet = None
    if repel_levels:
        nearest_magnet = min(repel_levels, key=lambda lv: abs(lv.strike - spot)).strike

    return GEXProfile(
        ticker=ticker,
        spot_price=spot,
        levels=levels,
        net_gex_total=net_total,
        flip_price=flip_price,
        nearest_pin=nearest_pin,
        nearest_magnet=nearest_magnet,
    )


# ── Sub-Strategy B: Dark Pool Levels ─────────────────────────────────────


def compute_dark_pool_levels(
    ticker: str,
    vol: VolContext,
    min_notional: float | None = None,
    cluster_pct: float = 0.005,
) -> DarkPoolProfile | None:
    """Cluster dark pool prints by price level and identify support/resistance.

    Requires: enable_smart_money=True + uw_api_key.

    Args:
        ticker: Stock symbol.
        vol: Current volatility context.
        min_notional: Minimum print notional (adaptive if None).
        cluster_pct: Price band width for clustering (0.5% default).
    """
    from backend.adaptive.thresholds import get_flow_params

    params = get_flow_params(vol)
    if min_notional is None:
        min_notional = params["min_dark_pool_notional"]

    spot = data_fetcher.get_current_price(ticker)
    if spot is None or spot <= 0:
        return None

    raw_prints = _fetch_dark_pool_prints(ticker)
    if not raw_prints:
        return None

    # Filter by minimum notional
    filtered = [p for p in raw_prints if p.get("notional", 0) >= min_notional]
    if not filtered:
        return DarkPoolProfile(ticker=ticker, spot_price=spot)

    # Cluster prints into price bands
    band_width = spot * cluster_pct
    clusters: dict[float, list[dict]] = {}
    for p in filtered:
        px = p["price"]
        band_center = round(px / band_width) * band_width
        clusters.setdefault(band_center, []).append(p)

    adv = _estimate_adv(ticker)
    levels: list[DarkPoolLevel] = []

    for band_center, prints in clusters.items():
        total_notional = sum(p.get("notional", 0) for p in prints)
        buy_notional = sum(p.get("notional", 0) for p in prints if p.get("side") == "buy")
        sell_notional = sum(p.get("notional", 0) for p in prints if p.get("side") == "sell")

        if buy_notional > sell_notional * 1.5:
            side = "buy"
        elif sell_notional > buy_notional * 1.5:
            side = "sell"
        else:
            side = "mixed"

        significance = min(1.0, total_notional / max(1.0, adv)) if adv > 0 else 0.0

        levels.append(DarkPoolLevel(
            price_level=band_center,
            total_notional=total_notional,
            print_count=len(prints),
            avg_print_size=total_notional / max(1, len(prints)),
            side=side,
            significance=significance,
        ))

    levels.sort(key=lambda lv: lv.total_notional, reverse=True)

    # Identify nearest support (buy cluster below spot) and resistance (sell cluster above)
    buy_below = [lv for lv in levels if lv.side == "buy" and lv.price_level < spot]
    sell_above = [lv for lv in levels if lv.side == "sell" and lv.price_level > spot]

    nearest_support = max(buy_below, key=lambda lv: lv.price_level).price_level if buy_below else None
    nearest_resistance = min(sell_above, key=lambda lv: lv.price_level).price_level if sell_above else None

    return DarkPoolProfile(
        ticker=ticker,
        spot_price=spot,
        levels=levels,
        total_dark_notional=sum(lv.total_notional for lv in levels),
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
    )


# ── Sub-Strategy C: Sweep Detection & Unusual Volume ─────────────────────


def detect_unusual_options_volume(
    ticker: str,
    vol: VolContext,
    volume_threshold: float = 3.0,
    premium_threshold: float | None = None,
) -> UnusualVolumeSignal | None:
    """Detect unusual options activity — sweeps, volume spikes, premium skew.

    Requires: enable_smart_money=True + uw_api_key.

    Args:
        ticker: Stock symbol.
        vol: Current volatility context.
        volume_threshold: Minimum ratio of current vol / 20d avg (default 3x).
        premium_threshold: Minimum net premium to qualify (adaptive if None).
    """
    from backend.adaptive.thresholds import get_flow_params

    params = get_flow_params(vol)
    if premium_threshold is None:
        premium_threshold = params["min_sweep_premium"]

    flow_data = data_fetcher.get_options_flow(ticker)
    if not flow_data:
        return None

    current_volume = flow_data.get("total_volume", 0)
    avg_volume = flow_data.get("avg_volume_20d", 1)
    vol_ratio = current_volume / max(1, avg_volume)

    if vol_ratio < volume_threshold:
        return None

    call_volume = flow_data.get("call_volume", 0)
    put_volume = flow_data.get("put_volume", 0)
    call_put_ratio = call_volume / max(1, put_volume)

    call_premium = flow_data.get("call_premium", 0.0)
    put_premium = flow_data.get("put_premium", 0.0)
    net_premium = call_premium - put_premium
    total_premium = call_premium + put_premium

    if abs(net_premium) < premium_threshold:
        return None

    # Determine direction from premium skew
    if net_premium > 0 and call_put_ratio > 1.5:
        direction = "bullish"
    elif net_premium < 0 and call_put_ratio < 0.67:
        direction = "bearish"
    else:
        direction = "neutral"

    # Parse individual sweeps if available
    sweeps: list[SweepSignal] = []
    for sweep in flow_data.get("sweeps", []):
        sweeps.append(SweepSignal(
            ticker=ticker,
            direction="bullish" if sweep.get("type") == "call" else "bearish",
            premium=sweep.get("premium", 0),
            contract_type=sweep.get("type", "call"),
            strike=sweep.get("strike", 0),
            expiry_days=sweep.get("dte", 0),
            volume=sweep.get("volume", 0),
            avg_volume_20d=avg_volume,
            volume_ratio=vol_ratio,
        ))

    confidence = min(1.0, (vol_ratio / 5.0 + abs(net_premium) / (premium_threshold * 5)) / 2.0)

    return UnusualVolumeSignal(
        ticker=ticker,
        direction=direction,
        options_volume=current_volume,
        avg_volume_20d=avg_volume,
        volume_ratio=vol_ratio,
        call_put_ratio=call_put_ratio,
        net_premium=net_premium,
        total_premium=total_premium,
        sweeps=sweeps,
        confidence=confidence,
    )


def scan_universe_for_flow(
    tickers: list[str],
    vol: VolContext,
    max_results: int = 20,
) -> list[UnusualVolumeSignal]:
    """Scan a universe of tickers for unusual options activity.

    Requires: enable_smart_money=True.
    Returns empty list if feature is disabled.
    """
    if not settings.enable_smart_money or not settings.uw_api_key:
        logger.info("Flow scan skipped: enable_smart_money=%s", settings.enable_smart_money)
        return []

    results: list[UnusualVolumeSignal] = []

    for ticker in tickers:
        try:
            sig = detect_unusual_options_volume(ticker, vol)
            if sig and sig.direction != "neutral":
                results.append(sig)
        except Exception:
            logger.debug("Flow scan failed for %s", ticker)

        if len(results) >= max_results:
            break

    results.sort(key=lambda s: s.confidence, reverse=True)
    logger.info("Flow scan: %d signals from %d tickers", len(results), len(tickers))
    return results


# ── Private Helpers (data fetching wrappers) ─────────────────────────────


def _fetch_options_chain(ticker: str) -> dict[float, dict]:
    """Fetch options chain with greeks.

    Returns dict mapping strike → {call_oi, put_oi, call_gamma, put_gamma}.
    Currently a stub — plug in Polygon or CBOE data when available.
    """
    if not settings.enable_polygon or not settings.polygon_api_key:
        logger.debug("Options chain unavailable for %s (Polygon disabled)", ticker)
        return {}

    try:
        from backend.data.sources.polygon_src import polygon_source
        return polygon_source.get_options_chain_greeks(ticker)
    except (ImportError, AttributeError):
        logger.debug("Polygon options chain not implemented for %s", ticker)
        return {}


def _fetch_dark_pool_prints(ticker: str) -> list[dict]:
    """Fetch dark pool prints for a ticker.

    Returns list of dicts with keys: price, notional, side, timestamp.
    Currently a stub — plug in Unusual Whales dark pool data.
    """
    if not settings.enable_smart_money or not settings.uw_api_key:
        return []

    raw = data_fetcher.get_dark_pool(ticker)
    if not raw:
        return []

    return raw.get("prints", [])


def _estimate_adv(ticker: str, period: int = 20) -> float:
    """Estimate average daily dollar volume over the last N days."""
    df = data_fetcher.get_daily_ohlcv(ticker, period="3mo")
    if df.empty or len(df) < period:
        return 0.0

    recent = df.tail(period)
    return float((recent["Close"] * recent["Volume"]).mean())
