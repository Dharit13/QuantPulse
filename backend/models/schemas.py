from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Regime(str, Enum):
    BULL_TREND = "bull_trend"
    BULL_CHOPPY = "bull_choppy"
    BEAR_TREND = "bear_trend"
    CRISIS = "crisis"
    MEAN_REVERTING = "mean_reverting"


class StrategyName(str, Enum):
    STAT_ARB = "stat_arb"
    CATALYST = "catalyst"
    CROSS_ASSET = "cross_asset"
    FLOW = "flow"
    INTRADAY = "intraday"


class VolRegime(str, Enum):
    ULTRA_LOW = "ultra_low"
    LOW = "low"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    EXTREME = "extreme"


# ── Trade Signals ──


class TradeSignal(BaseModel):
    strategy: StrategyName
    ticker: str
    direction: Literal["long", "short"]
    conviction: float = Field(ge=0.0, le=1.0)
    kelly_size_pct: float
    entry_price: float
    stop_loss: float
    target: float
    max_hold_days: int
    edge_reason: str
    kill_condition: str
    expected_sharpe: float
    signal_score: float = Field(ge=0.0, le=100.0, default=50.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Portfolio State ──


class PortfolioState(BaseModel):
    regime: Regime
    regime_confidence: float
    gross_exposure: float
    net_exposure: float
    daily_var: float
    current_drawdown_pct: float
    active_trades: list[TradeSignal]
    strategy_pnl: dict[StrategyName, float]
    total_pnl_ytd: float
    portfolio_sharpe_30d: float


# ── Trade Logging ──


class TradeEntry(BaseModel):
    id: int | None = None
    ticker: str
    direction: Literal["long", "short"]
    strategy: StrategyName
    signal_score: float
    regime_at_entry: Regime

    entry_date: date
    entry_price: float
    shares: int
    position_size_pct: float

    stop_loss: float
    target_1: float
    target_2: float | None = None
    max_hold_days: int
    atr_at_entry: float
    vix_at_entry: float
    vol_regime_at_entry: VolRegime
    kelly_fraction_used: float

    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl_dollars: float | None = None
    pnl_percent: float | None = None
    hold_days: int | None = None

    entry_notes: str = ""
    exit_notes: str = ""


class PhantomTrade(BaseModel):
    id: int | None = None
    ticker: str
    direction: Literal["long", "short"]
    strategy: StrategyName
    signal_score: float
    signal_date: date
    entry_price_suggested: float
    stop_suggested: float
    target_suggested: float
    pass_reason: str = ""

    phantom_exit_date: date | None = None
    phantom_exit_price: float | None = None
    phantom_pnl_pct: float | None = None
    phantom_outcome: str | None = None


# ── Regime Snapshot ──


class RegimeSnapshot(BaseModel):
    timestamp: datetime
    regime: Regime
    confidence: float
    regime_probabilities: dict[str, float]
    vix: float
    breadth_pct: float
    adx: float
    strategy_weights: dict[str, float]


# ── API Response Models ──


class StockAnalysis(BaseModel):
    ticker: str
    current_price: float
    signals: list[TradeSignal]
    regime: Regime
    sector: str
    fundamentals: dict | None = None


class ScannerResult(BaseModel):
    timestamp: datetime
    regime: Regime
    signals: list[TradeSignal]
    total_signals: int


class PerformanceStats(BaseModel):
    total_pnl_dollars: float
    total_pnl_pct: float
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    total_trades: int
    sharpe_ratio: float
    max_drawdown_pct: float
    strategy_breakdown: dict[str, dict]
