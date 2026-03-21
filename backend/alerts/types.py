"""Alert type definitions — what the system can notify you about."""

from enum import StrEnum


class AlertPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class AlertType(StrEnum):
    MORNING_BRIEF = "morning_brief"
    NEW_SIGNAL = "new_signal"
    ENTRY_ZONE_HIT = "entry_zone_hit"
    APPROACHING_STOP = "approaching_stop"
    STOP_HIT = "stop_hit"
    TARGET_HIT = "target_hit"
    TIME_STOP = "time_stop"
    REGIME_SHIFT = "regime_shift"
    DRAWDOWN_WARNING = "drawdown_warning"
    CORRELATION_SPIKE = "correlation_spike"
    SIGNAL_INVALIDATED = "signal_invalidated"
    WEEKLY_REVIEW = "weekly_review"


ALERT_CONFIG: dict[AlertType, dict] = {
    AlertType.MORNING_BRIEF: {
        "priority": AlertPriority.HIGH,
        "channels": ["ntfy", "slack", "email"],
        "throttle_minutes": 0,
        "description": "Daily pre-market overview with top signals and active trade updates",
    },
    AlertType.NEW_SIGNAL: {
        "priority": AlertPriority.HIGH,
        "channels": ["ntfy", "slack"],
        "throttle_minutes": 60,
        "description": "A strategy generated a high-conviction signal",
    },
    AlertType.ENTRY_ZONE_HIT: {
        "priority": AlertPriority.HIGH,
        "channels": ["ntfy"],
        "throttle_minutes": 30,
        "description": "A remind-later signal — stock hit the entry zone",
    },
    AlertType.APPROACHING_STOP: {
        "priority": AlertPriority.URGENT,
        "channels": ["ntfy", "slack"],
        "throttle_minutes": 15,
        "description": "Active trade price within 1% of stop-loss",
    },
    AlertType.STOP_HIT: {
        "priority": AlertPriority.URGENT,
        "channels": ["ntfy", "slack", "email"],
        "throttle_minutes": 0,
        "description": "Active trade breached stop-loss — exit now",
    },
    AlertType.TARGET_HIT: {
        "priority": AlertPriority.HIGH,
        "channels": ["ntfy", "slack"],
        "throttle_minutes": 0,
        "description": "Active trade reached profit target",
    },
    AlertType.TIME_STOP: {
        "priority": AlertPriority.HIGH,
        "channels": ["ntfy", "slack"],
        "throttle_minutes": 0,
        "description": "Active trade exceeded max hold period",
    },
    AlertType.REGIME_SHIFT: {
        "priority": AlertPriority.HIGH,
        "channels": ["slack", "email"],
        "throttle_minutes": 0,
        "description": "Market regime classification changed",
    },
    AlertType.DRAWDOWN_WARNING: {
        "priority": AlertPriority.URGENT,
        "channels": ["ntfy", "slack", "email"],
        "throttle_minutes": 60,
        "description": "Portfolio drawdown exceeded warning threshold",
    },
    AlertType.CORRELATION_SPIKE: {
        "priority": AlertPriority.MEDIUM,
        "channels": ["slack"],
        "throttle_minutes": 120,
        "description": "Portfolio positions became highly correlated",
    },
    AlertType.SIGNAL_INVALIDATED: {
        "priority": AlertPriority.MEDIUM,
        "channels": ["ntfy"],
        "throttle_minutes": 30,
        "description": "A pending signal's conditions changed",
    },
    AlertType.WEEKLY_REVIEW: {
        "priority": AlertPriority.MEDIUM,
        "channels": ["email"],
        "throttle_minutes": 0,
        "description": "Weekly performance summary",
    },
}
