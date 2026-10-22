# backend/tests/reporting/test_golden.py
"""Every metric and a grouped query give identical results on both clients and equal a plain-Python
calculation over the golden CSV (spec §10: "one template, any client")."""
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.mapping.introspect import introspect
from app.mapping.joins import plan_joins
from app.mapping.profile import profile_columns
from app.mapping.viewgen import build_base_select, build_view_ddl, publish
from app.reporting.metrics import load_metrics
from app.reporting.period import resolve_period
from app.reporting.query import grouped_select, scalar_select, view_table
from app.reporting.spec import Measure, QuerySpec
from mockdata import generate
from mockdata.golden import read_golden
from mockdata.writers import client1_pg, client2_mysql
from tests.mapping.conftest import CATALOG, answer_key_sources

EVAL = "lending_rpt_eval"
METRICS = load_metrics(Path(__file__).parents[3] / "catalog" / "metrics.yaml", CATALOG)
PERIOD = resolve_period({"preset": "custom", "start": "2026-01-01", "end": "2026-06-30"}, date(2026, 10, 22))
CLIENTS = {"client1": ("pg_engine", "los", client1_pg), "client2": ("mysql_engine", "bfs_core", client2_mysql)}


@pytest.fixture(scope="module", params=list(CLIENTS))
def published(request):
    engine_fixture, schema, writer = CLIENTS[request.param]
    engine = request.getfixturevalue(engine_fixture)
    if not generate.GOLDEN_PATH.exists():
        pytest.skip("golden CSV missing; run python -m mockdata.generate --reset")
    info = introspect(engine, [schema])
    plan = plan_joins(info, profile_columns(engine, info, CATALOG), lambda ref: 0.0)
    base = build_base_select(info, plan, answer_key_sources(writer, plan), CATALOG)
    publish(engine, build_view_ddl(engine.dialect.name, EVAL, base, CATALOG), plan.grain, EVAL)
    yield engine
    with engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {EVAL}.{v}"))


# ---- plain-Python reference over the golden CSV -------------------------------------------------

def num(x):
    return float(x) if x not in ("", None) else None


def day(x):
    return date.fromisoformat(x) if x else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def ratio(a, b):
    return None if not b else a / b * 100


def reference(rows: list[dict]) -> dict:
    approved = [r for r in rows if r["application_status"] in ("APPROVED", "DISBURSED")]
    disbursed = [r for r in rows if r["application_status"] == "DISBURSED"]
    decided = [r for r in rows if r["decision_date"]]
    rejected = [r for r in rows if r["application_status"] == "REJECTED"]

    def foir(r):
        net, emi = num(r["net_income_monthly"]), num(r["existing_emi_monthly"])
        if not net or emi is None:
            return None
        return (emi + (num(r["approved_emi"]) or 0)) / net * 100

    def tat(a, b, r):
        return (day(r[b]) - day(r[a])).days if r[a] and r[b] else None

    total = lambda rs, f: sum(num(r[f]) for r in rs if num(r[f]) is not None)
    return {
        "applications": len(rows), "decided": len(decided), "approved": len(approved),
        "rejected": len(rejected), "disbursed_count": len(disbursed),
        "approval_rate": ratio(len(approved), len(decided)), "rejection_rate": ratio(len(rejected), len(decided)),
        "disbursement_conversion": ratio(len(disbursed), len(approved)),
        "kyc_failure_rate": ratio(sum(r["kyc_status"] == "FAILED" for r in rows), len(rows)),
        "auto_decision_share": ratio(sum(r["decision_mode"] == "AUTO" for r in rows), len(decided)),
        "ntc_share": ratio(sum(r["cibil_score"] == "" for r in rows), len(rows)),
        "requested_amount_total": total(rows, "requested_amount"),
        "sanctioned_amount_total": total(rows, "approved_amount"),
        "disbursed_amount_total": total(rows, "disbursed_amount"),
        "avg_ticket_size": total(rows, "disbursed_amount") / len(disbursed) if disbursed else None,
        "processing_fee_income": total(rows, "processing_fee"),
        "avg_cibil": mean(num(r["cibil_score"]) for r in rows),
        "avg_interest_rate": mean(num(r["interest_rate_pct"]) for r in disbursed),
        "avg_post_loan_foir": mean(foir(r) for r in approved),
        "avg_decision_tat": mean(tat("application_date", "decision_date", r) for r in rows),
        "avg_disbursement_tat": mean(tat("decision_date", "disbursement_date", r) for r in rows),
        "avg_end_to_end_tat": mean(tat("application_date", "disbursement_date", r) for r in rows),
    }


def golden_in(start: date, end: date) -> list[dict]:
    return [r for r in read_golden(generate.GOLDEN_PATH) if start <= date.fromisoformat(r["application_date"]) < end]


@pytest.mark.db
def test_every_metric_matches_python_reference(published):
    view = view_table(CATALOG, EVAL)
    for start, end in [(PERIOD.start, PERIOD.end), (PERIOD.prev_start, PERIOD.prev_end)]:
        stmt = scalar_select([Measure(metric=m) for m in METRICS.ids], [], start, end, view, CATALOG, METRICS)
        with published.connect() as conn:
            got = dict(conn.execute(stmt).mappings().one())
        want = reference(golden_in(start, end))
        mismatches = {k: (got[k], want[k]) for k in METRICS.ids
                      if not (got[k] is None and want[k] is None)
                      and (got[k] is None or want[k] is None or float(got[k]) != pytest.approx(want[k], rel=1e-5))}
        assert mismatches == {}


@pytest.mark.db
def test_grouped_counts_match_python_reference(published):
    q = QuerySpec(measures=[Measure(metric="applications")], group_by=["channel", "application_status"], limit=500)
    stmt = grouped_select(q, PERIOD.start, PERIOD.end, view_table(CATALOG, EVAL), CATALOG, METRICS)
    with published.connect() as conn:
        got = {(r["channel"], r["application_status"]): r["applications"] for r in conn.execute(stmt).mappings()}
    want = Counter((r["channel"], r["application_status"]) for r in golden_in(PERIOD.start, PERIOD.end))
    assert got == dict(want)
