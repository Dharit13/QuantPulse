"""Cross-Asset Signal Computation — z-score engine for macro indicators.

Tracks yields, VIX, commodities, credit spreads, and dollar strength.
For each indicator, computes a rolling z-score vs its trailing 60-day
distribution.  When |z| > threshold (adaptive), the corresponding
sector rotation signal fires.

Reference: QUANTPULSE_FINAL_SPEC.md §6 — Cross-Asset Regime Momentum
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from backend.adaptive.vol_context import VolContext
from backend.data.cross_asset import SECTOR_ETFS, CrossAssetData, cross_asset_data

logger = logging.getLogger(__name__)

ZSCORE_LOOKBACK = 60


class MacroSignalType(str, Enum):
    YIELD_10Y = "yield_10y"
    YIELD_CURVE = "yield_curve"
    VIX_TERM = "vix_term"
    OIL = "oil"
    GOLD = "gold"
    COPPER_GOLD = "copper_gold"
    DOLLAR = "dollar"
    CREDIT_SPREAD = "credit_spread"


@dataclass
class CrossAssetSignal:
    """A single cross-asset macro signal with sector implications."""

    signal_type: MacroSignalType
    z_score: float
    direction: str  # "up" or "down"
    raw_value: float
    trailing_mean: float
    trailing_std: float
    long_sectors: list[str] = field(default_factory=list)
    short_sectors: list[str] = field(default_factory=list)
    long_etfs: list[str] = field(default_factory=list)
    short_etfs: list[str] = field(default_factory=list)
    description: str = ""


# ── Empirically validated signal → sector mapping (Spec §6) ──

SIGNAL_SECTOR_MAP: dict[str, dict[str, dict[str, list[str]]]] = {
    "yield_10y": {
        "up": {
            "long_sectors": ["financials"],
            "short_sectors": ["utilities", "real_estate"],
        },
        "down": {
            "long_sectors": ["utilities", "real_estate"],
            "short_sectors": ["financials"],
        },
    },
    "yield_curve": {
        "up": {  # steepening
            "long_sectors": ["financials", "industrials", "materials"],
            "short_sectors": ["utilities", "consumer_staples"],
        },
        "down": {  # inverting
            "long_sectors": ["utilities", "consumer_staples", "healthcare"],
            "short_sectors": ["financials", "consumer_discretionary"],
        },
    },
    "oil": {
        "up": {
            "long_sectors": ["energy"],
            "short_sectors": ["consumer_discretionary", "industrials"],
        },
        "down": {
            "long_sectors": ["consumer_discretionary", "industrials"],
            "short_sectors": ["energy"],
        },
    },
    "gold": {
        "up": {
            "long_sectors": ["materials"],
            "short_sectors": ["financials"],
        },
        "down": {
            "long_sectors": ["financials"],
            "short_sectors": ["materials"],
        },
    },
    "copper_gold": {
        "up": {  # risk-on
            "long_sectors": ["industrials", "materials", "consumer_discretionary"],
            "short_sectors": ["utilities", "consumer_staples"],
        },
        "down": {  # risk-off
            "long_sectors": ["utilities", "consumer_staples", "healthcare"],
            "short_sectors": ["industrials", "materials"],
        },
    },
    "dollar": {
        "up": {  # DXY strengthening
            "long_sectors": ["financials"],
            "short_sectors": ["materials", "technology"],
        },
        "down": {  # DXY weakening
            "long_sectors": ["materials", "technology"],
            "short_sectors": ["financials"],
        },
    },
    "credit_spread": {
        "up": {  # spreads tightening (HYG/LQD rising = risk-on)
            "long_sectors": ["financials", "consumer_discretionary"],
            "short_sectors": ["utilities", "consumer_staples"],
        },
        "down": {  # spreads widening (risk-off)
            "long_sectors": ["utilities", "consumer_staples", "healthcare"],
            "short_sectors": ["financials", "consumer_discretionary"],
        },
    },
    "vix_term": {
        "up": {  # contango deepening (calm)
            "long_sectors": ["technology", "consumer_discretionary"],
            "short_sectors": [],
        },
        "down": {  # inversion (fear)
            "long_sectors": ["utilities", "consumer_staples"],
            "short_sectors": ["technology", "consumer_discretionary"],
        },
    },
}


def _compute_zscore_series(
    series: pd.Series,
    lookback: int = ZSCORE_LOOKBACK,
) -> pd.Series:
    """Compute rolling z-score of a series vs its trailing distribution."""
    if len(series) < lookback:
        return pd.Series(dtype=float)

    rolling_mean = series.rolling(lookback).mean()
    rolling_std = series.rolling(lookback).std()
    rolling_std = rolling_std.replace(0, np.nan)

    return ((series - rolling_mean) / rolling_std).dropna()


def _compute_rate_of_change(
    series: pd.Series,
    window: int = 5,
) -> pd.Series:
    """Percentage change over a window — captures 'fast' moves."""
    if len(series) < window + 1:
        return pd.Series(dtype=float)
    return series.pct_change(window).dropna()


def _sectors_to_etfs(sectors: list[str]) -> list[str]:
    return [SECTOR_ETFS[s] for s in sectors if s in SECTOR_ETFS]


def compute_yield_signal(
    data: dict[str, pd.DataFrame],
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """10Y yield rate-of-change z-score."""
    if "10y_yield" not in data or data["10y_yield"].empty:
        return None

    close = data["10y_yield"]["Close"].dropna()
    roc = _compute_rate_of_change(close, window=5)
    z = _compute_zscore_series(roc, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    direction = "up" if current_z > 0 else "down"
    mapping = SIGNAL_SECTOR_MAP["yield_10y"][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.YIELD_10Y,
        z_score=current_z,
        direction=direction,
        raw_value=float(roc.iloc[-1]),
        trailing_mean=float(roc.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(roc.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"10Y yield 5d RoC z={current_z:+.2f}",
    )


def compute_yield_curve_signal(
    data: dict[str, pd.DataFrame],
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """Yield curve slope (10Y − 13W) z-score."""
    ten_y = data.get("10y_yield")
    short_y = data.get("13w_yield")
    if ten_y is None or short_y is None or ten_y.empty or short_y.empty:
        return None

    common = ten_y["Close"].index.intersection(short_y["Close"].index)
    if len(common) < lookback + 5:
        return None

    slope = (ten_y["Close"].loc[common] - short_y["Close"].loc[common]).dropna()
    roc = _compute_rate_of_change(slope, window=10)
    z = _compute_zscore_series(roc, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    direction = "up" if current_z > 0 else "down"
    mapping = SIGNAL_SECTOR_MAP["yield_curve"][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.YIELD_CURVE,
        z_score=current_z,
        direction=direction,
        raw_value=float(slope.iloc[-1]),
        trailing_mean=float(slope.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(slope.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"Yield curve slope RoC z={current_z:+.2f} (level={float(slope.iloc[-1]):.2f})",
    )


def compute_vix_term_signal(
    data: dict[str, pd.DataFrame],
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """VIX level z-score (proxy for term structure without VIX futures)."""
    if "vix" not in data or data["vix"].empty:
        return None

    vix_close = data["vix"]["Close"].dropna()
    z = _compute_zscore_series(vix_close, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    # Invert: high VIX z-score = fear = "down" direction (backwardation proxy)
    direction = "down" if current_z > 0 else "up"
    mapping = SIGNAL_SECTOR_MAP["vix_term"][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.VIX_TERM,
        z_score=current_z,
        direction=direction,
        raw_value=float(vix_close.iloc[-1]),
        trailing_mean=float(vix_close.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(vix_close.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"VIX z={current_z:+.2f} (level={float(vix_close.iloc[-1]):.1f})",
    )


def compute_commodity_signal(
    data: dict[str, pd.DataFrame],
    commodity: str,
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """Z-score of commodity rate-of-change (oil or gold)."""
    key = commodity
    if key not in data or data[key].empty:
        return None

    close = data[key]["Close"].dropna()
    roc = _compute_rate_of_change(close, window=5)
    z = _compute_zscore_series(roc, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    direction = "up" if current_z > 0 else "down"
    mapping = SIGNAL_SECTOR_MAP[commodity][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.OIL if commodity == "oil" else MacroSignalType.GOLD,
        z_score=current_z,
        direction=direction,
        raw_value=float(roc.iloc[-1]),
        trailing_mean=float(roc.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(roc.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"{commodity.capitalize()} 5d RoC z={current_z:+.2f}",
    )


def compute_copper_gold_signal(
    data: dict[str, pd.DataFrame],
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """Copper/Gold ratio z-score — risk appetite barometer."""
    copper_df = data.get("copper")
    gold_df = data.get("gold")
    if copper_df is None or gold_df is None or copper_df.empty or gold_df.empty:
        return None

    common = copper_df["Close"].index.intersection(gold_df["Close"].index)
    if len(common) < lookback + 5:
        return None

    ratio = (copper_df["Close"].loc[common] / gold_df["Close"].loc[common]).dropna()
    roc = _compute_rate_of_change(ratio, window=10)
    z = _compute_zscore_series(roc, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    direction = "up" if current_z > 0 else "down"
    mapping = SIGNAL_SECTOR_MAP["copper_gold"][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.COPPER_GOLD,
        z_score=current_z,
        direction=direction,
        raw_value=float(ratio.iloc[-1]),
        trailing_mean=float(ratio.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(ratio.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"Copper/Gold ratio RoC z={current_z:+.2f}",
    )


def compute_dollar_signal(
    data: dict[str, pd.DataFrame],
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """DXY rate-of-change z-score."""
    if "dxy" not in data or data["dxy"].empty:
        return None

    close = data["dxy"]["Close"].dropna()
    roc = _compute_rate_of_change(close, window=5)
    z = _compute_zscore_series(roc, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    direction = "up" if current_z > 0 else "down"
    mapping = SIGNAL_SECTOR_MAP["dollar"][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.DOLLAR,
        z_score=current_z,
        direction=direction,
        raw_value=float(roc.iloc[-1]),
        trailing_mean=float(roc.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(roc.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"DXY 5d RoC z={current_z:+.2f}",
    )


def compute_credit_signal(
    data: dict[str, pd.DataFrame],
    lookback: int = ZSCORE_LOOKBACK,
) -> CrossAssetSignal | None:
    """HYG/LQD ratio z-score — credit spread proxy."""
    hyg = data.get("hy_bond")
    lqd = data.get("ig_bond")
    if hyg is None or lqd is None or hyg.empty or lqd.empty:
        return None

    common = hyg["Close"].index.intersection(lqd["Close"].index)
    if len(common) < lookback + 5:
        return None

    ratio = (hyg["Close"].loc[common] / lqd["Close"].loc[common]).dropna()
    roc = _compute_rate_of_change(ratio, window=5)
    z = _compute_zscore_series(roc, lookback)
    if z.empty:
        return None

    current_z = float(z.iloc[-1])
    direction = "up" if current_z > 0 else "down"
    mapping = SIGNAL_SECTOR_MAP["credit_spread"][direction]

    return CrossAssetSignal(
        signal_type=MacroSignalType.CREDIT_SPREAD,
        z_score=current_z,
        direction=direction,
        raw_value=float(ratio.iloc[-1]),
        trailing_mean=float(ratio.rolling(lookback).mean().iloc[-1]),
        trailing_std=float(ratio.rolling(lookback).std().iloc[-1]),
        long_sectors=mapping["long_sectors"],
        short_sectors=mapping["short_sectors"],
        long_etfs=_sectors_to_etfs(mapping["long_sectors"]),
        short_etfs=_sectors_to_etfs(mapping["short_sectors"]),
        description=f"Credit spread (HYG/LQD) RoC z={current_z:+.2f}",
    )


def scan_all_cross_asset_signals(
    vol: VolContext,
    z_threshold: float | None = None,
    active_signals: list[str] | str = "all",
) -> list[CrossAssetSignal]:
    """Compute all cross-asset z-scores and return those exceeding threshold.

    Args:
        vol: Current volatility context (used to adaptive threshold).
        z_threshold: Override z-score threshold. If None, uses adaptive
            threshold from get_cross_asset_params().
        active_signals: Which signal types to compute. "all" for everything,
            or a list of MacroSignalType values to restrict.

    Returns:
        List of CrossAssetSignal where |z| exceeds the threshold.
    """
    from backend.adaptive.thresholds import get_cross_asset_params

    params = get_cross_asset_params(vol)
    threshold = z_threshold if z_threshold is not None else params["signal_z_threshold"]
    allowed = params["active_signals"]

    data = cross_asset_data.fetch_all(period="1y")
    if not data:
        logger.warning("No cross-asset data available")
        return []

    all_signal_fns: list[tuple[str, callable]] = [
        ("yield_10y", lambda: compute_yield_signal(data)),
        ("yield_curve", lambda: compute_yield_curve_signal(data)),
        ("vix_term", lambda: compute_vix_term_signal(data)),
        ("oil", lambda: compute_commodity_signal(data, "oil")),
        ("gold", lambda: compute_commodity_signal(data, "gold")),
        ("copper_gold", lambda: compute_copper_gold_signal(data)),
        ("dollar", lambda: compute_dollar_signal(data)),
        ("credit_spread", lambda: compute_credit_signal(data)),
    ]

    fired: list[CrossAssetSignal] = []

    for sig_name, compute_fn in all_signal_fns:
        if allowed != "all" and sig_name not in allowed:
            continue
        if isinstance(active_signals, list) and sig_name not in active_signals:
            continue

        try:
            signal = compute_fn()
            if signal is None:
                continue
            if abs(signal.z_score) >= threshold:
                fired.append(signal)
                logger.info(
                    "Cross-asset signal FIRED: %s z=%.2f (%s)",
                    sig_name,
                    signal.z_score,
                    signal.description,
                )
        except Exception:
            logger.exception("Failed to compute cross-asset signal: %s", sig_name)

    logger.info(
        "Cross-asset scan complete: %d/%d signals fired (threshold=%.2f)",
        len(fired),
        len(all_signal_fns),
        threshold,
    )
    return fired


def aggregate_sector_scores(
    signals: list[CrossAssetSignal],
) -> dict[str, float]:
    """Aggregate z-score weighted sector scores across all fired signals.

    Positive score = net long conviction, negative = net short conviction.
    Returns a dict mapping sector name → aggregate weighted score.
    """
    sector_scores: dict[str, float] = {s: 0.0 for s in SECTOR_ETFS}

    for sig in signals:
        weight = abs(sig.z_score)
        for sector in sig.long_sectors:
            if sector in sector_scores:
                sector_scores[sector] += weight
        for sector in sig.short_sectors:
            if sector in sector_scores:
                sector_scores[sector] -= weight

    return sector_scores
