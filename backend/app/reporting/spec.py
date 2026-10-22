# backend/app/reporting/spec.py
"""Report/dashboard block definitions and their validation against the catalog and metrics (spec §3, §5.2)."""
import re
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

Agg = Literal["count", "count_distinct", "sum", "avg", "min", "max"]
NUMERIC_AGGS = {"sum", "avg", "min", "max"}
AGG_LABELS = {"count": "Count of", "count_distinct": "Distinct", "sum": "Total", "avg": "Average",
              "min": "Minimum", "max": "Maximum"}
OPS = ("eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "is_null", "not_null")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)(?::([a-z0-9_]+))?\s*\}\}")
SIMPLE_PLACEHOLDERS = {"client_name", "period", "period_start", "period_end", "generated_at"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Measure(_Model):
    metric: str | None = None
    field: str | None = None
    agg: Agg | None = None
    label: str | None = None

    @property
    def key(self) -> str:
        return self.metric if self.metric else f"{self.agg}_{self.field}"


class Sort(_Model):
    by: str
    dir: Literal["asc", "desc"] = "asc"


class QuerySpec(_Model):
    measures: list[Measure] = Field(min_length=1, max_length=4)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[list[Any]] = Field(default_factory=list)
    sort: Sort | None = None
    limit: int | None = None


class KpiItem(_Model):
    measure: Measure
    label: str | None = None


class HeadingBlock(_Model):
    id: str
    type: Literal["heading"]
    text: str
    level: int = Field(1, ge=1, le=3)


class TextBlock(_Model):
    id: str
    type: Literal["text"]
    text: str


class KpiRowBlock(_Model):
    id: str
    type: Literal["kpi_row"]
    title: str | None = None
    items: list[KpiItem] = Field(min_length=1, max_length=6)
    filters: list[list[Any]] = Field(default_factory=list)


class KpiBlock(_Model):
    id: str
    type: Literal["kpi"]
    measure: Measure
    label: str | None = None
    filters: list[list[Any]] = Field(default_factory=list)
    sparkline: bool = True


class TableBlock(_Model):
    id: str
    type: Literal["table"]
    title: str | None = None
    query: QuerySpec
    totals: bool = False


class ChartBlock(_Model):
    id: str
    type: Literal["chart"]
    title: str | None = None
    chart: Literal["bar", "stacked_bar", "line", "area", "pie"]
    query: QuerySpec


class PageBreakBlock(_Model):
    id: str
    type: Literal["page_break"]


Block = Annotated[Union[HeadingBlock, TextBlock, KpiRowBlock, KpiBlock, TableBlock, ChartBlock, PageBreakBlock],
                  Field(discriminator="type")]
_ADAPTER = TypeAdapter(Block)


def parse_block(raw: dict) -> tuple[Block | None, list[str]]:
    try:
        return _ADAPTER.validate_python(raw), []
    except ValidationError as exc:
        return None, [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]


def _value_ok(v, field) -> bool:
    if field.type == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if field.type == "decimal":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if field.type == "boolean":
        return isinstance(v, bool)
    if field.type == "date":
        try:
            date.fromisoformat(v)
            return True
        except (TypeError, ValueError):
            return False
    return isinstance(v, str)


def filter_errors(flt, fields: dict, where: str) -> list[str]:
    if not isinstance(flt, list) or len(flt) not in (2, 3):
        return [f"{where}: must be [field, op, value]"]
    field_id, op = flt[0], flt[1]
    f = fields.get(field_id)
    if f is None:
        return [f"{where}: unknown field '{field_id}'"]
    if op not in OPS:
        return [f"{where}: unknown operator '{op}'"]
    value = flt[2] if len(flt) == 3 else None
    if op in ("is_null", "not_null"):
        return [f"{where}: {op} takes no value"] if value is not None else []
    if op in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            return [f"{where}: {op} needs a non-empty list"]
        values = value
    else:
        values = [value]
    if op in ("gt", "gte", "lt", "lte") and f.type not in ("integer", "decimal", "date"):
        return [f"{where}: {op} needs a number or date field; {f.id} is {f.type}"]
    errs = []
    for v in values:
        if f.type == "enum":
            if v not in (f.values or []):
                errs.append(f"{where}: {v!r} is not one of {f.id}'s values")
        elif not _value_ok(v, f):
            errs.append(f"{where}: {v!r} is not a valid {f.type} for {f.id}")
    return errs


def validate_block(block, catalog, metrics) -> list[str]:
    fields = {f.id: f for f in catalog.fields}
    errs: list[str] = []

    def measure(m: Measure, where: str) -> None:
        if (m.metric is None) == (m.field is None):
            errs.append(f"{where}: choose either a metric or a field")
            return
        if m.metric is not None:
            if m.metric not in metrics:
                errs.append(f"{where}: unknown metric '{m.metric}'")
            if m.agg is not None:
                errs.append(f"{where}: 'agg' is only for field measures")
            return
        f = fields.get(m.field)
        if f is None:
            errs.append(f"{where}: unknown field '{m.field}'")
        elif m.agg is None:
            errs.append(f"{where}: field measures need 'agg'")
        elif m.agg in NUMERIC_AGGS and f.role != "measure":
            errs.append(f"{where}: {m.agg} needs a measure field; {f.id} is a dimension")

    def filters(fs: list, prefix: str = "") -> None:
        for i, flt in enumerate(fs, start=1):
            errs.extend(filter_errors(flt, fields, f"{prefix}filter {i}"))

    def query(q: QuerySpec) -> None:
        for i, m in enumerate(q.measures, start=1):
            measure(m, f"measure {i}")
        if len({m.key for m in q.measures}) != len(q.measures):
            errs.append("the same measure is used twice")
        for g in q.group_by:
            f = fields.get(g)
            if f is None:
                errs.append(f"group_by: unknown field '{g}'")
            elif f.role != "dimension":
                errs.append(f"group_by: {g} is a measure, not a dimension")
        filters(q.filters)
        if q.sort and q.sort.by not in {m.key for m in q.measures} | set(q.group_by):
            errs.append(f"sort.by '{q.sort.by}' is not a measure or group-by of this block")
        if q.limit is not None and not 1 <= q.limit <= 500:
            errs.append("limit must be between 1 and 500")

    match block:
        case HeadingBlock() | TextBlock():
            for name, arg in PLACEHOLDER.findall(block.text):
                if name == "metric" and arg and arg not in metrics:
                    errs.append(f"unknown metric '{arg}' in placeholder")
        case KpiRowBlock():
            for i, item in enumerate(block.items, start=1):
                measure(item.measure, f"measure {i}")
            filters(block.filters)
        case KpiBlock():
            measure(block.measure, "measure 1")
            filters(block.filters)
        case TableBlock():
            query(block.query)
            if not block.query.group_by:
                errs.append("tables need at least 1 group-by")
        case ChartBlock():
            query(block.query)
            g, m = len(block.query.group_by), len(block.query.measures)
            if block.chart == "pie" and (g != 1 or m != 1):
                errs.append("pie charts need exactly 1 group-by and 1 measure")
            elif block.chart != "pie" and g == 0:
                errs.append(f"{block.chart.replace('_', ' ')} charts need at least 1 group-by")
            if g == 2 and m != 1:
                errs.append("charts with 2 group-bys need exactly 1 measure")
    return errs


def check_blocks(raw_blocks: list[dict], catalog, metrics,
                 allowed_types: set[str] | None = None) -> tuple[list, list[dict]]:
    blocks, errors, seen = [], [], set()
    for raw in raw_blocks:
        bid = raw.get("id") if isinstance(raw, dict) else None
        block, msgs = parse_block(raw) if isinstance(raw, dict) else (None, ["block must be an object"])
        if block is not None:
            if block.id in seen:
                msgs = ["duplicate block id"]
            elif allowed_types is not None and block.type not in allowed_types:
                msgs = [f"{block.type} blocks are not allowed here"]
            else:
                msgs = validate_block(block, catalog, metrics)
            seen.add(block.id)
        if msgs:
            errors.append({"block_id": bid, "messages": msgs})
        else:
            blocks.append(block)
    return blocks, errors
