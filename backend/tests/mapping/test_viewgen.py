import pytest
from sqlalchemy import inspect, text

from app.mapping.introspect import introspect
from app.mapping.joins import plan_joins
from app.mapping.profile import profile_columns
from app.mapping.types import ColumnRef, Join
from app.mapping.viewgen import PublishError, build_base_select, build_view_ddl, preview, publish
from mockdata import generate
from mockdata.golden import format_value, read_golden
from mockdata.writers import client1_pg, client2_mysql
from tests.mapping.conftest import CATALOG, answer_key_sources

EVAL = "lending_rpt_eval"
CLIENTS = {"client1": ("pg_engine", "los", client1_pg), "client2": ("mysql_engine", "bfs_core", client2_mysql)}


def drop_eval_views(engine):
    with engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {EVAL}.{v}"))


@pytest.fixture(scope="module", params=list(CLIENTS))
def client(request):
    engine_fixture, schema, writer = CLIENTS[request.param]
    engine = request.getfixturevalue(engine_fixture)
    if not generate.GOLDEN_PATH.exists():
        pytest.skip("golden CSV missing; run python -m mockdata.generate --reset")
    info = introspect(engine, [schema])
    profiles = profile_columns(engine, info, CATALOG)
    plan = plan_joins(info, profiles, lambda ref: 0.0)
    yield engine, info, plan, answer_key_sources(writer, plan)
    drop_eval_views(engine)   # leave no views behind: they would block mockdata --reset


@pytest.mark.db
def test_answer_key_mapping_reproduces_golden_csv(client):
    engine, info, plan, sources = client
    statements = build_view_ddl(engine.dialect.name, EVAL, build_base_select(info, plan, sources, CATALOG), CATALOG)
    result = publish(engine, statements, plan.grain, EVAL)
    assert result.row_count == 2000

    golden = {r["application_id"]: r for r in read_golden(generate.GOLDEN_PATH)}
    types = {f.id: f.type for f in CATALOG.raw_fields}
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM {EVAL}.applications_base")).mappings().all()
    mismatches = [(r["application_id"], k) for r in rows for k, v in r.items()
                  if format_value(v, types[k]) != golden[r["application_id"]][k]]
    assert len(rows) == 2000 and mismatches == []


@pytest.mark.db
def test_calculated_view_has_81_columns(client):
    engine, info, plan, sources = client
    publish(engine, build_view_ddl(engine.dialect.name, EVAL, build_base_select(info, plan, sources, CATALOG),
                                   CATALOG), plan.grain, EVAL)
    cols = [c["name"] for c in inspect(engine).get_columns("applications", schema=EVAL)]
    assert cols == [f.id for f in CATALOG.raw_fields] + [f.id for f in CATALOG.calculated_fields]
    with engine.connect() as conn:
        n = conn.execute(text(f"SELECT COUNT(*) FROM {EVAL}.applications WHERE is_disbursed")).scalar_one()
    assert 900 < n < 1100


@pytest.mark.db
def test_not_available_field_is_typed_null(client):
    engine, info, plan, sources = client
    sources = {**sources, "pan_number": None, "cibil_score": None}
    publish(engine, build_view_ddl(engine.dialect.name, EVAL, build_base_select(info, plan, sources, CATALOG),
                                   CATALOG), plan.grain, EVAL)
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT COUNT(pan_number), COUNT(cibil_score), "
                                f"MIN(cibil_band) FROM {EVAL}.applications")).one()
    assert row == (0, 0, "NTC")


@pytest.mark.db
def test_duplicating_join_fails_row_count_and_leaves_no_views(client):
    engine, info, plan, sources = client
    drop_eval_views(engine)
    cust = sources["customer_id"]
    bad_plan = type(plan)(plan.grain, plan.joins + [
        Join(plan.grain.schema, plan.grain.table, "one_to_one", [(cust.column, cust.column)])])
    statements = build_view_ddl(engine.dialect.name, EVAL, build_base_select(info, bad_plan, sources, CATALOG),
                                CATALOG)
    with pytest.raises(PublishError, match="row count"):
        publish(engine, statements, plan.grain, EVAL)
    assert "applications_base" not in inspect(engine).get_view_names(schema=EVAL)


@pytest.mark.db
def test_preview_returns_rows_and_creates_nothing(client):
    engine, info, plan, sources = client
    drop_eval_views(engine)
    columns, rows = preview(engine, build_base_select(info, plan, sources, CATALOG), CATALOG, limit=5)
    assert len(rows) == 5 and len(columns) == 81
    assert "applications_base" not in inspect(engine).get_view_names(schema=EVAL)


def test_source_outside_join_plan_is_rejected(catalog):
    from app.mapping.types import ColumnInfo, JoinPlan, SchemaInfo, TableInfo
    t = TableInfo("s", "a", (ColumnInfo("id", "V", "string", False),), ("id",), (), 1)
    o = TableInfo("s", "other", (ColumnInfo("x", "V", "string", True),), (), (), 1)
    info = SchemaInfo("postgresql", (t, o))
    plan = JoinPlan(ColumnRef("s", "a", "id"), [])
    with pytest.raises(ValueError, match="s.other is not part of the join plan"):
        build_base_select(info, plan, {"application_id": plan.grain, "city": ColumnRef("s", "other", "x")}, catalog)
