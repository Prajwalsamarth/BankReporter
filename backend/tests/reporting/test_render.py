# backend/tests/reporting/test_render.py
"""Render engine on SQLite: a table holding view-shaped rows, exposed as main.applications."""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.catalog.loader import load_catalog
from app.reporting.metrics import load_metrics
from app.reporting.period import resolve_period
from app.reporting.render import NotPublished, RenderContext, check_published, render_blocks

ROOT = Path(__file__).parents[3]
CATALOG = load_catalog(ROOT / "catalog" / "fields.yaml")
METRICS = load_metrics(ROOT / "catalog" / "metrics.yaml", CATALOG)
SEP = {"preset": "last_month"}                   # with TODAY: Sep 2026, previous Aug 2026
TODAY = date(2026, 10, 22)


def app_row(i, month, status, channel="WEB", amount=None, reason=None):
    approved = status in ("APPROVED", "DISBURSED")
    return {"application_id": f"A{i}", "application_date": f"2026-{month:02d}-10",
            "application_month": f"2026-{month:02d}-01", "application_status": status, "channel": channel,
            "decision_date": None if status == "SUBMITTED" else f"2026-{month:02d}-12",
            "is_approved": int(approved), "is_rejected": int(status == "REJECTED"),
            "is_disbursed": int(status == "DISBURSED"), "disbursed_amount": amount, "rejection_reason": reason,
            "cibil_score": 720, "is_new_to_credit": 0, "kyc_status": "VERIFIED", "decision_mode": "AUTO"}


ROWS = [
    app_row(1, 9, "DISBURSED", "WEB", 500000), app_row(2, 9, "APPROVED", "DSA"),
    app_row(3, 9, "REJECTED", "WEB", reason="LOW_CIBIL"), app_row(4, 9, "SUBMITTED", "BRANCH"),
    app_row(5, 8, "DISBURSED", "WEB", 300000), app_row(6, 8, "REJECTED", "DSA", reason="HIGH_FOIR"),
]


@pytest.fixture(scope="module")
def conn():
    engine = create_engine("sqlite://")
    cols = ", ".join(f'"{f.id}"' for f in CATALOG.fields)
    with engine.begin() as c:
        c.execute(text(f"CREATE TABLE data ({cols})"))
        c.execute(text("CREATE VIEW applications AS SELECT * FROM data"))
        for r in ROWS:
            keys = list(r)
            c.execute(text(f"INSERT INTO data ({', '.join(keys)}) VALUES ({', '.join(':' + k for k in keys)})"), r)
    with engine.connect() as c:
        yield c


def ctx(period=SEP):
    return RenderContext(CATALOG, METRICS, resolve_period(period, TODAY), "NovaBank", schema="main")


def render(conn, *blocks, period=SEP):
    return render_blocks(list(blocks), conn, ctx(period))


def test_kpi_row_values_previous_and_delta(conn):
    [r] = render(conn, {"id": "k", "type": "kpi_row", "items": [{"measure": {"metric": "approval_rate"}},
                                                                 {"measure": {"metric": "applications"}}]})
    rate, apps = r["items"]
    assert rate["value"] == {"raw": pytest.approx(66.666667, abs=1e-5), "display": "66.7%"}   # 2 of 3 decided
    assert rate["previous"]["display"] == "50.0%"
    assert rate["delta"]["display"] == "+16.7 pts" and rate["delta"]["good"] is True
    assert apps["value"]["display"] == "4" and apps["delta"]["display"] == "+100.0%"


def test_kpi_tile_has_sparkline(conn):
    [r] = render(conn, {"id": "k", "type": "kpi", "measure": {"metric": "applications"}})
    assert [p["month"] for p in r["kpi"]["sparkline"]] == ["Aug 2026", "Sep 2026"]
    assert [p["raw"] for p in r["kpi"]["sparkline"]] == [2.0, 4.0]


def test_grouped_table_with_totals_and_sort(conn):
    [r] = render(conn, {"id": "t", "type": "table", "totals": True, "query": {
        "measures": [{"metric": "applications"}, {"field": "disbursed_amount", "agg": "sum"}],
        "group_by": ["channel"], "sort": {"by": "applications", "dir": "desc"}}})
    assert [c["key"] for c in r["columns"]] == ["channel", "applications", "sum_disbursed_amount"]
    assert r["rows"][0]["channel"]["display"] == "WEB"          # 2 applications; DSA and BRANCH tie on 1
    assert r["totals"]["applications"]["display"] == "4"
    assert r["totals"]["sum_disbursed_amount"]["display"] == "₹5.0 L"


def test_null_group_key_renders_dash(conn):
    # Review focus 1
    [r] = render(conn, {"id": "t", "type": "table", "query": {"measures": [{"metric": "applications"}],
                                                              "group_by": ["rejection_reason"]}})
    labels = {row["rejection_reason"]["display"]: row["applications"]["raw"] for row in r["rows"]}
    assert labels == {"—": 3.0, "LOW_CIBIL": 1.0}


def test_zero_denominator_kpi_is_dash_without_delta(conn):
    # Review focus 2: no approvals among BRANCH applications in either period
    [r] = render(conn, {"id": "k", "type": "kpi", "measure": {"metric": "disbursement_conversion"},
                        "filters": [["channel", "eq", "BRANCH"]], "sparkline": False})
    assert r["kpi"]["value"] == {"raw": None, "display": "—"} and r["kpi"]["delta"] is None


def test_empty_period_renders_every_block(conn):
    # Review focus 3
    out = render(conn, {"id": "k", "type": "kpi_row", "items": [{"measure": {"metric": "applications"}},
                                                                 {"measure": {"metric": "approval_rate"}}]},
                 {"id": "c", "type": "chart", "chart": "bar",
                  "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"]}},
                 period={"preset": "this_month"})
    assert "error" not in out[0] and "error" not in out[1]
    assert out[0]["items"][0]["value"]["display"] == "0" and out[0]["items"][1]["value"]["display"] == "—"
    assert out[1]["empty"] is True and out[1]["rows"] == []


def test_stale_block_errors_alone(conn):
    # Review focus 4
    out = render(conn, {"id": "a", "type": "kpi", "measure": {"metric": "removed_metric"}},
                 {"id": "b", "type": "heading", "text": "OK"})
    assert out[0]["error"].startswith("invalid block: measure 1: unknown metric 'removed_metric'")
    assert out[1] == {"id": "b", "type": "heading", "text": "OK", "level": 1}


def test_sql_failure_in_one_block_does_not_stop_others(conn):
    from sqlalchemy.exc import OperationalError
    blocks = [{"id": "c", "type": "chart", "chart": "bar",
               "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"]}},
              {"id": "h", "type": "heading", "text": "after"}]
    c = ctx()
    c.schema = "nope"            # every query in the chart fails
    out = render_blocks(blocks, conn, c)
    assert "error" in out[0] and out[1]["text"] == "after"


def test_text_placeholders(conn):
    [r] = render(conn, {"id": "t", "type": "text",
                        "text": "{{client_name}} · {{period}} · {{metric:applications}} apps · {{metric:approval_rate}} · {{nope}}"})
    assert r["text"] == "NovaBank · Sep 2026 · 4 apps · 66.7% · [unknown: nope]"


def test_check_published(conn):
    check_published(conn, ctx())
    c = ctx()
    c.schema = "nope"
    with pytest.raises(NotPublished, match="NovaBank has no published views; publish its mapping first"):
        check_published(conn, c)
