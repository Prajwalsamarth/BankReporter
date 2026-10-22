# backend/tests/api/conftest.py
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text

from app.api import create_app
from app.auth.seed import seed
from app.mapping.matcher.embed import Embedder
from app.settings import Settings
from mockdata.config import CLIENT1_URL

PUBLISH_SCHEMA = "lending_rpt_eval"
ADMIN = ("admin", "admin123")
NOVA = ("nova.analyst", "nova123")
BHARAT = ("bharat.analyst", "bharat123")
NOVA_ID, BHARAT_ID = 1, 2          # seed() creates NovaBank first


def keyword_encoder(texts):
    vocab = ["income", "score", "date", "amount", "name", "status", "city", "pan", "loan", "customer"]
    return np.array([[t.lower().count(w) for w in vocab] for t in texts], dtype=float) + 1e-3


class Clock:
    """An adjustable 'now' for session expiry and login lockout."""
    def __init__(self):
        self.t = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **delta) -> None:
        self.t += timedelta(**delta)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return Settings(BANKREPORTER_SECRET_KEY=Fernet.generate_key().decode(),
                    BANKREPORTER_DB=tmp_path / "app.sqlite", OPENAI_API_KEY=None,
                    BANKREPORTER_PUBLISH_SCHEMA=PUBLISH_SCHEMA)


def make_app(settings, clock, **kwargs):
    app = create_app(settings, embedder=Embedder(encode=keyword_encoder), now=clock, **kwargs)
    seed(app.state.store)
    return app


@pytest.fixture
def app(settings, clock):
    return make_app(settings, clock)


def login(client, user) -> dict:
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return r.json()


@contextmanager
def signed_in(app, user=ADMIN, acting=NOVA_ID):
    """A TestClient signed in as `user`; the admin also selects client `acting`."""
    with TestClient(app) as client:
        login(client, user)
        if user == ADMIN and acting is not None:
            assert client.put("/api/auth/me/client", json={"client_id": acting}).status_code == 200
        yield client


@pytest.fixture
def api(app):
    with signed_in(app) as client:
        yield client


def client1_body(**overrides):
    url = make_url(CLIENT1_URL)
    body = {"name": "NovaBank", "dialect": "postgresql", "host": url.host, "port": url.port,
            "database": url.database, "user": url.username, "password": url.password, "schemas": ["los"],
            "client_id": NOVA_ID}
    return {**body, **overrides}


@pytest.fixture
def cleanup_eval_views(pg_engine):
    yield
    with pg_engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {PUBLISH_SCHEMA}.{v}"))
