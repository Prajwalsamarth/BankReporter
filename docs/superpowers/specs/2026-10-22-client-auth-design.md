# BankReporter — Part 4: Client Sign-in and Data Isolation

**Date:** 2026-10-22
**Status:** Draft for review
**Depends on:** Parts 1–3 (catalog, mapping, published views, reports and dashboards, app store, React app).

---

## 0. Goal and success criteria

Add a sample authentication layer. Users sign in on a login page at the start. A **client user** belongs to one bank and sees only that bank's connection, mapping, reports and dashboards. A **platform admin** (the vendor) sees every client and works on one client at a time.

This is a proof of concept: the layer must be sound, but it is not enterprise-grade. Success means:
1. Every page except `/login` needs a signed-in user. Signing out ends the session at once.
2. A NovaBank user cannot see or change any Bharat Finserv data, through the UI or by calling the API directly. Asking for another client's object returns 404.
3. Shared templates and dashboards are visible to every client, read-only for client users, and copyable with **Save as**. Each client's own items are invisible to other clients.
4. The admin can switch between clients and see each client's reports and dashboards.
5. The existing `data/bankreporter.sqlite` is upgraded in place. No mapping has to be redone.

## 1. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Who signs in | Client users (each tied to one client) plus a platform admin |
| Templates and dashboards | A shared library (built-ins plus admin-shared items) plus private items per client; clients **Save as** to copy a shared item |
| Client permissions | Full use of their own connection and mapping: edit, test, run, review, publish. The admin creates and deletes connections |
| Connections per client | One |
| Login mechanism | Server-side sessions in SQLite, an HttpOnly cookie, and passwords hashed with standard-library scrypt |
| Client and user records | Kept in the app's SQLite store and created by a seed command; no admin screens |

## 2. Data model (app SQLite store)

Nothing changes in the client databases.

### 2.1 New tables

**`client`**

| Column | Type | Notes |
|---|---|---|
| id | int PK | autoincrement |
| name | str(100), unique | e.g. "NovaBank" |
| code | str(40), unique | slug, e.g. `novabank` |
| active | bool | default true; users of an inactive client cannot sign in |
| created_at | datetime | |

**`app_user`**

| Column | Type | Notes |
|---|---|---|
| id | int PK | autoincrement |
| username | str(80), unique | stored lower-case; matched case-insensitively |
| display_name | str(120) | |
| password_hash | str | `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>` |
| role | str(10) | `admin` or `client` |
| client_id | int FK client, nullable | required when the role is `client`; NULL when it is `admin` (checked in code and by the seed) |
| active | bool | default true |
| failed_logins | int | consecutive failures; reset on success |
| locked_until | datetime, nullable | |
| created_at, last_login_at | datetime | |

**`auth_session`** (named so it doesn't clash with SQLAlchemy's `Session`)

| Column | Type | Notes |
|---|---|---|
| token_hash | str(64) PK | SHA-256 hex of the cookie token |
| user_id | int FK app_user | |
| acting_client_id | int FK client, nullable | the admin's selected client; always NULL for client users |
| created_at | datetime | |
| expires_at | datetime | created_at + `session_hours` (default 12) |

### 2.2 Changes to existing tables

- `connection.client_id`: int FK client, nullable, **unique**. NULL means "not assigned", and only the admin sees such a connection.
- `report_template.client_id` and `dashboard.client_id`: int FK client, nullable. NULL means a shared library item; set means the item is private to that client.
- The global unique constraint on `report_template.name` and `dashboard.name` is removed. Names are unique **per owner**, checked in code:
  - two items with the same `client_id` cannot share a name, and two shared items cannot share a name;
  - a new private item cannot reuse a shared item's name.

  The resulting 409 message names the conflict but never mentions another client's items.
- `mapping_run` and `publication` are unchanged. They belong to a connection and inherit its client.

### 2.3 Upgrading an existing store

`app/store/migrate.py` provides `upgrade(engine)`. It runs at `Store` start-up after `create_all`, and running it again does nothing.
1. For each missing column, run `ALTER TABLE … ADD COLUMN` (connection, report_template, dashboard).
2. If `report_template` or `dashboard` still has a unique index or constraint on `name`, rebuild the table without it, inside one transaction:
   1. create `<t>_new`;
   2. copy the rows;
   3. drop the old table;
   4. rename `<t>_new`;
   5. recreate the indexes.
3. Existing templates and dashboards keep `client_id = NULL` and so become shared.

SQLite cannot add a UNIQUE column with `ALTER TABLE`. The uniqueness of `connection.client_id` is therefore a unique index, `CREATE UNIQUE INDEX IF NOT EXISTS ux_connection_client ON connection(client_id)`. SQLite allows several NULLs in such an index.

### 2.4 Seed command

`python -m app.auth.seed [--admin-password X] [--client-password Y]` is run from `backend/`. Running it again leaves the same data.
- It creates the clients **NovaBank** (`novabank`) and **Bharat Finserv** (`bharat`) if they are missing.
- It creates the users if they are missing:
  - `admin` (role admin);
  - `nova.analyst` (NovaBank);
  - `bharat.analyst` (Bharat Finserv).
- Default passwords are `admin123`, `nova123` and `bharat123`. The command prints them, warns that they are samples, and never overwrites the password of an existing user.
- It attaches a connection named "NovaBank" or "Bharat Finserv" with `client_id IS NULL` to the client of the same name.
- It prints a summary of what it created and what it attached.

## 3. Backend

### 3.1 Module layout

- `app/auth/passwords.py`:
  - `hash_password(pw) -> str` uses scrypt with n=2**14, r=8, p=1, a 16-byte random salt and a 32-byte key;
  - `verify_password(pw, stored) -> bool` compares with `hmac.compare_digest`.
- `app/auth/sessions.py`:
  - `create_session(s, user) -> token` makes the token with `secrets.token_urlsafe(32)`;
  - `lookup(s, token) -> AuthSession | None` returns None for an expired session and deletes it;
  - `end_session(s, token)`;
  - `purge_expired(s)` runs at start-up.
- `app/auth/scope.py`:
  - `Scope(user_id, username, role, client_id)`, where `client_id` is the user's own client, or the admin's acting client, which may be None;
  - `is_admin`;
  - the FastAPI dependency `get_scope(request) -> Scope`.
- `app/auth/access.py`: visibility helpers. Each returns the object or raises `HTTPException(404)`.
  - `visible_connection(s, scope, cid)`: a client user sees only the connection whose `client_id == scope.client_id`; the admin sees all.
  - `visible_run(s, scope, rid)` checks the run's connection with `visible_connection`.
  - `visible_template(s, scope, tid)` and `visible_dashboard(s, scope, did)`: shared items, or items whose `client_id == scope.client_id`. The admin sees all.
  - `editable(scope, obj)` raises 403 "Shared items are read-only, use Save as" when a client user targets a shared item. A client user can only reach their own private items anyway.
  - `scope_connection(s, scope) -> Connection`, used for rendering:
    - an admin with no acting client gets 409 "Choose a client first";
    - with no connection for the client, or no publication, the existing "not published" 409 is raised.
- `app/api/auth_routes.py`: the `/api/auth` router (§3.2).

### 3.2 Auth API

| Method and path | Body | Result |
|---|---|---|
| `POST /api/auth/login` | `{username, password}` | 200 with `Me` and sets the cookie, or 401 "Wrong username or password" |
| `POST /api/auth/logout` | none | 204; clears the cookie and deletes the session (works even when not signed in) |
| `GET /api/auth/me` | none | 200 `Me`, or 401 |
| `PUT /api/auth/me/client` | `{client_id: int \| null}` | admin only; returns 200 `Me`. A client user gets 403; an unknown client gets 404 |

The `Me` object:

```json
{"user": {"id": 1, "username": "admin", "display_name": "Platform Admin", "role": "admin"},
 "client": {"id": 1, "name": "NovaBank", "code": "novabank"} | null,
 "clients": [{"id": 1, "name": "NovaBank", "code": "novabank"}, ...]}
```

`clients` is filled only for the admin. For a client user it is an empty list.

**Login rules**
- The username is trimmed and lower-cased.
- An unknown user, a wrong password, an inactive user, an inactive client and a locked account all return the same 401 body.
- For an unknown username a dummy hash is still verified, so the response time doesn't reveal that the username doesn't exist.
- Each failure increments `failed_logins`. At 5 failures, `locked_until` is set to now + 5 minutes and the counter resets.
- A successful login resets the counter and sets `last_login_at`.

**Cookie**
- Name `br_session`; attributes HttpOnly, SameSite=Lax, Path=/, and Max-Age equal to the session length.
- `Secure` comes from the new `cookie_secure` setting (default false for localhost).

### 3.3 Enforcement

- Every router except `/api/auth/login`, `/api/auth/logout` and `/api/auth/me` is included with `dependencies=[Depends(get_scope)]`. `/api/auth/me` resolves the scope itself so it can return 401.
- Handlers that touch an object take `scope: Scope = Depends(get_scope)` and fetch the object only through an `access.py` helper.
- Mutating requests (POST, PUT, PATCH, DELETE) that carry a body must have `Content-Type: application/json`; otherwise they get 415. This is checked in `get_scope`. Together with SameSite=Lax, this stops cross-site form posts.

### 3.4 Route changes

**Connections**
- `GET /connections`:
  - a client user sees their own connection (zero or one);
  - the admin sees every connection, each with `client: {id, name} | null`.
- `POST /connections` is admin only and takes `client_id` (required).
  - A client that already has a connection returns 409.
  - A client user gets 403.
- `PUT /connections/{cid}` and `POST /connections/{cid}/test`: use `visible_connection`. Client users cannot change `client_id`; only the admin may, and it stays unique.
- `DELETE /connections/{cid}` is admin only.
- `GET /connections/{cid}/columns` uses `visible_connection`.

**Mapping**
- `POST /connections/{cid}/mapping-runs` and `GET /connections/{cid}/mapping-runs/latest` use `visible_connection`.
- Every `/mapping-runs/{rid}...` route uses `visible_run`.

**Reports and dashboards**
- `GET /reports` and `GET /dashboards` list the visible items. Each item gets `shared: bool` and `editable: bool`.
- `POST /reports` and `POST /dashboards` (this includes Save as, which is a POST of a copy):
  - a client user always creates a private item (`client_id = scope.client_id`), and any `shared` flag in the body is ignored;
  - the admin passes `shared: bool`, default true. With `shared: false`, the item is owned by the acting client, and 409 "Choose a client first" is returned if none is selected.
- `GET`, `PUT` and `DELETE /reports/{rid}` and `/dashboards/{did}`: GET uses `visible_*`; PUT and DELETE also use `editable`. The owner never changes on PUT.
- Name rules (§2.2) apply on create and update.

**Rendering**
- `POST /reports/{rid}/render`, `POST /dashboards/{did}/render` and `POST /render-blocks` no longer accept `connection_id`. They render against `scope_connection(scope)`.
  - The request body keeps `period` (and `blocks` for `/render-blocks`).
  - An unknown `connection_id` key is rejected with 422 so old clients fail loudly.
- `GET /connections/published` is removed.

**Catalog and metrics**
- `GET /catalog` and `GET /metrics` need a session but are not client-specific.

### 3.5 Settings

| Setting | Default |
|---|---|
| `session_hours` | 12 |
| `cookie_secure` | false |
| `login_max_failures` | 5 |
| `login_lock_minutes` | 5 |

## 4. Frontend

**Auth state**
- `src/auth.tsx` provides `AuthProvider` and `useMe()`. `useMe()` is a TanStack Query on `/auth/me`, with `retry: false` and a 401 treated as "signed out".
- `api()` sends `credentials: "same-origin"`. The cookie is same-origin through the Vite proxy.
- On a 401 from any request, `api()` calls a registered handler that clears the query cache and navigates to `/login?next=<current path>`.

**Routing**
- `/login` is public.
- Every other route is wrapped in `RequireAuth`, which shows a loader while `/auth/me` loads and redirects to `/login` if the user is signed out.

**Login page** (`pages/LoginPage.tsx`)
- A centred card with the BankReporter title, a username field, a password field and a **Sign in** button.
- A 401 shows "Wrong username or password" under the button.
- On success it goes to `next`, or `/`.
- A user who is already signed in and opens `/login` is sent to `/`.

**Header** (`App.tsx`)
- Right side, for a client user: a badge with the client name.
- Right side, for the admin: a **Client** Select listing every client plus "— none —". On change it calls `PUT /auth/me/client`, then invalidates every query.
- Right side, for both: the display name and a **Sign out** button, which calls `POST /auth/logout`, clears the cache and goes to `/login`.

**Connections page**
- A client user sees no "New connection" or Delete controls.
- The admin's list shows a Client column, and the new-connection form has a required Client select.

**Mapping page:** unchanged. A 404 shows the existing error state as "Not found".

**Reports and dashboards pages**
- The client dropdown is removed.
- Picker options show a **Shared** or **Private** badge.
- When `editable` is false: no Edit or Delete, and **Save as** is shown.
  - In the dashboard, Edit mode on a shared item is replaced by **Save as copy**, which opens the name prompt and POSTs a copy.
  - In the report editor, a shared template opens with only "Save as" (the Save button is hidden).
- When the admin creates a new item, a radio offers "Shared with all clients" or "Only <selected client>". "Only …" is disabled when no client is selected.
- Render 409s map to messages:
  - "Your data mapping isn't published yet", with a link to that connection's Mapping page;
  - "Choose a client in the header to see data" for the admin.

## 5. Error handling summary

| Situation | Status | User sees |
|---|---|---|
| No session, or it expired | 401 | Redirect to the login page |
| Bad login | 401 | "Wrong username or password" |
| Another client's object | 404 | "Not found" |
| Client edits or deletes a shared item | 403 | "Shared items are read-only, use Save as" |
| Client calls an admin-only route | 403 | "Only the platform admin can do this" |
| Admin renders with no client selected | 409 | "Choose a client in the header to see data" |
| Client not published | 409 | "Your data mapping isn't published yet" |
| Duplicate name for the owner | 409 | "The name 'X' is already used" |
| Mutating request that isn't JSON | 415 | not shown in the UI |

## 6. Testing

### Backend (pytest)

- **Password hashing:** a round trip works; a wrong password fails; each password gets a different salt; a malformed stored hash returns false rather than raising.
- **Sessions:**
  - the token is not stored, only its hash;
  - an expired session gives 401 and is deleted;
  - logout ends the session;
  - `purge_expired` removes expired sessions.
- **Login:**
  - success sets the cookie and `last_login_at`;
  - the generic 401 is returned for an unknown user, a wrong password, an inactive user and an inactive client;
  - the account locks after 5 failures and the lock expires (the clock is injected);
  - the username is matched case-insensitively.
- **Route-coverage guard:**
  - walk `app.routes`;
  - every `/api` route except the three auth routes must declare `get_scope` as a dependency;
  - this test fails for a new unguarded route.
- **Isolation matrix:**
  - fixtures: two clients, each with a connection, a run, a private template and a private dashboard, plus shared items;
  - signed in as client A, every route parameterised with client B's IDs returns 404;
  - list endpoints never contain client B's items.
- **Shared items:**
  - a client user sees shared items and their own;
  - PUT or DELETE on a shared item gives 403;
  - POST copy works;
  - the per-owner name rules hold;
  - a client user's `shared: true` in the body is ignored.
- **Admin:**
  - sees every connection;
  - `PUT /auth/me/client` changes which client render uses;
  - render with no client selected gives 409;
  - a client user calling `/auth/me/client` gets 403.
- **Rendering:**
  - a client user's render uses their own connection;
  - a body with `connection_id` gets 422.
- **Migration:** build an old-format SQLite file (the Part 3 schema, with global unique names) holding rows, then run `upgrade`. Check that:
  - the columns were added;
  - the unique constraint is gone;
  - the data is kept;
  - templates and dashboards are now shared;
  - a second `upgrade` changes nothing.
- **Seed:**
  - running it twice leaves the same rows;
  - it attaches the matching connections;
  - it doesn't overwrite an existing password.
- **Existing tests:** the `client` fixture signs in as a seeded admin, so the Part 1–3 tests keep working. Render tests now select a client first.

### Frontend (Vitest)

- The login page signs in and redirects to `next`; a wrong password shows the error.
- `RequireAuth` redirects when the user is signed out, and a 401 mid-session redirects to `/login`.
- The header shows the client badge for a client user and the client Select for the admin; Sign out calls logout.
- Shared items show the badge and Save as, without Edit or Delete.
- The admin's new-item form shows the shared or private choice.

## 7. Documentation

The README gets a **Sign in** section covering:
- the seed command;
- the sample users and passwords, and that they are samples;
- what each role can see.

## 8. Out of scope

- Sign-up, password reset and changing your own password.
- Admin screens for clients and users.
- SSO, two-factor authentication and audit logs.
- More than one connection per client.
- Per-user (rather than per-client) private items.
- Rate limiting by IP address.
