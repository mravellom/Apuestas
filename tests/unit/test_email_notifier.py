"""Tests para EmailNotifier: SMTP flow, configuración y manejo de errores."""

from unittest.mock import MagicMock, patch

from app.notifications.base import NotificationPayload
from app.notifications.email_notifier import EmailNotifier


def _payload(**overrides) -> NotificationPayload:
    defaults = dict(
        match_home="Real Madrid",
        match_away="Barcelona",
        commence_time="2025-12-15 20:00 UTC",
        market_type="h2h",
        outcome_name="Real Madrid",
        bookmaker_name="William Hill",
        odds_price=2.50,
        value_pct=0.08,
        consensus_prob=0.45,
        kelly_stake_pct=0.057,
    )
    defaults.update(overrides)
    return NotificationPayload(**defaults)


class TestSMTPConfig:
    async def test_send_without_host_returns_false(self):
        notifier = EmailNotifier(smtp_host="", smtp_user="u")
        assert await notifier.send("to@test.com", _payload()) is False

    async def test_send_without_user_returns_false(self):
        notifier = EmailNotifier(smtp_host="mail.test", smtp_user="")
        assert await notifier.send("to@test.com", _payload()) is False


class TestSendSuccess:
    async def test_successful_send_returns_true(self):
        notifier = EmailNotifier(
            smtp_host="mail.test",
            smtp_port=587,
            smtp_user="bot@test.com",
            smtp_password="secret",
            from_email="bot@test.com",
        )

        mock_server = MagicMock()
        # SMTP is a context manager
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_server
        mock_cm.__exit__.return_value = False

        with patch("smtplib.SMTP", return_value=mock_cm) as mock_smtp:
            result = await notifier.send("dest@test.com", _payload())

        assert result is True
        mock_smtp.assert_called_once_with("mail.test", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("bot@test.com", "secret")
        mock_server.sendmail.assert_called_once()

        from_arg, to_arg, body_arg = mock_server.sendmail.call_args.args
        assert from_arg == "bot@test.com"
        assert to_arg == "dest@test.com"
        # Body is RFC822 string with expected headers
        assert "Subject:" in body_arg
        assert "Real Madrid" in body_arg
        assert "Barcelona" in body_arg
        # +8.0% value in subject
        assert "+8.0%" in body_arg

    async def test_message_includes_both_plain_and_html_parts(self):
        notifier = EmailNotifier(
            smtp_host="mail.test",
            smtp_user="bot@test.com",
            smtp_password="x",
        )

        mock_server = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_server
        mock_cm.__exit__.return_value = False

        with patch("smtplib.SMTP", return_value=mock_cm):
            await notifier.send("dest@test.com", _payload())

        body = mock_server.sendmail.call_args.args[2]
        assert "text/plain" in body.lower()
        assert "text/html" in body.lower()


class TestSendFailures:
    async def test_smtp_exception_returns_false(self):
        notifier = EmailNotifier(
            smtp_host="mail.test",
            smtp_user="bot@test.com",
            smtp_password="x",
        )
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("nope")):
            assert await notifier.send("dest@test.com", _payload()) is False

    async def test_login_failure_returns_false(self):
        notifier = EmailNotifier(
            smtp_host="mail.test",
            smtp_user="bot@test.com",
            smtp_password="x",
        )

        mock_server = MagicMock()
        mock_server.login.side_effect = Exception("auth failed")
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_server
        mock_cm.__exit__.return_value = False

        with patch("smtplib.SMTP", return_value=mock_cm):
            assert await notifier.send("dest@test.com", _payload()) is False


class TestHtmlRendering:
    def test_html_contains_core_fields(self):
        payload = _payload()
        html = EmailNotifier._to_html(payload)
        assert "Real Madrid" in html
        assert "Barcelona" in html
        assert "2.50" in html
        assert "William Hill" in html
        # Value formatted as +8.0%
        assert "+8.0%" in html
        # Kelly formatted with 2 decimals as percentage
        assert "5.70%" in html

    def test_html_kelly_na_when_none(self):
        payload = _payload(kelly_stake_pct=None)
        html = EmailNotifier._to_html(payload)
        assert "N/A" in html


class TestConstructor:
    def test_defaults_to_settings(self, monkeypatch):
        """Constructor falls back to settings values when args are None."""
        from app.config import settings

        monkeypatch.setattr(settings, "SMTP_HOST", "settings.example", raising=False)
        monkeypatch.setattr(settings, "SMTP_USER", "from-settings@x.com", raising=False)
        monkeypatch.setattr(settings, "SMTP_PORT", 465, raising=False)

        notifier = EmailNotifier()
        assert notifier.smtp_host == "settings.example"
        assert notifier.smtp_user == "from-settings@x.com"
        assert notifier.smtp_port == 465

    def test_explicit_from_email_overrides_settings(self):
        notifier = EmailNotifier(
            smtp_host="h",
            smtp_user="u@x.com",
            smtp_password="p",
            from_email="explicit@x.com",
        )
        assert notifier.from_email == "explicit@x.com"
