# backend/app/reporting/render.py
"""Render report/dashboard blocks against a client's canonical views (spec §5)."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import inspect

from app.reporting import formatting as fmt
from app.reporting.period import Period, sparkline_window
from app.reporting.query import VIEW, grouped_select, scalar_select, view_table
from app.reporting.spec import (
    AGG_LABELS, PLACEHOLDER, ChartBlock, HeadingBlock, KpiBlock, KpiRowBlock, Measure, PageBreakBlock,
    QuerySpec, TableBlock, TextBlock, parse_block, validate_block,
)


class NotPublished(Exception):
    pass


@dataclass
class RenderContext:
    catalog: object
    metrics: object
    period: Period
    client_name: str
    schema: str | None = "lending_rpt"
    generated_at: datetime = field(default_factory=lambda: datetime.now().replace(microsecond=0))
    mask: Callable[[str], str] = lambda s: s


def check_published(conn, ctx: RenderContext) -> None:
    try:
        views = inspect(conn).get_view_names(schema=ctx.schema)
    except Exception:
        views = []
    if VIEW not in views:
        raise NotPublished(f"{ctx.client_name} has no published views; publish its mapping first")


def measure_meta(m: Measure, ctx: RenderContext) -> tuple[str, str, str]:
    if m.metric:
        metric = ctx.metrics.get(m.metric)
        return m.label or metric.label, metric.unit, metric.better
    f = ctx.catalog.field(m.field)
    unit = "count" if m.agg in ("count", "count_distinct") else (f.unit if f.unit in ("INR", "pct", "days") else "number")
    return m.label or f"{AGG_LABELS[m.agg]} {f.label}", unit, "neutral"


def render_blocks(raw_blocks: list[dict], conn, ctx: RenderContext) -> list[dict]:
    view = view_table(ctx.catalog, ctx.schema)
    out = []
    for raw in raw_blocks:
        bid, btype = raw.get("id"), raw.get("type")
        block, errs = parse_block(raw)
        if block is not None:
            errs = validate_block(block, ctx.catalog, ctx.metrics)
        if errs:
            out.append({"id": bid, "type": btype, "error": "invalid block: " + "; ".join(errs)})
            continue
        try:
            out.append({"id": block.id, "type": block.type, **_render(block, conn, view, ctx)})
        except Exception as exc:
            message = str(getattr(exc, "orig", None) or exc).splitlines()[0][:300]
            out.append({"id": block.id, "type": block.type, "error": ctx.mask(message)})
    return out


def _render(block, conn, view, ctx: RenderContext) -> dict:
    match block:
        case HeadingBlock():
            return {"text": _resolve_text(block.text, conn, view, ctx), "level": block.level}
        case TextBlock():
            return {"text": _resolve_text(block.text, conn, view, ctx)}
        case KpiRowBlock():
            items = [(i.measure, i.label) for i in block.items]
            return {"title": block.title, "items": _kpis(items, block.filters, False, conn, view, ctx)}
        case KpiBlock():
            return {"kpi": _kpis([(block.measure, block.label)], block.filters, block.sparkline, conn, view, ctx)[0]}
        case TableBlock():
            result = _grouped(block.query, conn, view, ctx)
            result["title"] = block.title
            result["totals"] = _totals(block.query, conn, view, ctx) if block.totals and result["rows"] else None
            return result
        case ChartBlock():
            return {"title": block.title, "chart": block.chart, **_grouped(block.query, conn, view, ctx)}
        case PageBreakBlock():
            return {}
    raise ValueError(f"unsupported block {block.type}")


def _scalars(measures, filters, start, end, conn, view, ctx) -> dict:
    stmt = scalar_select(measures, filters, start, end, view, ctx.catalog, ctx.metrics)
    return dict(conn.execute(stmt).mappings().one())


def _kpis(items, filters, sparkline: bool, conn, view, ctx: RenderContext) -> list[dict]:
    p = ctx.period
    measures = [m for m, _ in items]
    cur = _scalars(measures, filters, p.start, p.end, conn, view, ctx)
    prev = _scalars(measures, filters, p.prev_start, p.prev_end, conn, view, ctx)
    spark_rows = []
    if sparkline:
        s, e = sparkline_window(p)
        q = QuerySpec(measures=measures, group_by=["application_month"], filters=filters)
        spark_rows = conn.execute(grouped_select(q, s, e, view, ctx.catalog, ctx.metrics)).mappings().all()
    result = []
    for m, label in items:
        default_label, unit, better = measure_meta(m, ctx)
        kpi = {"key": m.key, "label": label or default_label, "unit": unit,
               "value": fmt.val(cur[m.key], unit), "previous": fmt.val(prev[m.key], unit),
               "delta": fmt.delta(cur[m.key], prev[m.key], unit, better)}
        if sparkline:
            kpi["sparkline"] = [{"month": fmt.month_label(r["application_month"]),
                                 "raw": None if r[m.key] is None else float(r[m.key])} for r in spark_rows]
        result.append(kpi)
    return result


def _grouped(q: QuerySpec, conn, view, ctx: RenderContext) -> dict:
    p = ctx.period
    rows = conn.execute(grouped_select(q, p.start, p.end, view, ctx.catalog, ctx.metrics)).mappings().all()
    metas = {m.key: measure_meta(m, ctx) for m in q.measures}
    columns = ([{"key": g, "label": ctx.catalog.field(g).label, "kind": "dimension"} for g in q.group_by]
               + [{"key": k, "label": label, "kind": "measure", "unit": unit} for k, (label, unit, _) in metas.items()])
    out_rows = [{**{g: fmt.dimension(r[g], ctx.catalog.field(g)) for g in q.group_by},
                 **{k: fmt.val(r[k], unit) for k, (_, unit, _) in metas.items()}} for r in rows]
    return {"columns": columns, "rows": out_rows, "empty": not out_rows}


def _totals(q: QuerySpec, conn, view, ctx: RenderContext) -> dict:
    p = ctx.period
    values = _scalars(q.measures, q.filters, p.start, p.end, conn, view, ctx)
    return {m.key: fmt.val(values[m.key], measure_meta(m, ctx)[1]) for m in q.measures}


def _resolve_text(text: str, conn, view, ctx: RenderContext) -> str:
    p = ctx.period
    simple = {"client_name": ctx.client_name, "period": p.label, "period_start": p.start.isoformat(),
              "period_end": (p.end - timedelta(days=1)).isoformat(),
              "generated_at": fmt.datetime_label(ctx.generated_at)}

    def replace(match) -> str:
        name, arg = match.group(1), match.group(2)
        if name == "metric" and arg in ctx.metrics:
            m = Measure(metric=arg)
            value = _scalars([m], [], p.start, p.end, conn, view, ctx)[arg]
            return fmt.measure(value, ctx.metrics.get(arg).unit)
        if arg is None and name in simple:
            return simple[name]
        return f"[unknown: {name}{':' + arg if arg else ''}]"

    return PLACEHOLDER.sub(replace, text)
