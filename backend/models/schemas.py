from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Regime(StrEnum):
    BULL_TREND = "bull_trend"
    BULL_CHOPPY = "bull_choppy"
    BEAR_TREND = "bear_trend"
    CRISIS = "crisis"
    MEAN_REVERTING = "mean_reverting"


class StrategyName(StrEnum):
    STAT_ARB = "stat_arb"
    CATALYST = "catalyst"
    CROSS_ASSET = "cross_asset"
    FLOW = "flow"
    INTRADAY = "intraday"


class VolRegime(StrEnum):
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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

    regime: str | None = None
    vix_at_signal: float | None = None
    atr_at_signal: float | None = None
    conviction: float | None = None
    signal_id: int | None = None

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


# ── Level 8 Signal Card ──


class TradabilityResult(BaseModel):
    passed: bool
    projected_slippage_bps: float
    pct_adv_used: float
    borrow_available: bool
    spread_acceptable: bool
    reasons: list[str]


class ShadowEvidence(BaseModel):
    phantom_count: int
    win_rate: float
    avg_pnl_pct: float
    avg_hold_days: float
    realized_sharpe: float
    best_trade_pct: float
    worst_trade_pct: float
    has_enough_data: bool


class StrategyHealthSummary(BaseModel):
    status: str
    rolling_sharpe_60d: float
    rolling_win_rate_60d: float
    phantom_count_60d: int
    slippage_deteriorating: bool
    regime_alignment: str
    size_adjustment: float


class EnrichedSignal(BaseModel):
    signal: TradeSignal
    tradability: TradabilityResult
    shadow_evidence: ShadowEvidence
    strategy_health: StrategyHealthSummary
    regime: str
    regime_alignment: str
    recommended_size_mode: str
    size_adjustment_reason: str
    final_recommendation: str
    shadow_size_factor: float = 1.0


class ScannerResult(BaseModel):
    timestamp: datetime
    regime: Regime
    signals: list[EnrichedSignal]
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


# ── Backtest Models ──


class BacktestConfig(BaseModel):
    train_days: int = 504
    test_days: int = 126
    initial_capital: float = 100_000.0
    commission_per_share: float = 0.005
    slippage_pct: float = 0.0005
    short_borrow_rate: float = 0.005
    risk_free_rate: float = 0.05


class BacktestTrade(BaseModel):
    ticker: str
    direction: Literal["long", "short"]
    strategy: StrategyName
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    shares: int
    position_size_pct: float
    pnl_dollars: float
    pnl_pct: float
    hold_days: int
    exit_reason: str
    conviction: float
    signal_score: float


class BacktestResult(BaseModel):
    strategy: StrategyName
    config: BacktestConfig
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    max_drawdown_pct: float
    total_trades: int
    avg_hold_days: float
    equity_curve: list[dict]
    trades: list[BacktestTrade]
    monthly_returns: list[dict]
    regime_performance: dict[str, dict]
    validation: dict
    run_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Signal Sub-Models ──


class EarningsSignal(BaseModel):
    ticker: str
    report_date: date
    eps_actual: float
    eps_estimate: float
    surprise_pct: float
    earnings_day_gap_pct: float
    revision_trend_pre: float = 0.0
    guidance_raised: bool = False
    historical_drift_avg: float = 0.0
    composite_score: float = 0.0


class RevisionSignal(BaseModel):
    ticker: str
    as_of_date: date
    breadth_30d: float
    acceleration_15d: float
    price_moved_pct: float
    composite_score: float = 0.0
