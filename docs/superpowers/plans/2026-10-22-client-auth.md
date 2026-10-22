# Client Sign-in and Data Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a login page and server-side sessions. A client user sees only their own bank's connection, mapping, reports and dashboards. A platform admin sees every client and works on one at a time.

**Architecture:**
- **Store:** new `client`, `app_user` and `auth_session` tables in the app's SQLite store. `connection`, `report_template` and `dashboard` get a `client_id`. An idempotent `upgrade()` brings existing databases forward.
- **Session check:** a FastAPI dependency `get_scope` turns the `br_session` cookie into a `Scope` (user, role, client). Every router except the login, logout and me routes depends on it.
- **Visibility:** `app/auth/access.py` holds all visibility rules. Objects a user can't see return 404.
- **Frontend:**
  - `useMe()`, a TanStack Query on `/auth/me`, holds who is signed in.
  - `RequireAuth` guards every page except `/login`.
  - A global 401 handler in `api()` sends you back to `/login`.
  - Pages read the client from `useMe()` instead of a client dropdown.

**Tech Stack:**
- Backend: Python 3.12, FastAPI 0.115, SQLAlchemy 2, SQLite, `hashlib.scrypt` from the standard library (no new dependencies).
- Frontend: React 18, Mantine 7, TanStack Query 5, react-router 6, Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-10-22-client-auth-design.md`

## Global Constraints

- **No new Python or npm dependencies.** Passwords use `hashlib.scrypt` with n=2**14, r=8, p=1, a 16-byte salt and a 32-byte key. Stored format: `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`.
- **Cookie:** `br_session`; HttpOnly, SameSite=Lax, Path=/, Max-Age = `session_hours`×3600. `Secure` comes from the `cookie_secure` setting (default false).
- **Store only token hashes:** the session table keeps the SHA-256 hex of the token, never the token.
- **Settings:**
  - `session_hours`: 12 (`BANKREPORTER_SESSION_HOURS`)
  - `cookie_secure`: false (`BANKREPORTER_COOKIE_SECURE`)
  - `login_max_failures`: 5 (`BANKREPORTER_LOGIN_MAX_FAILURES`)
  - `login_lock_minutes`: 5 (`BANKREPORTER_LOGIN_LOCK_MINUTES`)
- **Every failed login gets one identical answer:** 401 with detail exactly `Wrong username or password`. This covers an unknown user, a wrong password, an inactive user, an inactive client and a locked account.
- **Fixed messages:**
  - another client's object: 404, `"<table> <id> not found"` (the existing format);
  - editing a shared item as a client user: 403, `Shared items are read-only, use Save as`;
  - an admin-only route: 403, `Only the platform admin can do this`;
  - an admin rendering with no client selected: 409, `Choose a client first`;
  - nothing published: 409, `<name> has no published views; publish its mapping first`;
  - a duplicate template or dashboard name: 409, `the name '<X>' is already used`.
- **Requests that change data must be JSON:** a POST, PUT, PATCH or DELETE with a non-empty body that isn't `application/json` gets 415.
- **Sample logins** (from `python -m app.auth.seed`):
  - `admin` / `admin123`;
  - `nova.analyst` / `nova123` (NovaBank, code `novabank`);
  - `bharat.analyst` / `bharat123` (Bharat Finserv, code `bharat`).
  The seed never overwrites the password of an existing user.
- **Lowercase usernames:** usernames are stored lower-case, and the login matches the trimmed, lower-cased input.
- **Render requests:** the render endpoints accept only `period` (plus `blocks` for `/render-blocks`). Any other key, including `connection_id`, gets 422.
- **Removed route:** `GET /api/connections/published` is removed.
- **Frontend copy:**
  - `Sign in`, `Sign out`;
  - `Wrong username or password`;
  - `Choose a client in the header to see data`;
  - `Your data mapping isn't published yet`;
  - badges `Shared` and `Private`;
  - `Save as copy`;
  - radio labels `Shared with all clients` and `Only <client>`.
- **Commands:**
  - backend tests run from `backend/` with `../.venv/bin/pytest -q`;
  - frontend tests run from `frontend/` with `npm test`, and type-checking with `npm run typecheck`.

## Review Focus

1. **The admin switches client while a page is open.** The report or dashboard must re-render for the new client and must never keep showing the old client's numbers under the new name. Render query keys include the client id, and switching invalidates queries. Tests: Task 6 (switch invalidates) and Task 7 (the render call happens again after a switch).
2. **The session expires in the middle of using a page.** You must land on `/login?next=<page>`, and signing in must return you to that page without a redirect loop. Test: Task 6, "401 mid-session".
3. **A client user renames their connection to another bank's connection name.** The 409 must not reveal that the other bank's connection exists. Test: Task 4, `test_rename_conflict_does_not_name_other_clients`.
4. **The admin deletes a client's connection while that client is signed in.** The client's render must give the "no published views" 409, not a 500. Test: Task 5, `test_client_without_connection_gets_not_published`.
5. **Signing in as a different user in the same browser.** The earlier session must end, not linger. Test: Task 3, `test_signing_in_again_ends_the_previous_session`.

---

## File structure

**Backend (new)**
- `backend/app/auth/__init__.py`: an empty package marker.
- `backend/app/auth/passwords.py`: `hash_password` and `verify_password`.
- `backend/app/auth/sessions.py`: `token_hash`, `aware`, `create_session`, `lookup`, `end_session`, `purge_expired`.
- `backend/app/auth/seed.py`: `seed(store, admin_password=None, client_password=None) -> list[str]` and `main()`.
- `backend/app/auth/scope.py`: `COOKIE`, `Scope`, `resolve`, `get_scope`.
- `backend/app/auth/access.py`: the visibility and permission helpers, plus the message constants.
- `backend/app/api/auth_routes.py`: the `/api/auth` router.
- `backend/app/store/migrate.py`: `upgrade(engine)`.

**Backend (modified)**
- `backend/app/store/__init__.py`: the new models, `client_id` columns, relationships, and a call to `upgrade`.
- `backend/app/settings.py`: four settings.
- `backend/app/api/__init__.py`: a `now` clock, purging expired sessions at start-up, and the guarded routers.
- `backend/app/api/routes.py`: connection and mapping routes scoped through `access`.
- `backend/app/api/schemas.py`: `ConnectionIn.client_id`, and `ConnectionOut.client`.
- `backend/app/api/reporting.py`: ownership, the name rules, rendering from the scope, and removing `/connections/published`.
- `backend/app/reporting/defaults.py`: the seeded defaults are found by name among shared items only.

**Backend tests**
- New:
  - `backend/tests/auth/__init__.py`
  - `backend/tests/auth/test_migrate.py`
  - `backend/tests/auth/test_passwords_sessions.py`
  - `backend/tests/auth/test_seed.py`
  - `backend/tests/api/test_auth_api.py`
  - `backend/tests/api/test_isolation_api.py`
- Modified:
  - `backend/tests/api/conftest.py`: a clock, seeding, signing in, and `client_id` in `client1_body`.
  - `backend/tests/api/test_api.py`: one test signs in on its second app.
  - `backend/tests/api/test_reporting_api.py`: signed-in fixture, render bodies without `connection_id`.

**Frontend (new)**
- `frontend/src/auth.tsx`: `ME_KEY`, `useMe`, `RequireAuth`, `useUnauthorizedRedirect`, `safeNext`.
- `frontend/src/pages/LoginPage.tsx`
- `frontend/src/components/UserMenu.tsx`: the header's right side.
- `frontend/src/components/RenderError.tsx`, `NoClient.tsx`, `SharingChoice.tsx`, `OwnerBadge.tsx`
- `frontend/src/App.test.tsx`

**Frontend (modified)**
- `frontend/src/api.ts`: `credentials`, the 401 handler, and the `Me`, `ClientRef` and ownership fields; `PublishedConnection` is removed.
- `frontend/src/App.tsx`: the login route, the guarded shell and the user menu.
- `frontend/src/pages/ConnectionsPage.tsx`, `components/ConnectionForm.tsx`: admin-only controls, and the Client column and select.
- `frontend/src/pages/ReportsPage.tsx`, `DashboardsPage.tsx`, `ReportEditorPage.tsx`: no ClientSelect; the client comes from `useMe`; badges, Save as copy, the sharing choice and error mapping.
- `frontend/src/test/fixtures.ts`: `meClient` and `meAdmin`.
- The page tests are updated.
- Deleted: `frontend/src/components/ClientSelect.tsx`.

**Docs:** `README.md`, a "Sign in" section.

---

### Task 1: Store models and in-place upgrade

**Files:**
- Modify: `backend/app/store/__init__.py`
- Create: `backend/app/store/migrate.py`
- Test: `backend/tests/auth/__init__.py` (empty), `backend/tests/auth/test_migrate.py`

**Interfaces:**
- Produces:
  - models `Client`, `AppUser` and `AuthSession`;
  - `Connection.client_id` and `Connection.client`, `ReportTemplate.client_id` and `ReportTemplate.client`, `Dashboard.client_id` and `Dashboard.client`;
  - the unique index `ux_connection_client`;
  - `app.store.migrate.upgrade(engine) -> None`, which `Store.__init__` calls after `create_all`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/auth/test_migrate.py -q`
Expected: FAIL. The collection error is `ImportError: cannot import name 'Client' from 'app.store'`.

- [ ] **Step 3: Add the models**

In `backend/app/store/__init__.py`:
- Change the sqlalchemy import to `from sqlalchemy import JSON, ForeignKey, Index, String, create_engine, make_url`.
- Insert these classes **after `class Base` and before `class Connection`**:

```python
class Client(Base):
    __tablename__ = "client"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)        # stored lower-case
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(String(10))                          # admin | client
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"), default=None)
    active: Mapped[bool] = mapped_column(default=True)
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)
    client: Mapped[Client | None] = relationship()


class AuthSession(Base):
    __tablename__ = "auth_session"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)   # SHA-256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    acting_client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    expires_at: Mapped[datetime]
    user: Mapped[AppUser] = relationship()
```

Change `Connection`'s `__table_args__` and add two attributes:

```python
class Connection(Base):
    __tablename__ = "connection"
    __table_args__ = (Index("ux_connection_client", "client_id", unique=True),
                      {"sqlite_autoincrement": True})   # never reuse ids of deleted rows
    ...existing columns unchanged...
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"), default=None)
    client: Mapped[Client | None] = relationship()
```

In `ReportTemplate` and `Dashboard`:
- change `name: Mapped[str] = mapped_column(String(200), unique=True)` to `name: Mapped[str] = mapped_column(String(200))`;
- add to each:

```python
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"), default=None)   # NULL = shared
    client: Mapped[Client | None] = relationship()
```

In `Store.__init__`, after `Base.metadata.create_all(self.engine)` add:

```python
        from app.store.migrate import upgrade
        upgrade(self.engine)
```

- [ ] **Step 4: Write the upgrade module**

```python
# backend/app/store/migrate.py
"""In-place upgrade of an existing app store (spec §2.3). Runs on every start; a second run changes nothing."""
from sqlalchemy import Engine, inspect
from sqlalchemy.schema import CreateTable

ADDED_COLUMNS = {"connection": "client_id", "report_template": "client_id", "dashboard": "client_id"}
OWNED = ("report_template", "dashboard")


def _unique_on_name(conn, table: str) -> bool:
    for row in conn.exec_driver_sql(f"PRAGMA index_list('{table}')").fetchall():
        index, unique = row[1], row[2]
        columns = [r[2] for r in conn.exec_driver_sql(f"PRAGMA index_info('{index}')").fetchall()]
        if unique and columns == ["name"]:
            return True
    return False


def _rebuild(engine: Engine, table: str) -> None:
    """Recreate `table` from the current model (no global UNIQUE on name), copying every row, atomically."""
    from app.store import Base
    model = Base.metadata.tables[table]
    with engine.connect() as conn:
        old = [c["name"] for c in inspect(conn).get_columns(table)]
    create = str(CreateTable(model).compile(engine)).strip()
    cols = ", ".join(f'"{c}"' for c in old if c in model.c)
    script = (f'BEGIN; ALTER TABLE "{table}" RENAME TO "{table}_old"; {create}; '
              f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM "{table}_old"; '
              f'DROP TABLE "{table}_old"; COMMIT;')
    raw = engine.raw_connection()
    try:
        driver = raw.driver_connection
        try:
            driver.executescript(script)
        except Exception:
            if driver.in_transaction:
                driver.execute("ROLLBACK")
            raise
    finally:
        raw.close()


def upgrade(engine: Engine) -> None:
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        rebuild = [t for t in OWNED if t in tables and _unique_on_name(conn, t)]
    for table in rebuild:
        _rebuild(engine, table)
    with engine.begin() as conn:
        insp = inspect(conn)
        for table, column in ADDED_COLUMNS.items():
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" INTEGER REFERENCES client(id)')
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ux_connection_client ON connection(client_id)")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/auth/test_migrate.py tests/mapping/test_store.py -q`
Expected: PASS (5 new tests, plus the existing store tests).

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && ../.venv/bin/pytest -q`
Expected: the same pass count as before plus 5. The previous baseline is 549 passed and 1 skipped.

- [ ] **Step 7: Commit**

```bash
git add backend/app/store backend/tests/auth
git commit -m "feat(store): clients, users, sessions, per-client ownership and in-place upgrade"
```

---

### Task 2: Password hashing, sessions, and the seed command

**Files:**
- Create: `backend/app/auth/__init__.py` (empty), `backend/app/auth/passwords.py`, `backend/app/auth/sessions.py`, `backend/app/auth/seed.py`
- Test: `backend/tests/auth/test_passwords_sessions.py`, `backend/tests/auth/test_seed.py`

**Interfaces:**
- Consumes: `Client`, `AppUser`, `AuthSession`, `Connection` and `Store` (Task 1).
- Produces:
  - `hash_password(password: str) -> str` and `verify_password(password: str, stored: str) -> bool`;
  - `token_hash(token: str) -> str` and `aware(dt: datetime | None) -> datetime | None`;
  - `create_session(s, user: AppUser, hours: int, now: datetime) -> str` returns the token and adds the row, without committing;
  - `lookup(s, token: str | None, now: datetime) -> AuthSession | None` deletes **and commits** an expired session;
  - `end_session(s, token: str | None) -> None` doesn't commit;
  - `purge_expired(s, now: datetime) -> int` doesn't commit;
  - `seed(store, admin_password: str | None = None, client_password: str | None = None) -> list[str]` creates NovaBank (id 1) then Bharat Finserv (id 2) in a fresh store.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/auth/test_passwords_sessions.py
import hashlib
from datetime import UTC, datetime, timedelta

from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import create_session, end_session, lookup, purge_expired, token_hash
from app.store import AppUser, AuthSession, Store

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


def test_hash_round_trip_and_wrong_password():
    stored = hash_password("nova123")
    assert stored.startswith("scrypt$16384$8$1$")
    assert verify_password("nova123", stored)
    assert not verify_password("nova124", stored)


def test_each_hash_has_its_own_salt():
    assert hash_password("same") != hash_password("same")


def test_malformed_stored_hash_is_false_not_an_error():
    for bad in ("", "plain", "scrypt$x$8$1$AAAA$AAAA", "bcrypt$1$2$3$4$5", "scrypt$16384$8$1$%%%$AAAA"):
        assert verify_password("x", bad) is False


def _store_with_user(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 's.sqlite'}")
    with store.session() as s:
        s.add(AppUser(username="u", display_name="U", password_hash=hash_password("p"), role="admin"))
        s.commit()
    return store


def test_session_round_trip_stores_only_the_hash(tmp_path):
    store = _store_with_user(tmp_path)
    with store.session() as s:
        token = create_session(s, s.query(AppUser).one(), 12, NOW)
        s.commit()
        row = s.query(AuthSession).one()
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest() == token_hash(token)
        assert token not in row.token_hash
        assert lookup(s, token, NOW + timedelta(hours=11)).user.username == "u"
        assert lookup(s, "not-a-token", NOW) is None and lookup(s, None, NOW) is None


def test_expired_session_is_deleted_on_lookup(tmp_path):
    store = _store_with_user(tmp_path)
    with store.session() as s:
        token = create_session(s, s.query(AppUser).one(), 12, NOW)
        s.commit()
        assert lookup(s, token, NOW + timedelta(hours=12)) is None
    with store.session() as s:
        assert s.query(AuthSession).count() == 0


def test_end_session_and_purge(tmp_path):
    store = _store_with_user(tmp_path)
    with store.session() as s:
        user = s.query(AppUser).one()
        keep = create_session(s, user, 12, NOW)
        gone = create_session(s, user, 12, NOW)
        create_session(s, user, 1, NOW - timedelta(hours=2))      # already expired
        s.commit()
        end_session(s, gone)
        assert purge_expired(s, NOW) == 1
        s.commit()
        assert [x.token_hash for x in s.query(AuthSession)] == [token_hash(keep)]
        end_session(s, None)                                       # harmless
```

```python
# backend/tests/auth/test_seed.py
from app.auth.passwords import verify_password
from app.auth.seed import seed
from app.store import AppUser, Client, Connection, Store


def _store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 's.sqlite'}")


def test_seed_creates_clients_users_and_attaches_connections(tmp_path):
    store = _store(tmp_path)
    with store.session() as s:
        s.add_all([Connection(name="NovaBank", dialect="postgresql", url_encrypted="x"),
                   Connection(name="Bharat Finserv", dialect="mysql", url_encrypted="y")])
        s.commit()
    lines = seed(store)
    with store.session() as s:
        clients = {c.code: c for c in s.query(Client)}
        assert [(c.id, c.name) for c in s.query(Client).order_by(Client.id)] == [(1, "NovaBank"), (2, "Bharat Finserv")]
        users = {u.username: u for u in s.query(AppUser)}
        assert users["admin"].role == "admin" and users["admin"].client_id is None
        assert users["nova.analyst"].role == "client" and users["nova.analyst"].client_id == clients["novabank"].id
        assert users["bharat.analyst"].client_id == clients["bharat"].id
        assert verify_password("admin123", users["admin"].password_hash)
        assert verify_password("nova123", users["nova.analyst"].password_hash)
        assert verify_password("bharat123", users["bharat.analyst"].password_hash)
        assert {c.name: c.client_id for c in s.query(Connection)} == {"NovaBank": 1, "Bharat Finserv": 2}
    assert "created user nova.analyst / nova123" in lines
    assert "attached connection NovaBank to NovaBank" in lines


def test_seed_twice_is_idempotent_and_keeps_passwords(tmp_path):
    store = _store(tmp_path)
    seed(store, admin_password="first", client_password="c1")
    lines = seed(store, admin_password="second", client_password="c2")
    with store.session() as s:
        assert s.query(Client).count() == 2 and s.query(AppUser).count() == 3
        admin = s.query(AppUser).filter_by(username="admin").one()
        assert verify_password("first", admin.password_hash)
        assert verify_password("c1", s.query(AppUser).filter_by(username="nova.analyst").one().password_hash)
    assert "user admin exists; password left unchanged" in lines


def test_seed_does_not_steal_a_connection_already_attached(tmp_path):
    store = _store(tmp_path)
    seed(store)
    with store.session() as s:
        s.add(Connection(name="NovaBank", dialect="postgresql", url_encrypted="x", client_id=2))
        s.commit()
    seed(store)
    with store.session() as s:
        assert s.query(Connection).one().client_id == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/auth -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`.

- [ ] **Step 3: Implement**

```python
# backend/app/auth/passwords.py
"""Password hashing with the standard library's scrypt (spec §3.1)."""
import base64
import hashlib
import hmac
import secrets

N, R, P, KEY_LEN = 2**14, 8, 1, 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=KEY_LEN)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, key = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(key, validate=True)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt, validate=True),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
```

```python
# backend/app/auth/sessions.py
"""Server-side sessions (spec §3.1): the cookie holds a random token; the store keeps only its SHA-256."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.store import AppUser, AuthSession


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; everything in the app is UTC."""
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def create_session(s, user: AppUser, hours: int, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    s.add(AuthSession(token_hash=token_hash(token), user_id=user.id, created_at=now,
                      expires_at=now + timedelta(hours=hours)))
    return token


def lookup(s, token: str | None, now: datetime) -> AuthSession | None:
    if not token:
        return None
    session = s.get(AuthSession, token_hash(token))
    if session is None:
        return None
    if aware(session.expires_at) <= now:
        s.delete(session)
        s.commit()
        return None
    return session


def end_session(s, token: str | None) -> None:
    if token and (session := s.get(AuthSession, token_hash(token))) is not None:
        s.delete(session)


def purge_expired(s, now: datetime) -> int:
    return s.query(AuthSession).filter(AuthSession.expires_at <= now).delete()
```

```python
# backend/app/auth/seed.py
"""Sample clients and users (spec §2.4). Run from backend/: python -m app.auth.seed"""
import argparse

from app.auth.passwords import hash_password
from app.settings import Settings
from app.store import AppUser, Client, Connection, Store

CLIENTS = [("NovaBank", "novabank"), ("Bharat Finserv", "bharat")]
USERS = [   # username, display name, client code (None = platform admin), default password
    ("admin", "Platform Admin", None, "admin123"),
    ("nova.analyst", "Nova Analyst", "novabank", "nova123"),
    ("bharat.analyst", "Bharat Analyst", "bharat", "bharat123"),
]


def seed(store: Store, admin_password: str | None = None, client_password: str | None = None) -> list[str]:
    lines = []
    with store.session() as s:
        clients = {}
        for name, code in CLIENTS:
            client = s.query(Client).filter_by(code=code).first()
            if client is None:
                client = Client(name=name, code=code)
                s.add(client)
                s.flush()
                lines.append(f"created client {name}")
            clients[code] = client
        for username, display, code, default in USERS:
            if s.query(AppUser).filter_by(username=username).first():
                lines.append(f"user {username} exists; password left unchanged")
                continue
            password = (admin_password if code is None else client_password) or default
            s.add(AppUser(username=username, display_name=display, password_hash=hash_password(password),
                          role="admin" if code is None else "client",
                          client_id=clients[code].id if code else None))
            lines.append(f"created user {username} / {password}")
        for client in clients.values():
            has_one = s.query(Connection).filter_by(client_id=client.id).first()
            orphan = s.query(Connection).filter_by(name=client.name, client_id=None).first()
            if orphan and not has_one:
                orphan.client_id = client.id
                lines.append(f"attached connection {orphan.name} to {client.name}")
        s.commit()
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create the sample clients and users.")
    parser.add_argument("--admin-password")
    parser.add_argument("--client-password")
    args = parser.parse_args(argv)
    settings = Settings()
    for line in seed(Store(settings.db_url), args.admin_password, args.client_password):
        print(line)
    print("These are sample logins for a proof of concept. Change them before showing the app to anyone else.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/auth -q`
Expected: PASS (5 + 6 + 3 = 14 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth backend/tests/auth
git commit -m "feat(auth): scrypt passwords, hashed server-side sessions, sample seed command"
```

---

### Task 3: The login API, with the session check on every route

**Files:**
- Modify: `backend/app/settings.py`, `backend/app/api/__init__.py`
- Create: `backend/app/auth/scope.py`, `backend/app/auth/access.py` (only the message constants and `require_admin` in this task), `backend/app/api/auth_routes.py`
- Modify tests: `backend/tests/api/conftest.py` (full rewrite below), `backend/tests/api/test_api.py`, `backend/tests/api/test_reporting_api.py`
- Test: `backend/tests/api/test_auth_api.py`

**Interfaces:**
- Consumes: Task 2 functions.
- Produces:
  - `create_app(settings, embedder=None, llm=None, today=date.today, now=None)`, where `now` is a `Callable[[], datetime]` (default: aware UTC now) stored as `app.state.now`;
  - `app.auth.scope`: `COOKIE = "br_session"`; `Scope(user_id, username, role, client_id, token)` with `.is_admin`; `resolve(request) -> Scope | None`; `get_scope(request) -> Scope`, which raises 415 or 401;
  - `app.auth.access`:
    - `ADMIN_ONLY = "Only the platform admin can do this"`;
    - `SHARED_READ_ONLY = "Shared items are read-only, use Save as"`;
    - `CHOOSE_CLIENT = "Choose a client first"`;
    - `require_admin(scope) -> None`.
  - Test helpers in `tests/api/conftest.py`:
    - `ADMIN`, `NOVA`, `BHARAT` as (username, password) tuples, and `NOVA_ID = 1`, `BHARAT_ID = 2`;
    - `Clock`;
    - fixtures `clock`, `app`, `api`;
    - `make_app(settings, clock, **kw)`, `login(client, user) -> dict`, `signed_in(app, user=ADMIN, acting=NOVA_ID)`, a context manager yielding a TestClient;
    - `client1_body(**overrides)`, which now includes `"client_id": NOVA_ID`.

- [ ] **Step 1: Rewrite the API test fixtures**

```python
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
```

In `backend/tests/api/test_api.py`, `test_connection_with_unreadable_url_needs_password`:
- change the import line `from tests.api.conftest import client1_body` to `from tests.api.conftest import ADMIN, client1_body, login`;
- add `login(c2, ADMIN)` as the first line inside `with TestClient(create_app(other)) as c2:`.

In `backend/tests/api/test_reporting_api.py`:
- replace the imports from `tests.api.conftest` and the `rapi` fixture with:

```python
from tests.api.conftest import PUBLISH_SCHEMA, client1_body, make_app, signed_in

TODAY = date(2026, 10, 22)


@pytest.fixture
def rapi(settings, clock):
    app = make_app(settings, clock, today=lambda: TODAY)
    with signed_in(app) as client:
        yield client
```

- delete the now-unused imports: `TestClient`, `create_app`, `Embedder`, `keyword_encoder`;
- in `test_defaults_seeded_once_and_valid`, the line `create_app(settings, today=lambda: TODAY)` stays. Re-add `from app.api import create_app` for it.

- [ ] **Step 2: Write the failing auth API tests**

```python
# backend/tests/api/test_auth_api.py
import hashlib
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth.scope import COOKIE, get_scope
from app.store import AppUser, AuthSession, Client
from tests.api.conftest import ADMIN, BHARAT, BHARAT_ID, NOVA, NOVA_ID, login

BAD = {"detail": "Wrong username or password"}
PUBLIC = {"/api/auth/login", "/api/auth/logout", "/api/auth/me"}


def _try(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def test_login_sets_an_httponly_session_cookie(app):
    with TestClient(app) as c:
        r = _try(c, *NOVA)
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert cookie.startswith(f"{COOKIE}=") and "httponly" in cookie
        assert "samesite=lax" in cookie and "max-age=43200" in cookie and "secure" not in cookie
        me = c.get("/api/auth/me").json()
        assert me["user"]["username"] == "nova.analyst" and me["user"]["role"] == "client"
        assert me["client"] == {"id": NOVA_ID, "name": "NovaBank", "code": "novabank"} and me["clients"] == []


def test_session_token_is_stored_only_as_a_hash(app):
    with TestClient(app) as c:
        _try(c, *NOVA)
        token = c.cookies[COOKIE]
    with app.state.store.session() as s:
        assert [x.token_hash for x in s.query(AuthSession)] == [_hash(token)]


def test_me_without_a_session_is_401(app):
    with TestClient(app) as c:
        assert c.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("username,password", [("ghost", "x"), ("nova.analyst", "wrong")])
def test_bad_logins_get_the_same_answer(app, username, password):
    with TestClient(app) as c:
        r = _try(c, username, password)
        assert r.status_code == 401 and r.json() == BAD


def test_inactive_user_and_inactive_client_cannot_sign_in(app):
    with app.state.store.session() as s:
        s.query(AppUser).filter_by(username="nova.analyst").one().active = False
        s.get(Client, BHARAT_ID).active = False
        s.commit()
    with TestClient(app) as c:
        assert _try(c, *NOVA).json() == BAD
        assert _try(c, *BHARAT).json() == BAD


def test_username_is_trimmed_and_case_insensitive(app):
    with TestClient(app) as c:
        assert _try(c, "  Nova.Analyst ", "nova123").status_code == 200


def test_account_locks_after_five_failures_then_unlocks(app, clock):
    with TestClient(app) as c:
        for _ in range(5):
            assert _try(c, "nova.analyst", "wrong").status_code == 401
        assert _try(c, *NOVA).json() == BAD               # locked: even the right password is refused
        clock.advance(minutes=5, seconds=1)
        assert _try(c, *NOVA).status_code == 200


def test_expired_session_is_401_and_deleted(app, clock):
    with TestClient(app) as c:
        _try(c, *NOVA)
        clock.advance(hours=12)
        assert c.get("/api/auth/me").status_code == 401
    with app.state.store.session() as s:
        assert s.query(AuthSession).count() == 0


def test_logout_ends_the_session(app):
    with TestClient(app) as c:
        _try(c, *NOVA)
        token = c.cookies[COOKIE]
        assert c.post("/api/auth/logout").status_code == 204
        assert c.get("/api/auth/me", headers={"Cookie": f"{COOKIE}={token}"}).status_code == 401
        assert c.post("/api/auth/logout").status_code == 204          # harmless when signed out


def test_signing_in_again_ends_the_previous_session(app):
    with TestClient(app) as c:
        _try(c, *NOVA)
        old = c.cookies[COOKIE]
        _try(c, *ADMIN)
    with app.state.store.session() as s:
        assert s.get(AuthSession, _hash(old)) is None
        assert s.query(AuthSession).count() == 1


def test_admin_switches_client(app):
    with TestClient(app) as c:
        me = login(c, ADMIN)
        assert me["client"] is None and [x["name"] for x in me["clients"]] == ["Bharat Finserv", "NovaBank"]
        assert c.put("/api/auth/me/client", json={"client_id": BHARAT_ID}).json()["client"]["name"] == "Bharat Finserv"
        assert c.get("/api/auth/me").json()["client"]["name"] == "Bharat Finserv"
        assert c.put("/api/auth/me/client", json={"client_id": 999}).status_code == 404
        assert c.put("/api/auth/me/client", json={"client_id": None}).json()["client"] is None


def test_client_users_cannot_switch_client(app):
    with TestClient(app) as c:
        login(c, NOVA)
        r = c.put("/api/auth/me/client", json={"client_id": BHARAT_ID})
        assert r.status_code == 403 and r.json()["detail"] == "Only the platform admin can do this"


def test_mutating_requests_must_be_json(api):
    r = api.post("/api/connections", content="name=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def _calls(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _calls(d)


def _guarded_routes(app):
    return [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api") and r.path not in PUBLIC]


def test_every_api_route_declares_the_session_check(app):
    routes = _guarded_routes(app)
    assert len(routes) > 25
    assert [r.path for r in routes if get_scope not in set(_calls(r.dependant))] == []


def test_every_api_route_refuses_anonymous_requests(app):
    with TestClient(app) as c:
        for r in _guarded_routes(app):
            path = re.sub(r"\{[^}]+\}", "1", r.path)
            for method in r.methods:
                kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
                assert c.request(method, path, **kwargs).status_code == 401, f"{method} {path}"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/api -q`
Expected: FAIL. `test_auth_api.py` errors on `ModuleNotFoundError: No module named 'app.auth.scope'`, and the other API tests error on `TypeError: create_app() got an unexpected keyword argument 'now'`.

- [ ] **Step 4: Add the settings**

Add to `Settings` in `backend/app/settings.py` (after `profile_row_limit`):

```python
    session_hours: int = Field(12, validation_alias="BANKREPORTER_SESSION_HOURS")
    cookie_secure: bool = Field(False, validation_alias="BANKREPORTER_COOKIE_SECURE")
    login_max_failures: int = Field(5, validation_alias="BANKREPORTER_LOGIN_MAX_FAILURES")
    login_lock_minutes: int = Field(5, validation_alias="BANKREPORTER_LOGIN_LOCK_MINUTES")
```

- [ ] **Step 5: Write the scope dependency and the access constants**

```python
# backend/app/auth/scope.py
"""Who is asking, and for which client (spec §3.1, §3.3)."""
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.auth.sessions import lookup

COOKIE = "br_session"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Scope:
    user_id: int
    username: str
    role: str                  # admin | client
    client_id: int | None      # a client user's own client, or the admin's selected client
    token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def resolve(request: Request) -> Scope | None:
    st = request.app.state
    token = request.cookies.get(COOKIE)
    with st.store.session() as s:
        session = lookup(s, token, st.now())
        if session is None:
            return None
        user = session.user
        if not user.active or (user.client is not None and not user.client.active):
            return None
        client_id = session.acting_client_id if user.role == "admin" else user.client_id
        return Scope(user.id, user.username, user.role, client_id, token)


def get_scope(request: Request) -> Scope:
    has_body = request.headers.get("content-length", "0") not in ("", "0")
    if request.method in MUTATING and has_body and \
            not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "requests must be JSON")
    scope = resolve(request)
    if scope is None:
        raise HTTPException(401, "Sign in to continue")
    return scope
```

```python
# backend/app/auth/access.py
"""Visibility and permission rules (spec §3.1). Every route fetches client data through these helpers."""
from fastapi import HTTPException

from app.auth.scope import Scope

ADMIN_ONLY = "Only the platform admin can do this"
SHARED_READ_ONLY = "Shared items are read-only, use Save as"
CHOOSE_CLIENT = "Choose a client first"


def require_admin(scope: Scope) -> None:
    if not scope.is_admin:
        raise HTTPException(403, ADMIN_ONLY)
```

- [ ] **Step 6: Write the auth router**

```python
# backend/app/api/auth_routes.py
"""Sign in, sign out, and who am I (spec §3.2)."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth.access import require_admin
from app.auth.passwords import hash_password, verify_password
from app.auth.scope import COOKIE, Scope, get_scope
from app.auth.sessions import aware, create_session, end_session, token_hash
from app.store import AppUser, AuthSession, Client

router = APIRouter(prefix="/api/auth")
BAD_LOGIN = "Wrong username or password"
DUMMY_HASH = hash_password("not-a-real-password")   # unknown users cost the same time as known ones


class LoginIn(BaseModel):
    username: str
    password: str


class ActingClientIn(BaseModel):
    client_id: int | None


def _client_out(c: Client | None) -> dict | None:
    return {"id": c.id, "name": c.name, "code": c.code} if c else None


def _me(s, user: AppUser, acting_client_id: int | None) -> dict:
    if user.role == "admin":
        client = s.get(Client, acting_client_id) if acting_client_id else None
        clients = [_client_out(c) for c in s.query(Client).order_by(Client.name)]
    else:
        client, clients = user.client, []
    return {"user": {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role},
            "client": _client_out(client), "clients": clients}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    st = request.app.state
    settings, now = st.settings, st.now()
    with st.store.session() as s:
        user = s.query(AppUser).filter_by(username=body.username.strip().lower()).first()
        ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if user is None:
            raise HTTPException(401, BAD_LOGIN)
        locked = user.locked_until is not None and aware(user.locked_until) > now
        usable = user.active and (user.client is None or user.client.active)
        if locked or not usable:
            raise HTTPException(401, BAD_LOGIN)
        if not ok:
            user.failed_logins += 1
            if user.failed_logins >= settings.login_max_failures:
                user.failed_logins = 0
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            s.commit()
            raise HTTPException(401, BAD_LOGIN)
        user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
        end_session(s, request.cookies.get(COOKIE))        # a new sign-in replaces this browser's old session
        token = create_session(s, user, settings.session_hours, now)
        s.commit()
        me = _me(s, user, None)
    response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600, httponly=True,
                        samesite="lax", secure=settings.cookie_secure, path="/")
    return me


@router.post("/logout", status_code=204)
def logout(request: Request):
    with request.app.state.store.session() as s:
        end_session(s, request.cookies.get(COOKIE))
        s.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/me")
def me(request: Request):
    scope = get_scope(request)
    with request.app.state.store.session() as s:
        return _me(s, s.get(AppUser, scope.user_id), scope.client_id)


@router.put("/me/client")
def set_acting_client(body: ActingClientIn, request: Request, scope: Scope = Depends(get_scope)):
    require_admin(scope)
    with request.app.state.store.session() as s:
        if body.client_id is not None and s.get(Client, body.client_id) is None:
            raise HTTPException(404, f"client {body.client_id} not found")
        s.get(AuthSession, token_hash(scope.token)).acting_client_id = body.client_id
        s.commit()
        return _me(s, s.get(AppUser, scope.user_id), body.client_id)
```

- [ ] **Step 7: Wire it into the app**

In `backend/app/api/__init__.py`:
- change `from datetime import date` to `from datetime import UTC, date, datetime`;
- add `from fastapi import Depends, FastAPI`, replacing `from fastapi import FastAPI`;
- change the signature to:

```python
def create_app(settings: Settings, embedder: Embedder | None = None, llm: LlmMatcher | None = None,
               today: Callable[[], date] = date.today, now: Callable[[], datetime] | None = None) -> FastAPI:
```

- replace the two router imports and the final `include_router` lines:

```python
    from app.api.auth_routes import router as auth_router
    from app.api.reporting import router as reporting_router
    from app.api.routes import router
    from app.auth.scope import get_scope
    from app.auth.sessions import purge_expired
```

```python
    app.state.today = today
    app.state.now = now or (lambda: datetime.now(UTC))
    with app.state.store.session() as s:
        purge_expired(s, app.state.now())
        s.commit()
```

The `app.state.today = today` line already exists; keep a single copy and add the rest after it.

```python
    guarded = [Depends(get_scope)]
    app.include_router(auth_router)
    app.include_router(router, dependencies=guarded)
    app.include_router(reporting_router, dependencies=guarded)
    return app
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/api -q`
Expected: PASS. Every existing API test passes, signed in as the admin with NovaBank selected, and the 16 new auth tests pass. Database tests run if Docker is up.

- [ ] **Step 9: Run the whole suite and commit**

Run: `cd backend && ../.venv/bin/pytest -q`
Expected: no failures.

```bash
git add backend/app backend/tests
git commit -m "feat(auth): login, logout, me and client switch; every API route requires a session"
```

---

### Task 4: Scope connections and mapping to the client

**Files:**
- Modify: `backend/app/auth/access.py`, `backend/app/api/routes.py`, `backend/app/api/schemas.py`
- Test: `backend/tests/api/test_isolation_api.py` (new)

**Interfaces:**
- Consumes:
  - `Scope`, `get_scope`, `require_admin` and `ADMIN_ONLY` (Task 3);
  - the test helpers from Task 3.
- Produces:
  - `visible_connection(s, scope, cid) -> Connection`;
  - `visible_run(s, scope, rid) -> MappingRun`;
  - `ConnectionIn.client_id: int | None = None`;
  - `ConnectionOut.client: ClientRefOut | None`, where `ClientRefOut(id: int, name: str)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/api/test_isolation_api.py
import pytest

from app.store import MappingRun
from tests.api.conftest import BHARAT, BHARAT_ID, NOVA, client1_body, signed_in


@pytest.fixture
def world(app):
    """Both clients with a connection (port 1: unreachable, no Docker needed) and a mapping run each."""
    with signed_in(app) as admin:
        nova = admin.post("/api/connections", json=client1_body(port=1)).json()["id"]
        bharat = admin.post("/api/connections", json=client1_body(name="Bharat Finserv", port=1,
                                                                   client_id=BHARAT_ID)).json()["id"]
    runs = {}
    with app.state.store.session() as s:
        for cid in (nova, bharat):
            run = MappingRun(connection_id=cid, catalog_version=1, layers="A", status="failed", error="x")
            s.add(run)
            s.flush()
            runs[cid] = run.id
        s.commit()
    return {"nova": {"cid": nova, "rid": runs[nova]}, "bharat": {"cid": bharat, "rid": runs[bharat]}}


def _call(client, method, path, body=None):
    return client.request(method, path, json=body) if body is not None else client.request(method, path)


CONNECTION_ROUTES = [
    ("PUT", "/api/connections/{cid}", client1_body(client_id=None)),
    ("DELETE", "/api/connections/{cid}", None),
    ("POST", "/api/connections/{cid}/test", None),
    ("GET", "/api/connections/{cid}/columns", None),
    ("POST", "/api/connections/{cid}/mapping-runs", {"layers": "A"}),
    ("GET", "/api/connections/{cid}/mapping-runs/latest", None),
]
RUN_ROUTES = [
    ("GET", "/api/mapping-runs/{rid}", None),
    ("PATCH", "/api/mapping-runs/{rid}/entries/cibil_score", {"action": "not_available"}),
    ("POST", "/api/mapping-runs/{rid}/accept-above", {"threshold": 0.9}),
    ("PUT", "/api/mapping-runs/{rid}/join-plan", {"join_plan": {}, "confirmed": True}),
    ("GET", "/api/mapping-runs/{rid}/preview", None),
    ("POST", "/api/mapping-runs/{rid}/publish", None),
]


@pytest.mark.parametrize("method,path,body", RUN_ROUTES + [r for r in CONNECTION_ROUTES if r[0] != "DELETE"])
def test_client_user_gets_404_for_another_clients_connection_and_runs(app, world, method, path, body):
    target = path.format(cid=world["bharat"]["cid"], rid=world["bharat"]["rid"])
    with signed_in(app, NOVA) as nova:
        r = _call(nova, method, target, body)
        assert r.status_code == 404, r.text


def test_client_user_reaches_own_connection_and_run(app, world):
    with signed_in(app, NOVA) as nova:
        assert nova.get(f"/api/mapping-runs/{world['nova']['rid']}").status_code == 200
        assert nova.post(f"/api/connections/{world['nova']['cid']}/test").json()["ok"] is False   # reached; port 1 refuses


def test_lists_show_only_the_clients_own_connection(app, world):
    with signed_in(app, NOVA) as nova:
        assert [c["name"] for c in nova.get("/api/connections").json()] == ["NovaBank"]
    with signed_in(app, BHARAT) as bharat:
        assert [c["name"] for c in bharat.get("/api/connections").json()] == ["Bharat Finserv"]
    with signed_in(app) as admin:
        listed = admin.get("/api/connections").json()
        assert {c["name"]: c["client"]["name"] for c in listed} == {"Bharat Finserv": "Bharat Finserv", "NovaBank": "NovaBank"}


def test_only_the_admin_creates_or_deletes_connections(app, world):
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/connections", json=client1_body(name="Another"))
        assert r.status_code == 403 and r.json()["detail"] == "Only the platform admin can do this"
        assert nova.delete(f"/api/connections/{world['nova']['cid']}").status_code == 403
    with signed_in(app) as admin:
        assert admin.delete(f"/api/connections/{world['bharat']['cid']}").status_code == 204


def test_admin_create_needs_a_client_and_one_connection_per_client(app, world):
    with signed_in(app) as admin:
        assert admin.post("/api/connections", json=client1_body(name="X", client_id=None)).status_code == 422
        assert admin.post("/api/connections", json=client1_body(name="X", client_id=999)).status_code == 404
        r = admin.post("/api/connections", json=client1_body(name="X"))
        assert r.status_code == 409 and r.json()["detail"] == "NovaBank already has a connection"


def test_client_user_can_edit_own_connection_but_not_move_it(app, world):
    cid = world["nova"]["cid"]
    with signed_in(app, NOVA) as nova:
        assert nova.put(f"/api/connections/{cid}", json=client1_body(name="Nova LOS", port=1, client_id=None)).status_code == 200
        r = nova.put(f"/api/connections/{cid}", json=client1_body(port=1, client_id=BHARAT_ID))
        assert r.status_code == 403


def test_rename_conflict_does_not_name_other_clients(app, world):
    with signed_in(app, NOVA) as nova:
        r = nova.put(f"/api/connections/{world['nova']['cid']}",
                     json=client1_body(name="Bharat Finserv", port=1, client_id=None))
        assert r.status_code == 409
        assert r.json()["detail"] == "the name 'Bharat Finserv' can't be used; choose another"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/api/test_isolation_api.py -q`
Expected: FAIL. The 404 cases return 200 or 409, and `test_only_the_admin_creates_or_deletes_connections` gets 201 instead of 403.

- [ ] **Step 3: Add the visibility helpers**

Add `from app.store import Connection, MappingRun` to the imports at the top of `backend/app/auth/access.py`, then append:

```python
def _not_found(table: str, id_) -> HTTPException:
    return HTTPException(404, f"{table} {id_} not found")


def visible_connection(s, scope: Scope, cid: int) -> Connection:
    c = s.get(Connection, cid)
    if c is None or not (scope.is_admin or (c.client_id is not None and c.client_id == scope.client_id)):
        raise _not_found("connection", cid)
    return c


def visible_run(s, scope: Scope, rid: int) -> MappingRun:
    run = s.get(MappingRun, rid)
    if run is None:
        raise _not_found("mapping_run", rid)
    try:
        visible_connection(s, scope, run.connection_id)
    except HTTPException:
        raise _not_found("mapping_run", rid) from None
    return run
```

- [ ] **Step 4: Update the schemas**

In `backend/app/api/schemas.py`:
- add `client_id: int | None = None` to `ConnectionIn`, as the last field;
- add before `ConnectionOut`:

```python
class ClientRefOut(BaseModel):
    id: int
    name: str
```

- and to `ConnectionOut` add `client: ClientRefOut | None = None`.

- [ ] **Step 5: Scope the routes**

In `backend/app/api/routes.py`:
- update the imports:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from app.auth.access import require_admin, visible_connection, visible_run
from app.auth.scope import Scope, get_scope
from app.store import Client, Connection, MappingRun, Publication
```

- delete the `_get` helper;
- `_connection_out` sets the client: append `client=S.ClientRefOut(id=c.client.id, name=c.client.name) if c.client else None` to the `S.ConnectionOut(...)` call;
- add this helper below `_url`:

```python
def _commit_named(s, name: str) -> None:
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, f"the name {name!r} can't be used; choose another") from None


def _check_client_free(s, client_id: int, except_cid: int | None = None) -> Client:
    client = s.get(Client, client_id)
    if client is None:
        raise HTTPException(404, f"client {client_id} not found")
    q = s.query(Connection).filter(Connection.client_id == client_id)
    if except_cid is not None:
        q = q.filter(Connection.id != except_cid)
    if q.first():
        raise HTTPException(409, f"{client.name} already has a connection")
    return client
```

Replace the connection handlers with:

```python
@router.get("/connections", response_model=list[S.ConnectionOut])
def list_connections(request: Request, scope: Scope = Depends(get_scope)):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        q = s.query(Connection).order_by(Connection.name)
        if not scope.is_admin:
            q = q.filter(Connection.client_id == scope.client_id)
        return [_connection_out(c, ctx.settings.secret_key) for c in q]


@router.post("/connections", response_model=S.ConnectionOut, status_code=201)
def create_connection(body: S.ConnectionIn, request: Request, scope: Scope = Depends(get_scope)):
    require_admin(scope)
    if not body.password:
        raise HTTPException(422, "password is required")
    if body.client_id is None:
        raise HTTPException(422, "client_id is required")
    ctx = _ctx(request)
    url = build_url(body.dialect, body.host, body.port, body.database, body.user, body.password)
    with ctx.store.session() as s:
        client = _check_client_free(s, body.client_id)
        c = Connection(name=body.name, dialect=body.dialect, schemas=body.schemas, client_id=client.id,
                       url_encrypted=encrypt_url(url, ctx.settings.secret_key))
        s.add(c)
        _commit_named(s, body.name)
        return _connection_out(c, ctx.settings.secret_key)


@router.put("/connections/{cid}", response_model=S.ConnectionOut)
def update_connection(cid: int, body: S.ConnectionIn, request: Request, scope: Scope = Depends(get_scope)):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        c = visible_connection(s, scope, cid)
        if body.client_id is not None and body.client_id != c.client_id:
            require_admin(scope)
            c.client_id = _check_client_free(s, body.client_id, except_cid=c.id).id
        password = body.password
        if not password:
            from sqlalchemy import make_url
            password = make_url(_url(c, ctx.settings.secret_key)).password
        url = build_url(body.dialect, body.host, body.port, body.database, body.user, password)
        c.name, c.dialect, c.schemas = body.name, body.dialect, body.schemas
        c.url_encrypted = encrypt_url(url, ctx.settings.secret_key)
        _commit_named(s, body.name)
        return _connection_out(c, ctx.settings.secret_key)


@router.delete("/connections/{cid}", status_code=204)
def delete_connection(cid: int, request: Request, scope: Scope = Depends(get_scope)):
    require_admin(scope)
    with _ctx(request).store.session() as s:
        s.delete(visible_connection(s, scope, cid))
        s.commit()
    return Response(status_code=204)
```

In the remaining handlers:
- add the parameter `scope: Scope = Depends(get_scope)`;
- replace `_get(s, Connection, cid)` with `visible_connection(s, scope, cid)`, in `test_connection_route`, `list_columns` and `start_run`;
- replace `_get(s, MappingRun, rid)` with `visible_run(s, scope, rid)`, in `get_run` and `publish_run`;
- in `latest_run`, call `visible_connection(s, scope, cid)` before querying;
- change `_ready_run` to:

```python
def _ready_run(s, scope: Scope, rid: int) -> MappingRun:
    run = visible_run(s, scope, rid)
    if run.status not in ("ready", "published"):
        raise HTTPException(409, f"run {rid} is {run.status}")
    return run
```

- call `_ready_run(s, scope, rid)` in `patch_entry`, `accept_above`, `put_join_plan` and `preview_run`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/api -q`
Expected: PASS. That's the 17 new isolation tests, the auth tests, and the existing API tests. `test_unknown_run_is_404` still passes.

- [ ] **Step 7: Commit**

```bash
git add backend/app backend/tests/api/test_isolation_api.py
git commit -m "feat(auth): connections and mapping runs are visible only to their client"
```

---

### Task 5: Report and dashboard ownership, and rendering from the scope

**Files:**
- Modify: `backend/app/auth/access.py`, `backend/app/api/reporting.py`, `backend/app/reporting/defaults.py`, `backend/tests/api/test_reporting_api.py`
- Test: append to `backend/tests/api/test_isolation_api.py`

**Interfaces:**
- Consumes: Task 4's helpers and the `world` fixture.
- Produces:
  - `visible_item(s, scope, model, id_)`;
  - `check_editable(scope, obj) -> None`, which raises 403;
  - `is_editable(scope, obj) -> bool`;
  - `scope_connection(s, scope) -> Connection`.
  - API changes:
    - report and dashboard JSON gains `shared: bool`, `editable: bool` and `owner: {id, name} | null`;
    - `ReportIn` and `DashboardIn` gain `shared: bool = True`;
    - render bodies are `{period}` or `{period, blocks}`, with extra keys forbidden;
    - `/connections/published` is gone.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/test_isolation_api.py`:

```python
from tests.api.conftest import NOVA_ID   # add to the import line at the top instead

CHART = {"id": "c1", "type": "chart", "chart": "bar",
         "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"]}}


@pytest.fixture
def items(app, world):
    """A private report and dashboard for each client (made by the admin), plus the seeded shared ones."""
    out = {}
    with signed_in(app) as admin:
        out["shared_report"] = admin.get("/api/reports").json()[0]["id"]
        out["shared_dashboard"] = admin.get("/api/dashboards").json()[0]["id"]
        for key, client_id in (("nova", NOVA_ID), ("bharat", BHARAT_ID)):
            admin.put("/api/auth/me/client", json={"client_id": client_id})
            out[f"{key}_report"] = admin.post("/api/reports", json={"name": f"{key} pack", "blocks": [CHART],
                                                                   "shared": False}).json()["id"]
            out[f"{key}_dashboard"] = admin.post("/api/dashboards", json={"name": f"{key} board", "tiles": [],
                                                                         "shared": False}).json()["id"]
    return out


ITEM_ROUTES = [
    ("GET", "/api/reports/{rid}", None),
    ("PUT", "/api/reports/{rid}", {"name": "x", "blocks": []}),
    ("DELETE", "/api/reports/{rid}", None),
    ("POST", "/api/reports/{rid}/render", {"period": {"preset": "last_month"}}),
    ("GET", "/api/dashboards/{did}", None),
    ("PUT", "/api/dashboards/{did}", {"name": "x", "tiles": []}),
    ("DELETE", "/api/dashboards/{did}", None),
    ("POST", "/api/dashboards/{did}/render", {"period": {"preset": "last_month"}}),
]


@pytest.mark.parametrize("method,path,body", ITEM_ROUTES)
def test_client_user_gets_404_for_another_clients_items(app, items, method, path, body):
    target = path.format(rid=items["bharat_report"], did=items["bharat_dashboard"])
    with signed_in(app, NOVA) as nova:
        assert _call(nova, method, target, body).status_code == 404


def test_lists_show_shared_and_own_items_with_flags(app, items):
    with signed_in(app, NOVA) as nova:
        reports = {r["name"]: r for r in nova.get("/api/reports").json()}
        assert set(reports) == {"Monthly Lending MIS", "nova pack"}
        assert (reports["Monthly Lending MIS"]["shared"], reports["Monthly Lending MIS"]["editable"]) == (True, False)
        assert (reports["nova pack"]["shared"], reports["nova pack"]["editable"]) == (False, True)
        assert reports["nova pack"]["owner"] == {"id": NOVA_ID, "name": "NovaBank"}
        assert {d["name"] for d in nova.get("/api/dashboards").json()} == {"Lending KPIs", "nova board"}
    with signed_in(app) as admin:
        assert {r["name"] for r in admin.get("/api/reports").json()} == {"Monthly Lending MIS", "nova pack", "bharat pack"}
        assert all(r["editable"] for r in admin.get("/api/reports").json())


def test_shared_items_are_read_only_for_clients(app, items):
    with signed_in(app, NOVA) as nova:
        r = nova.put(f"/api/reports/{items['shared_report']}", json={"name": "Monthly Lending MIS", "blocks": []})
        assert r.status_code == 403 and r.json()["detail"] == "Shared items are read-only, use Save as"
        assert nova.delete(f"/api/dashboards/{items['shared_dashboard']}").status_code == 403
        assert nova.get(f"/api/reports/{items['shared_report']}").status_code == 200


def test_save_as_makes_a_private_copy_and_ignores_shared_flag(app, items):
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/reports", json={"name": "My MIS", "blocks": [CHART], "shared": True})
        assert r.status_code == 201 and r.json()["shared"] is False and r.json()["owner"]["name"] == "NovaBank"
    with signed_in(app, BHARAT) as bharat:
        assert "My MIS" not in {x["name"] for x in bharat.get("/api/reports").json()}


def test_name_rules_are_per_owner(app, items):
    with signed_in(app, NOVA) as nova:
        clash = nova.post("/api/reports", json={"name": "Monthly Lending MIS", "blocks": []})
        assert clash.status_code == 409 and clash.json()["detail"] == "the name 'Monthly Lending MIS' is already used"
        assert nova.post("/api/reports", json={"name": "nova pack", "blocks": []}).status_code == 409
        assert nova.post("/api/reports", json={"name": "bharat pack", "blocks": []}).status_code == 201   # no leak


def test_admin_private_item_needs_a_selected_client(app, items):
    with signed_in(app, acting=None) as admin:
        r = admin.post("/api/reports", json={"name": "Z", "blocks": [], "shared": False})
        assert r.status_code == 409 and r.json()["detail"] == "Choose a client first"
        assert admin.post("/api/reports", json={"name": "Z", "blocks": []}).json()["shared"] is True


def test_render_uses_the_signed_in_clients_connection(app, items):
    body = {"period": {"preset": "last_month"}, "blocks": [CHART]}
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/render-blocks", json=body)
        assert r.status_code == 502 and "cannot reach NovaBank" in r.json()["detail"]
    with signed_in(app, BHARAT) as bharat:
        assert "cannot reach Bharat Finserv" in bharat.post("/api/render-blocks", json=body).json()["detail"]
    with signed_in(app, acting=BHARAT_ID) as admin:
        assert "cannot reach Bharat Finserv" in admin.post("/api/render-blocks", json=body).json()["detail"]
        admin.put("/api/auth/me/client", json={"client_id": None})
        r = admin.post("/api/render-blocks", json=body)
        assert r.status_code == 409 and r.json()["detail"] == "Choose a client first"


def test_render_rejects_a_connection_id(app, items):
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/render-blocks", json={"connection_id": 2, "period": {"preset": "last_month"}, "blocks": [CHART]})
        assert r.status_code == 422


def test_client_without_connection_gets_not_published(app, items, world):
    with signed_in(app) as admin:
        admin.delete(f"/api/connections/{world['nova']['cid']}")
    with signed_in(app, NOVA) as nova:
        r = nova.post(f"/api/reports/{items['shared_report']}/render", json={"period": {"preset": "last_month"}})
        assert r.status_code == 409
        assert r.json()["detail"] == "NovaBank has no published views; publish its mapping first"
```

In `backend/tests/api/test_reporting_api.py`, make these edits:
- Replace `test_render_unknown_connection_and_bad_period` with:

```python
def test_render_needs_a_connection_and_a_valid_period(rapi):
    rid = rapi.get("/api/reports").json()[0]["id"]
    r = rapi.post(f"/api/reports/{rid}/render", json={"period": {"preset": "last_month"}})
    assert r.status_code == 409 and r.json()["detail"] == "NovaBank has no published views; publish its mapping first"
    rapi.post("/api/connections", json=client1_body())
    r = rapi.post(f"/api/reports/{rid}/render", json={"period": {"preset": "custom", "start": "2026-05-01"}})
    assert r.status_code == 422 and "custom periods need start and end" in r.json()["detail"]
```

- In every other render call in this file, delete the `"connection_id": ...` entry from the JSON body.
  - `test_render_unreachable_client_is_502`: `rapi.post("/api/connections", json=client1_body(port=1, password="topsecret"))` and then `json={"period": ..., "blocks": [...]}`.
  - `test_render_default_report_and_dashboard`: delete the line asserting on `/api/connections/published`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/api/test_isolation_api.py tests/api/test_reporting_api.py -q`
Expected: FAIL. Render bodies without `connection_id` get 422 (`Field required`), the item lists have no `shared` key, and the other client's items return 200.

- [ ] **Step 3: Add the ownership helpers**

Append to `backend/app/auth/access.py`, and add `Client` to its `app.store` import:

```python
def visible_item(s, scope: Scope, model, id_: int):
    """A report template or dashboard: shared items, the scope's own items, or anything for the admin."""
    obj = s.get(model, id_)
    if obj is None or not (scope.is_admin or obj.client_id is None or obj.client_id == scope.client_id):
        raise _not_found(model.__tablename__, id_)
    return obj


def is_editable(scope: Scope, obj) -> bool:
    return scope.is_admin or (obj.client_id is not None and obj.client_id == scope.client_id)


def check_editable(scope: Scope, obj) -> None:
    if not is_editable(scope, obj):
        raise HTTPException(403, SHARED_READ_ONLY)


def scope_connection(s, scope: Scope) -> Connection:
    """The connection reports render against: the client user's own, or the admin's selected client's."""
    if scope.client_id is None:
        raise HTTPException(409, CHOOSE_CLIENT)
    conn = s.query(Connection).filter_by(client_id=scope.client_id).first()
    if conn is None:
        client = s.get(Client, scope.client_id)
        raise HTTPException(409, f"{client.name} has no published views; publish its mapping first")
    return conn
```

- [ ] **Step 4: Rewrite the reporting routes for ownership**

In `backend/app/api/reporting.py`:

Imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, or_
from sqlalchemy.exc import OperationalError

from app.auth.access import CHOOSE_CLIENT, check_editable, is_editable, scope_connection, visible_item
from app.auth.scope import Scope, get_scope
from app.connections import DecryptError, decrypt_url, mask_secrets
from app.reporting.period import PeriodError, resolve_period
from app.reporting.render import NotPublished, RenderContext, check_published, render_blocks
from app.reporting.spec import check_blocks
from app.store import Dashboard, ReportTemplate
```

Models:

```python
class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    blocks: list[dict]
    shared: bool = True          # admin only; client users always create private items


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_period: dict = Field(default_factory=lambda: {"preset": "last_month"})
    tiles: list[dict]
    shared: bool = True


class RenderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")      # an old client sending connection_id fails loudly
    period: dict


class RenderBlocksIn(RenderIn):
    blocks: list[dict]
```

Delete `_get` and `_save`. Replace `_report_out` and `_dashboard_out`, and add the ownership helpers:

```python
def _ownership(obj, scope: Scope) -> dict:
    return {"shared": obj.client_id is None, "editable": is_editable(scope, obj),
            "owner": {"id": obj.client.id, "name": obj.client.name} if obj.client else None}


def _report_out(t: ReportTemplate, scope: Scope) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "blocks": t.blocks,
            "updated_at": t.updated_at.isoformat(), **_ownership(t, scope)}


def _dashboard_out(d: Dashboard, scope: Scope) -> dict:
    return {"id": d.id, "name": d.name, "default_period": d.default_period, "tiles": d.tiles,
            "updated_at": d.updated_at.isoformat(), **_ownership(d, scope)}


def _visible_query(s, model, scope: Scope):
    q = s.query(model).order_by(model.name)
    if not scope.is_admin:
        q = q.filter(or_(model.client_id.is_(None), model.client_id == scope.client_id))
    return q


def _new_owner(scope: Scope, shared: bool) -> int | None:
    if not scope.is_admin:
        return scope.client_id
    if shared:
        return None
    if scope.client_id is None:
        raise HTTPException(409, CHOOSE_CLIENT)
    return scope.client_id


def _check_name(s, model, name: str, owner: int | None, exclude: int | None = None) -> None:
    """Names are unique per owner, and a private item can't reuse a shared item's name (spec §2.2)."""
    clash = s.query(model).filter(model.name == name, model.id != (exclude or 0))
    same_owner = model.client_id.is_(None) if owner is None else model.client_id == owner
    if clash.filter(same_owner).first() or (owner is not None and clash.filter(model.client_id.is_(None)).first()):
        raise HTTPException(409, f"the name {name!r} is already used")


def _commit(s, obj) -> None:
    s.commit()
    s.refresh(obj)
```

Delete the whole `published_connections` route. Then rewrite the CRUD routes:

```python
@router.get("/reports")
def list_reports(request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _report_out(t, scope).items() if k != "blocks"}
                for t in _visible_query(s, ReportTemplate, scope)]


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, request: Request, scope: Scope = Depends(get_scope)):
    st = _state(request)
    _check_report(body, st)
    owner = _new_owner(scope, body.shared)
    with st.store.session() as s:
        _check_name(s, ReportTemplate, body.name, owner)
        t = ReportTemplate(name=body.name, description=body.description, blocks=body.blocks, client_id=owner)
        s.add(t)
        _commit(s, t)
        return _report_out(t, scope)


@router.get("/reports/{rid}")
def get_report(rid: int, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        return _report_out(visible_item(s, scope, ReportTemplate, rid), scope)


@router.put("/reports/{rid}")
def update_report(rid: int, body: ReportIn, request: Request, scope: Scope = Depends(get_scope)):
    st = _state(request)
    with st.store.session() as s:
        t = visible_item(s, scope, ReportTemplate, rid)
        check_editable(scope, t)
        _check_report(body, st)
        _check_name(s, ReportTemplate, body.name, t.client_id, exclude=t.id)
        t.name, t.description, t.blocks = body.name, body.description, body.blocks
        _commit(s, t)
        return _report_out(t, scope)


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: int, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        t = visible_item(s, scope, ReportTemplate, rid)
        check_editable(scope, t)
        s.delete(t)
        s.commit()
    return Response(status_code=204)
```

Do the same for dashboards:
- `list_dashboards` uses `_visible_query(s, Dashboard, scope)` and drops `"tiles"`;
- `create_dashboard` calls `_check_dashboard(body, st)`, then `_new_owner` and `_check_name(s, Dashboard, ...)`, then `Dashboard(name=..., default_period=..., tiles=..., client_id=owner)`;
- `get_dashboard`, `update_dashboard` and `delete_dashboard` follow the report pattern, using `_check_dashboard` and `_dashboard_out(d, scope)`.

Rendering:

```python
def _render(request: Request, scope: Scope, period_spec: dict, blocks: list[dict]) -> dict:
    st = _state(request)
    with st.store.session() as s:
        conn = scope_connection(s, scope)
        try:
            url = decrypt_url(conn.url_encrypted, st.settings.secret_key)
        except DecryptError as exc:
            raise HTTPException(409, f"{exc}; re-enter the password") from None
        connection_id, name = conn.id, conn.name
    ...the rest of the existing body is unchanged...


@router.post("/reports/{rid}/render")
def render_report(rid: int, body: RenderIn, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        blocks = visible_item(s, scope, ReportTemplate, rid).blocks
    return _render(request, scope, body.period, blocks)


@router.post("/dashboards/{did}/render")
def render_dashboard(did: int, body: RenderIn, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        blocks = [t["block"] for t in visible_item(s, scope, Dashboard, did).tiles]
    return _render(request, scope, body.period, blocks)


@router.post("/render-blocks")
def render_unsaved(body: RenderBlocksIn, request: Request, scope: Scope = Depends(get_scope)):
    return _render(request, scope, body.period, body.blocks)
```

- [ ] **Step 5: Seed the defaults among shared items only**

In `backend/app/reporting/defaults.py`:
- change both `filter_by(name=doc["name"])` calls to `filter_by(name=doc["name"], client_id=None)`;
- update the docstring to "added as shared items when missing by name".

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/api -q`
Expected: PASS. With Docker up, the database render tests pass too (`published_client` signs in as the admin with NovaBank selected).

- [ ] **Step 7: Run the whole suite and commit**

Run: `cd backend && ../.venv/bin/pytest -q`
Expected: no failures.

```bash
git add backend/app backend/tests
git commit -m "feat(auth): shared and private templates and dashboards; render uses the signed-in client"
```

---

### Task 6: Frontend sign-in, guarded routes and header

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/test/fixtures.ts`
- Create: `frontend/src/auth.tsx`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/components/UserMenu.tsx`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: the `/api/auth/*` endpoints (Task 3).
- Produces:
  - `api.ts`: `setUnauthorizedHandler(fn | null)`; types `ClientRef { id; name; code? }` and `Me { user: { id; username; display_name; role: "admin" | "client" }; client: ClientRef | null; clients: ClientRef[] }`;
  - `auth.tsx`: `ME_KEY = ["me"]`, `useMe()` (query data `Me | null`), `RequireAuth`, `useUnauthorizedRedirect()`, `safeNext(next: string | null): string`;
  - `test/fixtures.ts`: `meClient` and `meAdmin`.
- **Deviation from spec §4:** there is no separate `AuthProvider` component. The TanStack Query cache entry `["me"]`, read through `useMe()`, already plays that role, and `QueryClientProvider` is already at the root.

- [ ] **Step 1: Add the fixtures and write the failing tests**

Append to `frontend/src/test/fixtures.ts`:

```ts
import type { Me } from "../api";

export const meClient: Me = {
  user: { id: 2, username: "nova.analyst", display_name: "Nova Analyst", role: "client" },
  client: { id: 1, name: "NovaBank", code: "novabank" }, clients: [],
};
export const meAdmin: Me = {
  user: { id: 1, username: "admin", display_name: "Platform Admin", role: "admin" },
  client: { id: 1, name: "NovaBank", code: "novabank" },
  clients: [{ id: 2, name: "Bharat Finserv", code: "bharat" }, { id: 1, name: "NovaBank", code: "novabank" }],
};
```

Move the `import type` to the top of the file with any existing imports.

```tsx
// frontend/src/App.test.tsx
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { safeNext } from "./auth";
import { meAdmin, meClient } from "./test/fixtures";
import { mockApi } from "./test/render";

const unauthorized = () => new Response(JSON.stringify({ detail: "Sign in to continue" }), { status: 401 });

function renderApp(route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider><QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}><App /></MemoryRouter>
    </QueryClientProvider></MantineProvider>,
  );
}

describe("sign-in", () => {
  it("sends a signed-out visitor to the login page and back after signing in", async () => {
    let signedIn = false;
    const calls = mockApi({
      "GET /api/auth/me": () => (signedIn ? meClient : unauthorized()),
      "POST /api/auth/login": () => { signedIn = true; return meClient; },
      "GET /api/reports": [],
    });
    renderApp("/reports");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "nova.analyst");
    await user.type(screen.getByLabelText("Password"), "nova123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/auth/login")?.body).toEqual({ username: "nova.analyst", password: "nova123" });
    expect(screen.getByText("NovaBank")).toBeInTheDocument();
  });

  it("shows the generic error for a wrong password", async () => {
    mockApi({
      "GET /api/auth/me": unauthorized,
      "POST /api/auth/login": () => new Response(JSON.stringify({ detail: "Wrong username or password" }), { status: 401 }),
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "x");
    await user.type(screen.getByLabelText("Password"), "y");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Wrong username or password")).toBeInTheDocument();
  });

  it("returns to the login page when the session expires mid-use", async () => {
    let expired = false;
    mockApi({
      "GET /api/auth/me": () => (expired ? unauthorized() : meClient),
      "GET /api/connections": () => { expired = true; return unauthorized(); },
    });
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("only follows same-site next paths", () => {
    expect(safeNext("/reports")).toBe("/reports");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});

describe("header", () => {
  it("lets the admin switch client and sign out", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meAdmin,
      "GET /api/connections": [],
      "PUT /api/auth/me/client": { ...meAdmin, client: meAdmin.clients[0] },
      "POST /api/auth/logout": undefined,
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("textbox", { name: "Client" }));
    await user.click(await screen.findByRole("option", { name: "Bharat Finserv" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/auth/me/client")?.body).toEqual({ client_id: 2 }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/connections").length).toBeGreaterThan(1));   // refetched
    expect(screen.getByText("Platform Admin")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/auth/logout")).toBe(true));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test -- App.test`
Expected: FAIL to import `./auth` (`Failed to resolve import "./auth"`).

- [ ] **Step 3: Update `api.ts`**

Above `export async function api`, add:

```ts
let onUnauthorized: (() => void) | null = null;
/** Called when a non-auth request comes back 401 (the session expired or was ended elsewhere). */
export function setUnauthorizedHandler(handler: (() => void) | null) { onUnauthorized = handler; }
```

In `api()`:
- add `credentials: "same-origin",` to the fetch init, right after `...rest,`;
- after the `fetch` line, add:

```ts
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized?.();
```

Add the types (near `Connection`):

```ts
export interface ClientRef { id: number; name: string; code?: string }
export interface Me {
  user: { id: number; username: string; display_name: string; role: "admin" | "client" };
  client: ClientRef | null;
  clients: ClientRef[];
}
```

- [ ] **Step 4: Write `auth.tsx`**

```tsx
// frontend/src/auth.tsx
import { Alert, Center, Loader } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api, errorText, setUnauthorizedHandler, type Me } from "./api";

export const ME_KEY = ["me"];

/** Who is signed in: Me, or null when signed out. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY, retry: false, staleTime: Infinity,
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
  });
}

/** Only same-site paths: "/x" yes, "//host" or "https://host" no. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

const loginPath = (pathname: string, search: string) => `/login?next=${encodeURIComponent(pathname + search)}`;

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return <Center h="60vh"><Loader /></Center>;
  if (me.isError) return <Alert color="red">{errorText(me.error)}</Alert>;
  if (!me.data) return <Navigate to={loginPath(location.pathname, location.search)} replace />;
  return <>{children}</>;
}

/** On any 401 mid-session: forget cached data and go to the login page, remembering where we were. */
export function useUnauthorizedRedirect() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const where = useRef(location);
  where.current = location;
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (where.current.pathname === "/login") return;
      qc.clear();
      navigate(loginPath(where.current.pathname, where.current.search), { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, navigate]);
}
```

- [ ] **Step 5: Write the login page and the user menu**

```tsx
// frontend/src/pages/LoginPage.tsx
import { Button, Card, Center, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api, errorText, type Me } from "../api";
import { ME_KEY, safeNext, useMe } from "../auth";

export function LoginPage() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api<Me>("/auth/login", { method: "POST", json: { username, password } }),
    onSuccess: (m) => { qc.clear(); qc.setQueryData(ME_KEY, m); navigate(next, { replace: true }); },
  });

  if (me.data) return <Navigate to="/" replace />;
  const submit = (e: FormEvent) => { e.preventDefault(); login.mutate(); };
  const failure = login.isError
    ? (login.error instanceof ApiError && login.error.status === 401 ? "Wrong username or password" : errorText(login.error))
    : null;

  return (
    <Center mih="80vh">
      <Card withBorder shadow="sm" padding="lg" w={360}>
        <form onSubmit={submit}>
          <Stack>
            <div>
              <Title order={3}>BankReporter</Title>
              <Text size="sm" c="dimmed">Sign in to continue</Text>
            </div>
            <TextInput label="Username" autoComplete="username" value={username}
              onChange={(e) => setUsername(e.currentTarget.value)} />
            <PasswordInput label="Password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.currentTarget.value)} />
            <Button type="submit" loading={login.isPending} disabled={!username || !password}>Sign in</Button>
            {failure && <Text c="red" size="sm">{failure}</Text>}
          </Stack>
        </form>
      </Card>
    </Center>
  );
}
```

```tsx
// frontend/src/components/UserMenu.tsx
import { Badge, Button, Group, Select, Text } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type Me } from "../api";
import { ME_KEY, useMe } from "../auth";

const NONE = "none";

export function UserMenu() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const switchClient = useMutation({
    mutationFn: (id: number | null) => api<Me>("/auth/me/client", { method: "PUT", json: { client_id: id } }),
    onSuccess: (m) => {
      qc.setQueryData(ME_KEY, m);
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] });
    },
  });
  const logout = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => { qc.clear(); qc.setQueryData(ME_KEY, null); navigate("/login", { replace: true }); },
  });
  if (!me.data) return null;
  const { user, client, clients } = me.data;
  return (
    <Group gap="sm" ml="auto" wrap="nowrap">
      {user.role === "admin" ? (
        <Select aria-label="Client" size="xs" w={200} allowDeselect={false}
          data={[{ value: NONE, label: "— none —" }, ...clients.map((c) => ({ value: String(c.id), label: c.name }))]}
          value={client ? String(client.id) : NONE}
          onChange={(v) => switchClient.mutate(v && v !== NONE ? Number(v) : null)} />
      ) : (
        client && <Badge variant="light" size="lg">{client.name}</Badge>
      )}
      <Text size="sm">{user.display_name}</Text>
      <Button size="xs" variant="default" onClick={() => logout.mutate()} loading={logout.isPending}>Sign out</Button>
    </Group>
  );
}
```

- [ ] **Step 6: Restructure `App.tsx`**

```tsx
// frontend/src/App.tsx
import { AppShell, Group, NavLink as MantineNavLink, Title } from "@mantine/core";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { RequireAuth, useUnauthorizedRedirect } from "./auth";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { UserMenu } from "./components/UserMenu";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { DashboardsPage } from "./pages/DashboardsPage";
import { LoginPage } from "./pages/LoginPage";
import { MappingPage } from "./pages/MappingPage";
import { ReportEditorPage } from "./pages/ReportEditorPage";
import { ReportsPage } from "./pages/ReportsPage";

const NAV = [{ to: "/", label: "Connections", end: true }, { to: "/reports", label: "Reports" }, { to: "/dashboards", label: "Dashboards" }];

function Shell() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header className="no-print">
        <Group h="100%" px="md" gap="lg" wrap="nowrap">
          <Title order={3}><Link to="/" style={{ color: "inherit", textDecoration: "none" }}>BankReporter</Link></Title>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} style={{ textDecoration: "none" }}>
              {({ isActive }) => <MantineNavLink component="span" label={n.label} active={isActive} w="auto" />}
            </NavLink>
          ))}
          <UserMenu />
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<ConnectionsPage />} />
            <Route path="/connections/:id/mapping" element={<MappingPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/reports/new" element={<ReportEditorPage />} />
            <Route path="/reports/:id/edit" element={<ReportEditorPage />} />
            <Route path="/dashboards" element={<DashboardsPage />} />
            <Route path="/dashboards/:id" element={<DashboardsPage />} />
          </Routes>
        </ErrorBoundary>
      </AppShell.Main>
    </AppShell>
  );
}

export function App() {
  useUnauthorizedRedirect();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<RequireAuth><Shell /></RequireAuth>} />
    </Routes>
  );
}
```

- [ ] **Step 7: Run the tests and the type check**

Run: `cd frontend && npm test && npm run typecheck`
Expected: PASS, with 5 new tests. The existing page tests still pass, because they render pages directly and their pages don't use `useMe` yet.

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): login page, guarded routes, 401 redirect, client switcher and sign out"
```

---

### Task 7: Pages scoped to the signed-in client

**Files:**
- Create: `frontend/src/components/RenderError.tsx`, `NoClient.tsx`, `SharingChoice.tsx`, `OwnerBadge.tsx`
- Modify: `frontend/src/api.ts`, `pages/ConnectionsPage.tsx`, `components/ConnectionForm.tsx`, `pages/ReportsPage.tsx`, `pages/DashboardsPage.tsx`, `pages/ReportEditorPage.tsx`
- Delete: `frontend/src/components/ClientSelect.tsx`
- Tests: `pages/ConnectionsPage.test.tsx`, `components/ConnectionForm.test.tsx`, `pages/ReportsPage.test.tsx`, `pages/DashboardsPage.test.tsx`, `pages/ReportEditorPage.test.tsx`

**Interfaces:**
- Consumes:
  - `useMe` and `ME_KEY` (Task 6);
  - from the API (Tasks 4–5): `ConnectionOut.client`; the `shared`, `editable` and `owner` fields; the render body `{period}`; the 409 messages.
- Produces: no new exports beyond the four components.

- [ ] **Step 1: Update the API types**

In `frontend/src/api.ts`:
- `Connection` gets `client: ClientRef | null;`.
- `ConnectionInput` gets `client_id?: number | null;`.
- Replace `ReportSummary` and `DashboardSummary` with:

```ts
export interface Ownership { shared: boolean; editable: boolean; owner: ClientRef | null }
export interface ReportSummary extends Ownership { id: number; name: string; description: string; updated_at: string }
export interface DashboardSummary extends Ownership { id: number; name: string; default_period: PeriodSpec; updated_at: string }
```

- Delete the `PublishedConnection` interface.

Delete `frontend/src/components/ClientSelect.tsx`.

- [ ] **Step 2: Update the page tests (failing first)**

Make these test edits. Each one uses `meClient` and `meAdmin` from `../test/fixtures`.

`frontend/src/pages/ReportsPage.test.tsx`: replace the file body with:

```tsx
// frontend/src/pages/ReportsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReportsPage } from "./ReportsPage";
import { meAdmin, meClient } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/render";

const rendered = {
  client: { id: 7, name: "NovaBank" },
  period: { start: "2026-09-01", end: "2026-09-30", prev_start: "2026-08-01", prev_end: "2026-08-31", label: "Sep 2026" },
  generated_at: "2026-10-22T18:05:00",
  blocks: [{ id: "h1", type: "heading", text: "Personal Loans MIS — NovaBank", level: 1 },
           { id: "bad", type: "chart", error: "invalid block: measure 1: unknown metric 'gone'" }],
};
const shared = { id: 1, name: "Monthly Lending MIS", description: "", updated_at: "", shared: true, editable: false, owner: null };
const mine = { id: 2, name: "Mine", description: "", updated_at: "", shared: false, editable: true, owner: { id: 1, name: "NovaBank" } };
const ROUTE = { route: "/reports", path: "/reports" };

describe("ReportsPage", () => {
  it("renders the first template for the signed-in client and prints to PDF", async () => {
    const calls = mockApi({ "GET /api/auth/me": meClient, "GET /api/reports": [shared], "POST /api/reports/1/render": rendered });
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Personal Loans MIS — NovaBank")).toBeInTheDocument();
    expect(screen.getByText("invalid block: measure 1: unknown metric 'gone'")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ period: { preset: "last_month" } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Download PDF" }));
    expect(print).toHaveBeenCalled();
  });

  it("offers only Save as for a shared template", async () => {
    mockApi({ "GET /api/auth/me": meClient, "GET /api/reports": [shared], "POST /api/reports/1/render": rendered });
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Shared")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Save as…" })).toHaveAttribute("href", "/reports/1/edit");
    expect(screen.queryByRole("link", { name: "Edit template" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete template" })).not.toBeInTheDocument();
  });

  it("deletes an own template only after an in-page confirmation", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meClient, "GET /api/reports": [mine],
      "POST /api/reports/2/render": rendered, "DELETE /api/reports/2": undefined,
    });
    renderWithProviders(<ReportsPage />, ROUTE);
    const user = userEvent.setup();
    expect(await screen.findByText("Private")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Delete template" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("asks the admin to choose a client before rendering", async () => {
    const calls = mockApi({ "GET /api/auth/me": { ...meAdmin, client: null }, "GET /api/reports": [shared] });
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Choose a client in the header to see data")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("explains an unpublished mapping and links to it", async () => {
    mockApi({
      "GET /api/auth/me": meClient, "GET /api/reports": [shared],
      "POST /api/reports/1/render": () => new Response(JSON.stringify(
        { detail: "NovaBank has no published views; publish its mapping first" }), { status: 409 }),
      "GET /api/connections": [{ id: 7, name: "NovaBank", dialect: "postgresql", url_masked: "x", schemas: ["los"],
                                 needs_password: false, client: { id: 1, name: "NovaBank" } }],
    });
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Your data mapping isn't published yet")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Open the mapping" })).toHaveAttribute("href", "/connections/7/mapping");
  });
});
```

`frontend/src/pages/DashboardsPage.test.tsx`:
- add `shared: false, editable: true, owner: { id: 1, name: "NovaBank" }` to `board` and to the summary in `GET /api/dashboards`;
- add `"GET /api/auth/me": meClient`;
- delete the `/api/connections/published` mock;
- change the render-body expectation to `toEqual({ period: { preset: "last_month" } })`;
- append two tests:

```tsx
  it("offers only Save as copy on a shared dashboard", async () => {
    const sharedBoard = { ...board, shared: true, editable: false, owner: null };
    const calls = mockApi({
      "GET /api/auth/me": meClient,
      "GET /api/dashboards": [{ ...sharedBoard, tiles: undefined }],
      "GET /api/dashboards/1": sharedBoard,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/dashboards": (_u: string, init?: RequestInit) => ({ ...sharedBoard, id: 9, shared: false, editable: true, ...JSON.parse(String(init!.body)) }),
      "GET /api/dashboards/9": { ...board, id: 9 },
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    expect(await screen.findByText("Shared")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save as copy" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/dashboards")?.body)
      .toMatchObject({ name: "Lending KPIs (copy)" }));
  });

  it("lets the admin save a private copy for the selected client", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meAdmin,
      "GET /api/dashboards": [{ id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "", shared: true, editable: true, owner: null }],
      "GET /api/dashboards/1": { ...board, shared: true, editable: true, owner: null },
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/dashboards": (_u: string, init?: RequestInit) => ({ ...board, id: 9, ...JSON.parse(String(init!.body)) }),
      "GET /api/dashboards/9": { ...board, id: 9 },
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Save as…" }));
    await user.click(screen.getByRole("radio", { name: "Only NovaBank" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/dashboards")?.body)
      .toMatchObject({ shared: false }));
  });
```

Also add `meAdmin, meClient` to the imports from `../test/fixtures`.

`frontend/src/pages/ReportEditorPage.test.tsx`:
- in both `mockApi` calls, replace the `/api/connections/published` mock with `"GET /api/auth/me": meClient`;
- add `shared: false, editable: true, owner: null` to the `server` object in the reopen test;
- import `meClient` from `../test/fixtures`;
- append:

```tsx
describe("ReportEditorPage on a shared template", () => {
  it("saves a shared template only as a copy", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meClient,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "GET /api/reports/1": { id: 1, name: "Monthly Lending MIS", description: "", updated_at: "", blocks: [],
                              shared: true, editable: false, owner: null },
      "POST /api/reports": (_u: string, init?: RequestInit) => ({ id: 5, updated_at: "", ...JSON.parse(String(init!.body)) }),
    });
    renderWithProviders(<ReportEditorPage />, { route: "/reports/1/edit", path: "/reports/:id/edit" });
    expect(await screen.findByLabelText("Template name")).toHaveValue("Monthly Lending MIS (copy)");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Save as copy" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/reports")).toBe(true));
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});
```

`frontend/src/pages/ConnectionsPage.test.tsx`:
- add `client: { id: 1, name: "NovaBank" }` to `conn`;
- import `meAdmin, meClient` from `../test/fixtures`;
- in every existing `mockApi` call add `"GET /api/auth/me": meAdmin`, so the existing tests still see Delete;
- append:

```tsx
  it("hides admin-only controls from client users", async () => {
    mockApi({ "GET /api/auth/me": meClient, "GET /api/connections": [conn] });
    renderWithProviders(<ConnectionsPage />);
    expect(await screen.findByText("NovaBank")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add connection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("shows the admin which client each connection belongs to", async () => {
    mockApi({ "GET /api/auth/me": meAdmin, "GET /api/connections": [conn] });
    renderWithProviders(<ConnectionsPage />);
    expect(await screen.findByRole("columnheader", { name: "Client" })).toBeInTheDocument();
    expect(screen.getAllByText("NovaBank")).toHaveLength(2);     // the name cell and the client cell
  });
```

`frontend/src/components/ConnectionForm.test.tsx`: add `client: null` to `existing`, then append:

```tsx
  it("asks the admin which client the connection belongs to", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ConnectionForm initial={existing} onSubmit={onSubmit}
      clients={[{ id: 1, name: "NovaBank" }, { id: 2, name: "Bharat Finserv" }]} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Choose a client")).toBeInTheDocument();
    await user.click(screen.getByRole("textbox", { name: "Client" }));
    await user.click(await screen.findByRole("option", { name: "Bharat Finserv" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ client_id: 2 }));
  });
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL. ReportsPage, DashboardsPage and ReportEditorPage fail to import `../components/ClientSelect` (deleted), and the new ConnectionsPage and ConnectionForm tests fail on missing elements.

- [ ] **Step 4: Write the small shared components**

```tsx
// frontend/src/components/NoClient.tsx
import { Alert } from "@mantine/core";

export function NoClient() {
  return <Alert color="blue" className="no-print">Choose a client in the header to see data</Alert>;
}
```

```tsx
// frontend/src/components/OwnerBadge.tsx
import { Badge } from "@mantine/core";
import type { Ownership } from "../api";

export function OwnerBadge({ item }: { item: Ownership }) {
  return item.shared
    ? <Badge variant="light" color="gray">Shared</Badge>
    : <Badge variant="light" color="blue">Private</Badge>;
}
```

```tsx
// frontend/src/components/SharingChoice.tsx
import { Group, Radio } from "@mantine/core";
import { useMe } from "../auth";

/** Admin only: a new item is shared with every client or private to the selected one. */
export function SharingChoice({ shared, onChange }: { shared: boolean; onChange: (shared: boolean) => void }) {
  const me = useMe();
  if (me.data?.user.role !== "admin") return null;
  const client = me.data.client;
  return (
    <Radio.Group label="Who can see it" value={shared ? "shared" : "private"} onChange={(v) => onChange(v === "shared")}>
      <Group mt={4}>
        <Radio value="shared" label="Shared with all clients" />
        <Radio value="private" label={`Only ${client?.name ?? "the selected client"}`} disabled={!client} />
      </Group>
    </Radio.Group>
  );
}
```

```tsx
// frontend/src/components/RenderError.tsx
import { Alert, Anchor } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, api, errorText, type Connection } from "../api";
import { useMe } from "../auth";

function NotPublished() {
  const me = useMe();
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/connections") });
  const own = connections.data?.find((c) => c.client?.id === me.data?.client?.id);
  return (
    <Alert color="yellow" title="Your data mapping isn't published yet" className="no-print">
      {own
        ? <Anchor component={Link} to={`/connections/${own.id}/mapping`}>Open the mapping</Anchor>
        : "Ask the platform admin to set up your connection."}
    </Alert>
  );
}

export function RenderError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 409 && errorText(error).includes("no published views")) {
    return <NotPublished />;
  }
  return <Alert color="red" className="no-print">{errorText(error)}</Alert>;
}
```

- [ ] **Step 5: Update Connections**

`frontend/src/components/ConnectionForm.tsx`:
- import `Select` from `@mantine/core`, and `ClientRef` from `../api`;
- extend `Props` with `clients?: ClientRef[];` and destructure `clients`;
- add `client: initial?.client ? String(initial.client.id) : (null as string | null),` to the `values` state;
- in `submit`, before `setErrors(errs)`, add `if (clients && !values.client) errs.client = "Choose a client";`;
- in the `onSubmit({...})` object, append `...(clients ? { client_id: Number(values.client) } : {}),`;
- render the select first in the `Stack`, before the Name input:

```tsx
        {clients && (
          <Select label="Client" placeholder="Choose client" allowDeselect={false} value={values.client}
            data={clients.map((c) => ({ value: String(c.id), label: c.name }))}
            onChange={(v) => set("client")(v)} error={errors.client} />
        )}
```

`frontend/src/pages/ConnectionsPage.tsx`:
- add `import { useMe } from "../auth";`;
- in `ConnectionsPage`: `const me = useMe(); const isAdmin = me.data?.user.role === "admin";`;
- show the "Add connection" `Button` only when `isAdmin`;
- in the table head, insert `{isAdmin && <Table.Th>Client</Table.Th>}` after Name;
- pass `isAdmin` to `ConnectionRow`. In `ConnectionRow({ conn, onEdit, isAdmin })`:
  - insert `{isAdmin && <Table.Td>{conn.client?.name ?? "—"}</Table.Td>}` after the name cell;
  - wrap the delete `confirming ? … : …` block in `{isAdmin && (…)}`;
- pass `clients={isAdmin ? me.data?.clients : undefined}` to `<ConnectionForm …/>`.

- [ ] **Step 6: Update the Reports page**

In `frontend/src/pages/ReportsPage.tsx`:
- remove the `ClientSelect` import and the `client` state;
- add the imports `useMe` (from `../auth`), `NoClient`, `OwnerBadge` and `RenderError`;
- after the `reports` query:

```tsx
  const me = useMe();
  const clientId = me.data?.client?.id ?? null;
```

- in the render query, use `queryKey: ["render-report", selected, clientId, period]` and `enabled: selected !== null && clientId !== null && periodReady(period)`, and change the body to `json: { period }`;
- delete `<ClientSelect … />`;
- after the template `Select`, add `{template && <OwnerBadge item={template} />}`;
- replace the `{template && (<Group gap="xs"> … </Group>)}` block with:

```tsx
          {template && (template.editable ? (
            <Group gap="xs">
              <Anchor component={Link} to={`/reports/${template.id}/edit`} size="sm">Edit template</Anchor>
              {confirming ? (
                <>
                  <Button size="xs" color="red" loading={remove.isPending} onClick={() => remove.mutate(template.id)}>Confirm delete</Button>
                  <Button size="xs" variant="subtle" onClick={() => setConfirming(false)}>Cancel</Button>
                </>
              ) : (
                <Button size="xs" variant="subtle" color="red" onClick={() => setConfirming(true)}>Delete template</Button>
              )}
            </Group>
          ) : (
            <Anchor component={Link} to={`/reports/${template.id}/edit`} size="sm">Save as…</Anchor>
          ))}
```

- replace `{rendered.isError && <Alert …>{errorText(rendered.error)}</Alert>}` with:

```tsx
      {me.data && clientId === null && <NoClient />}
      {rendered.isError && <RenderError error={rendered.error} />}
```

- remove the now-unused `Alert` and `errorText` imports if TypeScript reports them as unused.

- [ ] **Step 7: Update the Dashboards page**

In `frontend/src/pages/DashboardsPage.tsx`:
- remove `ClientSelect` and the `client` state;
- add `useMe`, `NoClient`, `OwnerBadge`, `RenderError` and `SharingChoice`;
- add:

```tsx
  const me = useMe();
  const clientId = me.data?.client?.id ?? null;
  const [shared, setShared] = useState(true);
```

- in the render query:
  - `queryKey: ["render-dashboard", id, tiles === null ? "saved" : debounced, clientId, period]`;
  - `enabled: !!id && clientId !== null && periodReady(period) && shown.length > 0`;
  - the bodies become `json: { period }` and `json: { blocks: debounced.map((t) => t.block), period }`;
- `saveAs`'s `mutationFn: (name: string) => api<Dashboard>("/dashboards", { method: "POST", json: { ...body(), name, shared } })`;
- after the dashboard `Select`, add `<OwnerBadge item={board.data} />`;
- render the Edit button only when `board.data.editable`;
- the Save as button label is `{board.data.editable ? "Save as…" : "Save as copy"}`;
- inside the open Save-as group, before the Create button, add `<SharingChoice shared={shared} onChange={setShared} />`;
- replace `{rendered.isError && <Alert color="red">{errorText(rendered.error)}</Alert>}` with:

```tsx
      {me.data && clientId === null && <NoClient />}
      {rendered.isError && <RenderError error={rendered.error} />}
```

- [ ] **Step 8: Update the report editor**

In `frontend/src/pages/ReportEditorPage.tsx`:
- remove `ClientSelect` and the `client` state;
- add `useMe`, `NoClient`, `RenderError` and `SharingChoice`;
- add:

```tsx
  const me = useMe();
  const clientId = me.data?.client?.id ?? null;
  const readOnly = !isNew && existing.data?.editable === false;     // a shared template: save only as a copy
  const [shared, setShared] = useState(true);
```

- in the effect that loads `existing.data`, set the name to `existing.data.editable === false ? \`${name} (copy)\` : name`;
- in the preview query:
  - `queryKey: ["render-blocks", debounced, clientId, period]`;
  - `enabled: clientId !== null && debounced.length > 0 && periodReady(period)`;
  - the body becomes `json: { blocks: debounced, period }`;
- `save.mutationFn`:

```tsx
    mutationFn: () => (isNew || readOnly
      ? api<ReportTemplate>("/reports", { method: "POST", json: { ...draft, shared } })
      : api<ReportTemplate>(`/reports/${id}`, { method: "PUT", json: draft })),
```

- in `onSuccess`, change `if (isNew) navigate(...)` to `if (isNew || readOnly) navigate(\`/reports/${t.id}/edit\`, { replace: true });`;
- in the toolbar:
  - delete `<ClientSelect … />`;
  - after the Description input, add `{(isNew || readOnly) && <SharingChoice shared={shared} onChange={setShared} />}`;
  - the Save button label is `{readOnly ? "Save as copy" : "Save"}`;
- below the toolbar, add:

```tsx
      {readOnly && <Alert color="blue">This is a shared template. Saving creates your own copy.</Alert>}
```

- in the preview column:
  - replace `{client === null && <Text c="dimmed" size="sm">Choose a preview client to see live data.</Text>}` with `{me.data && clientId === null && <NoClient />}`;
  - replace `{preview.isError && <Alert color="red">{errorText(preview.error)}</Alert>}` with `{preview.isError && <RenderError error={preview.error} />}`.

- [ ] **Step 9: Run the tests and the type check**

Run: `cd frontend && npm test && npm run typecheck`
Expected: PASS (all frontend tests, including about 10 new ones), and `tsc` is clean.

- [ ] **Step 10: Commit**

```bash
git add -A frontend/src
git commit -m "feat(frontend): pages scoped to the signed-in client; shared vs private items; admin client choice"
```

---

### Task 8: README, local setup and an end-to-end check

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above. Produces nothing.

- [ ] **Step 1: Add the README section**

In `README.md`, insert after the "Run the app" code block (before "Walkthrough:"):

```markdown
### Sign in

Create the sample clients and users once (run from `backend/`; safe to repeat):

```bash
../.venv/bin/python -m app.auth.seed      # --admin-password / --client-password to choose your own
```

| User | Password | Sees |
|---|---|---|
| `admin` | `admin123` | every client; pick one in the header's **Client** menu; creates connections and shared templates |
| `nova.analyst` | `nova123` | NovaBank only |
| `bharat.analyst` | `bharat123` | Bharat Finserv only |

These are sample passwords for a proof of concept.
- Templates and dashboards are either **Shared** or **Private**.
  - Shared ones are visible to every client; a client can only **Save as copy**.
  - Private ones are visible only to their own client.
- The seed attaches the existing "NovaBank" and "Bharat Finserv" connections to their clients by name.
- Sessions last 12 hours (`BANKREPORTER_SESSION_HOURS`). Five wrong passwords lock an account for 5 minutes.
```

In the walkthrough:
- step 1 becomes "**Sign in** as `admin`. **Connections:** add NovaBank … (choose the client for each)…", keeping the rest of the existing text;
- in the layout list, add `backend/app/auth/`: passwords, sessions, the seed command, and the visibility rules.

- [ ] **Step 2: Run both full suites**

Run: `cd backend && ../.venv/bin/pytest -q` and then `cd frontend && npm test && npm run typecheck`
Expected: everything passes. Backend: the 549 + 1-skipped baseline plus the new tests, still with only the live LLM test skipped. Frontend: all pass.

- [ ] **Step 3: Upgrade and seed the real local store, then check end to end**

These steps upgrade `data/bankreporter.sqlite` in place: the API applies `upgrade()` at start-up. Restart the API, then seed:

```bash
cd backend && ../.venv/bin/python -m app.auth.seed
```

Expected output includes `attached connection NovaBank to NovaBank` and `attached connection Bharat Finserv to Bharat Finserv`. On a rerun, it shows the "exists; password left unchanged" lines instead.

Then check with curl, through the Vite proxy on 5173:

```bash
J=/tmp/br.cookies
curl -s -c $J -H 'Content-Type: application/json' -d '{"username":"nova.analyst","password":"nova123"}' localhost:5173/api/auth/login
curl -s -b $J localhost:5173/api/connections            # only NovaBank
curl -s -b $J -H 'Content-Type: application/json' -d '{"period":{"preset":"last_month"}}' localhost:5173/api/dashboards/1/render | head -c 300
curl -s -o /dev/null -w "%{http_code}\n" localhost:5173/api/connections   # 401 without the cookie
```

Expected:
- the login returns the `Me` JSON with client NovaBank;
- the connections list has one item;
- render returns Sep 2026 data for NovaBank (97 applications);
- the call without the cookie returns 401.

Then open http://localhost:5173. It should redirect to `/login`; sign in as `bharat.analyst` and check that only Bharat Finserv appears.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: sign-in, sample users and shared vs private items"
```
