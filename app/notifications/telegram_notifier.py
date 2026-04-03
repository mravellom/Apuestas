"""Notificador via Telegram Bot API."""

import logging

import httpx

from app.config import settings
from app.notifications.base import NotificationPayload, Notifier

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str | None = None):
        self.bot_token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        self.client = httpx.AsyncClient(timeout=10.0)

    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        """
        Envía notificación por Telegram.

        Args:
            destination: chat_id del usuario o grupo
            payload: datos de la oportunidad
        """
        if not self.bot_token:
            logger.warning("Telegram bot token not configured")
            return False

        url = TELEGRAM_API_URL.format(token=self.bot_token)
        message = payload.format_message()

        try:
            response = await self.client.post(url, json={
                "chat_id": destination,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })

            if response.status_code == 200:
                logger.info("Telegram notification sent to %s", destination)
                return True
            else:
                logger.error(
                    "Telegram API error %d: %s", response.status_code, response.text
                )
                return False
        except Exception as e:
            logger.error("Failed to send Telegram notification: %s", e)
            return False

    async def close(self):
        await self.client.aclose()
