"""Formulas give the same results on SQLite, Postgres and MySQL."""
from datetime import date

import pytest
from sqlalchemy import Date, Integer, create_engine, literal, select

from app.catalog.dialect_funcs import UnsupportedDialect
from app.catalog.formula import compile_formula, parse_formula


def run(engine, formula: str, **values):
    def resolve(name):
        v = values[name]
        return literal(v, Date if isinstance(v, date) else Integer)

    expr = compile_formula(parse_formula(formula, set(values)), resolve)
    with engine.connect() as conn:
        return conn.execute(select(expr)).scalar_one()


@pytest.mark.parametrize("start, end, expected", [
    (date(2026, 1, 1), date(2026, 1, 1), 0),
    (date(2026, 1, 31), date(2026, 3, 1), 29),
    (date(2024, 2, 28), date(2024, 3, 1), 2),     # leap year
    (date(2026, 3, 10), date(2026, 3, 1), -9),
])
def test_date_diff_days(any_engine, start, end, expected):
    assert run(any_engine, "DATE_DIFF_DAYS(a, b)", a=start, b=end) == expected


@pytest.mark.parametrize("start, end, expected", [
    (date(1990, 6, 15), date(2026, 6, 14), 35),
    (date(1990, 6, 15), date(2026, 6, 15), 36),
    (date(2000, 2, 29), date(2026, 2, 28), 25),   # leap-day birthday, not yet
    (date(2000, 2, 29), date(2026, 3, 1), 26),
    (date(2000, 2, 29), date(2024, 2, 29), 24),
])
def test_years_between(any_engine, start, end, expected):
    assert run(any_engine, "YEARS_BETWEEN(a, b)", a=start, b=end) == expected


@pytest.mark.parametrize("d, expected", [
    (date(2026, 3, 1), date(2026, 3, 1)),
    (date(2026, 3, 31), date(2026, 3, 1)),
    (date(2024, 2, 29), date(2024, 2, 1)),
])
def test_month_start(any_engine, d, expected):
    result = run(any_engine, "MONTH_START(a)", a=d)
    assert str(result)[:10] == expected.isoformat()


def test_date_functions_null_in_null_out(any_engine):
    def resolve(name):
        return literal(None, Date) if name == "a" else literal(date(2026, 1, 1), Date)

    expr = compile_formula(parse_formula("DATE_DIFF_DAYS(a, b)", {"a", "b"}), resolve)
    with any_engine.connect() as conn:
        assert conn.execute(select(expr)).scalar_one() is None


def test_division_keeps_fraction(any_engine):
    assert float(run(any_engine, "i / j", i=7, j=2)) == pytest.approx(3.5)


def test_division_keeps_fraction_for_large_amounts(any_engine):
    # e.g. requested_amount / (net_income_monthly * 12) with crore-scale amounts
    result = run(any_engine, "i / j", i=25_000_000, j=7)
    assert float(result) == pytest.approx(3571428.571429, abs=1e-6)


def test_division_by_zero_is_null(any_engine):
    assert run(any_engine, "i / j", i=7, j=0) is None


def test_round(any_engine):
    assert float(run(any_engine, "ROUND(i / j, 2)", i=2, j=3)) == pytest.approx(0.67)


def test_least_greatest(any_engine):
    assert run(any_engine, "LEAST(i, j)", i=3, j=9) == 3
    assert run(any_engine, "GREATEST(i, j)", i=3, j=9) == 9


def test_unsupported_dialect_names_function():
    engine = create_engine("sqlite://")
    expr = compile_formula(parse_formula("MONTH_START(a)", {"a"}), lambda _: literal(date(2026, 1, 5), Date))
    from sqlalchemy.dialects import mssql
    with pytest.raises(UnsupportedDialect, match="MONTH_START not supported on mssql"):
        expr.compile(dialect=mssql.dialect())
    engine.dispose()
