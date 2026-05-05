"""Notificador via Webhook (HTTP POST)."""

import logging
from dataclasses import asdict

import httpx

from app.notifications.base import NotificationPayload, Notifier

logger = logging.getLogger(__name__)


class WebhookNotifier(Notifier):
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)

    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        """
        Envía notificación via HTTP POST a un webhook.

        Args:
            destination: URL del webhook
            payload: datos de la oportunidad (se envía como JSON)
        """
        try:
            data = asdict(payload)
            data["message"] = payload.format_message()

            response = await self.client.post(
                destination,
                json=data,
                headers={"Content-Type": "application/json"},
            )

            if 200 <= response.status_code < 300:
                logger.info("Webhook notification sent to %s", destination)
                return True
            else:
                logger.error(
                    "Webhook error %d: %s", response.status_code, response.text
                )
                return False
        except Exception:
            logger.exception("Failed to send webhook notification to %s", destination)
            return False

    async def close(self):
        await self.client.aclose()
