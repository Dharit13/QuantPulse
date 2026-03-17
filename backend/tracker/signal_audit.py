"""Signal Audit — why did we enter/exit this trade?

Provides a structured audit trail for every signal generated and every
trade decision.  Useful for post-trade review and strategy calibration.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, SignalRecord, TradeRecord
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
        with SessionLocal() as db:
            record = SignalRecord(
                timestamp=signal.created_at or datetime.utcnow(),
                ticker=signal.ticker,
                strategy=signal.strategy.value,
                direction=signal.direction,
                signal_score=signal.signal_score,
                conviction=signal.conviction,
                kelly_size_pct=signal.kelly_size_pct,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                target=signal.target,
                edge_reason=signal.edge_reason,
                kill_condition=signal.kill_condition,
                acted_on=acted_on,
                regime=regime,
                vix_at_signal=vix,
                max_hold_days=signal.max_hold_days,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id

    def mark_acted_on(self, signal_id: int) -> None:
        """Flag a previously logged signal as acted-on (user took the trade)."""
        with SessionLocal() as db:
            record = db.query(SignalRecord).filter(SignalRecord.id == signal_id).first()
            if record:
                record.acted_on = True
                db.commit()

    def get_signals(
        self,
        strategy: StrategyName | None = None,
        ticker: str | None = None,
        since: date | None = None,
        acted_on_only: bool = False,
    ) -> list[dict]:
        """Retrieve historical signals with optional filters."""
        with SessionLocal() as db:
            q = db.query(SignalRecord).order_by(SignalRecord.timestamp.desc())
            if strategy:
                q = q.filter(SignalRecord.strategy == strategy.value)
            if ticker:
                q = q.filter(SignalRecord.ticker == ticker)
            if since:
                q = q.filter(SignalRecord.timestamp >= datetime.combine(since, datetime.min.time()))
            if acted_on_only:
                q = q.filter(SignalRecord.acted_on.is_(True))
            return [self._record_to_dict(r) for r in q.limit(500).all()]

    def build_trade_audit(self, trade_id: int) -> dict | None:
        """Build a complete audit report for a specific trade.

        Combines the original signal, entry context, exit context, and outcome.
        """
        with SessionLocal() as db:
            trade = db.query(TradeRecord).filter(TradeRecord.id == trade_id).first()
            if not trade:
                return None

            matching_signals = (
                db.query(SignalRecord)
                .filter(
                    SignalRecord.ticker == trade.ticker,
                    SignalRecord.strategy == trade.strategy,
                    SignalRecord.acted_on.is_(True),
                )
                .order_by(SignalRecord.timestamp.desc())
                .limit(5)
                .all()
            )

            return {
                "trade_id": trade.id,
                "ticker": trade.ticker,
                "strategy": trade.strategy,
                "direction": trade.direction,
                "entry": {
                    "date": str(trade.entry_date),
                    "price": trade.entry_price,
                    "signal_score": trade.signal_score,
                    "regime": trade.regime_at_entry,
                    "vol_regime": trade.vol_regime_at_entry,
                    "vix": trade.vix_at_entry,
                    "atr": trade.atr_at_entry,
                    "kelly_fraction": trade.kelly_fraction_used,
                    "position_size_pct": trade.position_size_pct,
                    "notes": trade.entry_notes,
                },
                "risk_plan": {
                    "stop_loss": trade.stop_loss,
                    "target_1": trade.target_1,
                    "target_2": trade.target_2,
                    "max_hold_days": trade.max_hold_days,
                },
                "exit": {
                    "date": str(trade.exit_date) if trade.exit_date else None,
                    "price": trade.exit_price,
                    "reason": trade.exit_reason,
                    "pnl_dollars": trade.pnl_dollars,
                    "pnl_percent": trade.pnl_percent,
                    "hold_days": trade.hold_days,
                    "notes": trade.exit_notes,
                },
                "original_signals": [self._record_to_dict(s) for s in matching_signals],
            }

    def signal_accuracy_report(self, strategy: StrategyName | None = None, since: date | None = None) -> dict:
        """How accurate were our signals? Compares acted-on vs all signals."""
        with SessionLocal() as db:
            q = db.query(SignalRecord)
            if strategy:
                q = q.filter(SignalRecord.strategy == strategy.value)
            if since:
                q = q.filter(SignalRecord.timestamp >= datetime.combine(since, datetime.min.time()))
            signals = q.all()

        total = len(signals)
        acted = [s for s in signals if s.acted_on]
        not_acted = [s for s in signals if not s.acted_on]

        return {
            "total_signals": total,
            "acted_on": len(acted),
            "passed": len(not_acted),
            "act_rate": round(len(acted) / total, 4) if total else 0,
            "avg_score_acted": round(sum(s.signal_score for s in acted) / max(len(acted), 1), 2),
            "avg_score_passed": round(sum(s.signal_score for s in not_acted) / max(len(not_acted), 1), 2),
            "avg_conviction_acted": round(sum(s.conviction for s in acted) / max(len(acted), 1), 4),
        }

    @staticmethod
    def _record_to_dict(r: SignalRecord) -> dict:
        return {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "ticker": r.ticker,
            "strategy": r.strategy,
            "direction": r.direction,
            "signal_score": r.signal_score,
            "conviction": r.conviction,
            "kelly_size_pct": r.kelly_size_pct,
            "entry_price": r.entry_price,
            "stop_loss": r.stop_loss,
            "target": r.target,
            "edge_reason": r.edge_reason,
            "kill_condition": r.kill_condition,
            "acted_on": r.acted_on,
        }
