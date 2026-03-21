"""Alert dispatcher — routes alerts to the appropriate channels with throttling."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from backend.alerts.channels import ALL_CHANNELS
from backend.alerts.types import ALERT_CONFIG, AlertPriority, AlertType

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Central alert routing engine with per-type throttling."""

    def __init__(self) -> None:
        self._last_sent: dict[str, datetime] = {}

    def dispatch(
        self,
        alert_type: AlertType,
        title: str,
        body: str,
        override_priority: AlertPriority | None = None,
    ) -> dict[str, bool]:
        """Send an alert through configured channels, respecting throttle rules.

        Returns: {channel_name: success_bool}
        """
        config = ALERT_CONFIG.get(alert_type)
        if config is None:
            logger.warning("Unknown alert type: %s", alert_type)
            return {}

        throttle_key = f"{alert_type.value}"
        throttle_minutes = config.get("throttle_minutes", 0)
        if throttle_minutes > 0:
            last = self._last_sent.get(throttle_key)
            if last and (datetime.now(UTC) - last) < timedelta(minutes=throttle_minutes):
                logger.debug("Alert %s throttled (last sent %s)", alert_type.value, last)
                return {}

        priority = (override_priority or config["priority"]).value
        channels = config.get("channels", [])
        results: dict[str, bool] = {}

        for ch_name in channels:
            channel = ALL_CHANNELS.get(ch_name)
            if channel is None:
                continue
            if not channel.is_configured:
                results[ch_name] = False
                continue
            results[ch_name] = channel.send(title=title, body=body, priority=priority)

        if any(results.values()):
            self._last_sent[throttle_key] = datetime.now(UTC)

        logger.info("Alert dispatched: %s → %s", alert_type.value, results)
        return results

    def send_morning_brief(self, signals_summary: str, active_trades_summary: str, regime_info: str) -> dict[str, bool]:
        body = f"REGIME: {regime_info}\n\nTOP SIGNALS:\n{signals_summary}\n\nACTIVE TRADES:\n{active_trades_summary}"
        return self.dispatch(AlertType.MORNING_BRIEF, title="QuantPulse Morning Brief", body=body)

    def send_new_signal(
        self, ticker: str, strategy: str, direction: str, score: float, entry: float
    ) -> dict[str, bool]:
        body = f"{direction.upper()} {ticker} — {strategy} (score: {score:.0f})\nEntry zone: ${entry:.2f}"
        return self.dispatch(AlertType.NEW_SIGNAL, title=f"New Signal: {ticker}", body=body)

    def send_stop_alert(
        self, ticker: str, current_price: float, stop_price: float, approaching: bool = False
    ) -> dict[str, bool]:
        alert_type = AlertType.APPROACHING_STOP if approaching else AlertType.STOP_HIT
        distance_pct = abs(current_price - stop_price) / stop_price * 100
        verb = "approaching" if approaching else "HIT"
        body = f"{ticker} {verb} stop at ${stop_price:.2f}\nCurrent: ${current_price:.2f} ({distance_pct:.1f}% away)"
        title = f"{'⚠' if approaching else '🔴'} {ticker} Stop {'Warning' if approaching else 'HIT'}"
        return self.dispatch(alert_type, title=title, body=body)

    def send_target_alert(self, ticker: str, current_price: float, target_price: float) -> dict[str, bool]:
        body = f"{ticker} reached target at ${target_price:.2f}\nCurrent: ${current_price:.2f}\nConsider taking profit."
        return self.dispatch(AlertType.TARGET_HIT, title=f"🟢 {ticker} Target Hit", body=body)

    def send_regime_shift(self, old_regime: str, new_regime: str, confidence: float) -> dict[str, bool]:
        body = f"Regime shifted: {old_regime} → {new_regime} (confidence: {confidence:.0%})\nReview active trades and strategy weights."
        return self.dispatch(AlertType.REGIME_SHIFT, title="Regime Change Detected", body=body)

    def send_drawdown_warning(self, drawdown_pct: float) -> dict[str, bool]:
        body = f"Portfolio down {drawdown_pct:.1f}% from peak.\nConsider reducing exposure or reviewing positions."
        return self.dispatch(
            AlertType.DRAWDOWN_WARNING,
            title=f"Drawdown Warning: {drawdown_pct:.1f}%",
            body=body,
            override_priority=AlertPriority.URGENT,
        )
