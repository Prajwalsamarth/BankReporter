# backend/tests/api/test_isolation_api.py
import pytest

from app.store import MappingRun
from tests.api.conftest import BHARAT, BHARAT_ID, NOVA, NOVA_ID, client1_body, signed_in


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


def test_renaming_to_another_clients_connection_name_reveals_nothing(app, world):
    """Names are not unique across clients, so a rename behaves the same whether the name is taken or not."""
    with signed_in(app, NOVA) as nova:
        taken = nova.put(f"/api/connections/{world['nova']['cid']}",
                         json=client1_body(name="Bharat Finserv", port=1, client_id=None))
        unused = nova.put(f"/api/connections/{world['nova']['cid']}",
                          json=client1_body(name="Zzz", port=1, client_id=None))
        assert taken.status_code == unused.status_code == 200


CHART = {"id": "c1", "type": "chart", "chart": "bar",
         "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"]}}


@pytest.fixture
def items(app, world):
    """A private report and dashboard for each client (made by the admin), plus the seeded shared ones."""
    out = {}
    with signed_in(app) as admin:
        out["shared_report"] = admin.get("/api/reports").json()[0]["id"]
        out["shared_dashboard"] = admin.get("/api/dashboards").json()[0]["id"]
        for key, client_id in (("nova", NOVA_ID), ("bharat", BHARAT_ID)):
            admin.put("/api/auth/me/client", json={"client_id": client_id})
            out[f"{key}_report"] = admin.post("/api/reports", json={"name": f"{key} pack", "blocks": [CHART],
                                                                   "shared": False}).json()["id"]
            out[f"{key}_dashboard"] = admin.post("/api/dashboards", json={"name": f"{key} board", "tiles": [],
                                                                         "shared": False}).json()["id"]
    return out


ITEM_ROUTES = [
    ("GET", "/api/reports/{rid}", None),
    ("PUT", "/api/reports/{rid}", {"name": "x", "blocks": []}),
    ("DELETE", "/api/reports/{rid}", None),
    ("POST", "/api/reports/{rid}/render", {"period": {"preset": "last_month"}}),
    ("GET", "/api/dashboards/{did}", None),
    ("PUT", "/api/dashboards/{did}", {"name": "x", "tiles": []}),
    ("DELETE", "/api/dashboards/{did}", None),
    ("POST", "/api/dashboards/{did}/render", {"period": {"preset": "last_month"}}),
]


@pytest.mark.parametrize("method,path,body", ITEM_ROUTES)
def test_client_user_gets_404_for_another_clients_items(app, items, method, path, body):
    target = path.format(rid=items["bharat_report"], did=items["bharat_dashboard"])
    with signed_in(app, NOVA) as nova:
        assert _call(nova, method, target, body).status_code == 404


def test_lists_show_shared_and_own_items_with_flags(app, items):
    with signed_in(app, NOVA) as nova:
        reports = {r["name"]: r for r in nova.get("/api/reports").json()}
        assert set(reports) == {"Monthly Lending MIS", "nova pack"}
        assert (reports["Monthly Lending MIS"]["shared"], reports["Monthly Lending MIS"]["editable"]) == (True, False)
        assert (reports["nova pack"]["shared"], reports["nova pack"]["editable"]) == (False, True)
        assert reports["nova pack"]["owner"] == {"id": NOVA_ID, "name": "NovaBank"}
        assert {d["name"] for d in nova.get("/api/dashboards").json()} == {"Lending KPIs", "nova board"}
    with signed_in(app) as admin:
        assert {r["name"] for r in admin.get("/api/reports").json()} == {"Monthly Lending MIS", "nova pack", "bharat pack"}
        assert all(r["editable"] for r in admin.get("/api/reports").json())


def test_shared_items_are_read_only_for_clients(app, items):
    with signed_in(app, NOVA) as nova:
        r = nova.put(f"/api/reports/{items['shared_report']}", json={"name": "Monthly Lending MIS", "blocks": []})
        assert r.status_code == 403 and r.json()["detail"] == "Shared items are read-only, use Save as"
        assert nova.delete(f"/api/dashboards/{items['shared_dashboard']}").status_code == 403
        assert nova.get(f"/api/reports/{items['shared_report']}").status_code == 200


def test_save_as_makes_a_private_copy_and_ignores_shared_flag(app, items):
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/reports", json={"name": "My MIS", "blocks": [CHART], "shared": True})
        assert r.status_code == 201 and r.json()["shared"] is False and r.json()["owner"]["name"] == "NovaBank"
    with signed_in(app, BHARAT) as bharat:
        assert "My MIS" not in {x["name"] for x in bharat.get("/api/reports").json()}


def test_name_rules_are_per_owner(app, items):
    with signed_in(app, NOVA) as nova:
        clash = nova.post("/api/reports", json={"name": "Monthly Lending MIS", "blocks": []})
        assert clash.status_code == 409 and clash.json()["detail"] == "the name 'Monthly Lending MIS' is already used"
        assert nova.post("/api/reports", json={"name": "nova pack", "blocks": []}).status_code == 409
        assert nova.post("/api/reports", json={"name": "bharat pack", "blocks": []}).status_code == 201   # no leak


def test_admin_private_item_needs_a_selected_client(app, items):
    with signed_in(app, acting=None) as admin:
        r = admin.post("/api/reports", json={"name": "Z", "blocks": [], "shared": False})
        assert r.status_code == 409 and r.json()["detail"] == "Choose a client first"
        assert admin.post("/api/reports", json={"name": "Z", "blocks": []}).json()["shared"] is True


def test_render_uses_the_signed_in_clients_connection(app, items):
    body = {"period": {"preset": "last_month"}, "blocks": [CHART]}
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/render-blocks", json=body)
        assert r.status_code == 502 and "cannot reach NovaBank" in r.json()["detail"]
    with signed_in(app, BHARAT) as bharat:
        assert "cannot reach Bharat Finserv" in bharat.post("/api/render-blocks", json=body).json()["detail"]
    with signed_in(app, acting=BHARAT_ID) as admin:
        assert "cannot reach Bharat Finserv" in admin.post("/api/render-blocks", json=body).json()["detail"]
        admin.put("/api/auth/me/client", json={"client_id": None})
        r = admin.post("/api/render-blocks", json=body)
        assert r.status_code == 409 and r.json()["detail"] == "Choose a client first"


def test_render_rejects_a_connection_id(app, items):
    with signed_in(app, NOVA) as nova:
        r = nova.post("/api/render-blocks", json={"connection_id": 2, "period": {"preset": "last_month"}, "blocks": [CHART]})
        assert r.status_code == 422


def test_client_without_connection_gets_not_published(app, items, world):
    with signed_in(app) as admin:
        admin.delete(f"/api/connections/{world['nova']['cid']}")
    with signed_in(app, NOVA) as nova:
        r = nova.post(f"/api/reports/{items['shared_report']}/render", json={"period": {"preset": "last_month"}})
        assert r.status_code == 409
        assert r.json()["detail"] == "NovaBank has no published views; publish its mapping first"
