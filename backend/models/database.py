from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    pass


class TradeRecord(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    direction = Column(String(5), nullable=False)
    strategy = Column(String(20), nullable=False, index=True)
    signal_score = Column(Float, nullable=False)
    regime_at_entry = Column(String(20), nullable=False)

    entry_date = Column(Date, nullable=False)
    entry_price = Column(Float, nullable=False)
    shares = Column(Integer, nullable=False)
    position_size_pct = Column(Float, nullable=False)

    stop_loss = Column(Float, nullable=False)
    target_1 = Column(Float, nullable=False)
    target_2 = Column(Float, nullable=True)
    max_hold_days = Column(Integer, nullable=False)
    atr_at_entry = Column(Float, nullable=False)
    vix_at_entry = Column(Float, nullable=False)
    vol_regime_at_entry = Column(String(20), nullable=False)
    kelly_fraction_used = Column(Float, nullable=False)

    exit_date = Column(Date, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_reason = Column(String(30), nullable=True)
    pnl_dollars = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)
    hold_days = Column(Integer, nullable=True)

    entry_notes = Column(Text, default="")
    exit_notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class PhantomTradeRecord(Base):
    __tablename__ = "phantom_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    direction = Column(String(5), nullable=False)
    strategy = Column(String(20), nullable=False)
    signal_score = Column(Float, nullable=False)
    signal_date = Column(Date, nullable=False)
    entry_price_suggested = Column(Float, nullable=False)
    stop_suggested = Column(Float, nullable=False)
    target_suggested = Column(Float, nullable=False)
    pass_reason = Column(Text, default="")

    phantom_exit_date = Column(Date, nullable=True)
    phantom_exit_price = Column(Float, nullable=True)
    phantom_pnl_pct = Column(Float, nullable=True)
    phantom_outcome = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RegimeRecord(Base):
    __tablename__ = "regimes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    regime = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)
    vix = Column(Float, nullable=False)
    breadth_pct = Column(Float, nullable=False)
    adx = Column(Float, nullable=False)
    strategy_weights_json = Column(Text, nullable=False)
    regime_probabilities_json = Column(Text, nullable=False)


class SignalRecord(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    strategy = Column(String(20), nullable=False)
    direction = Column(String(5), nullable=False)
    signal_score = Column(Float, nullable=False)
    conviction = Column(Float, nullable=False)
    kelly_size_pct = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    edge_reason = Column(Text, nullable=False)
    kill_condition = Column(Text, nullable=False)
    acted_on = Column(Boolean, default=False)


class CacheRecord(Base):
    __tablename__ = "data_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(200), nullable=False, unique=True, index=True)
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


# ── Engine & Session ──

engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
