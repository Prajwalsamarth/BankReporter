import pytest
from cryptography.fernet import Fernet

from app.api import create_app
from app.settings import Settings
from tests.api.conftest import client1_body


def test_refuses_to_start_without_secret_key(tmp_path):
    with pytest.raises(RuntimeError, match="BANKREPORTER_SECRET_KEY"):
        create_app(Settings(BANKREPORTER_SECRET_KEY=None, BANKREPORTER_DB=tmp_path / "a.sqlite"))


def test_refuses_to_start_with_invalid_secret_key(tmp_path):
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        create_app(Settings(BANKREPORTER_SECRET_KEY="nope", BANKREPORTER_DB=tmp_path / "a.sqlite"))


def test_catalog_endpoint(api):
    body = api.get("/api/catalog").json()
    assert len(body["fields"]) == 81
    assert body["sections"][0]["id"] == "application"


def test_connection_crud_never_returns_password(api):
    created = api.post("/api/connections", json=client1_body(password="topsecret")).json()
    assert created["url_masked"].startswith("postgresql+psycopg://novabank:***@")
    assert "topsecret" not in str(created)
    listed = api.get("/api/connections").json()
    assert [c["name"] for c in listed] == ["NovaBank"] and "topsecret" not in str(listed)

    updated = api.put(f"/api/connections/{created['id']}",
                      json={**client1_body(password=None), "name": "Nova"}).json()
    assert updated["name"] == "Nova"
    assert api.delete(f"/api/connections/{created['id']}").status_code == 204
    assert api.get("/api/connections").json() == []


def test_duplicate_connection_name_conflicts(api):
    api.post("/api/connections", json=client1_body())
    assert api.post("/api/connections", json=client1_body()).status_code == 409


def test_create_requires_password(api):
    assert api.post("/api/connections", json=client1_body(password=None)).status_code == 422


def test_unknown_dialect_rejected(api):
    assert api.post("/api/connections", json=client1_body(dialect="oracle")).status_code == 422


def test_connection_with_unreadable_url_needs_password(api, settings, tmp_path):
    cid = api.post("/api/connections", json=client1_body()).json()["id"]
    other = Settings(BANKREPORTER_SECRET_KEY=Fernet.generate_key().decode(), BANKREPORTER_DB=settings.db_path)
    from fastapi.testclient import TestClient
    with TestClient(create_app(other)) as c2:
        conn = c2.get("/api/connections").json()[0]
        assert conn["needs_password"] is True and conn["url_masked"] is None
        assert c2.put(f"/api/connections/{cid}", json=client1_body(password=None)).status_code == 409
        assert c2.put(f"/api/connections/{cid}", json=client1_body()).status_code == 200


def test_failed_connection_test_is_masked(api):
    cid = api.post("/api/connections", json=client1_body(port=1, password="topsecret")).json()["id"]
    result = api.post(f"/api/connections/{cid}/test").json()
    assert result["ok"] is False and "topsecret" not in result["error"]


def test_unknown_run_is_404(api):
    assert api.get("/api/mapping-runs/999").status_code == 404


# ---- run lifecycle against the real Client 1 database -------------------------------------------

@pytest.fixture
def run(api, pg_engine):
    cid = api.post("/api/connections", json=client1_body()).json()["id"]
    started = api.post(f"/api/connections/{cid}/mapping-runs", json={"layers": "AB"}).json()
    assert started["status"] == "running"
    detail = api.get(f"/api/mapping-runs/{started['run_id']}").json()   # TestClient ran the task
    assert detail["run"]["status"] == "ready", detail["run"]["error"]
    return cid, detail


@pytest.mark.db
def test_run_produces_entries_plan_and_blockers(run, api):
    cid, detail = run
    entries = {e["field_id"]: e for e in detail["entries"]}
    assert len(entries) == 59
    assert entries["cibil_score"]["source"] == {"schema": "los", "table": "bureau_report", "column": "cibil_score"}
    assert entries["cibil_score"]["decided_by"] == "A" and entries["cibil_score"]["status"] == "suggested"
    assert detail["join_plan"]["grain"]["table"] == "loan_application"
    assert detail["blockers"] == ["Join plan not confirmed"]
    assert "llm_disabled" in detail["run"]["warnings"] or detail["run"]["layers"] == "AB"
    assert api.get(f"/api/connections/{cid}/mapping-runs/latest").json()["run"]["id"] == detail["run"]["id"]


@pytest.mark.db
def test_entry_edits(run, api):
    _, detail = run
    rid = detail["run"]["id"]
    url = f"/api/mapping-runs/{rid}/entries"
    assert api.patch(f"{url}/cibil_score", json={"action": "accept"}).json()["status"] == "accepted"

    na = api.patch(f"{url}/card_utilization_pct", json={"action": "not_available"}).json()
    assert na["status"] == "not_available" and na["source"] is None
    after = api.get(f"/api/mapping-runs/{rid}").json()
    assert "card_utilization_pct" not in [a for a in after["affected_calculated"]]   # no calc uses it

    api.patch(f"{url}/existing_emi_monthly", json={"action": "not_available"})
    affected = api.get(f"/api/mapping-runs/{rid}").json()
    assert {"foir_pct", "post_loan_foir_pct"} <= set(affected["affected_calculated"])
    assert "Required field Existing Monthly EMIs is marked not available" in affected["blockers"]

    reset = api.patch(f"{url}/existing_emi_monthly", json={"action": "reset"}).json()
    assert reset["status"] == "suggested" and reset["source"]["column"] == "monthly_emi_obligations"


@pytest.mark.db
def test_choose_validates_type_conflict_and_plan(run, api):
    _, detail = run
    url = f"/api/mapping-runs/{detail['run']['id']}/entries"
    taken = api.patch(f"{url}/city", json={"action": "choose", "schema": "los", "table": "customer",
                                          "column": "state"})
    assert taken.status_code == 409 and "already the source of State" in taken.json()["detail"]
    wrong_type = api.patch(f"{url}/city", json={"action": "choose", "schema": "los",
                                               "table": "bureau_report", "column": "cibil_score"})
    assert wrong_type.status_code == 409 and "not compatible" in wrong_type.json()["detail"]
    missing = api.patch(f"{url}/city", json={"action": "choose", "schema": "los", "table": "customer",
                                            "column": "nope"})
    assert missing.status_code == 404


@pytest.mark.db
def test_accept_above_threshold(run, api):
    _, detail = run
    n = api.post(f"/api/mapping-runs/{detail['run']['id']}/accept-above", json={"threshold": 0.9}).json()
    assert n["accepted"] >= 50


@pytest.mark.db
def test_join_plan_validation_and_confirm(run, api):
    _, detail = run
    rid = detail["run"]["id"]
    plan = detail["join_plan"]
    bad = {**plan, "joins": plan["joins"] + [{"schema": "los", "table": "credit_decision", "kind": "one_to_one",
                                             "on": [["application_id", "decision_mode"]]}]}
    r = api.put(f"/api/mapping-runs/{rid}/join-plan", json={"join_plan": bad, "confirmed": True})
    assert r.status_code == 422 and "not unique" in str(r.json()["detail"])
    ok = api.put(f"/api/mapping-runs/{rid}/join-plan", json={"join_plan": plan, "confirmed": True})
    assert ok.status_code == 200 and ok.json()["run"]["join_plan_confirmed"] is True


@pytest.mark.db
def test_preview_and_publish(run, api, cleanup_eval_views):
    _, detail = run
    rid = detail["run"]["id"]
    blocked = api.post(f"/api/mapping-runs/{rid}/publish")
    assert blocked.status_code == 409 and blocked.json()["detail"]["blockers"] == ["Join plan not confirmed"]

    api.put(f"/api/mapping-runs/{rid}/join-plan", json={"join_plan": detail["join_plan"], "confirmed": True})
    prev = api.get(f"/api/mapping-runs/{rid}/preview?limit=3").json()
    assert len(prev["rows"]) == 3 and len(prev["columns"]) == 81

    published = api.post(f"/api/mapping-runs/{rid}/publish").json()
    assert published["row_count"] == 2000 and published["schema"] == "lending_rpt_eval"
    assert "CREATE VIEW lending_rpt_eval.applications_base" in published["ddl"]
    assert api.get(f"/api/mapping-runs/{rid}").json()["run"]["status"] == "published"

    api.patch(f"/api/mapping-runs/{rid}/entries/city", json={"action": "accept"})
    assert api.get(f"/api/mapping-runs/{rid}").json()["run"]["status"] == "ready"


@pytest.mark.db
def test_run_failure_is_recorded_and_masked(api):
    cid = api.post("/api/connections", json=client1_body(port=1, password="topsecret")).json()["id"]
    rid = api.post(f"/api/connections/{cid}/mapping-runs", json={}).json()["run_id"]
    run = api.get(f"/api/mapping-runs/{rid}").json()["run"]
    assert run["status"] == "failed" and "topsecret" not in run["error"]


@pytest.mark.db
def test_columns_endpoint(api, pg_engine):
    cid = api.post("/api/connections", json=client1_body()).json()["id"]
    cols = api.get(f"/api/connections/{cid}/columns").json()
    assert {"schema": "los", "table": "customer", "column": "city", "type": "string"} in cols


@pytest.mark.db
def test_patch_response_uses_schema_key(run, api):
    _, detail = run
    e = api.patch(f"/api/mapping-runs/{detail['run']['id']}/entries/city", json={"action": "accept"}).json()
    assert e["source"] == {"schema": "los", "table": "customer", "column": "city"}
    assert all("schema" in c for c in e["candidates"])
