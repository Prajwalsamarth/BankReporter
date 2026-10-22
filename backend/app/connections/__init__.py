"""Client connection URLs: building, encrypting, masking and testing."""
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import URL, create_engine, inspect, make_url
from sqlalchemy.exc import SQLAlchemyError

DRIVERS = {"postgresql": "postgresql+psycopg", "mysql": "mysql+pymysql"}


class DecryptError(Exception):
    pass


def build_url(dialect: str, host: str, port: int, database: str, user: str, password: str) -> str:
    if dialect not in DRIVERS:
        raise ValueError(f"unsupported dialect '{dialect}'")
    url = URL.create(DRIVERS[dialect], username=user, password=password, host=host, port=port,
                     database=database)
    return url.render_as_string(hide_password=False)


def encrypt_url(url: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(url.encode()).decode()


def decrypt_url(token: str, key: str) -> str:
    try:
        return Fernet(key.encode()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise DecryptError("stored connection URL cannot be decrypted with the current secret key") from exc


def mask_url(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def mask_secrets(text: str, url: str) -> str:
    """Replace the URL's password (raw and URL-encoded) anywhere in `text`."""
    parsed = make_url(url)
    if not parsed.password:
        return text
    encoded = parsed.render_as_string(hide_password=False).split("://", 1)[1].split("@", 1)[0].split(":", 1)[-1]
    for secret in sorted({str(parsed.password), encoded}, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


@dataclass
class TestResult:
    __test__ = False   # not a pytest test class
    ok: bool
    tables: list[str] = field(default_factory=list)
    error: str | None = None


def check_connection(url: str, schemas: list[str]) -> TestResult:
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        tables = [f"{s}.{t}" for s in schemas for t in insp.get_table_names(schema=s)]
        return TestResult(ok=True, tables=tables)
    except SQLAlchemyError as exc:
        return TestResult(ok=False, error=mask_secrets(str(exc.orig if hasattr(exc, "orig") else exc), url))
    finally:
        engine.dispose()
