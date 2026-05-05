"""Notificador via Email (SMTP)."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.notifications.base import NotificationPayload, Notifier

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_email: str | None = None,
    ):
        self.smtp_host = smtp_host or getattr(settings, "SMTP_HOST", "")
        self.smtp_port = smtp_port or getattr(settings, "SMTP_PORT", 587)
        self.smtp_user = smtp_user or getattr(settings, "SMTP_USER", "")
        self.smtp_password = smtp_password or getattr(settings, "SMTP_PASSWORD", "")
        self.from_email = from_email or getattr(settings, "SMTP_FROM", self.smtp_user)

    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        """
        Envía notificación por email.

        Args:
            destination: dirección email del destinatario
            payload: datos de la oportunidad
        """
        if not self.smtp_host or not self.smtp_user:
            logger.warning("SMTP not configured, email notification skipped")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = (
                f"ValueBet: {payload.match_home} vs {payload.match_away} "
                f"(+{payload.value_pct * 100:.1f}%)"
            )
            msg["From"] = self.from_email
            msg["To"] = destination

            text_body = payload.format_message()
            html_body = self._to_html(payload)

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, destination, msg.as_string())

            logger.info("Email notification sent to %s", destination)
            return True
        except Exception:
            logger.exception("Failed to send email to %s", destination)
            return False

    @staticmethod
    def _to_html(payload: NotificationPayload) -> str:
        value_str = f"{payload.value_pct * 100:.1f}%"
        prob_str = f"{payload.consensus_prob * 100:.1f}%"
        kelly_str = (
            f"{payload.kelly_stake_pct * 100:.2f}%" if payload.kelly_stake_pct else "N/A"
        )

        return f"""
        <html><body style="font-family: Arial, sans-serif;">
        <h2 style="color: #2d7d46;">⚡ Value Bet Detectada</h2>
        <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Partido</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{payload.match_home} vs {payload.match_away}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Fecha</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{payload.commence_time}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Apuesta</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{payload.outcome_name} ({payload.market_type})</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Bookmaker</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{payload.bookmaker_name}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Cuota</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>{payload.odds_price:.2f}</strong></td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Value</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; color: #2d7d46;"><strong>+{value_str}</strong></td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Prob. consenso</strong></td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{prob_str}</td></tr>
            <tr><td style="padding: 8px;"><strong>Kelly</strong></td>
                <td style="padding: 8px;">{kelly_str}</td></tr>
        </table>
        <p style="color: #888; font-size: 12px; margin-top: 16px;">ValueBet Engine</p>
        </body></html>
        """
