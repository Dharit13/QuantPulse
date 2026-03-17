"""Trade Journal — manual entry, P&L tracking, and phantom trade monitoring.

Handles the human-in-the-loop workflow:
  [Take Trade] → log entry with actual fill → monitor → log exit → compute P&L
  [Pass]       → log phantom trade → track what-would-have-happened
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend.data.fetcher import DataFetcher
from backend.models.database import (
    PhantomTradeRecord,
    SessionLocal,
    TradeRecord,
)
from backend.models.schemas import PhantomTrade, StrategyName, TradeEntry

logger = logging.getLogger(__name__)


class TradeJournal:
    """Central trade logging and retrieval layer."""

    def __init__(self, fetcher: DataFetcher | None = None):
        self._fetcher = fetcher or DataFetcher()

    # ── Write Operations ────────────────────────────────────────

    def log_entry(self, entry: TradeEntry) -> int:
        """Record a new trade the user has taken. Returns the trade id."""
        with SessionLocal() as db:
            record = TradeRecord(
                ticker=entry.ticker,
                direction=entry.direction,
                strategy=entry.strategy.value,
                signal_score=entry.signal_score,
                regime_at_entry=entry.regime_at_entry.value,
                entry_date=entry.entry_date,
                entry_price=entry.entry_price,
                shares=entry.shares,
                position_size_pct=entry.position_size_pct,
                stop_loss=entry.stop_loss,
                target_1=entry.target_1,
                target_2=entry.target_2,
                max_hold_days=entry.max_hold_days,
                atr_at_entry=entry.atr_at_entry,
                vix_at_entry=entry.vix_at_entry,
                vol_regime_at_entry=entry.vol_regime_at_entry.value,
                kelly_fraction_used=entry.kelly_fraction_used,
                entry_notes=entry.entry_notes,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            logger.info("Trade logged: %s %s %s (id=%d)", entry.direction, entry.ticker, entry.strategy.value, record.id)
            return record.id

    def log_exit(
        self,
        trade_id: int,
        exit_date: date,
        exit_price: float,
        exit_reason: str,
        exit_notes: str = "",
    ) -> TradeEntry | None:
        """Close an active trade with exit details and compute P&L."""
        with SessionLocal() as db:
            record = db.query(TradeRecord).filter(TradeRecord.id == trade_id).first()
            if record is None:
                logger.warning("Trade id=%d not found", trade_id)
                return None

            record.exit_date = exit_date
            record.exit_price = exit_price
            record.exit_reason = exit_reason
            record.exit_notes = exit_notes
            record.hold_days = (exit_date - record.entry_date).days

            multiplier = 1.0 if record.direction == "long" else -1.0
            record.pnl_dollars = round(multiplier * (exit_price - record.entry_price) * record.shares, 2)
            record.pnl_percent = round(multiplier * (exit_price - record.entry_price) / record.entry_price * 100, 4)

            db.commit()
            logger.info(
                "Trade closed: id=%d %s P&L=$%.2f (%.2f%%)",
                trade_id, record.ticker, record.pnl_dollars, record.pnl_percent,
            )
            return self._record_to_entry(record)

    def log_phantom(self, phantom: PhantomTrade) -> int:
        """Record a signal the user passed on for what-if tracking."""
        with SessionLocal() as db:
            record = PhantomTradeRecord(
                ticker=phantom.ticker,
                direction=phantom.direction,
                strategy=phantom.strategy.value,
                signal_score=phantom.signal_score,
                signal_date=phantom.signal_date,
                entry_price_suggested=phantom.entry_price_suggested,
                stop_suggested=phantom.stop_suggested,
                target_suggested=phantom.target_suggested,
                pass_reason=phantom.pass_reason,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            logger.info("Phantom trade logged: %s %s (id=%d)", phantom.ticker, phantom.strategy.value, record.id)
            return record.id

    # ── Read Operations ─────────────────────────────────────────

    def get_active_trades(self) -> list[TradeEntry]:
        """All trades that have not been exited yet."""
        with SessionLocal() as db:
            rows = db.query(TradeRecord).filter(TradeRecord.exit_date.is_(None)).all()
            return [self._record_to_entry(r) for r in rows]

    def get_closed_trades(
        self,
        strategy: StrategyName | None = None,
        since: date | None = None,
    ) -> list[TradeEntry]:
        """Closed trades with optional strategy/date filters."""
        with SessionLocal() as db:
            q = db.query(TradeRecord).filter(TradeRecord.exit_date.isnot(None))
            if strategy:
                q = q.filter(TradeRecord.strategy == strategy.value)
            if since:
                q = q.filter(TradeRecord.exit_date >= since)
            return [self._record_to_entry(r) for r in q.order_by(TradeRecord.exit_date.desc()).all()]

    def get_trade(self, trade_id: int) -> TradeEntry | None:
        with SessionLocal() as db:
            record = db.query(TradeRecord).filter(TradeRecord.id == trade_id).first()
            return self._record_to_entry(record) if record else None

    def get_phantom_trades(
        self,
        strategy: StrategyName | None = None,
        since: date | None = None,
    ) -> list[PhantomTrade]:
        with SessionLocal() as db:
            q = db.query(PhantomTradeRecord)
            if strategy:
                q = q.filter(PhantomTradeRecord.strategy == strategy.value)
            if since:
                q = q.filter(PhantomTradeRecord.signal_date >= since)
            return [self._phantom_to_model(r) for r in q.order_by(PhantomTradeRecord.signal_date.desc()).all()]

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
                    alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "stop_hit", "price": current_price})
                elif current_price >= trade.target_1:
                    alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "target_hit", "price": current_price})
                elif trade.stop_loss > 0 and current_price <= trade.stop_loss * 1.01:
                    alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "approaching_stop", "price": current_price})
            else:
                if current_price >= trade.stop_loss:
                    alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "stop_hit", "price": current_price})
                elif current_price <= trade.target_1:
                    alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "target_hit", "price": current_price})
                elif trade.stop_loss > 0 and current_price >= trade.stop_loss * 0.99:
                    alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "approaching_stop", "price": current_price})

            if hold_days >= trade.max_hold_days:
                alerts.append({"trade_id": trade.id, "ticker": trade.ticker, "type": "time_stop", "hold_days": hold_days})

        return alerts

    def update_phantom_outcomes(self) -> int:
        """Re-evaluate open phantoms against current prices. Returns count updated."""
        updated = 0
        with SessionLocal() as db:
            phantoms = db.query(PhantomTradeRecord).filter(
                PhantomTradeRecord.phantom_exit_date.is_(None),
            ).all()
            for p in phantoms:
                days_since = (date.today() - p.signal_date).days
                if days_since < 1:
                    continue
                try:
                    df = self._fetcher.get_daily_ohlcv(p.ticker, period="3mo")
                    if df.empty:
                        continue
                    current_price = float(df["Close"].iloc[-1])
                except Exception:
                    continue

                hit_stop = (p.direction == "long" and current_price <= p.stop_suggested) or \
                           (p.direction == "short" and current_price >= p.stop_suggested)
                hit_target = (p.direction == "long" and current_price >= p.target_suggested) or \
                             (p.direction == "short" and current_price <= p.target_suggested)

                if hit_stop or hit_target or days_since > 30:
                    exit_price = current_price
                    mult = 1.0 if p.direction == "long" else -1.0
                    pnl_pct = mult * (exit_price - p.entry_price_suggested) / p.entry_price_suggested * 100

                    p.phantom_exit_date = date.today()
                    p.phantom_exit_price = exit_price
                    p.phantom_pnl_pct = round(pnl_pct, 4)
                    p.phantom_outcome = "would_have_won" if pnl_pct > 0 else "would_have_lost"
                    updated += 1

            db.commit()
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
    def _record_to_entry(r: TradeRecord) -> TradeEntry:
        return TradeEntry(
            id=r.id,
            ticker=r.ticker,
            direction=r.direction,
            strategy=StrategyName(r.strategy),
            signal_score=r.signal_score,
            regime_at_entry=r.regime_at_entry,
            entry_date=r.entry_date,
            entry_price=r.entry_price,
            shares=r.shares,
            position_size_pct=r.position_size_pct,
            stop_loss=r.stop_loss,
            target_1=r.target_1,
            target_2=r.target_2,
            max_hold_days=r.max_hold_days,
            atr_at_entry=r.atr_at_entry,
            vix_at_entry=r.vix_at_entry,
            vol_regime_at_entry=r.vol_regime_at_entry,
            kelly_fraction_used=r.kelly_fraction_used,
            exit_date=r.exit_date,
            exit_price=r.exit_price,
            exit_reason=r.exit_reason,
            pnl_dollars=r.pnl_dollars,
            pnl_percent=r.pnl_percent,
            hold_days=r.hold_days,
            entry_notes=r.entry_notes or "",
            exit_notes=r.exit_notes or "",
        )

    @staticmethod
    def _phantom_to_model(r: PhantomTradeRecord) -> PhantomTrade:
        return PhantomTrade(
            id=r.id,
            ticker=r.ticker,
            direction=r.direction,
            strategy=StrategyName(r.strategy),
            signal_score=r.signal_score,
            signal_date=r.signal_date,
            entry_price_suggested=r.entry_price_suggested,
            stop_suggested=r.stop_suggested,
            target_suggested=r.target_suggested,
            pass_reason=r.pass_reason or "",
            phantom_exit_date=r.phantom_exit_date,
            phantom_exit_price=r.phantom_exit_price,
            phantom_pnl_pct=r.phantom_pnl_pct,
            phantom_outcome=r.phantom_outcome,
        )
