# backend/tests/api/test_reporting_api.py
from datetime import date

import pytest
from sqlalchemy import text

from app.api import create_app
from tests.api.conftest import BHARAT_ID, NOVA_ID, PUBLISH_SCHEMA, client1_body, make_app, signed_in

TODAY = date(2026, 10, 22)


@pytest.fixture
def rapi(settings, clock):
    app = make_app(settings, clock, today=lambda: TODAY)
    with signed_in(app) as client:
        yield client


def chart_block(bid="c1", **query):
    return {"id": bid, "type": "chart", "chart": "bar",
            "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"], **query}}


def test_metrics_endpoint(rapi):
    metrics = rapi.get("/api/metrics").json()
    assert len(metrics) == 22 and {"id", "label", "unit", "better", "group", "description"} <= set(metrics[0])


def test_defaults_seeded_once_and_valid(rapi, settings):
    reports = rapi.get("/api/reports").json()
    dashboards = rapi.get("/api/dashboards").json()
    assert [r["name"] for r in reports] == ["Monthly Lending MIS"]
    assert [d["name"] for d in dashboards] == ["Lending KPIs"]
    create_app(settings, today=lambda: TODAY)          # second start: no duplicates
    assert len(rapi.get("/api/reports").json()) == 1
    template = rapi.get(f"/api/reports/{reports[0]['id']}").json()
    assert rapi.put(f"/api/reports/{template['id']}", json={k: template[k] for k in ("name", "description", "blocks")}).status_code == 200
    board = rapi.get(f"/api/dashboards/{dashboards[0]['id']}").json()
    assert rapi.put(f"/api/dashboards/{board['id']}",
                    json={k: board[k] for k in ("name", "default_period", "tiles")}).status_code == 200


def test_report_crud_and_validation(rapi):
    created = rapi.post("/api/reports", json={"name": "Mine", "blocks": [chart_block()]})
    assert created.status_code == 201
    rid = created.json()["id"]
    bad = rapi.put(f"/api/reports/{rid}", json={"name": "Mine", "blocks": [chart_block(measures=[{"metric": "nope"}])]})
    assert bad.status_code == 422
    assert bad.json()["detail"]["errors"] == [{"block_id": "c1", "messages": ["measure 1: unknown metric 'nope'"]}]
    assert rapi.post("/api/reports", json={"name": "Mine", "blocks": []}).status_code == 409
    assert rapi.delete(f"/api/reports/{rid}").status_code == 204
    assert rapi.get(f"/api/reports/{rid}").status_code == 404


def test_dashboard_tile_validation(rapi):
    body = {"name": "D", "tiles": [{"id": "t", "width": 5, "height": "m", "block": chart_block()},
                                    {"id": "u", "width": 6, "height": "m", "block": {"id": "h", "type": "heading", "text": "x"}}]}
    r = rapi.post("/api/dashboards", json=body)
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert {"block_id": "t", "messages": ["width must be one of 3, 4, 6, 8, 12"]} in errors
    assert {"block_id": "h", "messages": ["heading blocks are not allowed here"]} in errors


def test_render_needs_a_connection_and_a_valid_period(rapi):
    rid = rapi.get("/api/reports").json()[0]["id"]
    r = rapi.post(f"/api/reports/{rid}/render", json={"period": {"preset": "last_month"}})
    assert r.status_code == 409 and r.json()["detail"] == "NovaBank has no published views; publish its mapping first"
    rapi.post("/api/connections", json=client1_body())
    r = rapi.post(f"/api/reports/{rid}/render", json={"period": {"preset": "custom", "start": "2026-05-01"}})
    assert r.status_code == 422 and "custom periods need start and end" in r.json()["detail"]


def test_render_unreachable_client_is_502(rapi):
    rapi.post("/api/connections", json=client1_body(port=1, password="topsecret"))
    r = rapi.post("/api/render-blocks", json={"period": {"preset": "last_month"}, "blocks": [chart_block()]})
    assert r.status_code == 502 and "topsecret" not in r.text


@pytest.fixture
def published_client(rapi, pg_engine):
    """Client 1 mapped and published to the eval schema through the API."""
    cid = rapi.post("/api/connections", json=client1_body()).json()["id"]
    rid = rapi.post(f"/api/connections/{cid}/mapping-runs", json={"layers": "A"}).json()["run_id"]
    detail = rapi.get(f"/api/mapping-runs/{rid}").json()
    rapi.put(f"/api/mapping-runs/{rid}/join-plan", json={"join_plan": detail["join_plan"], "confirmed": True})
    assert rapi.post(f"/api/mapping-runs/{rid}/publish").status_code == 200
    yield cid
    with pg_engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {PUBLISH_SCHEMA}.{v}"))


@pytest.mark.db
def test_render_default_report_and_dashboard(rapi, published_client):
    rid = rapi.get("/api/reports").json()[0]["id"]
    out = rapi.post(f"/api/reports/{rid}/render", json={"period": {"preset": "last_month"}}).json()
    assert out["client"]["name"] == "NovaBank" and out["period"]["label"] == "Sep 2026"
    assert [b.get("error") for b in out["blocks"]] == [None] * len(out["blocks"])
    assert out["blocks"][0]["text"] == "Personal Loans MIS — NovaBank"
    did = rapi.get("/api/dashboards").json()[0]["id"]
    board = rapi.post(f"/api/dashboards/{did}/render", json={"period": {"preset": "last_month"}}).json()
    assert len(board["blocks"]) == 14 and all("error" not in b for b in board["blocks"])
    assert board["blocks"][0]["kpi"]["sparkline"]


@pytest.mark.db
def test_render_blocks_stores_nothing(rapi, published_client):
    before = rapi.get("/api/reports").json()
    r = rapi.post("/api/render-blocks", json={"period": {"preset": "last_month"},
                                              "blocks": [chart_block()]})
    assert r.status_code == 200 and r.json()["blocks"][0]["rows"]
    assert rapi.get("/api/reports").json() == before


@pytest.mark.db
def test_render_unpublished_client_is_409(rapi, pg_engine):
    with pg_engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {PUBLISH_SCHEMA}.{v}"))
    rapi.post("/api/connections", json=client1_body())
    r = rapi.post("/api/render-blocks", json={"period": {"preset": "last_month"}, "blocks": [chart_block()]})
    assert r.status_code == 409 and r.json()["detail"] == "NovaBank has no published views; publish its mapping first"


@pytest.fixture
def bharat_connection_first(rapi):
    """Bharat's connection takes id 1, so NovaBank's connection id differs from NovaBank's client id."""
    assert rapi.post("/api/connections", json=client1_body(name="Bharat Finserv", port=1, client_id=BHARAT_ID)).status_code == 201


@pytest.mark.db
def test_render_names_the_client_it_was_made_for(rapi, bharat_connection_first, published_client):
    assert published_client != NOVA_ID
    out = rapi.post("/api/render-blocks", json={"period": {"preset": "last_month"}, "blocks": [chart_block()]}).json()
    assert out["client"] == {"id": NOVA_ID, "name": "NovaBank"}     # the client, so a stale tab can detect a switch
