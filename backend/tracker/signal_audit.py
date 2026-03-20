"""Signal Audit — why did we enter/exit this trade?

Provides a structured audit trail for every signal generated and every
trade decision.  Useful for post-trade review and strategy calibration.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from backend.models.database import get_supabase
from backend.models.schemas import StrategyName, TradeSignal

logger = logging.getLogger(__name__)


class SignalAuditor:
    """Records and queries the audit trail for signals and trade decisions."""

    def log_signal(
        self,
        signal: TradeSignal,
        acted_on: bool = False,
        regime: str | None = None,
        vix: float | None = None,
    ) -> int:
        """Persist a generated signal for the audit trail. Returns signal id."""
        sb = get_supabase()
        row = {
            "timestamp": (signal.created_at or datetime.now(UTC)).isoformat(),
            "ticker": signal.ticker,
            "strategy": signal.strategy.value,
            "direction": signal.direction,
            "signal_score": signal.signal_score,
            "conviction": signal.conviction,
            "kelly_size_pct": signal.kelly_size_pct,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
            "edge_reason": signal.edge_reason,
            "kill_condition": signal.kill_condition,
            "acted_on": acted_on,
            "regime": regime,
            "vix_at_signal": vix,
            "max_hold_days": signal.max_hold_days,
        }
        result = sb.table("signals").insert(row).execute()
        return result.data[0]["id"]

    def mark_acted_on(self, signal_id: int) -> None:
        """Flag a previously logged signal as acted-on (user took the trade)."""
        sb = get_supabase()
        sb.table("signals").update({"acted_on": True}).eq("id", signal_id).execute()

    def get_signals(
        self,
        strategy: StrategyName | None = None,
        ticker: str | None = None,
        since: date | None = None,
        acted_on_only: bool = False,
    ) -> list[dict]:
        """Retrieve historical signals with optional filters."""
        sb = get_supabase()
        q = sb.table("signals").select("*").order("timestamp", desc=True)
        if strategy:
            q = q.eq("strategy", strategy.value)
        if ticker:
            q = q.eq("ticker", ticker)
        if since:
            q = q.gte("timestamp", datetime.combine(since, datetime.min.time()).isoformat())
        if acted_on_only:
            q = q.eq("acted_on", True)
        result = q.limit(500).execute()
        return [self._record_to_dict(r) for r in result.data]

    def build_trade_audit(self, trade_id: int) -> dict | None:
        """Build a complete audit report for a specific trade."""
        sb = get_supabase()
        trade_result = sb.table("trades").select("*").eq("id", trade_id).execute()
        if not trade_result.data:
            return None

        trade = trade_result.data[0]

        signals_result = (
            sb.table("signals")
            .select("*")
            .eq("ticker", trade["ticker"])
            .eq("strategy", trade["strategy"])
            .eq("acted_on", True)
            .order("timestamp", desc=True)
            .limit(5)
            .execute()
        )

        return {
            "trade_id": trade["id"],
            "ticker": trade["ticker"],
            "strategy": trade["strategy"],
            "direction": trade["direction"],
            "entry": {
                "date": str(trade["entry_date"]),
                "price": trade["entry_price"],
                "signal_score": trade["signal_score"],
                "regime": trade["regime_at_entry"],
                "vol_regime": trade["vol_regime_at_entry"],
                "vix": trade["vix_at_entry"],
                "atr": trade["atr_at_entry"],
                "kelly_fraction": trade["kelly_fraction_used"],
                "position_size_pct": trade["position_size_pct"],
                "notes": trade.get("entry_notes"),
            },
            "risk_plan": {
                "stop_loss": trade["stop_loss"],
                "target_1": trade["target_1"],
                "target_2": trade.get("target_2"),
                "max_hold_days": trade["max_hold_days"],
            },
            "exit": {
                "date": str(trade["exit_date"]) if trade.get("exit_date") else None,
                "price": trade.get("exit_price"),
                "reason": trade.get("exit_reason"),
                "pnl_dollars": trade.get("pnl_dollars"),
                "pnl_percent": trade.get("pnl_percent"),
                "hold_days": trade.get("hold_days"),
                "notes": trade.get("exit_notes"),
            },
            "original_signals": [self._record_to_dict(s) for s in signals_result.data],
        }

    def signal_accuracy_report(self, strategy: StrategyName | None = None, since: date | None = None) -> dict:
        """How accurate were our signals? Compares acted-on vs all signals."""
        sb = get_supabase()
        q = sb.table("signals").select("*")
        if strategy:
            q = q.eq("strategy", strategy.value)
        if since:
            q = q.gte("timestamp", datetime.combine(since, datetime.min.time()).isoformat())
        result = q.execute()
        signals = result.data

        total = len(signals)
        acted = [s for s in signals if s.get("acted_on")]
        not_acted = [s for s in signals if not s.get("acted_on")]

        return {
            "total_signals": total,
            "acted_on": len(acted),
            "passed": len(not_acted),
            "act_rate": round(len(acted) / total, 4) if total else 0,
            "avg_score_acted": round(sum(s["signal_score"] for s in acted) / max(len(acted), 1), 2),
            "avg_score_passed": round(sum(s["signal_score"] for s in not_acted) / max(len(not_acted), 1), 2),
            "avg_conviction_acted": round(sum(s["conviction"] for s in acted) / max(len(acted), 1), 4),
        }

    @staticmethod
    def _record_to_dict(r: dict) -> dict:
        return {
            "id": r["id"],
            "timestamp": r.get("timestamp"),
            "ticker": r["ticker"],
            "strategy": r["strategy"],
            "direction": r["direction"],
            "signal_score": r["signal_score"],
            "conviction": r["conviction"],
            "kelly_size_pct": r["kelly_size_pct"],
            "entry_price": r["entry_price"],
            "stop_loss": r["stop_loss"],
            "target": r["target"],
            "edge_reason": r["edge_reason"],
            "kill_condition": r["kill_condition"],
            "acted_on": r.get("acted_on", False),
        }
