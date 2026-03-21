"""Background data pipeline — pre-computes and caches all heavy endpoints.

Runs every 10 minutes via APScheduler.  API endpoints read from
``data_cache`` (Supabase) instead of making live market-data calls,
keeping response times instant.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.config import settings
from backend.data.cache import data_cache
from backend.data.fetcher import DataFetcher
from backend.models.schemas import Regime
from backend.regime.detector import detect_regime

logger = logging.getLogger(__name__)

TTL_FAST = 0.2  # 12 min — regime, portfolio (refreshed every 10 min by scheduler)
TTL_MEDIUM = 0.5  # 30 min — scanner, sectors, swing, flow
TTL_DAILY = 12.0  # 12 hours — for daily data (earnings calendar)

_fetcher = DataFetcher()
_regime_lock = threading.Lock()


# ── Shared helpers ───────────────────────────────────────────


def _fetch_regime_and_vol() -> tuple[Regime, VolContext, dict]:
    """Fetch VIX/SPY + FRED macro data, detect regime, compute vol context.

    Uses live=True to go straight to yfinance (~1s) instead of querying
    the market_prices DB table which can hang on large tables.
    """
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)

    yield_curve_slope: float | None = None
    credit_spread_ratio: float | None = None
    try:
        yc = _fetcher.get_yield_curve_slope()
        if not yc.empty:
            yield_curve_slope = float(yc.iloc[-1])
        cs = _fetcher.get_credit_spread()
        if not cs.empty:
            credit_spread_ratio = float(cs.iloc[-1])
    except Exception as e:
        logger.debug("FRED data unavailable for regime detection: %s", e)

    regime_result = detect_regime(
        vix_df,
        spy_df,
        yield_curve_slope=yield_curve_slope,
        credit_spread_ratio=credit_spread_ratio,
    )
    regime: Regime = regime_result["regime"]
    vol = compute_vol_context(spy_df, vix_df)
    return regime, vol, regime_result


# ── Individual refresh functions ─────────────────────────────


def refresh_regime(
    _prefetched: tuple[Regime, VolContext, dict] | None = None,
) -> dict | None:
    """Detect current market regime and cache the snapshot.

    Uses a lock to prevent duplicate simultaneous computations — if another
    thread is already computing, this one waits and returns the cached result.
    """
    acquired = _regime_lock.acquire(timeout=120)
    if not acquired:
        logger.warning("Pipeline: regime lock timeout, returning cached")
        cached = data_cache.get("pipeline:regime")
        return cached if isinstance(cached, dict) else None

    try:
        cached = data_cache.get("pipeline:regime")
        if cached and isinstance(cached, dict) and not _prefetched:
            return cached

        regime, vol, regime_result = _prefetched or _fetch_regime_and_vol()

        indicators = regime_result.get("indicators", {})
        vix_val = indicators.get("vix", {}).get("vix", 18.0) if isinstance(indicators.get("vix"), dict) else 18.0
        breadth = (
            indicators.get("breadth", {}).get("pct_above_200sma", 50.0)
            if isinstance(indicators.get("breadth"), dict)
            else 50.0
        )
        adx = indicators.get("adx", {}).get("adx", 20.0) if isinstance(indicators.get("adx"), dict) else 20.0

        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "regime": regime.value,
            "confidence": regime_result["confidence"],
            "regime_probabilities": regime_result["probabilities"],
            "vix": vix_val,
            "breadth_pct": breadth,
            "adx": adx,
            "strategy_weights": regime_result.get("strategy_weights", {}),
            "refreshed_at": datetime.now(UTC).isoformat(),
        }

        import json

        from backend.models.database import get_supabase

        try:
            sb = get_supabase()
            sb.table("regimes").insert(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "regime": regime.value,
                    "confidence": regime_result["confidence"],
                    "vix": vix_val,
                    "breadth_pct": breadth,
                    "adx": adx,
                    "strategy_weights_json": json.dumps(regime_result.get("strategy_weights", {})),
                    "regime_probabilities_json": json.dumps(regime_result["probabilities"]),
                }
            ).execute()
        except Exception as e:
            logger.warning("Failed to persist regime record: %s", e)

        data_cache.set("pipeline:regime", payload, ttl_hours=TTL_FAST)
        logger.info("Pipeline: regime refreshed — %s (confidence=%.2f)", regime.value, regime_result["confidence"])
        return payload
    except Exception as e:
        logger.exception("Pipeline: regime refresh failed: %s", e)
        return None
    finally:
        _regime_lock.release()


def refresh_scanner(
    _prefetched: tuple[Regime, VolContext, dict] | None = None,
) -> dict | None:
    """Run the full universe scan and cache results."""
    try:
        from backend.api.scanner import _enrich_signals, _log_signals_to_shadow_book, _run_scan

        regime, vol, _ = _prefetched or _fetch_regime_and_vol()
        all_signals = _run_scan(vol, regime)
        _log_signals_to_shadow_book(all_signals, regime, vol)

        enriched = _enrich_signals(all_signals, vol, regime)
        enriched = [e for e in enriched if e.signal.signal_score >= 60.0]
        enriched.sort(key=lambda e: e.signal.conviction, reverse=True)
        enriched = enriched[:10]

        from backend.models.schemas import ScannerResult

        result = ScannerResult(
            timestamp=datetime.now(UTC),
            regime=regime,
            signals=enriched,
            total_signals=len(all_signals),
        )
        payload = {
            "data": result.model_dump(mode="json"),
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        data_cache.set("pipeline:scanner", payload, ttl_hours=TTL_MEDIUM)
        logger.info("Pipeline: scanner refreshed — %d signals (of %d total)", len(enriched), len(all_signals))
        return payload
    except Exception as e:
        logger.exception("Pipeline: scanner refresh failed: %s", e)
        return None


def refresh_sectors() -> dict | None:
    """Run sector analysis and cache results."""
    try:
        from backend.api.sectors import _analyze_sectors

        result = _analyze_sectors()
        payload = {
            "data": result,
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        data_cache.set("pipeline:sectors", payload, ttl_hours=TTL_MEDIUM)
        logger.info("Pipeline: sectors refreshed — %d sectors", len(result.get("sectors", [])))
        return payload
    except Exception as e:
        logger.exception("Pipeline: sectors refresh failed: %s", e)
        return None


def refresh_portfolio(
    _prefetched: tuple[Regime, VolContext, dict] | None = None,
) -> dict | None:
    """Compute portfolio state and cache it."""
    try:
        regime, vol, regime_result = _prefetched or _fetch_regime_and_vol()
        confidence = regime_result["confidence"]

        from backend.models.schemas import StrategyName, TradeSignal
        from backend.tracker.trade_journal import TradeJournal

        journal = TradeJournal(fetcher=_fetcher)
        active_entries = journal.get_active_trades()

        active_signals: list[dict] = []
        for t in active_entries:
            sig = TradeSignal(
                strategy=t.strategy if isinstance(t.strategy, StrategyName) else StrategyName(t.strategy),
                ticker=t.ticker,
                direction=t.direction,
                conviction=t.signal_score / 100,
                kelly_size_pct=t.kelly_fraction_used * 100,
                entry_price=t.entry_price,
                stop_loss=t.stop_loss,
                target=t.target_1,
                max_hold_days=t.max_hold_days,
                edge_reason="Active position",
                kill_condition="See trade plan",
                expected_sharpe=0.0,
                signal_score=t.signal_score,
            )
            active_signals.append(sig.model_dump(mode="json"))

        gross = sum(t.position_size_pct for t in active_entries)
        long_exp = sum(t.position_size_pct for t in active_entries if t.direction == "long")
        short_exp = sum(t.position_size_pct for t in active_entries if t.direction == "short")
        net = long_exp - short_exp

        try:
            all_closed = journal.get_closed_trades()
        except Exception:
            all_closed = []

        summary = journal.compute_summary_from_trades(all_closed)
        strategy_pnl = {}
        for s in StrategyName:
            strategy_pnl[s.value] = sum(
                t.pnl_dollars or 0 for t in all_closed
                if (t.strategy == s or t.strategy == s.value)
            )

        payload = {
            "data": {
                "regime": regime.value,
                "regime_confidence": confidence,
                "gross_exposure": round(gross, 4),
                "net_exposure": round(net, 4),
                "daily_var": 0.0,
                "current_drawdown_pct": 0.0,
                "active_trades": active_signals,
                "strategy_pnl": strategy_pnl,
                "total_pnl_ytd": summary.get("total_pnl_dollars", 0),
                "portfolio_sharpe_30d": 0.0,
            },
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        data_cache.set("pipeline:portfolio", payload, ttl_hours=TTL_FAST)
        logger.info("Pipeline: portfolio refreshed — %d active trades", len(active_entries))
        return payload
    except Exception as e:
        logger.exception("Pipeline: portfolio refresh failed: %s", e)
        return None


def refresh_swing() -> dict | None:
    """Run the swing picks scan and cache results."""
    try:
        from backend.api.swing_picks import _run_swing_scan

        result = _run_swing_scan(min_return_pct=30.0, max_hold_days=10)
        payload = {
            "data": result,
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        data_cache.set("pipeline:swing", payload, ttl_hours=TTL_MEDIUM)
        quick = len(result.get("quick_trades", []))
        swing = len(result.get("swing_trades", []))
        logger.info("Pipeline: swing refreshed — %d quick + %d swing picks", quick, swing)
        return payload
    except Exception as e:
        logger.exception("Pipeline: swing refresh failed: %s", e)
        return None


def refresh_flow() -> dict | None:
    """Pre-compute institutional options flow summary from SteadyAPI."""
    try:
        if not settings.enable_steadyapi or not settings.steadyapi_api_key:
            logger.debug("Pipeline: SteadyAPI disabled, skipping flow refresh")
            return None

        from backend.data.sources.steadyapi_src import steadyapi_source

        summary = steadyapi_source.get_flow_summary(max_pages=3)
        if not summary:
            return None

        unusual = steadyapi_source.get_unusual_options_activity(max_pages=2)

        payload = {
            "data": {
                "flow_summary": summary,
                "unusual_activity": unusual[:20],
                "unusual_count": len(unusual),
            },
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        data_cache.set("pipeline:flow", payload, ttl_hours=TTL_MEDIUM)
        logger.info(
            "Pipeline: flow refreshed — %d records, C/P ratio=%.2f, %d unusual",
            summary.get("total_records", 0),
            summary.get("call_put_premium_ratio", 0),
            len(unusual),
        )
        return payload
    except Exception as e:
        logger.exception("Pipeline: flow refresh failed: %s", e)
        return None


def refresh_earnings_calendar() -> dict | None:
    """Pre-compute upcoming earnings calendar from FMP."""
    try:
        if not settings.fmp_api_key:
            return None

        from backend.data.sources.fmp_src import fmp_source

        calendar = fmp_source.get_earnings_calendar()
        if not calendar:
            return None

        payload = {
            "data": calendar[:30],
            "refreshed_at": datetime.now(UTC).isoformat(),
        }
        data_cache.set("pipeline:earnings_calendar", payload, ttl_hours=TTL_DAILY)
        logger.info("Pipeline: earnings calendar refreshed — %d upcoming", len(calendar[:30]))
        return payload
    except Exception as e:
        logger.exception("Pipeline: earnings calendar refresh failed: %s", e)
        return None


# ── Tiered refresh ───────────────────────────────────────────


def refresh_dashboard_ai(regime_payload: dict) -> None:
    """Pre-compute the 4 AI summaries for the Market Overview dashboard.

    Runs after regime refresh so the dashboard loads instantly.
    Results are cached keyed by regime fingerprint — only re-generated
    when the regime actually changes.
    """
    import hashlib
    import json as _json

    fingerprint = {
        "regime": regime_payload.get("regime", ""),
        "vix": round(regime_payload.get("vix", 0), 0),
        "confidence": round(regime_payload.get("confidence", 0), 1),
    }
    h = hashlib.md5(_json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:8]

    already_cached = data_cache.get(f"ai:market:{h}")
    if already_cached is not None:
        logger.debug("Pipeline: dashboard AI already cached for fingerprint %s", h)
        return

    try:
        from backend.ai.market_ai import (
            ai_allocation_explain,
            ai_market_action_banner,
            ai_market_summary,
            ai_regime_probs,
        )

        ttl = 0.5

        market = ai_market_summary(regime_payload)
        if market:
            data_cache.set(f"ai:market:{h}", market, ttl_hours=ttl)

        probs_data = {
            "probabilities": regime_payload.get("regime_probabilities", {}),
            "vix": regime_payload.get("vix", 0),
            "adx": regime_payload.get("adx", 0),
            "breadth_pct": regime_payload.get("breadth_pct", 0),
        }
        probs = ai_regime_probs(probs_data)
        if probs:
            probs_h = hashlib.md5(
                _json.dumps(
                    {
                        "regime": probs_data.get("regime", regime_payload.get("regime", "")),
                        "vix": round(probs_data.get("vix", 0), 0),
                        "confidence": round(probs_data.get("confidence", regime_payload.get("confidence", 0)), 1),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:8]
            data_cache.set(f"ai:regime_probs:{probs_h}", probs, ttl_hours=ttl)

        alloc = ai_allocation_explain(regime_payload)
        if alloc:
            data_cache.set(f"ai:allocation_explain:{h}", alloc, ttl_hours=ttl)

        action = ai_market_action_banner(regime_payload)
        if action:
            data_cache.set(f"ai:market_action:{h}", action, ttl_hours=ttl)

        logger.info("Pipeline: dashboard AI pre-computed (fingerprint=%s)", h)
    except Exception as e:
        logger.warning("Pipeline: dashboard AI pre-compute failed: %s", e)


def refresh_fast() -> None:
    """Every 2 min: stock prices, regime, portfolio state.
    Fetches VIX/SPY/FRED once and shares across regime + portfolio.
    """
    started = datetime.now(UTC)
    prefetched = _fetch_regime_and_vol()
    regime_payload = refresh_regime(_prefetched=prefetched)
    refresh_portfolio(_prefetched=prefetched)
    if regime_payload:
        refresh_dashboard_ai(regime_payload)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    logger.info("Pipeline[fast]: regime + portfolio + dashboard AI in %.1fs", elapsed)


def refresh_medium() -> None:
    """Every 10 min: full scanner, sectors, swing picks.
    Fetches VIX/SPY/FRED once and shares across scanner.
    """
    started = datetime.now(UTC)
    prefetched = _fetch_regime_and_vol()
    refresh_scanner(_prefetched=prefetched)
    refresh_sectors()
    refresh_swing()
    elapsed = (datetime.now(UTC) - started).total_seconds()
    logger.info("Pipeline[medium]: scanner + sectors + swing in %.1fs", elapsed)


def refresh_all() -> None:
    """Run the full pipeline (all tiers). Used on startup."""
    started = datetime.now(UTC)
    logger.info("Pipeline: starting full refresh at %s", started.isoformat())

    refresh_fast()
    refresh_medium()
    refresh_earnings_calendar()

    elapsed = (datetime.now(UTC) - started).total_seconds()
    logger.info("Pipeline: full refresh completed in %.1fs", elapsed)
