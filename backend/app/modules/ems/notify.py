"""Alert delivery: Slack / Mattermost incoming webhooks, Telegram bot, e-mail (SMTP)."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, ClassVar

import httpx
import structlog

from app.core.crypto import decrypt_json
from app.modules.ems.models import Alert, NotificationChannel

log = structlog.get_logger("notify")
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
ICON = {"warning": "⚠️", "critical": "🔴", "info": "ℹ️"}


class Notifier:
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None  # tests inject a mock

    @classmethod
    def text(cls, alert: Alert, project_name: str, base_url: str = "") -> str:
        link = f"\n{base_url}/ems?alert={alert.id}" if base_url else ""
        return f"{ICON.get(alert.severity, '')} [{project_name}] {alert.title}\n{alert.message}{link}"

    @classmethod
    async def send(cls, channel: NotificationChannel, text: str, subject: str) -> None:
        secrets = decrypt_json(channel.secrets_encrypted)
        cfg = channel.config
        if channel.kind in ("slack", "mattermost"):
            await cls._post(secrets["webhook_url"], {"text": text})
        elif channel.kind == "telegram":
            url = f"{cfg.get('api_url', 'https://api.telegram.org')}/bot{secrets['bot_token']}/sendMessage"
            await cls._post(url, {"chat_id": cfg["chat_id"], "text": text, "disable_web_page_preview": True})
        elif channel.kind == "email":
            await asyncio.to_thread(_smtp_send, cfg, secrets, subject, text)
        else:  # pragma: no cover
            raise ValueError(channel.kind)

    @classmethod
    async def _post(cls, url: str, payload: dict[str, Any]) -> None:
        async with httpx.AsyncClient(transport=cls.transport, timeout=15) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()


def _smtp_send(cfg: dict[str, Any], secrets: dict[str, Any], subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = ", ".join(cfg["to"]) if isinstance(cfg["to"], list) else cfg["to"]
    msg.set_content(text)
    port = int(cfg.get("port", 587))
    with smtplib.SMTP(cfg["host"], port, timeout=20) as s:
        if cfg.get("starttls", True):
            s.starttls(context=ssl.create_default_context())
        if cfg.get("user"):
            s.login(cfg["user"], secrets.get("password", ""))
        s.send_message(msg)


def wants(channel: NotificationChannel, alert: Alert) -> bool:
    if not channel.enabled:
        return False
    if channel.project_ids is not None and alert.project_id not in channel.project_ids:
        return False
    return SEVERITY_RANK.get(alert.severity, 0) >= SEVERITY_RANK.get(channel.min_severity, 1)


async def dispatch(
    channels: list[NotificationChannel], alert: Alert, project_name: str, base_url: str = ""
) -> list[str]:
    """Sends to every matching channel; failures are logged, never block validation."""
    sent = []
    text = Notifier.text(alert, project_name, base_url)
    for ch in channels:
        if not wants(ch, alert):
            continue
        try:
            await Notifier.send(ch, text, f"[{project_name}] {alert.title}")
            sent.append(ch.name)
        except Exception as exc:
            log.warning("notification failed", channel=ch.name, kind=ch.kind, error=str(exc))
    return sent
