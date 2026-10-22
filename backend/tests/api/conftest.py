import numpy as np
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text

from app.api import create_app
from app.mapping.matcher.embed import Embedder
from app.settings import Settings
from mockdata.config import CLIENT1_URL

PUBLISH_SCHEMA = "lending_rpt_eval"


def keyword_encoder(texts):
    vocab = ["income", "score", "date", "amount", "name", "status", "city", "pan", "loan", "customer"]
    return np.array([[t.lower().count(w) for w in vocab] for t in texts], dtype=float) + 1e-3


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return Settings(BANKREPORTER_SECRET_KEY=Fernet.generate_key().decode(),
                    BANKREPORTER_DB=tmp_path / "app.sqlite", OPENAI_API_KEY=None,
                    BANKREPORTER_PUBLISH_SCHEMA=PUBLISH_SCHEMA)


@pytest.fixture
def api(settings):
    app = create_app(settings, embedder=Embedder(encode=keyword_encoder))
    with TestClient(app) as client:
        yield client


def client1_body(**overrides):
    url = make_url(CLIENT1_URL)
    body = {"name": "NovaBank", "dialect": "postgresql", "host": url.host, "port": url.port,
            "database": url.database, "user": url.username, "password": url.password, "schemas": ["los"]}
    return {**body, **overrides}


@pytest.fixture
def cleanup_eval_views(pg_engine):
    yield
    with pg_engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {PUBLISH_SCHEMA}.{v}"))
