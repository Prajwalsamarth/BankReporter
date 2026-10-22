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
