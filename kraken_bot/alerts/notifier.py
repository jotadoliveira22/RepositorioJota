"""Alert notifications: Telegram and Email."""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Optional

import httpx

from ..config import AlertConfig

logger = logging.getLogger(__name__)


class AlertNotifier:
    """Send alerts via Telegram and/or Email."""

    def __init__(self, config: AlertConfig):
        self.cfg = config
        self._client = httpx.AsyncClient(timeout=10)

    async def send(self, message: str, level: str = "INFO"):
        """Send alert to all configured channels."""
        formatted = f"[{level}] KrakenBot: {message}"
        tasks = []
        if self.cfg.telegram_enabled:
            tasks.append(self._send_telegram(formatted))
        if self.cfg.email_enabled:
            tasks.append(self._send_email(f"KrakenBot Alert [{level}]", formatted))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Alert [{level}]: {message}")

    async def _send_telegram(self, message: str):
        try:
            url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
            resp = await self._client.post(url, json={
                "chat_id": self.cfg.telegram_chat_id,
                "text": message[:4096],
                "parse_mode": "HTML",
            })
            if resp.status_code != 200:
                logger.error(f"Telegram error: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def _send_email(self, subject: str, body: str):
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.cfg.email_from
            msg["To"] = self.cfg.email_to
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._smtp_send, msg)
        except Exception as e:
            logger.error(f"Email send failed: {e}")

    def _smtp_send(self, msg: MIMEText):
        with smtplib.SMTP(self.cfg.email_smtp_host, self.cfg.email_smtp_port) as server:
            server.starttls()
            server.login(self.cfg.email_from, self.cfg.email_password)
            server.send_message(msg)

    async def close(self):
        await self._client.aclose()
