from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from src.api import main


def test_health_failure_does_not_expose_credentials(monkeypatch):
    secret = "postgresql://user:private-password@example.invalid/postgres"
    failure = OperationalError("SELECT 1", {}, Exception(f"connection timed out: {secret}"))
    warning = MagicMock()

    def fail(_query):
        raise failure

    monkeypatch.setattr(main.settings, "database_url", secret)
    monkeypatch.setattr(main.db, "read_sql", fail)
    monkeypatch.setattr(main.log, "warning", warning)

    with pytest.raises(HTTPException) as caught:
        main.health()

    assert caught.value.status_code == 503
    assert caught.value.detail == "database unavailable"
    warning.assert_called_once()
    args, kwargs = warning.call_args
    assert kwargs["category"] == "connection_timeout"
    assert kwargs["error_type"] == "OperationalError"
    assert secret not in str(args) + str(kwargs) + caught.value.detail


def test_health_failure_classifies_authentication_without_logging_message(monkeypatch):
    monkeypatch.setattr(main.settings, "database_url", "postgresql://redacted")
    failure = OperationalError("SELECT 1", {}, Exception("password authentication failed"))
    assert main._database_failure_category(failure) == "authentication_failed"
