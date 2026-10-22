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
