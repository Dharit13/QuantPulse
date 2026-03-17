"""Recalibration schedule definitions.

Defines WHEN each parameter recalibrates — from real-time to monthly.
Used by backend/scheduler.py to set up APScheduler jobs.
"""

CALIBRATION_SCHEDULE = {
    "vol_context":         {"interval": "15min", "market_hours_only": True},
    "risk_limits":         {"interval": "15min", "market_hours_only": True},
    "strategy_params":     {"interval": "1h",    "market_hours_only": True},
    "correlation_matrix":  {"interval": "1h",    "market_hours_only": True},
    "regime_detection":    {"interval": "daily",  "time": "07:00 EST"},
    "kelly_fractions":     {"interval": "daily",  "time": "07:00 EST"},
    "strategy_weights":    {"interval": "daily",  "time": "07:00 EST"},
    "regime_thresholds":   {"interval": "weekly",  "day": "sunday"},
    "pair_revalidation":   {"interval": "weekly",  "day": "sunday"},
    "alpha_decay_audit":   {"interval": "weekly",  "day": "sunday"},
    "universe_refresh":    {"interval": "monthly"},
    "full_backtest":       {"interval": "monthly"},
}
