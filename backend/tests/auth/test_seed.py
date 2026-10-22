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
