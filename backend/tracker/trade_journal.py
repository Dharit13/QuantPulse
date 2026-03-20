"""Trade Journal — manual entry, P&L tracking, and phantom trade monitoring.

Handles the human-in-the-loop workflow:
  [Take Trade] → log entry with actual fill → monitor → log exit → compute P&L
  [Pass]       → log phantom trade → track what-would-have-happened
"""

from __future__ import annotations

import logging
from datetime import date

from backend.data.fetcher import DataFetcher
from backend.models.database import get_supabase
from backend.models.schemas import PhantomTrade, StrategyName, TradeEntry

logger = logging.getLogger(__name__)


class TradeJournal:
    """Central trade logging and retrieval layer."""

    def __init__(self, fetcher: DataFetcher | None = None):
        self._fetcher = fetcher or DataFetcher()

    # ── Write Operations ────────────────────────────────────────

    def log_entry(self, entry: TradeEntry) -> int:
        """Record a new trade the user has taken. Returns the trade id."""
        sb = get_supabase()
        row = {
            "ticker": entry.ticker,
            "direction": entry.direction,
            "strategy": entry.strategy.value,
            "signal_score": entry.signal_score,
            "regime_at_entry": entry.regime_at_entry.value
            if hasattr(entry.regime_at_entry, "value")
            else str(entry.regime_at_entry),
            "entry_date": str(entry.entry_date),
            "entry_price": entry.entry_price,
            "shares": entry.shares,
            "position_size_pct": entry.position_size_pct,
            "stop_loss": entry.stop_loss,
            "target_1": entry.target_1,
            "target_2": entry.target_2,
            "max_hold_days": entry.max_hold_days,
            "atr_at_entry": entry.atr_at_entry,
            "vix_at_entry": entry.vix_at_entry,
            "vol_regime_at_entry": entry.vol_regime_at_entry.value
            if hasattr(entry.vol_regime_at_entry, "value")
            else str(entry.vol_regime_at_entry),
            "kelly_fraction_used": entry.kelly_fraction_used,
            "entry_notes": entry.entry_notes,
        }
        result = sb.table("trades").insert(row).execute()
        record_id = result.data[0]["id"]
        logger.info("Trade logged: %s %s %s (id=%d)", entry.direction, entry.ticker, entry.strategy.value, record_id)
        return record_id

    def log_exit(
        self,
        trade_id: int,
        exit_date: date,
        exit_price: float,
        exit_reason: str,
        exit_notes: str = "",
    ) -> TradeEntry | None:
        """Close an active trade with exit details and compute P&L."""
        sb = get_supabase()
        result = sb.table("trades").select("*").eq("id", trade_id).execute()
        if not result.data:
            logger.warning("Trade id=%d not found", trade_id)
            return None

        record = result.data[0]
        entry_date_val = (
            date.fromisoformat(record["entry_date"]) if isinstance(record["entry_date"], str) else record["entry_date"]
        )
        hold_days = (exit_date - entry_date_val).days

        multiplier = 1.0 if record["direction"] == "long" else -1.0
        pnl_dollars = round(multiplier * (exit_price - record["entry_price"]) * record["shares"], 2)
        pnl_percent = round(multiplier * (exit_price - record["entry_price"]) / record["entry_price"] * 100, 4)

        sb.table("trades").update(
            {
                "exit_date": str(exit_date),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "exit_notes": exit_notes,
                "hold_days": hold_days,
                "pnl_dollars": pnl_dollars,
                "pnl_percent": pnl_percent,
            }
        ).eq("id", trade_id).execute()

        logger.info("Trade closed: id=%d %s P&L=$%.2f (%.2f%%)", trade_id, record["ticker"], pnl_dollars, pnl_percent)

        updated = sb.table("trades").select("*").eq("id", trade_id).execute()
        return self._record_to_entry(updated.data[0]) if updated.data else None

    def log_phantom(self, phantom: PhantomTrade) -> int:
        """Record a signal the user passed on for what-if tracking."""
        sb = get_supabase()
        row = {
            "ticker": phantom.ticker,
            "direction": phantom.direction,
            "strategy": phantom.strategy.value,
            "signal_score": phantom.signal_score,
            "signal_date": str(phantom.signal_date),
            "entry_price_suggested": phantom.entry_price_suggested,
            "stop_suggested": phantom.stop_suggested,
            "target_suggested": phantom.target_suggested,
            "pass_reason": phantom.pass_reason,
            "regime": phantom.regime,
            "vix_at_signal": phantom.vix_at_signal,
            "atr_at_signal": phantom.atr_at_signal,
            "conviction": phantom.conviction,
            "signal_id": phantom.signal_id,
        }
        result = sb.table("phantom_trades").insert(row).execute()
        record_id = result.data[0]["id"]
        logger.info("Phantom trade logged: %s %s (id=%d)", phantom.ticker, phantom.strategy.value, record_id)
        return record_id

    # ── Read Operations ─────────────────────────────────────────

    def get_active_trades(self) -> list[TradeEntry]:
        """All trades that have not been exited yet."""
        sb = get_supabase()
        result = sb.table("trades").select("*").is_("exit_date", "null").execute()
        return [self._record_to_entry(r) for r in result.data]

    def get_closed_trades(
        self,
        strategy: StrategyName | None = None,
        since: date | None = None,
    ) -> list[TradeEntry]:
        """Closed trades with optional strategy/date filters."""
        sb = get_supabase()
        q = sb.table("trades").select("*").not_.is_("exit_date", "null")
        if strategy:
            q = q.eq("strategy", strategy.value)
        if since:
            q = q.gte("exit_date", str(since))
        result = q.order("exit_date", desc=True).execute()
        return [self._record_to_entry(r) for r in result.data]

    def get_trade(self, trade_id: int) -> TradeEntry | None:
        sb = get_supabase()
        result = sb.table("trades").select("*").eq("id", trade_id).execute()
        return self._record_to_entry(result.data[0]) if result.data else None

    def get_phantom_trades(
        self,
        strategy: StrategyName | None = None,
        since: date | None = None,
    ) -> list[PhantomTrade]:
        sb = get_supabase()
        q = sb.table("phantom_trades").select("*")
        if strategy:
            q = q.eq("strategy", strategy.value)
        if since:
            q = q.gte("signal_date", str(since))
        result = q.order("signal_date", desc=True).execute()
        return [self._phantom_to_model(r) for r in result.data]

    # ── Monitoring ──────────────────────────────────────────────

    def check_active_trade_alerts(self) -> list[dict]:
        """Check all active trades against current prices for stop/target/time alerts."""
        active = self.get_active_trades()
        alerts: list[dict] = []
        for trade in active:
            try:
                df = self._fetcher.get_daily_ohlcv(trade.ticker, period="5d")
                if df.empty:
                    continue
                current_price = float(df["Close"].iloc[-1])
            except Exception:
                continue

            hold_days = (date.today() - trade.entry_date).days

            if trade.direction == "long":
                if current_price <= trade.stop_loss:
                    alerts.append(
                        {"trade_id": trade.id, "ticker": trade.ticker, "type": "stop_hit", "price": current_price}
                    )
                elif current_price >= trade.target_1:
                    alerts.append(
                        {"trade_id": trade.id, "ticker": trade.ticker, "type": "target_hit", "price": current_price}
                    )
                elif trade.stop_loss > 0 and current_price <= trade.stop_loss * 1.01:
                    alerts.append(
                        {
                            "trade_id": trade.id,
                            "ticker": trade.ticker,
                            "type": "approaching_stop",
                            "price": current_price,
                        }
                    )
            else:
                if current_price >= trade.stop_loss:
                    alerts.append(
                        {"trade_id": trade.id, "ticker": trade.ticker, "type": "stop_hit", "price": current_price}
                    )
                elif current_price <= trade.target_1:
                    alerts.append(
                        {"trade_id": trade.id, "ticker": trade.ticker, "type": "target_hit", "price": current_price}
                    )
                elif trade.stop_loss > 0 and current_price >= trade.stop_loss * 0.99:
                    alerts.append(
                        {
                            "trade_id": trade.id,
                            "ticker": trade.ticker,
                            "type": "approaching_stop",
                            "price": current_price,
                        }
                    )

            if hold_days >= trade.max_hold_days:
                alerts.append(
                    {"trade_id": trade.id, "ticker": trade.ticker, "type": "time_stop", "hold_days": hold_days}
                )

        return alerts

    def update_phantom_outcomes(self) -> int:
        """Re-evaluate open phantoms against current prices. Returns count updated."""
        sb = get_supabase()
        result = sb.table("phantom_trades").select("*").is_("phantom_exit_date", "null").execute()
        updated = 0

        for p in result.data:
            signal_date_val = (
                date.fromisoformat(p["signal_date"]) if isinstance(p["signal_date"], str) else p["signal_date"]
            )
            days_since = (date.today() - signal_date_val).days
            if days_since < 1:
                continue
            try:
                df = self._fetcher.get_daily_ohlcv(p["ticker"], period="3mo")
                if df.empty:
                    continue
                current_price = float(df["Close"].iloc[-1])
            except Exception:
                continue

            hit_stop = (p["direction"] == "long" and current_price <= p["stop_suggested"]) or (
                p["direction"] == "short" and current_price >= p["stop_suggested"]
            )
            hit_target = (p["direction"] == "long" and current_price >= p["target_suggested"]) or (
                p["direction"] == "short" and current_price <= p["target_suggested"]
            )

            if hit_stop or hit_target or days_since > 30:
                mult = 1.0 if p["direction"] == "long" else -1.0
                pnl_pct = mult * (current_price - p["entry_price_suggested"]) / p["entry_price_suggested"] * 100

                sb.table("phantom_trades").update(
                    {
                        "phantom_exit_date": str(date.today()),
                        "phantom_exit_price": current_price,
                        "phantom_pnl_pct": round(pnl_pct, 4),
                        "phantom_outcome": "would_have_won" if pnl_pct > 0 else "would_have_lost",
                    }
                ).eq("id", p["id"]).execute()
                updated += 1

        logger.info("Updated %d phantom trade outcomes", updated)
        return updated

    # ── Summary Stats ───────────────────────────────────────────

    def compute_summary(self, since: date | None = None) -> dict:
        """Aggregate P&L stats across all closed trades."""
        trades = self.get_closed_trades(since=since)
        if not trades:
            return {"total_trades": 0}

        wins = [t for t in trades if t.pnl_percent and t.pnl_percent > 0]
        losses = [t for t in trades if t.pnl_percent and t.pnl_percent <= 0]

        total_pnl = sum(t.pnl_dollars or 0 for t in trades)
        gross_wins = sum(t.pnl_dollars for t in wins if t.pnl_dollars)
        gross_losses = abs(sum(t.pnl_dollars for t in losses if t.pnl_dollars))

        return {
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades) if trades else 0,
            "total_pnl_dollars": round(total_pnl, 2),
            "avg_win_pct": round(sum(t.pnl_percent for t in wins if t.pnl_percent) / max(len(wins), 1), 4),
            "avg_loss_pct": round(sum(t.pnl_percent for t in losses if t.pnl_percent) / max(len(losses), 1), 4),
            "profit_factor": round(gross_wins / gross_losses, 2) if gross_losses > 0 else 99.99,
            "avg_hold_days": round(sum(t.hold_days or 0 for t in trades) / len(trades), 1),
        }

    # ── Internal ────────────────────────────────────────────────

    @staticmethod
    def _record_to_entry(r: dict) -> TradeEntry:
        return TradeEntry(
            id=r["id"],
            ticker=r["ticker"],
            direction=r["direction"],
            strategy=StrategyName(r["strategy"]),
            signal_score=r["signal_score"],
            regime_at_entry=r["regime_at_entry"],
            entry_date=r["entry_date"],
            entry_price=r["entry_price"],
            shares=r["shares"],
            position_size_pct=r["position_size_pct"],
            stop_loss=r["stop_loss"],
            target_1=r["target_1"],
            target_2=r.get("target_2"),
            max_hold_days=r["max_hold_days"],
            atr_at_entry=r["atr_at_entry"],
            vix_at_entry=r["vix_at_entry"],
            vol_regime_at_entry=r["vol_regime_at_entry"],
            kelly_fraction_used=r["kelly_fraction_used"],
            exit_date=r.get("exit_date"),
            exit_price=r.get("exit_price"),
            exit_reason=r.get("exit_reason"),
            pnl_dollars=r.get("pnl_dollars"),
            pnl_percent=r.get("pnl_percent"),
            hold_days=r.get("hold_days"),
            entry_notes=r.get("entry_notes", ""),
            exit_notes=r.get("exit_notes", ""),
        )

    @staticmethod
    def _phantom_to_model(r: dict) -> PhantomTrade:
        return PhantomTrade(
            id=r["id"],
            ticker=r["ticker"],
            direction=r["direction"],
            strategy=StrategyName(r["strategy"]),
            signal_score=r["signal_score"],
            signal_date=r["signal_date"],
            entry_price_suggested=r["entry_price_suggested"],
            stop_suggested=r["stop_suggested"],
            target_suggested=r["target_suggested"],
            pass_reason=r.get("pass_reason", ""),
            phantom_exit_date=r.get("phantom_exit_date"),
            phantom_exit_price=r.get("phantom_exit_price"),
            phantom_pnl_pct=r.get("phantom_pnl_pct"),
            phantom_outcome=r.get("phantom_outcome"),
        )
