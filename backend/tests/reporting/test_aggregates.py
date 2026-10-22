# backend/tests/reporting/test_aggregates.py
import re

import pytest
from sqlalchemy import Column, Integer, MetaData, Numeric, String, Table, create_engine, insert, select

from app.catalog.formula import FormulaError
from app.reporting.aggregates import compile_aggregate, metric_refs, parse_aggregate

TYPES = {"amount": "decimal", "score": "integer", "ok": "boolean", "status": "enum", "d": "date"}
METRICS = {"approved", "total"}


def parse(formula):
    return parse_aggregate(formula, TYPES, METRICS)


@pytest.mark.parametrize("formula", [
    "COUNT()", "COUNT_IF(ok)", "COUNT_IF(status == 'X')", "SUM(amount)", "SUM_IF(amount, ok)",
    "AVG(score)", "AVG_IF(score, status in ['A', 'B'])", "MIN(d)", "MAX(amount)", "COUNT_DISTINCT(status)",
    "approved / total * 100", "ROUND(SUM(amount) / COUNT(), 2)", "COALESCE(SUM(amount), 0)", "-approved",
    "SUM(amount * 2 + COALESCE(score, 0))",
])
def test_valid_formulas(formula):
    parse(formula)


@pytest.mark.parametrize("formula, msg", [
    ("amount", "field 'amount' must be inside an aggregate"),
    ("SUM(SUM(amount))", "nested aggregates are not allowed"),
    ("COUNT_IF(score)", "COUNT_IF needs a boolean argument, got integer"),
    ("SUM(status)", "SUM needs a numeric argument, got string"),
    ("AVG_IF(amount, score)", "AVG_IF needs a boolean argument, got integer"),
    ("MIN(status)", "MIN needs a numeric or date argument, got string"),
    ("unknown_metric + 1", "unknown metric 'unknown_metric'"),
    ("SUM(nope)", "unknown field 'nope'"),
    ("COUNT(amount)", "COUNT takes 0 argument(s), got 1"),
    ("MEDIAN(amount)", "unknown function 'MEDIAN'"),
    ("'text'", "Constant not allowed outside aggregates"),
    ("approved > 1", "Compare not allowed outside aggregates"),
    ("ROUND(approved, total)", "ROUND takes an expression and an integer number of digits"),
])
def test_rejected_formulas(formula, msg):
    with pytest.raises(FormulaError, match=re.escape(msg)):
        parse(formula)


def test_metric_refs_ignore_names_inside_aggregates():
    assert metric_refs(parse("approved / total + SUM(amount)")) == {"approved", "total"}


metadata = MetaData()
t = Table("t", metadata, Column("id", Integer, primary_key=True), Column("amount", Numeric(14, 2)),
          Column("score", Integer), Column("ok", Integer), Column("status", String))


@pytest.fixture(scope="module")
def conn():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(insert(t), [
            {"id": 1, "amount": 100, "score": 700, "ok": 1, "status": "A"},
            {"id": 2, "amount": 50, "score": None, "ok": 0, "status": "B"},
            {"id": 3, "amount": None, "score": 650, "ok": 1, "status": "A"},
        ])
    with engine.connect() as c:
        yield c


def run(conn, formula, metrics=None, where=None):
    metrics = metrics or {}

    def resolve_metric(name):
        return compile_aggregate(parse(metrics[name]), TYPES, lambda f: t.c[f], resolve_metric)

    expr = compile_aggregate(parse(formula), TYPES, lambda f: t.c[f], resolve_metric)
    stmt = select(expr).select_from(t)
    if where is not None:
        stmt = stmt.where(where)
    return conn.execute(stmt).scalar_one()


def test_count_and_conditional_aggregates(conn):
    assert run(conn, "COUNT()") == 3
    assert run(conn, "COUNT_IF(ok)") == 2
    assert run(conn, "COUNT_IF(status == 'B')") == 1
    assert float(run(conn, "SUM_IF(amount, ok)")) == pytest.approx(100)
    assert float(run(conn, "AVG_IF(score, ok)")) == pytest.approx(675)
    assert run(conn, "COUNT_DISTINCT(status)") == 2


def test_metric_ratio_and_zero_denominator(conn):
    metrics = {"approved": "COUNT_IF(ok)", "total": "COUNT()"}
    assert float(run(conn, "approved / total * 100", metrics)) == pytest.approx(66.666667, abs=1e-5)
    assert run(conn, "approved / total", metrics, where=t.c.id > 99) is None   # empty -> 0/0 -> NULL


def test_count_if_on_empty_set_is_zero_not_null(conn):
    assert run(conn, "COUNT_IF(ok)", where=t.c.id > 99) == 0
