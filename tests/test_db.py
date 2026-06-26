"""
test_db.py — Test sulla gestione degli errori di connessione DB.

Verifica che credenziali errate generino DBConnectionError e che il retry
esegua esattamente il numero atteso di tentativi.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

_root = Path(__file__).resolve().parent.parent
for _p in (str(_root / "oop"), str(_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data_source import IsualDataSource, DBConnectionError


BAD_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "nonexistent",
    "user":     "wrong_user",
    "password": "wrong_password",
    "sslmode":  "disable",
}


@pytest.fixture
def bad_source():
    end   = datetime.utcnow()
    start = end - timedelta(days=30)
    return IsualDataSource(BAD_CONFIG, start, end)


def test_bad_credentials_raise_db_connection_error(bad_source):
    """Con credenziali errate, _get_engine deve sollevare DBConnectionError."""
    with pytest.raises(DBConnectionError):
        bad_source._get_engine()


def test_retry_count_on_failure(bad_source):
    """Deve tentare esattamente max_attempts volte prima di arrendersi."""
    call_count = 0
    original_create = __import__("sqlalchemy").create_engine

    def counting_create_engine(url, **kwargs):
        nonlocal call_count
        call_count += 1
        raise Exception("connessione rifiutata (simulata)")

    with patch("data_source.create_engine", side_effect=counting_create_engine):
        with patch("data_source.time.sleep"):  # evita ritardi reali nei test
            with pytest.raises(DBConnectionError):
                bad_source._create_engine_with_retry(max_attempts=3)

    assert call_count == 3


def test_retry_sleeps_between_attempts(bad_source):
    """Tra i tentativi deve esserci almeno una sleep."""
    sleep_calls = []

    def mock_sleep(delay):
        sleep_calls.append(delay)

    with patch("data_source.create_engine", side_effect=Exception("timeout")):
        with patch("data_source.time.sleep", side_effect=mock_sleep):
            with pytest.raises(DBConnectionError):
                bad_source._create_engine_with_retry(max_attempts=3)

    # 3 tentativi → 2 sleep (non c'è sleep dopo l'ultimo tentativo)
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == 1
    assert sleep_calls[1] == 2


def test_db_connection_error_message(bad_source):
    """Il messaggio dell'eccezione deve contenere info utili al debug."""
    with patch("data_source.create_engine", side_effect=Exception("timeout simulato")):
        with patch("data_source.time.sleep"):
            with pytest.raises(DBConnectionError) as exc_info:
                bad_source._create_engine_with_retry(max_attempts=2)

    assert "2 tentativi" in str(exc_info.value)
    assert "timeout simulato" in str(exc_info.value)


def test_engine_singleton_on_success():
    """_get_engine deve restituire lo stesso oggetto a chiamate successive."""
    end   = datetime.utcnow()
    start = end - timedelta(days=30)
    source = IsualDataSource(BAD_CONFIG, start, end)

    mock_engine = MagicMock()
    mock_conn   = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__  = MagicMock(return_value=False)
    mock_engine.connect.return_value = mock_conn

    with patch("data_source.create_engine", return_value=mock_engine):
        e1 = source._get_engine()
        e2 = source._get_engine()

    assert e1 is e2
