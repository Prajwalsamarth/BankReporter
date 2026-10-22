import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from mockdata.config import CLIENT1_URL, CLIENT2_URL

DB_URLS = {"postgresql": CLIENT1_URL, "mysql": CLIENT2_URL}


def _engine_or_skip(url: str):
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        engine.dispose()
        pytest.skip(f"database not reachable: {engine.url.render_as_string(hide_password=True)}")
    return engine


@pytest.fixture(scope="session")
def pg_engine():
    engine = _engine_or_skip(CLIENT1_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def mysql_engine():
    engine = _engine_or_skip(CLIENT2_URL)
    yield engine
    engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql", "mysql"])
def any_engine(request):
    """Same test against every supported dialect; real DBs skip if unreachable."""
    if request.param == "sqlite":
        engine = create_engine("sqlite://")
        yield engine
        engine.dispose()
    else:
        request.applymarker(pytest.mark.db)
        yield request.getfixturevalue("pg_engine" if request.param == "postgresql" else "mysql_engine")
