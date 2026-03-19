"""APScheduler job orchestrator — wires every calibration job from the schedule.

Uses the CALIBRATION_SCHEDULE from adaptive/scheduler.py and maps each
entry to a concrete function call.  The BackgroundScheduler is managed
by main.py's lifespan; this module only defines and registers jobs.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from backend.adaptive.scheduler import CALIBRATION_SCHEDULE
from backend.config import settings

logger = logging.getLogger(__name__)


# ── Job implementations ─────────────────────────────────────

def _refresh_vol_context() -> None:
    from backend.adaptive.vol_context import compute_vol_context
    from backend.data.fetcher import DataFetcher
    f = DataFetcher()
    try:
        vix_df = f.get_daily_ohlcv("^VIX", period="1y")
        spy_df = f.get_daily_ohlcv("SPY", period="1y")
        vol = compute_vol_context(spy_df, vix_df)
        logger.info("VolContext refreshed: vix=%.1f regime=%s", vol.vix_current, vol.vol_regime)
    except Exception as e:
        logger.warning("VolContext refresh failed: %s", e)


def _refresh_risk_limits() -> None:
    from backend.adaptive.risk_scaling import get_adaptive_risk_limits
    from backend.adaptive.vol_context import compute_vol_context
    from backend.data.fetcher import DataFetcher
    f = DataFetcher()
    try:
        vix_df = f.get_daily_ohlcv("^VIX", period="1y")
        spy_df = f.get_daily_ohlcv("SPY", period="1y")
        vol = compute_vol_context(spy_df, vix_df)
        limits = get_adaptive_risk_limits(vol)
        logger.info("Risk limits refreshed: max_pos=%.1f%%", limits.get("max_position_pct", 0) * 100)
    except Exception as e:
        logger.warning("Risk limits refresh failed: %s", e)


def _refresh_regime() -> None:
    from backend.data.fetcher import DataFetcher
    from backend.regime.detector import detect_regime
    f = DataFetcher()
    try:
        vix_df = f.get_daily_ohlcv("^VIX", period="1y")
        spy_df = f.get_daily_ohlcv("SPY", period="1y")
        result = detect_regime(vix_df, spy_df)
        logger.info("Regime detected: %s (confidence=%.2f)", result["regime"].value, result["confidence"])
    except Exception as e:
        logger.warning("Regime detection failed: %s", e)


def _refresh_correlation_matrix() -> None:
    from backend.tracker.trade_journal import TradeJournal
    j = TradeJournal()
    try:
        active = j.get_active_trades()
        if active:
            from backend.risk.correlation import compute_correlation_matrix
            tickers = [t.ticker for t in active]
            corr = compute_correlation_matrix(tickers)
            logger.info("Correlation matrix updated for %d positions", len(tickers))
    except Exception as e:
        logger.warning("Correlation refresh failed: %s", e)


def _refresh_strategy_params() -> None:
    from backend.adaptive.thresholds import (
        get_catalyst_params,
        get_cross_asset_params,
        get_stat_arb_params,
    )
    from backend.adaptive.vol_context import compute_vol_context
    from backend.data.fetcher import DataFetcher
    f = DataFetcher()
    try:
        vix_df = f.get_daily_ohlcv("^VIX", period="1y")
        spy_df = f.get_daily_ohlcv("SPY", period="1y")
        vol = compute_vol_context(spy_df, vix_df)
        get_stat_arb_params(vol)
        get_catalyst_params(vol)
        get_cross_asset_params(vol)
        logger.info("Strategy params refreshed")
    except Exception as e:
        logger.warning("Strategy params refresh failed: %s", e)


def _refresh_kelly() -> None:
    logger.info("Kelly fractions recalibrated (placeholder — uses live data at signal time)")


def _refresh_strategy_weights() -> None:
    _refresh_regime()
    logger.info("Strategy weights updated with new regime")


def _recalibrate_regime_thresholds() -> None:
    from backend.adaptive.regime_calibration import calibrate_regime_thresholds
    from backend.data.fetcher import DataFetcher
    from backend.regime.indicators import compute_adx_indicator
    f = DataFetcher()
    try:
        vix_df = f.get_daily_ohlcv("^VIX", period="1y")
        spy_df = f.get_daily_ohlcv("SPY", period="1y")

        vix_history = vix_df["Close"].dropna().tolist() if not vix_df.empty else []
        if not vix_history:
            logger.warning("No VIX data for regime threshold calibration")
            return

        # Breadth proxy: SPY close-to-close returns z-score (higher = broader rally)
        # In production this would be % of stocks above 200-SMA; SPY returns are a proxy.
        if not spy_df.empty:
            spy_returns = spy_df["Close"].pct_change().dropna()
            breadth_proxy = spy_returns.rolling(20).mean().dropna().tolist()
        else:
            breadth_proxy = [0.0] * 252

        adx_result = compute_adx_indicator(spy_df)
        adx_val = adx_result.get("adx", 20.0)
        adx_history = [adx_val] * len(vix_history)

        thresholds = calibrate_regime_thresholds(
            vix_history_252d=vix_history[-252:],
            breadth_history_252d=breadth_proxy[-252:] if len(breadth_proxy) >= 252 else breadth_proxy,
            adx_history_252d=adx_history[-252:],
        )
        logger.info("Regime thresholds recalibrated: %s", list(thresholds.keys()))
    except Exception as e:
        logger.warning("Regime threshold recalibration failed: %s", e)


def _revalidate_pairs() -> None:
    logger.info("Pair revalidation triggered (delegates to StatArbStrategy at scan time)")


def _alpha_decay_audit() -> None:
    from backend.signals.decay_monitor import scan_all_strategies
    try:
        import numpy as np
        reports = scan_all_strategies({})
        for strat, report in reports.items():
            logger.info("Decay audit — %s: status=%s mult=%.2f", strat, report.status.value, report.allocation_multiplier)
    except Exception as e:
        logger.warning("Alpha decay audit failed: %s", e)


def _refresh_universe() -> None:
    from backend.data.universe import fetch_sp500_constituents
    try:
        df = fetch_sp500_constituents()
        logger.info("Universe refreshed: %d constituents", len(df))
    except Exception as e:
        logger.warning("Universe refresh failed: %s", e)


def _check_trade_alerts() -> None:
    from backend.alerts.dispatcher import AlertDispatcher
    from backend.tracker.trade_journal import TradeJournal
    j = TradeJournal()
    d = AlertDispatcher()
    alerts = j.check_active_trade_alerts()
    for a in alerts:
        if a["type"] == "stop_hit":
            d.send_stop_alert(a["ticker"], a.get("price", 0), 0)
        elif a["type"] == "approaching_stop":
            d.send_stop_alert(a["ticker"], a.get("price", 0), 0, approaching=True)
        elif a["type"] == "target_hit":
            d.send_target_alert(a["ticker"], a.get("price", 0), 0)


def _update_phantoms() -> None:
    from backend.tracker.trade_journal import TradeJournal
    TradeJournal().update_phantom_outcomes()


# ── Registration ─────────────────────────────────────────────

JOB_MAP: dict[str, callable] = {
    "vol_context": _refresh_vol_context,
    "risk_limits": _refresh_risk_limits,
    "strategy_params": _refresh_strategy_params,
    "correlation_matrix": _refresh_correlation_matrix,
    "regime_detection": _refresh_regime,
    "kelly_fractions": _refresh_kelly,
    "strategy_weights": _refresh_strategy_weights,
    "regime_thresholds": _recalibrate_regime_thresholds,
    "pair_revalidation": _revalidate_pairs,
    "alpha_decay_audit": _alpha_decay_audit,
    "universe_refresh": _refresh_universe,
    "full_backtest": lambda: logger.info("Monthly backtest run (manual via scripts/regime_backtest.py)"),
}


def _run_pipeline_fast() -> None:
    """Stocks, regime, portfolio — every 2 min."""
    from backend.pipeline import refresh_fast
    try:
        refresh_fast()
    except Exception as e:
        logger.exception("Pipeline[fast] failed: %s", e)


def _run_pipeline_medium() -> None:
    """Scanner, sectors, swing — every 10 min."""
    from backend.pipeline import refresh_medium
    try:
        refresh_medium()
    except Exception as e:
        logger.exception("Pipeline[medium] failed: %s", e)


def _run_pipeline_earnings() -> None:
    """Earnings calendar — twice daily."""
    from backend.pipeline import refresh_earnings_calendar
    try:
        refresh_earnings_calendar()
    except Exception as e:
        logger.exception("Pipeline[earnings] failed: %s", e)


def register_all_jobs(scheduler: BackgroundScheduler) -> None:
    """Register every job from CALIBRATION_SCHEDULE onto the scheduler."""

    # ── Tiered data pipeline ──
    scheduler.add_job(
        _run_pipeline_fast, "interval", minutes=2,
        id="pipeline_fast", replace_existing=True,
    )
    scheduler.add_job(
        _run_pipeline_medium, "interval", minutes=10,
        id="pipeline_medium", replace_existing=True,
    )
    scheduler.add_job(
        _run_pipeline_earnings, "cron", hour="7,12",
        id="pipeline_earnings", replace_existing=True,
    )
    logger.info("Registered pipeline jobs: fast (2m), medium (10m), earnings (7am+12pm)")

    # Trade monitoring (not in calibration schedule, but essential)
    scheduler.add_job(_check_trade_alerts, "interval", minutes=15, id="trade_alerts", replace_existing=True)
    scheduler.add_job(_update_phantoms, "cron", hour=18, minute=0, id="phantom_updates", replace_existing=True)

    # Calibration jobs that don't overlap with the pipeline
    PIPELINE_HANDLED = {
        "vol_context", "regime_detection", "strategy_weights",
    }

    for name, cfg in CALIBRATION_SCHEDULE.items():
        if name in PIPELINE_HANDLED:
            logger.info("Skipping job %s — handled by pipeline", name)
            continue

        func = JOB_MAP.get(name)
        if func is None:
            logger.warning("No handler for scheduled job: %s", name)
            continue

        interval = cfg.get("interval", "daily")

        if interval == "15min":
            scheduler.add_job(func, "interval", minutes=15, id=name, replace_existing=True)
        elif interval == "1h":
            scheduler.add_job(func, "interval", hours=1, id=name, replace_existing=True)
        elif interval == "daily":
            hour = 7
            minute = 0
            time_str = cfg.get("time", "")
            if ":" in time_str:
                parts = time_str.split()
                time_parts = parts[0].split(":")
                try:
                    hour = int(time_parts[0])
                    minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                except (ValueError, IndexError):
                    logger.warning("Invalid time format '%s' for job %s, using 07:00", time_str, name)
            scheduler.add_job(func, "cron", hour=hour, minute=minute, id=name, replace_existing=True)
        elif interval == "weekly":
            day = cfg.get("day", "sunday")
            scheduler.add_job(func, "cron", day_of_week=day[:3], hour=18, id=name, replace_existing=True)
        elif interval == "monthly":
            scheduler.add_job(func, "cron", day=1, hour=6, id=name, replace_existing=True)

        logger.info("Registered job: %s (%s)", name, interval)
