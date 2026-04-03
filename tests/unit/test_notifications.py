"""Tests para el sistema de notificaciones."""

from unittest.mock import AsyncMock, patch

from app.notifications.base import NotificationPayload
from app.notifications.telegram_notifier import TelegramNotifier
from app.notifications.webhook_notifier import WebhookNotifier


def make_payload() -> NotificationPayload:
    return NotificationPayload(
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


class TestNotificationPayload:
    def test_format_message(self):
        payload = make_payload()
        msg = payload.format_message()
        assert "Real Madrid" in msg
        assert "Barcelona" in msg
        assert "William Hill" in msg
        assert "2.50" in msg
        assert "8.0%" in msg  # value
        assert "45.0%" in msg  # consensus prob
        assert "5.70%" in msg  # kelly

    def test_format_message_no_kelly(self):
        payload = make_payload()
        payload.kelly_stake_pct = None
        msg = payload.format_message()
        assert "N/A" in msg


class TestTelegramNotifier:
    async def test_send_success(self):
        notifier = TelegramNotifier(bot_token="test-token")
        payload = make_payload()

        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch.object(notifier.client, "post", return_value=mock_response) as mock_post:
            result = await notifier.send("123456", payload)

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "123456" in str(call_kwargs)

    async def test_send_failure(self):
        notifier = TelegramNotifier(bot_token="test-token")
        payload = make_payload()

        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch.object(notifier.client, "post", return_value=mock_response):
            result = await notifier.send("123456", payload)

        assert result is False

    async def test_send_no_token(self):
        notifier = TelegramNotifier(bot_token="")
        payload = make_payload()
        result = await notifier.send("123456", payload)
        assert result is False

    async def test_send_network_error(self):
        notifier = TelegramNotifier(bot_token="test-token")
        payload = make_payload()

        with patch.object(notifier.client, "post", side_effect=Exception("Connection failed")):
            result = await notifier.send("123456", payload)

        assert result is False


class TestWebhookNotifier:
    async def test_send_success(self):
        notifier = WebhookNotifier()
        payload = make_payload()

        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch.object(notifier.client, "post", return_value=mock_response) as mock_post:
            result = await notifier.send("https://example.com/webhook", payload)

        assert result is True
        call_args = mock_post.call_args
        json_data = call_args.kwargs.get("json") or call_args[1].get("json")
        assert json_data["match_home"] == "Real Madrid"
        assert "message" in json_data

    async def test_send_server_error(self):
        notifier = WebhookNotifier()
        payload = make_payload()

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(notifier.client, "post", return_value=mock_response):
            result = await notifier.send("https://example.com/webhook", payload)

        assert result is False
