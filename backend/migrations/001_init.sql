-- QuantPulse v2 — Full schema migration
-- Run this once in Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- Creates all existing tables + new pre-fetch data tables

-- ════════════════════════════════════════════════════════════
-- EXISTING TABLES (migrated from SQLAlchemy)
-- ════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    strategy VARCHAR(20) NOT NULL,
    signal_score DOUBLE PRECISION NOT NULL,
    regime_at_entry VARCHAR(20) NOT NULL,

    entry_date DATE NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    shares INTEGER NOT NULL,
    position_size_pct DOUBLE PRECISION NOT NULL,

    stop_loss DOUBLE PRECISION NOT NULL,
    target_1 DOUBLE PRECISION NOT NULL,
    target_2 DOUBLE PRECISION,
    max_hold_days INTEGER NOT NULL,
    atr_at_entry DOUBLE PRECISION NOT NULL,
    vix_at_entry DOUBLE PRECISION NOT NULL,
    vol_regime_at_entry VARCHAR(20) NOT NULL,
    kelly_fraction_used DOUBLE PRECISION NOT NULL,

    exit_date DATE,
    exit_price DOUBLE PRECISION,
    exit_reason VARCHAR(30),
    pnl_dollars DOUBLE PRECISION,
    pnl_percent DOUBLE PRECISION,
    hold_days INTEGER,

    entry_notes TEXT DEFAULT '',
    exit_notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);


CREATE TABLE IF NOT EXISTS phantom_trades (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    strategy VARCHAR(20) NOT NULL,
    signal_score DOUBLE PRECISION NOT NULL,
    signal_date DATE NOT NULL,
    entry_price_suggested DOUBLE PRECISION NOT NULL,
    stop_suggested DOUBLE PRECISION NOT NULL,
    target_suggested DOUBLE PRECISION NOT NULL,
    pass_reason TEXT DEFAULT '',

    regime VARCHAR(20),
    vix_at_signal DOUBLE PRECISION,
    atr_at_signal DOUBLE PRECISION,
    conviction DOUBLE PRECISION,
    signal_id INTEGER,

    phantom_exit_date DATE,
    phantom_exit_price DOUBLE PRECISION,
    phantom_pnl_pct DOUBLE PRECISION,
    phantom_outcome VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_phantom_ticker ON phantom_trades(ticker);


CREATE TABLE IF NOT EXISTS regimes (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    regime VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    vix DOUBLE PRECISION NOT NULL,
    breadth_pct DOUBLE PRECISION NOT NULL,
    adx DOUBLE PRECISION NOT NULL,
    strategy_weights_json TEXT NOT NULL,
    regime_probabilities_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regimes_timestamp ON regimes(timestamp);


CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    strategy VARCHAR(20) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    signal_score DOUBLE PRECISION NOT NULL,
    conviction DOUBLE PRECISION NOT NULL,
    kelly_size_pct DOUBLE PRECISION NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    stop_loss DOUBLE PRECISION NOT NULL,
    target DOUBLE PRECISION NOT NULL,
    edge_reason TEXT NOT NULL,
    kill_condition TEXT NOT NULL,
    acted_on BOOLEAN DEFAULT FALSE,

    regime VARCHAR(20),
    vix_at_signal DOUBLE PRECISION,
    max_hold_days INTEGER
);

CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);


CREATE TABLE IF NOT EXISTS data_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key VARCHAR(200) NOT NULL UNIQUE,
    data_json TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache_key ON data_cache(cache_key);


-- ════════════════════════════════════════════════════════════
-- NEW PRE-FETCH DATA TABLES
-- ════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS market_prices (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    price_date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    source VARCHAR(20) DEFAULT 'yfinance',
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, price_date)
);

CREATE INDEX IF NOT EXISTS idx_market_prices_ticker ON market_prices(ticker);
CREATE INDEX IF NOT EXISTS idx_market_prices_date ON market_prices(price_date);
CREATE INDEX IF NOT EXISTS idx_market_prices_ticker_date ON market_prices(ticker, price_date);


CREATE TABLE IF NOT EXISTS cross_asset_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    price_date DATE NOT NULL,
    close DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, price_date)
);

CREATE INDEX IF NOT EXISTS idx_cross_asset_symbol_date ON cross_asset_prices(symbol, price_date);


CREATE TABLE IF NOT EXISTS fundamentals (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    market_cap DOUBLE PRECISION,
    pe_ratio DOUBLE PRECISION,
    forward_pe DOUBLE PRECISION,
    eps DOUBLE PRECISION,
    revenue_growth DOUBLE PRECISION,
    profit_margin DOUBLE PRECISION,
    sector VARCHAR(50),
    industry VARCHAR(100),
    avg_volume BIGINT,
    shares_outstanding BIGINT,
    analyst_target DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker ON fundamentals(ticker);


CREATE TABLE IF NOT EXISTS earnings_data (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    report_date DATE,
    fiscal_quarter VARCHAR(10),
    eps_actual DOUBLE PRECISION,
    eps_estimate DOUBLE PRECISION,
    surprise_pct DOUBLE PRECISION,
    revenue_actual DOUBLE PRECISION,
    revenue_estimate DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, report_date)
);

CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_data(ticker);
CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings_data(report_date);


CREATE TABLE IF NOT EXISTS analyst_revisions (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    revision_date DATE,
    firm VARCHAR(100),
    action VARCHAR(30),
    rating_from VARCHAR(30),
    rating_to VARCHAR(30),
    price_target DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_revisions_ticker ON analyst_revisions(ticker);
CREATE INDEX IF NOT EXISTS idx_revisions_date ON analyst_revisions(revision_date);


CREATE TABLE IF NOT EXISTS news_sentiment (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    headline TEXT NOT NULL,
    source_name VARCHAR(100),
    published_at TIMESTAMPTZ,
    sentiment_score DOUBLE PRECISION,
    sentiment_label VARCHAR(20),
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_ticker ON news_sentiment(ticker);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_sentiment(published_at);


CREATE TABLE IF NOT EXISTS options_flow (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    flow_timestamp TIMESTAMPTZ,
    flow_type VARCHAR(20),
    side VARCHAR(10),
    strike DOUBLE PRECISION,
    expiry DATE,
    premium DOUBLE PRECISION,
    volume INTEGER,
    open_interest INTEGER,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_flow_ticker ON options_flow(ticker);
CREATE INDEX IF NOT EXISTS idx_flow_timestamp ON options_flow(flow_timestamp);


CREATE TABLE IF NOT EXISTS dark_pool (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    report_date DATE NOT NULL,
    volume BIGINT,
    short_volume BIGINT,
    short_ratio DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, report_date)
);

CREATE INDEX IF NOT EXISTS idx_dark_pool_ticker ON dark_pool(ticker);


CREATE TABLE IF NOT EXISTS insider_trades (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    insider_name VARCHAR(200),
    title VARCHAR(100),
    transaction_date DATE,
    transaction_type VARCHAR(30),
    shares DOUBLE PRECISION,
    price DOUBLE PRECISION,
    value DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_insider_date ON insider_trades(transaction_date);


CREATE TABLE IF NOT EXISTS universe (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(200),
    sector VARCHAR(50),
    sub_industry VARCHAR(100),
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_universe_ticker ON universe(ticker);
CREATE INDEX IF NOT EXISTS idx_universe_sector ON universe(sector);
