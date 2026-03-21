export interface StrategyActivity {
  signal_count: number;
  active: boolean;
}

export interface StrategyHealthInfo {
  status: string;
  sharpe_60d: number;
  win_rate_60d: number;
  size_adjustment?: number;
}

export interface PortfolioRiskInfo {
  strategy_health?: Record<string, StrategyHealthInfo>;
  correlation_dropped?: string[];
  risk_rejected?: string[];
  health_skipped?: string[];
  portfolio_var_pct?: number;
  expected_sharpe?: number;
  var_adjusted?: boolean;
  sharpe_adjusted?: boolean;
}

export interface RegimeData {
  regime: string;
  confidence: number;
  vix: number;
  breadth_pct: number;
  adx: number;
  regime_probabilities: Record<string, number>;
  strategy_weights: Record<string, number>;
  strategy_activity?: Record<string, StrategyActivity>;
  strategy_health?: Record<string, StrategyHealthInfo>;
}

export interface AIResult {
  result: {
    market_summary?: string;
    strategy_advice?: string;
    action?: string;
    timing?: string;
    news_sentiment?: string;
    picks_summary?: string;
    scan_summary?: string;
    scan_summary_simple?: string;
    top_pick?: string;
    top_pick_simple?: string;
    swing_summary?: string;
    swing_summary_simple?: string;
    top_pick_advice?: string;
    top_pick_advice_simple?: string;
    review?: string;
  };
}

export interface SectorRecommendation {
  sector: string;
  etf: string;
  verdict: "BUY" | "HOLD" | "REDUCE" | "AVOID";
  score: number;
  return_5d: number;
  return_20d: number;
  rsi: number;
}

export interface StockPick {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  score: number;
  why: string;
  entry?: number;
  stop_loss?: number;
  target?: number;
  analyst_target?: number;
  return_20d?: number;
  rsi?: number;
  atr?: number;
}

export interface SectorRecommendations {
  sectors: SectorRecommendation[];
  stock_picks: StockPick[];
}

export interface AnalysisData {
  ticker: string;
  sector: string;
  regime: string;
  resolved_from?: string;
  technicals: {
    current_price: number;
    return_1d: number;
    return_5d: number;
    return_20d: number;
    return_60d: number;
    rsi_14: number;
    atr_14: number;
    atr_pct: number;
    volume_ratio: number;
    trend: string;
    sma_20?: number;
    sma_50?: number;
    sma_200?: number;
    support_20d: number;
    resistance_20d: number;
    low_52w: number;
    high_52w: number;
    pct_from_52w_high: number;
  };
  fundamentals: {
    market_cap?: number;
    pe_ratio?: number;
    forward_pe?: number;
    revenue_growth?: number;
    profit_margin?: number;
    beta?: number;
    eps_trailing?: number;
    eps_forward?: number;
    debt_to_equity?: number;
    analyst_target?: number;
  };
  system_take: {
    bias: string;
    score: number;
    summary: string;
    notes: string[];
    return_outlook?: string;
    already_own_it?: {
      action: string;
      headline: string;
      reasoning: string;
      simple?: string;
      hold_days: number;
      stop_price: number;
      target_price: number;
    };
  };
  sentiment?: {
    article_count: number;
    avg_compound: number;
    pct_positive: number;
    pct_negative: number;
    pct_neutral: number;
    sentiment_label: string;
    composite_score: number;
    strongest_positive: string;
    strongest_negative: string;
  };
  dcf_valuation?: {
    intrinsic_value: number;
    current_price: number;
    upside_pct: number;
    verdict: string;
    margin_of_safety: number;
    reasoning?: string;
    assumptions: {
      fcf_latest: number;
      growth_rate: number;
      discount_rate: number;
      terminal_growth: number;
      shares_outstanding: number;
      projection_years: number;
      net_cash?: number;
    };
  };
  trade_plan: {
    action: string;
    entry_price: number;
    entry_note?: string;
    stop_loss: number;
    target_1: number;
    target_1_pct: number;
    target_2: number;
    target_2_pct: number;
    risk_reward: number;
    hold_period?: string;
    time_to_50pct?: string;
    sizing: {
      shares: number;
      position_value: number;
      position_pct: number;
      max_loss: number;
      gain_at_target_1: number;
      gain_at_target_2?: number;
      note?: string;
    };
  };
  signals: TradeSignal[];
  price_history?: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
}

export interface TradeSignal {
  ticker: string;
  direction: string;
  strategy: string;
  signal_score: number;
  entry_price: number;
  stop_loss: number;
  target: number;
  edge_reason: string;
}

export interface ScanStatus {
  status: "idle" | "scanning" | "done" | "error";
  progress?: number;
  total?: number;
  step?: string;
  error?: string;
  result?: {
    regime?: string;
    signals: TradeSignal[];
  };
}

export interface SwingScanStatus {
  status: "idle" | "scanning" | "done" | "error";
  progress?: number;
  total?: number;
  error?: string;
  result?: {
    quick_trades: SwingTrade[];
    swing_trades: SwingTrade[];
    scan_stats: {
      tickers_scanned: number;
    };
  };
}

export interface SwingTrade {
  ticker: string;
  direction: string;
  entry: number;
  target: number;
  stop: number;
  return_pct: number;
  risk_reward: number;
  hold_days: number;
  score: number;
  risk_level: string;
  catalyst?: string;
  analysis?: string;
}

export type BadgeVariant = "green" | "red" | "amber" | "blue" | "purple" | "gray";

export type BiasType =
  | "bullish"
  | "lean bullish"
  | "cautiously bullish"
  | "neutral"
  | "lean bearish"
  | "bearish";
