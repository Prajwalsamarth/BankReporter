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
