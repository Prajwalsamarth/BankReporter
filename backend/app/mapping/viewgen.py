"""Canonical views in the client database (spec §5): applications_base (59 raw) + applications (+22 calculated)."""
from dataclasses import dataclass

from sqlalchemy import (
    Boolean, Date, Engine, Integer, Numeric, Select, String, and_, cast, column, null, select, table, text,
)
from sqlalchemy.exc import DBAPIError

from app.catalog.expressions import calculated_expressions
from app.catalog.models import Catalog
from app.mapping.types import ColumnRef, JoinPlan, SchemaInfo, jsonable

BASE_VIEW = "applications_base"
CALC_VIEW = "applications"

SQL_TYPES = {"string": lambda: String(255), "enum": lambda: String(255), "integer": Integer,
             "decimal": lambda: Numeric(18, 4), "date": Date, "boolean": Boolean}


class PublishError(Exception):
    pass


@dataclass
class PublishResult:
    row_count: int
    ddl: str


def _null_of(field_type: str, dialect: str):
    if field_type == "boolean" and dialect == "mysql":
        return cast(null(), Integer)          # MySQL has no BOOLEAN cast target
    return cast(null(), SQL_TYPES[field_type]())


def build_base_select(info: SchemaInfo, plan: JoinPlan, sources: dict[str, ColumnRef | None],
                      catalog: Catalog) -> Select:
    """One row per grain row; the 59 raw fields in catalog order. Unmapped -> typed NULL."""
    def sa_table(schema, name, alias):
        t = info.table(schema, name)
        return table(t.name, *[column(c.name) for c in t.columns], schema=t.schema).alias(alias)

    grain = sa_table(plan.grain.schema, plan.grain.table, "g")
    aliases = {(plan.grain.schema, plan.grain.table): grain}
    joined = grain
    for i, j in enumerate(plan.joins, start=1):
        t = sa_table(j.schema, j.table, f"j{i}")
        aliases.setdefault((j.schema, j.table), t)
        joined = joined.outerjoin(t, and_(*[grain.c[left] == t.c[right] for left, right in j.on]))

    columns = []
    for f in catalog.raw_fields:
        ref = sources.get(f.id)
        if ref is None:
            columns.append(_null_of(f.type, info.dialect).label(f.id))
            continue
        src = aliases.get((ref.schema, ref.table))
        if src is None:
            label = f"{ref.schema}.{ref.table}" if ref.schema else ref.table
            raise ValueError(f"{label} is not part of the join plan")
        col_type = info.table(ref.schema, ref.table).column(ref.column).type
        target = "string" if f.type == "enum" else f.type
        expr = src.c[ref.column]
        if col_type != target and not (target == "boolean" and info.dialect == "mysql"):
            expr = cast(expr, SQL_TYPES[f.type]())
        columns.append(expr.label(f.id))
    return select(*columns).select_from(joined)


def _calculated_select(source, catalog: Catalog) -> Select:
    exprs = calculated_expressions(catalog, lambda fid: source.c[fid])
    return select(*[source.c[f.id] for f in catalog.raw_fields], *[e.label(k) for k, e in exprs.items()])


def _sql(stmt, dialect) -> str:
    return str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def build_view_ddl(dialect: str, schema: str, base: Select, catalog: Catalog) -> list[str]:
    from sqlalchemy.dialects import mysql, postgresql
    d = {"postgresql": postgresql.dialect(), "mysql": mysql.dialect()}[dialect]
    base_view = table(BASE_VIEW, *[column(f.id) for f in catalog.raw_fields], schema=schema)
    base_sql = _sql(base, d)
    calc_sql = _sql(_calculated_select(base_view, catalog), d)
    if dialect == "postgresql":
        return [f"CREATE SCHEMA IF NOT EXISTS {schema}",
                f"DROP VIEW IF EXISTS {schema}.{CALC_VIEW}",
                f"DROP VIEW IF EXISTS {schema}.{BASE_VIEW}",
                f"CREATE VIEW {schema}.{BASE_VIEW} AS {base_sql}",
                f"CREATE VIEW {schema}.{CALC_VIEW} AS {calc_sql}"]
    return [f"CREATE DATABASE IF NOT EXISTS {schema}",
            f"CREATE OR REPLACE VIEW {schema}.{BASE_VIEW} AS {base_sql}",
            f"CREATE OR REPLACE VIEW {schema}.{CALC_VIEW} AS {calc_sql}"]


def _grain_count_sql(grain: ColumnRef) -> str:
    return f"SELECT COUNT(*) FROM {grain.schema + '.' if grain.schema else ''}{grain.table}"


def _verify(conn, grain: ColumnRef, schema: str) -> int:
    views = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{BASE_VIEW}")).scalar_one()
    rows = conn.execute(text(_grain_count_sql(grain))).scalar_one()
    if views != rows:
        raise PublishError(f"row count check failed: view has {views} rows, grain table has {rows}; "
                           "a join is duplicating application rows")
    conn.execute(text(f"SELECT * FROM {schema}.{CALC_VIEW} LIMIT 1")).fetchall()
    return views


def _permission_message(exc: DBAPIError, engine: Engine, schema: str) -> str | None:
    msg = str(exc.orig).lower()
    if "permission denied" in msg or "command denied" in msg or "access denied" in msg:
        url = engine.url
        return (f"user {url.username} cannot create objects in {schema} on {url.host}; "
                f"grant CREATE on that schema")
    return None


def publish(engine: Engine, statements: list[str], grain: ColumnRef, schema: str) -> PublishResult:
    ddl = ";\n".join(statements) + ";"
    try:
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:        # DDL is transactional: any failure rolls back
                for s in statements:
                    conn.execute(text(s))
                count = _verify(conn, grain, schema)
        else:
            with engine.connect() as conn:
                try:
                    for s in statements:
                        conn.execute(text(s))
                    count = _verify(conn, grain, schema)
                except Exception:
                    for v in (CALC_VIEW, BASE_VIEW):
                        conn.execute(text(f"DROP VIEW IF EXISTS {schema}.{v}"))
                    raise
    except DBAPIError as exc:
        raise PublishError(_permission_message(exc, engine, schema) or str(exc.orig)) from exc
    return PublishResult(count, ddl)


def preview(engine: Engine, base: Select, catalog: Catalog, limit: int = 20) -> tuple[list[str], list[list]]:
    """Run the view SELECT without creating anything; rows go to the caller only."""
    stmt = _calculated_select(base.subquery("b"), catalog).limit(limit)
    with engine.connect() as conn:
        result = conn.execute(stmt)
        columns = list(result.keys())
        rows = [jsonable(list(r)) for r in result]
    return columns, rows
