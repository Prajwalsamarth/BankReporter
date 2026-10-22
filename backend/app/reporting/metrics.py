# backend/app/reporting/metrics.py
"""The metric library (spec §2): named aggregate formulas loaded from catalog/metrics.yaml."""
import ast
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import ColumnElement

from app.catalog.formula import FormulaError
from app.catalog.models import Catalog
from app.reporting.aggregates import compile_aggregate, metric_refs, parse_aggregate

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    formula: str
    unit: Literal["count", "INR", "pct", "days", "score", "ratio"]
    better: Literal["higher", "lower", "neutral"]
    group: Literal["volume", "rates", "amounts", "credit", "turnaround"]
    description: str = ""


class MetricError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid metrics:\n  " + "\n  ".join(errors))


class MetricLibrary:
    def __init__(self, metrics: list[Metric], trees: dict[str, ast.Expression], field_types: dict[str, str]):
        self.metrics = metrics
        self._by_id = {m.id: m for m in metrics}
        self._trees = trees
        self._field_types = field_types

    @property
    def ids(self) -> list[str]:
        return [m.id for m in self.metrics]

    def get(self, metric_id: str) -> Metric:
        return self._by_id[metric_id]

    def __contains__(self, metric_id: object) -> bool:
        return metric_id in self._by_id

    def compile(self, metric_id: str, resolve_field) -> ColumnElement:
        return compile_aggregate(self._trees[metric_id], self._field_types, resolve_field,
                                 lambda ref: self.compile(ref, resolve_field))


def load_metrics(path: str | Path, catalog: Catalog) -> MetricLibrary:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    field_types = {f.id: f.type for f in catalog.fields}
    errors: list[str] = []
    metrics: list[Metric] = []
    for entry in raw.get("metrics") or []:
        mid = entry.get("id", "<missing id>") if isinstance(entry, dict) else "<invalid>"
        try:
            m = Metric.model_validate(entry)
        except ValidationError as exc:
            errors.extend(f"{mid}: {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            continue
        if not ID_RE.match(m.id):
            errors.append(f"{mid}: id must match {ID_RE.pattern}")
        elif m.id in field_types:
            errors.append(f"{mid}: id clashes with a catalog field")
        elif any(x.id == m.id for x in metrics):
            errors.append(f"{mid}: duplicate metric id")
        else:
            metrics.append(m)

    ids = {m.id for m in metrics}
    trees: dict[str, ast.Expression] = {}
    for m in metrics:
        try:
            trees[m.id] = parse_aggregate(m.formula, field_types, ids)
        except FormulaError as exc:
            errors.append(f"{m.id}: {exc}")
    errors.extend(_cycle_errors({mid: metric_refs(t) for mid, t in trees.items()}))
    if errors:
        raise MetricError(errors)
    return MetricLibrary(metrics, trees, field_types)


def _cycle_errors(deps: dict[str, set[str]]) -> list[str]:
    errors, done = [], set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            cycle = path[path.index(node):] + [node]
            errors.append(f"{cycle[0]}: metric cycle: {' -> '.join(cycle)}")
            return
        if node in done or node not in deps:
            return
        for dep in sorted(deps[node]):
            visit(dep, path + [node])
        done.add(node)

    for node in sorted(deps):
        visit(node, [])
    return errors
