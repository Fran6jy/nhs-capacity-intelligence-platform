from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy.exc import OperationalError

from src import db


def _operational_error() -> OperationalError:
    return OperationalError("INSERT", {}, Exception("statement timeout"))


def test_write_table_uses_small_batches(monkeypatch):
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    frame = MagicMock(spec=pd.DataFrame)
    frame.__len__.return_value = 3
    monkeypatch.setattr(db, "get_engine", lambda: engine)

    assert db.write_table(frame, "example") == 3
    frame.to_sql.assert_called_once_with(
        "example",
        conn,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=200,
    )


def test_write_table_retries_operational_errors(monkeypatch):
    engine = MagicMock()
    engine.begin.return_value.__enter__.side_effect = [_operational_error(), MagicMock()]
    frame = MagicMock(spec=pd.DataFrame)
    frame.__len__.return_value = 2
    sleep = MagicMock()
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db.time, "sleep", sleep)

    assert db.write_table(frame, "example") == 2
    assert engine.begin.call_count == 2
    engine.dispose.assert_called_once()
    sleep.assert_called_once_with(2)


def test_write_table_stops_after_max_attempts(monkeypatch):
    engine = MagicMock()
    engine.begin.return_value.__enter__.side_effect = [_operational_error()] * 4
    frame = MagicMock(spec=pd.DataFrame)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db.time, "sleep", MagicMock())

    with pytest.raises(OperationalError):
        db.write_table(frame, "example")
    assert engine.begin.call_count == 4
