# backend/tests/auth/test_migrate.py
import sqlite3

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.store import Client, Connection, Dashboard, ReportTemplate, Store

# The Part 3 schema of the three tables that change (global UNIQUE names, no client_id).
OLD_SCHEMA = """
CREATE TABLE connection (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name VARCHAR(100) NOT NULL UNIQUE,
  dialect VARCHAR(20) NOT NULL, url_encrypted VARCHAR NOT NULL, schemas JSON NOT NULL,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE TABLE report_template (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name VARCHAR(200) NOT NULL UNIQUE,
  description VARCHAR NOT NULL, blocks JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE TABLE dashboard (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name VARCHAR(200) NOT NULL UNIQUE,
  default_period JSON NOT NULL, tiles JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
INSERT INTO connection VALUES (1, 'NovaBank', 'postgresql', 'enc', '["los"]', '2026-10-01 00:00:00', '2026-10-01 00:00:00');
INSERT INTO report_template VALUES (5, 'Monthly Lending MIS', '', '[]', '2026-10-01 00:00:00', '2026-10-01 00:00:00');
INSERT INTO dashboard VALUES (3, 'Lending KPIs', '{"preset": "last_month"}', '[]', '2026-10-01 00:00:00', '2026-10-01 00:00:00');
"""


def old_store_url(tmp_path) -> str:
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.close()
    return f"sqlite:///{path}"


def test_new_store_has_auth_tables(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'new.sqlite'}")
    assert {"client", "app_user", "auth_session"} <= set(inspect(store.engine).get_table_names())


def test_upgrade_keeps_data_and_makes_items_shared(tmp_path):
    store = Store(old_store_url(tmp_path))
    with store.session() as s:
        assert s.get(Connection, 1).client_id is None
        template = s.get(ReportTemplate, 5)
        assert template.name == "Monthly Lending MIS" and template.client_id is None
        assert s.get(Dashboard, 3).client_id is None


def test_upgrade_drops_global_unique_names(tmp_path):
    store = Store(old_store_url(tmp_path))
    with store.session() as s:
        nova = Client(name="NovaBank", code="novabank")
        s.add(nova)
        s.flush()
        s.add(ReportTemplate(name="Monthly Lending MIS", blocks=[], client_id=nova.id))
        s.add(Dashboard(name="Lending KPIs", tiles=[], client_id=nova.id))
        s.commit()          # same names as the shared items: allowed once names are unique per owner


def test_upgrade_makes_connection_client_unique(tmp_path):
    store = Store(old_store_url(tmp_path))
    with store.session() as s:
        nova = Client(name="NovaBank", code="novabank")
        s.add(nova)
        s.flush()
        s.get(Connection, 1).client_id = nova.id
        s.add(Connection(name="Other", dialect="mysql", url_encrypted="x", client_id=nova.id))
        with pytest.raises(IntegrityError):
            s.commit()


def test_upgrade_twice_changes_nothing(tmp_path):
    url = old_store_url(tmp_path)
    Store(url)

    def snapshot():
        con = sqlite3.connect(url.removeprefix("sqlite:///"))
        try:
            return con.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        finally:
            con.close()

    before = snapshot()
    Store(url)
    assert snapshot() == before
