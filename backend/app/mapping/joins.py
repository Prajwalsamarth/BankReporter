"""Grain table and LEFT JOIN plan by rules (spec §4.1); the user confirms the result."""
from collections.abc import Callable

from app.mapping.names import norm
from app.mapping.types import ColumnProfile, ColumnRef, Join, JoinPlan, SchemaInfo, TableInfo

# Surrogate-key names shared by unrelated tables: same-name links need a declared FK.
GENERIC_KEYS = {"id", "uuid", "guid", "pk", "key", "row_id", "rowid"}


def plan_joins(info: SchemaInfo, profiles: list[ColumnProfile],
               key_scorer: Callable[[ColumnRef], float]) -> JoinPlan:
    """key_scorer(pk column) -> how well it matches application_id (0..1)."""
    unique = {p.ref for p in profiles if p.unique}
    candidates = [t for t in info.tables if len(t.pk) == 1]
    if not candidates:
        raise ValueError("no table with a single-column primary key to use as the grain")
    max_rows = max(t.row_count for t in candidates) or 1

    def score(t: TableInfo):
        # A declared FK pointing here is strong evidence; a same-name unique key is weak, because
        # every 1:1 child shares the grain's key name and links to every other child too.
        fk_links = name_links = 0
        for o in info.tables:
            if o is not t and _one_to_one_column(o, t, unique):
                if _declared_fk_to(o, t):
                    fk_links += 1
                else:
                    name_links += 1
        s = (3 * fk_links + name_links + 2 * t.row_count / max_rows
             + key_scorer(ColumnRef(t.schema, t.name, t.pk[0])))
        return (s, len(t.columns), t.name)

    grain = max(candidates, key=score)
    plan = JoinPlan(grain=ColumnRef(grain.schema, grain.name, grain.pk[0]), joins=[])
    for t in info.tables:
        if t is grain:
            continue
        if col := _one_to_one_column(t, grain, unique):
            plan.joins.append(Join(t.schema, t.name, "one_to_one", [(grain.pk[0], col)]))
        elif col := _many_to_one_column(grain, t):
            plan.joins.append(Join(t.schema, t.name, "many_to_one", [(col, t.pk[0])]))
        else:
            plan.excluded.append({"table": t.label, "reason": _exclusion_reason(t, grain)})
    return plan


def _declared_fk_to(t: TableInfo, target: TableInfo) -> bool:
    return any((fk.ref_table, fk.ref_schema) == (target.name, target.schema) for fk in t.fks)


def _one_to_one_column(t: TableInfo, grain: TableInfo, unique: set[ColumnRef]) -> str | None:
    """A unique column of t that refers to grain's PK (declared FK, or same normalised name)."""
    for fk in t.fks:
        if (fk.ref_table, fk.ref_schema) == (grain.name, grain.schema) and fk.ref_columns == grain.pk:
            if ColumnRef(t.schema, t.name, fk.columns[0]) in unique:
                return fk.columns[0]
    if norm(grain.pk[0]) in GENERIC_KEYS:
        return None
    for c in t.columns:
        if norm(c.name) == norm(grain.pk[0]) and ColumnRef(t.schema, t.name, c.name) in unique:
            return c.name
    return None


def _many_to_one_column(grain: TableInfo, t: TableInfo) -> str | None:
    """A grain column that refers to t's single-column PK (declared FK, or same normalised name)."""
    if len(t.pk) != 1:
        return None
    for fk in grain.fks:
        if (fk.ref_table, fk.ref_schema) == (t.name, t.schema) and fk.ref_columns == t.pk:
            return fk.columns[0]
    if norm(t.pk[0]) in GENERIC_KEYS:
        return None
    for c in grain.columns:
        if c.name != grain.pk[0] and norm(c.name) == norm(t.pk[0]):
            return c.name
    return None


def _exclusion_reason(t: TableInfo, grain: TableInfo) -> str:
    for c in t.columns:
        if norm(c.name) == norm(grain.pk[0]):
            return f"join column {c.name} is not unique (would duplicate application rows)"
    return "no join path to the grain table"


def key_columns(plan: JoinPlan) -> set[ColumnRef]:
    """Columns excluded from matching: the grain PK and the non-grain side of every join."""
    keys = {plan.grain}
    for j in plan.joins:
        keys.update(ColumnRef(j.schema, j.table, right) for _, right in j.on)
    return keys


def validate_join_plan(plan: JoinPlan, info: SchemaInfo, profiles: list[ColumnProfile]) -> list[str]:
    errors = []
    unique = {p.ref for p in profiles if p.unique}
    known = {ColumnRef(t.schema, t.name, c.name) for t in info.tables for c in t.columns}
    if plan.grain not in known:
        return [f"unknown column {plan.grain.label}"]
    for j in plan.joins:
        for left, right in j.on:
            grain_ref = ColumnRef(plan.grain.schema, plan.grain.table, left)
            ref = ColumnRef(j.schema, j.table, right)
            for r in (grain_ref, ref):
                if r not in known:
                    errors.append(f"unknown column {r.label}")
            if ref in known and ref not in unique:
                errors.append(f"{ref.label} is not unique; joining on it would duplicate application rows")
    return errors
