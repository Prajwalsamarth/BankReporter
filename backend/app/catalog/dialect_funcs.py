"""SQL functions whose spelling differs per dialect (spec §4.2).

Each is a FunctionElement with a @compiles override per supported dialect;
any other dialect raises UnsupportedDialect.
"""
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import Date, Integer

SUPPORTED = ("postgresql", "mysql", "sqlite")


class UnsupportedDialect(Exception):
    pass


class _DialectFunction(FunctionElement):
    inherit_cache = True


class Least(_DialectFunction):
    name = "least"
    inherit_cache = True


class Greatest(_DialectFunction):
    name = "greatest"
    inherit_cache = True


@compiles(Least)
@compiles(Greatest)
def _least_greatest(element, compiler, **kw):
    name = element.name
    if compiler.dialect.name == "sqlite":
        name = "min" if name == "least" else "max"
    elif compiler.dialect.name not in SUPPORTED:
        raise UnsupportedDialect(f"{element.name.upper()} not supported on {compiler.dialect.name}")
    return f"{name}({compiler.process(element.clauses, **kw)})"


class DateDiffDays(_DialectFunction):
    """DATE_DIFF_DAYS(start, end): whole days from start to end."""
    name = "DATE_DIFF_DAYS"
    type = Integer()
    inherit_cache = True


class YearsBetween(_DialectFunction):
    """YEARS_BETWEEN(start, end): completed years from start to end."""
    name = "YEARS_BETWEEN"
    type = Integer()
    inherit_cache = True


class MonthStart(_DialectFunction):
    """MONTH_START(d): first day of d's month."""
    name = "MONTH_START"
    type = Date()
    inherit_cache = True


def _args(element, compiler, **kw) -> list[str]:
    return [compiler.process(c, **kw) for c in element.clauses]


def _unsupported(element, compiler):
    raise UnsupportedDialect(f"{element.name} not supported on {compiler.dialect.name}")


@compiles(DateDiffDays)
@compiles(YearsBetween)
@compiles(MonthStart)
def _unsupported_default(element, compiler, **kw):
    _unsupported(element, compiler)


@compiles(DateDiffDays, "postgresql")
def _pg_date_diff(element, compiler, **kw):
    start, end = _args(element, compiler, **kw)
    return f"(CAST({end} AS DATE) - CAST({start} AS DATE))"


@compiles(DateDiffDays, "mysql")
def _mysql_date_diff(element, compiler, **kw):
    start, end = _args(element, compiler, **kw)
    return f"DATEDIFF({end}, {start})"


@compiles(DateDiffDays, "sqlite")
def _sqlite_date_diff(element, compiler, **kw):
    start, end = _args(element, compiler, **kw)
    return f"CAST(julianday({end}) - julianday({start}) AS INTEGER)"


@compiles(YearsBetween, "postgresql")
def _pg_years(element, compiler, **kw):
    start, end = _args(element, compiler, **kw)
    return f"CAST(date_part('year', age(CAST({end} AS DATE), CAST({start} AS DATE))) AS INTEGER)"


@compiles(YearsBetween, "mysql")
def _mysql_years(element, compiler, **kw):
    start, end = _args(element, compiler, **kw)
    return f"TIMESTAMPDIFF(YEAR, {start}, {end})"


@compiles(YearsBetween, "sqlite")
def _sqlite_years(element, compiler, **kw):
    start, end = _args(element, compiler, **kw)
    return (f"(CAST(strftime('%Y', {end}) AS INTEGER) - CAST(strftime('%Y', {start}) AS INTEGER)"
            f" - (strftime('%m-%d', {end}) < strftime('%m-%d', {start})))")


@compiles(MonthStart, "postgresql")
def _pg_month_start(element, compiler, **kw):
    (d,) = _args(element, compiler, **kw)
    return f"CAST(date_trunc('month', {d}) AS DATE)"


@compiles(MonthStart, "mysql")
def _mysql_month_start(element, compiler, **kw):
    (d,) = _args(element, compiler, **kw)
    return f"DATE_SUB({d}, INTERVAL DAYOFMONTH({d}) - 1 DAY)"


@compiles(MonthStart, "sqlite")
def _sqlite_month_start(element, compiler, **kw):
    (d,) = _args(element, compiler, **kw)
    return f"date({d}, 'start of month')"
