from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── API Keys ──
    finnhub_api_key: str = ""
    fmp_api_key: str = ""
    polygon_api_key: str = ""
    uw_api_key: str = ""
    quiver_api_key: str = ""
    steadyapi_api_key: str = ""
    fred_api_key: str = ""

    # ── Contact (SEC EDGAR requires User-Agent with email) ──
    sec_edgar_email: str = ""

    # ── Feature Flags ──
    enable_polygon: bool = False
    enable_smart_money: bool = False
    enable_steadyapi: bool = False
    enable_quiver: bool = False
    enable_intraday: bool = False
    paper_trade_mode: bool = True

    # ── Strategy Enable/Disable ──
    enable_stat_arb: bool = True
    enable_catalyst: bool = True
    enable_cross_asset: bool = True
    enable_flow: bool = False
    enable_gap_reversion: bool = False

    # ── Risk Parameters ──
    initial_capital: float = 100_000.0
    max_position_pct: float = 0.08
    max_gross_exposure: float = 2.0
    max_drawdown_pct: float = 0.15
    kelly_fraction: float = 0.5
    tail_hedge_pct: float = 0.03

    # ── Execution Mode ──
    execution_mode: str = "advisory"

    # ── Database ──
    database_url: str = "sqlite:///./quantpulse.db"

    # ── Alert Delivery ──
    ntfy_topic: str = "quantpulse-alerts"
    ntfy_priority: str = "high"
    slack_webhook_url: str = ""
    slack_channel: str = "trading"
    sendgrid_api_key: str = ""
    alert_email_to: str = ""

    # ── Alert Preferences ──
    alert_market_hours_only: bool = True
    alert_throttle_minutes: int = 30
    alert_min_score_for_push: int = 65

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
