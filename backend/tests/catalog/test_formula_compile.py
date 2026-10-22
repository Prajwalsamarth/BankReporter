from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, MetaData, Numeric, String, Table, create_engine, insert, select

from app.catalog.formula import compile_formula, parse_formula

metadata = MetaData()
t = Table(
    "t", metadata,
    Column("id", Integer, primary_key=True),
    Column("i", Integer),
    Column("j", Integer),
    Column("x", Numeric(14, 2)),
    Column("s", String),
)
ROWS = [
    {"id": 1, "i": 7, "j": 2, "x": Decimal("10.50"), "s": "A"},
    {"id": 2, "i": 5, "j": 0, "x": None, "s": "B"},
    {"id": 3, "i": None, "j": 3, "x": Decimal("-4.00"), "s": None},
]


@pytest.fixture(scope="module")
def conn():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(insert(t), ROWS)
    with engine.connect() as c:
        yield c


def run(conn, formula: str) -> list:
    tree = parse_formula(formula, {"i", "j", "x", "s"})
    expr = compile_formula(tree, lambda name: t.c[name])
    return [r[0] for r in conn.execute(select(expr).select_from(t).order_by(t.c.id))]


def approx(values):
    return [None if v is None else pytest.approx(float(v)) for v in values]


def test_field_reference(conn):
    assert run(conn, "i") == [7, 5, None]


def test_integer_arithmetic(conn):
    assert run(conn, "i + j * 2 - 1") == [10, 4, None]


def test_division_does_not_truncate(conn):
    assert approx(run(conn, "i / j")) == [3.5, None, None]


def test_division_by_zero_is_null(conn):
    assert run(conn, "i / j")[1] is None


def test_unary_minus(conn):
    assert run(conn, "-i") == [-7, -5, None]


def test_comparisons_and_bool_ops(conn):
    assert run(conn, "i > 6 or j == 3") == [1, 0, 1]
    assert run(conn, "i >= 5 and j != 0") == [1, 0, None]
    assert run(conn, "not (i < 6)") == [1, 0, None]


def test_is_none(conn):
    assert run(conn, "i is None") == [0, 0, 1]
    assert run(conn, "x is not None") == [1, 0, 1]


def test_in_list(conn):
    assert run(conn, "s in ['A', 'C']") == [1, 0, None]


def test_string_constant(conn):
    assert run(conn, "'k'") == ["k", "k", "k"]


def test_coalesce(conn):
    assert run(conn, "COALESCE(i, 0)") == [7, 5, 0]


def test_nullif(conn):
    assert run(conn, "NULLIF(j, 0)") == [2, None, 3]


def test_round(conn):
    assert approx(run(conn, "ROUND(i / 3, 2)")) == [2.33, 1.67, None]


def test_abs(conn):
    assert approx(run(conn, "ABS(x)")) == [10.5, None, 4.0]


def test_least_greatest(conn):
    assert run(conn, "LEAST(i, j)") == [2, 0, None]
    assert run(conn, "GREATEST(i, j, 6)") == [7, 6, None]


def test_if(conn):
    assert run(conn, "IF(i > 6, 'big', 'small')") == ["big", "small", "small"]


def test_case(conn):
    formula = "CASE(i is None, None, i < 6, 'low', i < 7, 'mid', 'high')"
    assert run(conn, formula) == ["high", "low", None]


def test_true_false_none_constants(conn):
    assert run(conn, "IF(True, 1, 0)") == [1, 1, 1]
    assert run(conn, "IF(False, 1, None)") == [None, None, None]
