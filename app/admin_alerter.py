"""
Alertas operacionales al admin.

Diferente del flujo de notificaciones de oportunidades: estas son alertas
de **infraestructura** (jobs falando, API key inválida, etc.) que deben
llegar al operador del sistema, no a usuarios premium.

Canal soportado: Telegram. Si el admin quiere email/webhook en el futuro,
se generaliza igual que `Notifier`.

Diseño:
- Best-effort. Si el envío falla, se loguea como ERROR y se traga la
  excepción — un fallo en el alerter NO debe romper el job que disparó
  la alerta.
- Lee `ADMIN_TELEGRAM_CHAT_ID` de settings. Si está vacío, no hace nada
  (logging de WARNING para que el operador sepa que está silenciado).
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_admin_alert(message: str) -> bool:
    """
    Envía un mensaje plano al chat admin configurado. Devuelve True si
    el envío fue aceptado por Telegram.

    No lanza. Errores se loguean. El caller no debería decidir lógica de
    negocio sobre el retorno — es informativo.
    """
    chat_id = settings.ADMIN_TELEGRAM_CHAT_ID
    token = settings.TELEGRAM_BOT_TOKEN

    if not chat_id or not token:
        logger.warning(
            "Admin alert silenced: ADMIN_TELEGRAM_CHAT_ID o TELEGRAM_BOT_TOKEN "
            "no configurados. Mensaje: %s",
            message[:200],
        )
        return False

    url = _TELEGRAM_API_URL.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
            )
        if response.status_code == 200:
            return True
        logger.error(
            "Admin alert failed: Telegram %d %s",
            response.status_code,
            response.text[:200],
        )
        return False
    except Exception as e:
        # Network, DNS, timeout — no hay nada útil que el caller pueda
        # hacer al respecto. Logueamos y seguimos.
        logger.error("Admin alert exception: %s", e)
        return False
