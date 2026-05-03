"""Tests del sistema de logging estructurado y correlation IDs."""

import json
import logging

import pytest

from app.log_context import (
    get_job_run_id,
    get_request_id,
    job_run_id_var,
    request_id_var,
)
from app.logging_config import configure_logging
from app.metrics import track_job


@pytest.fixture(autouse=True)
def restore_logging():
    """Cada test arranca con logging limpio y lo deja como estaba al final."""
    yield
    configure_logging(level="WARNING", fmt="text")


class TestContextFilter:
    def test_request_id_propagates_to_logs(self, capsys):
        # `caplog` no aplica nuestro filter; usamos capsys para validar
        # que el formato real en stdout incluye el id.
        configure_logging(level="DEBUG", fmt="text")
        token = request_id_var.set("abc12345")
        try:
            logging.getLogger("test").info("hello")
        finally:
            request_id_var.reset(token)
        out = capsys.readouterr().out
        assert "[req=abc12345]" in out
        assert "hello" in out

    def test_request_id_omitted_when_absent(self, capsys):
        configure_logging(level="DEBUG", fmt="text")
        logging.getLogger("test").info("no context")
        out = capsys.readouterr().out
        # Sin id activo, el formato text no debe incluir el bracket.
        assert "[req=" not in out
        assert "no context" in out

    def test_get_helpers_return_none_outside_scope(self):
        # Sin nadie haber seteado el contextvar, los helpers retornan None.
        assert get_request_id() is None
        assert get_job_run_id() is None


class TestJsonFormatter:
    def test_json_output_includes_required_fields(self, capsys):
        configure_logging(level="INFO", fmt="json")
        token = request_id_var.set("req-id-1")
        try:
            logging.getLogger("test.json").info("hello world")
        finally:
            request_id_var.reset(token)

        captured = capsys.readouterr()
        # Última línea de stdout = el record JSON.
        line = [ln for ln in captured.out.splitlines() if ln.strip()][-1]
        record = json.loads(line)
        assert record["level"] == "INFO"
        assert record["message"] == "hello world"
        assert record["request_id"] == "req-id-1"
        assert record["name"] == "test.json"
        assert "timestamp" in record


class TestJobRunIdScope:
    async def test_track_job_sets_and_resets_id(self, capsys):
        configure_logging(level="INFO", fmt="json")
        log = logging.getLogger("test.job")

        log.info("before")
        assert get_job_run_id() is None
        async with track_job("unit-demo"):
            inside_id = get_job_run_id()
            assert inside_id is not None
            assert len(inside_id) == 8  # uuid4 hex truncado
            log.info("during")
        # Tras salir, el contextvar vuelve a None.
        assert get_job_run_id() is None
        log.info("after")

        captured = capsys.readouterr()
        records = [
            json.loads(ln) for ln in captured.out.splitlines() if ln.strip()
        ]
        msgs = {r["message"]: r for r in records}
        assert msgs["before"]["job_run_id"] == "-"
        assert msgs["during"]["job_run_id"] == inside_id
        assert msgs["after"]["job_run_id"] == "-"

    async def test_track_job_resets_on_exception(self):
        token = job_run_id_var.set("preexisting")
        try:
            with pytest.raises(ValueError):
                async with track_job("crashing"):
                    raise ValueError("boom")
            # El contextvar debe volver al valor previo, no quedarse con el
            # del job que falló.
            assert get_job_run_id() == "preexisting"
        finally:
            job_run_id_var.reset(token)
