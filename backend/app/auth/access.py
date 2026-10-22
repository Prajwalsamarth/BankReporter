# backend/app/auth/access.py
"""Visibility and permission rules (spec §3.1). Every route fetches client data through these helpers."""
from fastapi import HTTPException

from app.auth.scope import Scope
from app.store import Connection, MappingRun

ADMIN_ONLY = "Only the platform admin can do this"
SHARED_READ_ONLY = "Shared items are read-only, use Save as"
CHOOSE_CLIENT = "Choose a client first"


def require_admin(scope: Scope) -> None:
    if not scope.is_admin:
        raise HTTPException(403, ADMIN_ONLY)


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
