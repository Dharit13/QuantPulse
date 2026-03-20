"""Alert delivery channels — ntfy.sh (push), Slack, email stubs.

ntfy.sh is the primary free push channel. Slack and email degrade
gracefully when credentials are absent.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class AlertChannel(ABC):
    """Base class for all alert delivery channels."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def send(self, title: str, body: str, priority: str = "high") -> bool:
        """Send an alert. Returns True on success."""
        ...

    @property
    def is_configured(self) -> bool:
        return True


class NtfyChannel(AlertChannel):
    """Push notifications via ntfy.sh (free, no account required)."""

    @property
    def name(self) -> str:
        return "ntfy"

    @property
    def is_configured(self) -> bool:
        return bool(settings.ntfy_topic)

    def send(self, title: str, body: str, priority: str = "high") -> bool:
        if not self.is_configured:
            logger.debug("ntfy not configured, skipping")
            return False
        try:
            priority_map = {"low": "2", "medium": "3", "high": "4", "urgent": "5"}
            resp = httpx.post(
                f"https://ntfy.sh/{settings.ntfy_topic}",
                content=body,
                headers={
                    "Title": title,
                    "Priority": priority_map.get(priority, "4"),
                    "Tags": "chart_with_upwards_trend",
                },
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("ntfy alert sent: %s", title)
            return True
        except Exception as e:
            logger.warning("ntfy send failed: %s", e)
            return False


class SlackChannel(AlertChannel):
    """Slack webhook delivery."""

    @property
    def name(self) -> str:
        return "slack"

    @property
    def is_configured(self) -> bool:
        return bool(settings.slack_webhook_url)

    def send(self, title: str, body: str, priority: str = "high") -> bool:
        if not self.is_configured:
            logger.debug("Slack not configured, skipping")
            return False
        try:
            priority_emoji = {
                "urgent": ":rotating_light:",
                "high": ":warning:",
                "medium": ":information_source:",
                "low": ":memo:",
            }
            emoji = priority_emoji.get(priority, ":bell:")
            payload = {
                "channel": settings.slack_channel,
                "text": f"{emoji} *{title}*\n{body}",
            }
            resp = httpx.post(settings.slack_webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Slack alert sent: %s", title)
            return True
        except Exception as e:
            logger.warning("Slack send failed: %s", e)
            return False


class EmailChannel(AlertChannel):
    """Email via SendGrid. Degrades gracefully when not configured."""

    @property
    def name(self) -> str:
        return "email"

    @property
    def is_configured(self) -> bool:
        return bool(settings.sendgrid_api_key and settings.alert_email_to)

    def send(self, title: str, body: str, priority: str = "high") -> bool:
        if not self.is_configured:
            logger.debug("Email not configured, skipping")
            return False
        try:
            resp = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": settings.alert_email_to}]}],
                    "from": {"email": "alerts@quantpulse.local", "name": "QuantPulse"},
                    "subject": f"[QuantPulse] {title}",
                    "content": [{"type": "text/plain", "value": body}],
                },
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Email alert sent: %s", title)
            return True
        except Exception as e:
            logger.warning("Email send failed: %s", e)
            return False


ALL_CHANNELS: dict[str, AlertChannel] = {
    "ntfy": NtfyChannel(),
    "slack": SlackChannel(),
    "email": EmailChannel(),
}
