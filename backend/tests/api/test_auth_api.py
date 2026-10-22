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
