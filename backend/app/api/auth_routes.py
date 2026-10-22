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
