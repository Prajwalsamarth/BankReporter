# backend/app/reporting/query.py
"""Block query spec + period -> SQL over <schema>.applications (spec §5.1)."""
from datetime import date

from sqlalchemy import ColumnElement, Date, Select, and_, column, distinct, func, literal, select, table

from app.reporting.spec import Measure, QuerySpec

VIEW = "applications"
DEFAULT_LIMIT = 100


def view_table(catalog, schema: str | None):
    return table(VIEW, *[column(f.id) for f in catalog.fields], schema=schema)


def measure_expr(m: Measure, view, metrics) -> ColumnElement:
    if m.metric:
        return metrics.compile(m.metric, lambda fid: view.c[fid])
    col = view.c[m.field]
    return {"count": lambda: func.count(col), "count_distinct": lambda: func.count(distinct(col)),
            "sum": lambda: func.sum(col), "avg": lambda: func.avg(col),
            "min": lambda: func.min(col), "max": lambda: func.max(col)}[m.agg]()


def filter_expr(flt: list, view, catalog) -> ColumnElement:
    field_id, op = flt[0], flt[1]
    value = flt[2] if len(flt) > 2 else None
    col = view.c[field_id]
    is_date = catalog.field(field_id).type == "date"

    def v(x):   # typed literal: SQLite needs Date conversion, other dialects bind normally
        return literal(date.fromisoformat(x), Date) if is_date else x

    match op:
        case "eq":
            return col == v(value)
        case "ne":
            return col != v(value)
        case "in":
            return col.in_([v(x) for x in value])
        case "not_in":
            return col.not_in([v(x) for x in value])
        case "gt":
            return col > v(value)
        case "gte":
            return col >= v(value)
        case "lt":
            return col < v(value)
        case "lte":
            return col <= v(value)
        case "is_null":
            return col.is_(None)
        case "not_null":
            return col.is_not(None)
    raise ValueError(f"unknown operator {op}")


def _where(start: date, end: date, filters: list, view, catalog):
    return and_(view.c.application_date >= literal(start, Date), view.c.application_date < literal(end, Date),
                *[filter_expr(f, view, catalog) for f in filters])


def scalar_select(measures: list[Measure], filters: list, start: date, end: date, view, catalog, metrics) -> Select:
    return (select(*[measure_expr(m, view, metrics).label(m.key) for m in measures])
            .select_from(view).where(_where(start, end, filters, view, catalog)))


def grouped_select(q: QuerySpec, start: date, end: date, view, catalog, metrics) -> Select:
    groups = [view.c[g] for g in q.group_by]
    measures = {m.key: measure_expr(m, view, metrics).label(m.key) for m in q.measures}
    stmt = (select(*[g.label(g.name) for g in groups], *measures.values())
            .select_from(view).where(_where(start, end, q.filters, view, catalog)).group_by(*groups))
    if q.sort:
        target = view.c[q.sort.by] if q.sort.by in q.group_by else measures[q.sort.by]
        stmt = stmt.order_by(target.desc() if q.sort.dir == "desc" else target.asc())
    else:
        stmt = stmt.order_by(*groups)
    return stmt.limit(q.limit or DEFAULT_LIMIT)
