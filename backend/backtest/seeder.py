"""Backtest phantom trade seeder — pre-populate phantom_trades with
historically resolved signals so win rate and strategy health metrics
are meaningful from day one.

Runs backtestable strategies (cross_asset_momentum, catalyst PEAD) on
weekly historical checkpoints, resolves each signal using subsequent
price data, and inserts pre-resolved phantom trades into Supabase.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.data.cross_asset import CROSS_ASSET_TICKERS, SECTOR_ETFS
from backend.models.database import get_supabase
from backend.models.schemas import TradeSignal
from backend.regime.detector import detect_regime

logger = logging.getLogger(__name__)

LOOKBACK_WEEKS = 12
OHLCV_DOWNLOAD_PERIOD = "9mo"
MAX_RESOLVE_DAYS = 90


def _get_checkpoints(weeks: int = LOOKBACK_WEEKS) -> list[date]:
    """Generate weekly Monday checkpoints going back N weeks."""
    today = date.today()
    current = today - timedelta(days=today.weekday())
    checkpoints: list[date] = []
    for i in range(1, weeks + 1):
        cp = current - timedelta(weeks=i)
        checkpoints.append(cp)
    return sorted(checkpoints)


def _batch_download(tickers: list[str], period: str = OHLCV_DOWNLOAD_PERIOD) -> dict[str, pd.DataFrame]:
    """Download OHLCV for many tickers in one yfinance call."""
    result: dict[str, pd.DataFrame] = {}
    if not tickers:
        return result
    try:
        raw = yf.download(tickers, period=period, group_by="ticker", threads=False, progress=False)
        if raw.empty:
            return result
        for t in tickers:
            try:
                df = raw[t].dropna(how="all") if len(tickers) > 1 else raw
                if not df.empty:
                    result[t] = df
            except (KeyError, Exception):
                pass
    except Exception as e:
        logger.warning("Batch OHLCV download failed: %s", e)
    return result


def _slice_to_date(df: pd.DataFrame, end_date: date) -> pd.DataFrame:
    """Return rows up to and including end_date (no look-ahead)."""
    end_ts = pd.Timestamp(end_date)
    return df[df.index <= end_ts]


def _resolve_signal(
    signal: TradeSignal,
    ohlcv: pd.DataFrame,
    signal_date: date,
) -> dict | None:
    """Resolve a signal using subsequent daily closes.

    Returns dict with exit_date, exit_price, pnl_pct, outcome — or None
    if there isn't enough subsequent data.
    """
    start_ts = pd.Timestamp(signal_date)
    future = ohlcv[ohlcv.index > start_ts]
    if future.empty:
        return None

    max_days = signal.max_hold_days or 30
    future = future.head(max_days)

    entry = signal.entry_price
    stop = signal.stop_loss
    target = signal.target
    direction = signal.direction

    for idx, row in future.iterrows():
        close = float(row["Close"])
        row_date = idx.date() if hasattr(idx, "date") else idx

        if direction == "long":
            if close <= stop:
                pnl = (close - entry) / entry * 100
                return _make_result(row_date, close, pnl)
            if close >= target:
                pnl = (close - entry) / entry * 100
                return _make_result(row_date, close, pnl)
        else:
            if close >= stop:
                pnl = (entry - close) / entry * 100
                return _make_result(row_date, close, pnl)
            if close <= target:
                pnl = (entry - close) / entry * 100
                return _make_result(row_date, close, pnl)

    last_row = future.iloc[-1]
    last_close = float(last_row["Close"])
    last_date = future.index[-1].date() if hasattr(future.index[-1], "date") else future.index[-1]
    mult = 1.0 if direction == "long" else -1.0
    pnl = mult * (last_close - entry) / entry * 100
    return _make_result(last_date, last_close, pnl)


def _make_result(exit_date: date, exit_price: float, pnl_pct: float) -> dict:
    return {
        "exit_date": exit_date,
        "exit_price": round(exit_price, 2),
        "pnl_pct": round(pnl_pct, 4),
        "outcome": "would_have_won" if pnl_pct > 0 else "would_have_lost",
    }


def _clear_backtest_phantoms() -> int:
    """Delete previously seeded backtest phantoms. Returns count deleted."""
    sb = get_supabase()
    result = sb.table("phantom_trades").select("id").like("pass_reason", "backtest%").execute()
    count = len(result.data)
    if count > 0:
        sb.table("phantom_trades").delete().like("pass_reason", "backtest%").execute()
    logger.info("Cleared %d previous backtest phantoms", count)
    return count


def _insert_phantom(
    signal: TradeSignal,
    signal_date: date,
    resolution: dict,
    regime: str,
    vix: float | None = None,
) -> None:
    """Insert a single resolved phantom trade."""
    sb = get_supabase()
    row = {
        "ticker": signal.ticker,
        "direction": signal.direction,
        "strategy": signal.strategy.value,
        "signal_score": signal.signal_score,
        "signal_date": str(signal_date),
        "entry_price_suggested": round(signal.entry_price, 2),
        "stop_suggested": round(signal.stop_loss, 2),
        "target_suggested": round(signal.target, 2),
        "pass_reason": "backtest-seeded",
        "regime": regime,
        "vix_at_signal": vix,
        "conviction": signal.conviction,
        "phantom_exit_date": str(resolution["exit_date"]),
        "phantom_exit_price": resolution["exit_price"],
        "phantom_pnl_pct": resolution["pnl_pct"],
        "phantom_outcome": resolution["outcome"],
    }
    sb.table("phantom_trades").insert(row).execute()


def _run_cross_asset(vol: VolContext, regime: str) -> list[TradeSignal]:
    """Run cross-asset momentum strategy."""
    try:
        from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy

        return CrossAssetMomentumStrategy().generate_signals(vol, regime=regime)
    except Exception as e:
        logger.warning("Backtest cross_asset failed: %s", e)
        return []


def _run_catalyst(vol: VolContext, regime: str, tickers: list[str]) -> list[TradeSignal]:
    """Run catalyst strategy with a small ticker sample to avoid rate limits."""
    try:
        from backend.strategies.catalyst_event import CatalystEventStrategy

        return CatalystEventStrategy().generate_signals(
            vol,
            tickers=tickers[:15],
            regime=regime,
        )
    except Exception as e:
        logger.warning("Backtest catalyst failed: %s", e)
        return []


def run_backtest_seed(
    progress_cb: Callable | None = None,
) -> dict:
    """Main entry point. Downloads data, runs strategies on historical
    checkpoints, resolves signals, and inserts phantom trades.

    progress_cb: optional callback(done, total, step_label) for progress.
    Returns summary dict.
    """
    checkpoints = _get_checkpoints(LOOKBACK_WEEKS)
    total_steps = len(checkpoints)
    logger.info("Backtest seeder: %d weekly checkpoints from %s to %s", total_steps, checkpoints[0], checkpoints[-1])

    if progress_cb:
        progress_cb(0, total_steps + 2, "Clearing old backtest data...")

    _clear_backtest_phantoms()

    if progress_cb:
        progress_cb(1, total_steps + 2, "Downloading historical OHLCV...")

    from backend.data.universe import get_all_tickers

    sp500 = get_all_tickers()
    cross_tickers = list(CROSS_ASSET_TICKERS.values()) + list(SECTOR_ETFS.values())
    all_tickers = list(set(sp500 + cross_tickers + ["SPY", "^VIX"]))

    ohlcv_cache = _batch_download(all_tickers, period=OHLCV_DOWNLOAD_PERIOD)
    logger.info("Backtest: downloaded OHLCV for %d/%d tickers", len(ohlcv_cache), len(all_tickers))

    spy_full = ohlcv_cache.get("SPY", pd.DataFrame())
    vix_full = ohlcv_cache.get("^VIX", pd.DataFrame())
    if spy_full.empty or vix_full.empty:
        logger.error("Backtest: SPY or VIX data unavailable, aborting")
        return {"error": "SPY/VIX data unavailable", "signals": 0, "inserted": 0}

    total_signals = 0
    total_inserted = 0
    strategy_stats: dict[str, dict] = {}

    for i, cp_date in enumerate(checkpoints):
        step = i + 2
        label = f"Checkpoint {i + 1}/{total_steps}: {cp_date}"
        if progress_cb:
            progress_cb(step, total_steps + 2, label)
        logger.info("Backtest checkpoint: %s", cp_date)

        spy_slice = _slice_to_date(spy_full, cp_date)
        vix_slice = _slice_to_date(vix_full, cp_date)
        if len(spy_slice) < 30 or len(vix_slice) < 10:
            logger.info("Skipping %s: insufficient SPY/VIX data", cp_date)
            continue

        try:
            regime_result = detect_regime(vix_slice, spy_slice)
            regime = regime_result.get("regime", "unknown")
            if hasattr(regime, "value"):
                regime = regime.value
            vol = compute_vol_context(spy_slice, vix_slice)
        except Exception as e:
            logger.warning("Skipping %s: regime/vol computation failed: %s", cp_date, e)
            continue

        vix_current = vol.vix_current

        signals: list[TradeSignal] = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            ca_future = pool.submit(_run_cross_asset, vol, regime)
            cat_future = pool.submit(_run_catalyst, vol, regime, sp500)

            for name, future in [("cross_asset", ca_future), ("catalyst", cat_future)]:
                try:
                    sigs = future.result(timeout=300)
                    signals.extend(sigs)
                    logger.info("  %s: %d signals on %s", name, len(sigs), cp_date)
                except TimeoutError:
                    logger.warning("  %s timed out on %s", name, cp_date)
                except Exception as e:
                    logger.warning("  %s error on %s: %s", name, cp_date, e)

        total_signals += len(signals)

        for sig in signals:
            ticker_ohlcv = ohlcv_cache.get(sig.ticker)
            if ticker_ohlcv is None or ticker_ohlcv.empty:
                continue

            resolution = _resolve_signal(sig, ticker_ohlcv, cp_date)
            if resolution is None:
                continue

            try:
                _insert_phantom(sig, cp_date, resolution, regime, vix_current)
                total_inserted += 1

                strat_key = sig.strategy.value
                if strat_key not in strategy_stats:
                    strategy_stats[strat_key] = {"total": 0, "won": 0, "lost": 0}
                strategy_stats[strat_key]["total"] += 1
                if resolution["outcome"] == "would_have_won":
                    strategy_stats[strat_key]["won"] += 1
                else:
                    strategy_stats[strat_key]["lost"] += 1
            except Exception as e:
                logger.debug("Failed to insert phantom for %s: %s", sig.ticker, e)

    if progress_cb:
        progress_cb(total_steps + 2, total_steps + 2, "Done!")

    for strat, stats in strategy_stats.items():
        wr = stats["won"] / stats["total"] * 100 if stats["total"] > 0 else 0
        logger.info("Backtest %s: %d signals, %.1f%% win rate", strat, stats["total"], wr)

    summary = {
        "checkpoints": len(checkpoints),
        "total_signals": total_signals,
        "inserted": total_inserted,
        "strategy_stats": strategy_stats,
    }
    logger.info("Backtest seeder complete: %d signals, %d inserted", total_signals, total_inserted)
    return summary
