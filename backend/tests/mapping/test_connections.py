import pytest
from cryptography.fernet import Fernet

from app.connections import (
    DecryptError, build_url, decrypt_url, encrypt_url, mask_secrets, mask_url, check_connection,
)

KEY = Fernet.generate_key().decode()
URL = "postgresql+psycopg://novabank:s3cr%40t@localhost:5433/novabank"


def test_encrypt_round_trip():
    token = encrypt_url(URL, KEY)
    assert "s3cr" not in token
    assert decrypt_url(token, KEY) == URL


def test_decrypt_with_wrong_key_raises():
    token = encrypt_url(URL, KEY)
    with pytest.raises(DecryptError):
        decrypt_url(token, Fernet.generate_key().decode())


@pytest.mark.parametrize("url, expected", [
    (URL, "postgresql+psycopg://novabank:***@localhost:5433/novabank"),
    ("mysql+pymysql://bfs:bfs@localhost:3307/bfs_core", "mysql+pymysql://bfs:***@localhost:3307/bfs_core"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_mask_url(url, expected):
    assert mask_url(url) == expected


def test_mask_secrets_removes_raw_and_encoded_password():
    msg = 'connection to "localhost" failed for novabank:s3cr@t and s3cr%40t'
    assert mask_secrets(msg, URL) == 'connection to "localhost" failed for novabank:*** and ***'


def test_build_url_escapes_password():
    url = build_url("postgresql", "localhost", 5433, "novabank", "novabank", "p@ss/word")
    assert url == "postgresql+psycopg://novabank:p%40ss%2Fword@localhost:5433/novabank"
    assert build_url("mysql", "h", 3307, "db", "u", "p") == "mysql+pymysql://u:p@h:3307/db"


def test_build_url_rejects_unknown_dialect():
    with pytest.raises(ValueError, match="unsupported dialect 'oracle'"):
        build_url("oracle", "h", 1, "d", "u", "p")


def test_check_connection_failure_is_masked():
    result = check_connection("postgresql+psycopg://u:topsecret@localhost:1/x", ["public"])
    assert result.ok is False
    assert "topsecret" not in result.error


@pytest.mark.db
def test_check_connection_lists_tables(pg_engine):
    from mockdata.config import CLIENT1_URL
    result = check_connection(CLIENT1_URL, ["los"])
    assert result.ok is True
    assert "los.loan_application" in result.tables
