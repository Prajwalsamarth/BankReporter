"""Per-column statistics (spec §3.3). Raw values are used in memory only and never returned."""
import re
from collections import Counter

from sqlalchemy import Engine, column, distinct, func, select, table

from app.catalog.models import Catalog
from app.mapping.types import ColumnProfile, ColumnRef, SchemaInfo, TableInfo

LOW_CARDINALITY = 20
PATTERN_SAMPLE = 1000
_RUN = re.compile(r"(A{13,}|9{13,})")


def mask_pattern(value: str) -> str:
    masked = "".join("A" if ch.isalpha() else "9" if ch.isdigit() else ch for ch in value)
    return _RUN.sub(lambda m: m.group(0)[:12] + "…", masked)


def _norm_code(value) -> str:
    return str(value).strip().upper()


def profile_columns(engine: Engine, info: SchemaInfo, catalog: Catalog,
                    row_limit: int = 50_000) -> list[ColumnProfile]:
    enum_fields = {f.id: set(f.values) for f in catalog.raw_fields if f.type == "enum"}
    profiles = []
    with engine.connect() as conn:
        for t in info.tables:
            profiles.extend(_profile_table(conn, engine.dialect.name, t, enum_fields, row_limit))
    return profiles


def _profile_table(conn, dialect: str, t: TableInfo, enum_fields, row_limit) -> list[ColumnProfile]:
    src = table(t.name, *[column(c.name) for c in t.columns], schema=t.schema)
    sample = select(*[src.c[c.name] for c in t.columns]).limit(row_limit).subquery("s")
    total = conn.execute(select(func.count()).select_from(sample)).scalar_one()
    sampled = t.row_count > row_limit
    fk_targets = {fk.columns[0]: ColumnRef(fk.ref_schema, fk.ref_table, fk.ref_columns[0])
                  for fk in t.fks if len(fk.columns) == 1}
    length = func.length if dialect == "sqlite" else func.char_length

    out = []
    for c in t.columns:
        col = sample.c[c.name]
        aggs = [func.count(col), func.count(distinct(col))]
        if c.type in ("integer", "decimal", "date"):
            aggs += [func.min(col), func.max(col)]
        elif c.type == "string":
            aggs += [func.min(length(col)), func.max(length(col))]
        row = conn.execute(select(*aggs)).one()
        non_null, n_distinct = row[0], row[1]
        p = ColumnProfile(
            ref=ColumnRef(t.schema, t.name, c.name), sql_type=c.sql_type, type=c.type,
            is_pk=c.name in t.pk, fk_to=fk_targets.get(c.name),
            null_pct=round(100.0 * (total - non_null) / total, 2) if total else 0.0,
            distinct_count=n_distinct, unique=non_null > 0 and n_distinct == non_null, sampled=sampled,
        )
        if c.type in ("integer", "decimal", "date"):
            p.min, p.max = row[2], row[3]
        elif c.type == "string":
            p.len_min, p.len_max = row[2], row[3]
            values = conn.execute(select(col).where(col.is_not(None)).limit(PATTERN_SAMPLE)).scalars().all()
            counts = Counter(mask_pattern(str(v)) for v in values)
            p.patterns = [(pat, round(n / len(values), 3)) for pat, n in counts.most_common(3)]
        if 0 < n_distinct <= LOW_CARDINALITY:
            values = conn.execute(select(col).where(col.is_not(None)).distinct()).scalars().all()
            _low_cardinality_signals(p, values, enum_fields)
        out.append(p)
    return out


def _low_cardinality_signals(p: ColumnProfile, values: list, enum_fields: dict[str, set]) -> None:
    if p.type in ("integer", "boolean"):
        p.bool_like = {int(v) for v in values} <= {0, 1}
    if p.type == "string":
        codes = {_norm_code(v) for v in values}
        for field_id, allowed in enum_fields.items():
            share = len(codes & allowed) / len(codes)
            if share >= 0.5:
                p.enum_overlap[field_id] = round(share, 3)
