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
