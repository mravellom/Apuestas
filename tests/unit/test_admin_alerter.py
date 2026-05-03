"""Tests del despacho de alertas admin via Telegram."""

from app import admin_alerter


class TestSendAdminAlert:
    async def test_silenced_when_chat_id_missing(self, monkeypatch, caplog):
        monkeypatch.setattr(admin_alerter.settings, "ADMIN_TELEGRAM_CHAT_ID", "")
        monkeypatch.setattr(admin_alerter.settings, "TELEGRAM_BOT_TOKEN", "tok")

        ok = await admin_alerter.send_admin_alert("test message")
        assert ok is False
        # Debe loguear WARNING para que el operador note el silenciamiento.
        assert any("silenced" in r.message.lower() for r in caplog.records)

    async def test_silenced_when_token_missing(self, monkeypatch):
        monkeypatch.setattr(admin_alerter.settings, "ADMIN_TELEGRAM_CHAT_ID", "abc")
        monkeypatch.setattr(admin_alerter.settings, "TELEGRAM_BOT_TOKEN", "")
        ok = await admin_alerter.send_admin_alert("test")
        assert ok is False

    async def test_dispatches_to_telegram_when_configured(self, monkeypatch):
        monkeypatch.setattr(admin_alerter.settings, "ADMIN_TELEGRAM_CHAT_ID", "789")
        monkeypatch.setattr(admin_alerter.settings, "TELEGRAM_BOT_TOKEN", "tok")

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            text = "ok"

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                captured["url"] = url
                captured["json"] = json
                return FakeResponse()

        monkeypatch.setattr(admin_alerter.httpx, "AsyncClient", FakeClient)

        ok = await admin_alerter.send_admin_alert("hello admin")
        assert ok is True
        assert "tok" in captured["url"]
        assert captured["json"]["chat_id"] == "789"
        assert captured["json"]["text"] == "hello admin"

    async def test_swallows_exceptions(self, monkeypatch, caplog):
        monkeypatch.setattr(admin_alerter.settings, "ADMIN_TELEGRAM_CHAT_ID", "1")
        monkeypatch.setattr(admin_alerter.settings, "TELEGRAM_BOT_TOKEN", "t")

        class CrashingClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                raise RuntimeError("network down")

        monkeypatch.setattr(admin_alerter.httpx, "AsyncClient", CrashingClient)

        # No debe lanzar — un fallo del alerter NO debe romper el job que
        # disparó la alerta.
        ok = await admin_alerter.send_admin_alert("urgent")
        assert ok is False
        assert any("network down" in r.message for r in caplog.records)

    async def test_returns_false_on_telegram_error_status(self, monkeypatch, caplog):
        monkeypatch.setattr(admin_alerter.settings, "ADMIN_TELEGRAM_CHAT_ID", "1")
        monkeypatch.setattr(admin_alerter.settings, "TELEGRAM_BOT_TOKEN", "t")

        class ErrResp:
            status_code = 400
            text = '{"ok":false,"error_code":400,"description":"Bad Request"}'

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                return ErrResp()

        monkeypatch.setattr(admin_alerter.httpx, "AsyncClient", FakeClient)

        ok = await admin_alerter.send_admin_alert("oops")
        assert ok is False
        assert any("400" in r.message for r in caplog.records)
