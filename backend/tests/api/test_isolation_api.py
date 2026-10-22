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
