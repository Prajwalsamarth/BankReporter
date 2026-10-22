# Reporting & Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users can build custom report templates (MIS-style documents printed to PDF) and custom dashboards (KPI and chart tiles). Both are rendered live from any mapped client's `lending_rpt.applications` view.

**Architecture:**
- **Metrics:** a YAML library of aggregate formulas (`catalog/metrics.yaml`) is compiled to SQLAlchemy by reusing Part 1's row-level formula compiler inside aggregate calls.
- **Blocks:** reports and dashboards are JSON lists of blocks. A backend render engine turns each block into SQL over `<schema>.applications` for a period and its previous period, and returns formatted values.
- **Frontend:** the React app (Mantine + `@mantine/charts`) draws the results, edits blocks, and prints reports with the browser's print-to-PDF.

**Tech Stack:**
- **Backend:** Python 3.12, FastAPI 0.115, SQLAlchemy 2, Pydantic 2, PyYAML.
- **Frontend:** React 18.3, Mantine 7.17.8 (`@mantine/core`, `@mantine/charts`, `@mantine/dates`), Recharts 2.15.4, dayjs 1.11.13, TanStack Query 5, Vitest 3.

**Spec:** `docs/superpowers/specs/2026-10-22-reporting-dashboards-design.md`. Read it alongside this plan; section numbers below (§) refer to it.

## Global Constraints

- **Running commands:**
  - Backend commands run from `backend/` with `../.venv/bin/pytest -q`.
  - Frontend commands run from `frontend/` with `npx vitest run` and `npx tsc -b --noEmit`.
  - Docker DBs must be up for tests marked `db` (`docker compose up -d --wait` from the repo root).
- **What is queried:** only `<schema>.applications`, where the schema comes from `settings.publish_schema`, default `lending_rpt`. Tests use `lending_rpt_eval` and drop their views afterwards, because leftover views block `mockdata.generate --reset`.
- **No client data at rest:** rendered rows are returned to the caller and never stored in SQLite.
- **Value shape:** every value returned to the UI is `{"raw": number|string|bool|null, "display": str}`. The UI shows `display` and charts plot `raw`.
- **Indian formatting:** `1,23,456`; INR as `₹4.52 Cr` (≥ 1e7), `₹38.6 L` (≥ 1e5), otherwise `₹85,400`; pct as `61.2%`; days as `4.3 days`; null as `—`.
- **Periods:** the default period preset is `last_month`. Period end dates are **exclusive** internally and **inclusive** in API responses.
- **Library pins:**
  - backend: `fastapi==0.115.14`;
  - frontend: `@mantine/*` at exactly `7.17.8`, `recharts@2.15.4`, `dayjs@1.11.13`.
- **No browser dialogs:** no `window.confirm` or `window.alert`; confirmations happen inside the page.
- **Commit trailer:** every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

These are failure modes the spec implies but doesn't test directly. Each has a test pinned to its owning task.
1. **Group-by values that are NULL** (for example `rejection_reason` for approved applications). The row must render with the label `—`, without crashing or being dropped. Test: Task 6, `test_null_group_key_renders_dash`.
2. **A KPI whose denominator is zero for the period** (for example `disbursement_conversion` when nothing is approved). The value shows `—` and the delta is `null`, with no SQL error. Test: Task 6, `test_zero_denominator_kpi_is_dash_without_delta`.
3. **A period with no applications** (`this_month` in Oct 2026, after the mock data ends). Every block renders: tables and charts are `empty: true`, and counts show `0`. Test: Task 6, `test_empty_period_renders_every_block`.
4. **A saved block that refers to a field or metric that no longer exists.** Only that block shows an error; the rest render. Test: Task 6, `test_stale_block_errors_alone`.
5. **A filter value of the wrong type from the UI** (the string `"650"` for `cibil_score`). It's a validation error naming the field, not a SQL error. Test: Task 5, `test_filter_value_type_checked`.

---

## File Structure

**Backend (`backend/app/reporting/`, new package):**

| File | Responsibility |
|---|---|
| `__init__.py` | empty |
| `aggregates.py` | parse, check and compile aggregate formulas |
| `metrics.py` | `Metric`, `MetricLibrary`, `load_metrics`, `MetricError` |
| `period.py` | `Period`, `resolve_period`, `sparkline_window`, `PeriodError` |
| `formatting.py` | Indian number formatting, `val`, `delta`, `dimension`, labels |
| `spec.py` | Pydantic block models, `parse_block`, `validate_block`, `check_blocks` |
| `query.py` | `view_table`, `measure_expr`, `filter_expr`, `scalar_select`, `grouped_select` |
| `render.py` | `RenderContext`, `render_blocks`, `check_published`, `NotPublished` |
| `defaults.py` | `seed_defaults` from `catalog/defaults/*.yaml` |

**Other backend files:**

| File | Change |
|---|---|
| `catalog/metrics.yaml` | the 22 metrics (§2.3) |
| `catalog/defaults/monthly_lending_mis.yaml`, `catalog/defaults/lending_kpis.yaml` | the ready-made report and dashboard |
| `backend/app/store/__init__.py` | add the `ReportTemplate` and `Dashboard` models |
| `backend/app/settings.py` | add `metrics_path` and `defaults_dir` |
| `backend/app/api/reporting.py` | the new router |
| `backend/app/api/__init__.py` | load metrics, seed defaults, include the router, injectable `today` |

**Backend tests:** `backend/tests/reporting/` with `test_aggregates.py`, `test_metrics.py`, `test_period.py`, `test_formatting.py`, `test_spec.py`, `test_render.py` (SQLite) and `test_golden.py` (db); plus `backend/tests/api/test_reporting_api.py`.

**Frontend (`frontend/src/`):**

| File | Responsibility |
|---|---|
| `api.ts` | add the reporting types |
| `print.css` | print layout |
| `components/PeriodSelect.tsx`, `ClientSelect.tsx` | period and client selectors |
| `components/BlockView.tsx` | `KpiCard`, `TableView` and `ChartView` inside |
| `components/BlockSettings.tsx` | `MeasurePicker` and `FiltersEditor` inside |
| `blocks.ts` | `newBlock(type)`, `describeBlock(block)` |
| `pages/ReportsPage.tsx`, `ReportEditorPage.tsx`, `DashboardsPage.tsx` | the new pages |
| `App.tsx`, `main.tsx` | navigation, routes, CSS imports |
| tests | `*.test.tsx` next to each component or page |

---

### Task 1: Aggregate formula language

**Files:**
- Create: `backend/app/reporting/__init__.py` (empty), `backend/app/reporting/aggregates.py`
- Test: `backend/tests/reporting/__init__.py` (empty), `backend/tests/reporting/test_aggregates.py`

**Interfaces:**
- **Consumes, from `app.catalog.formula`:**
  - `parse_formula(formula: str, known_fields: set[str]) -> ast.Expression`
  - `infer_type(tree, field_types: dict[str, str]) -> str`
  - `compile_formula(tree, resolve: Callable[[str], ColumnElement]) -> ColumnElement`
  - `FormulaError(message, col=None)`
  - `DIVISION_TYPE` (`Numeric(20, 6)`)
- **Produces:**
  - `AGGREGATES: dict[str, int]` (name → number of arguments)
  - `parse_aggregate(formula: str, field_types: dict[str, str], metric_ids: set[str]) -> ast.Expression`, raising `FormulaError`
  - `metric_refs(tree: ast.Expression) -> set[str]`
  - `compile_aggregate(tree, field_types, resolve_field: Callable[[str], ColumnElement], resolve_metric: Callable[[str], ColumnElement]) -> ColumnElement`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/reporting/test_aggregates.py
import pytest
from sqlalchemy import Column, Integer, MetaData, Numeric, String, Table, create_engine, insert, select

from app.catalog.formula import FormulaError
from app.reporting.aggregates import compile_aggregate, metric_refs, parse_aggregate

TYPES = {"amount": "decimal", "score": "integer", "ok": "boolean", "status": "enum", "d": "date"}
METRICS = {"approved", "total"}


def parse(formula):
    return parse_aggregate(formula, TYPES, METRICS)


@pytest.mark.parametrize("formula", [
    "COUNT()", "COUNT_IF(ok)", "COUNT_IF(status == 'X')", "SUM(amount)", "SUM_IF(amount, ok)",
    "AVG(score)", "AVG_IF(score, status in ['A', 'B'])", "MIN(d)", "MAX(amount)", "COUNT_DISTINCT(status)",
    "approved / total * 100", "ROUND(SUM(amount) / COUNT(), 2)", "COALESCE(SUM(amount), 0)", "-approved",
    "SUM(amount * 2 + COALESCE(score, 0))",
])
def test_valid_formulas(formula):
    parse(formula)


@pytest.mark.parametrize("formula, msg", [
    ("amount", "field 'amount' must be inside an aggregate"),
    ("SUM(SUM(amount))", "nested aggregates are not allowed"),
    ("COUNT_IF(score)", "COUNT_IF needs a boolean argument, got integer"),
    ("SUM(status)", "SUM needs a numeric argument, got string"),
    ("AVG_IF(amount, score)", "AVG_IF needs a boolean argument, got integer"),
    ("MIN(status)", "MIN needs a numeric or date argument, got string"),
    ("unknown_metric + 1", "unknown metric 'unknown_metric'"),
    ("SUM(nope)", "unknown field 'nope'"),
    ("COUNT(amount)", "COUNT takes 0 argument(s), got 1"),
    ("MEDIAN(amount)", "unknown function 'MEDIAN'"),
    ("'text'", "Constant not allowed outside aggregates"),
    ("approved > 1", "Compare not allowed outside aggregates"),
    ("ROUND(approved, total)", "ROUND takes an expression and an integer number of digits"),
])
def test_rejected_formulas(formula, msg):
    with pytest.raises(FormulaError, match=msg):
        parse(formula)


def test_metric_refs_ignore_names_inside_aggregates():
    assert metric_refs(parse("approved / total + SUM(amount)")) == {"approved", "total"}


metadata = MetaData()
t = Table("t", metadata, Column("id", Integer, primary_key=True), Column("amount", Numeric(14, 2)),
          Column("score", Integer), Column("ok", Integer), Column("status", String))


@pytest.fixture(scope="module")
def conn():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(insert(t), [
            {"id": 1, "amount": 100, "score": 700, "ok": 1, "status": "A"},
            {"id": 2, "amount": 50, "score": None, "ok": 0, "status": "B"},
            {"id": 3, "amount": None, "score": 650, "ok": 1, "status": "A"},
        ])
    with engine.connect() as c:
        yield c


def run(conn, formula, metrics=None, where=None):
    metrics = metrics or {}

    def resolve_metric(name):
        return compile_aggregate(parse(metrics[name]), TYPES, lambda f: t.c[f], resolve_metric)

    expr = compile_aggregate(parse(formula), TYPES, lambda f: t.c[f], resolve_metric)
    stmt = select(expr).select_from(t)
    if where is not None:
        stmt = stmt.where(where)
    return conn.execute(stmt).scalar_one()


def test_count_and_conditional_aggregates(conn):
    assert run(conn, "COUNT()") == 3
    assert run(conn, "COUNT_IF(ok)") == 2
    assert run(conn, "COUNT_IF(status == 'B')") == 1
    assert float(run(conn, "SUM_IF(amount, ok)")) == pytest.approx(100)
    assert float(run(conn, "AVG_IF(score, ok)")) == pytest.approx(675)
    assert run(conn, "COUNT_DISTINCT(status)") == 2


def test_metric_ratio_and_zero_denominator(conn):
    metrics = {"approved": "COUNT_IF(ok)", "total": "COUNT()"}
    assert float(run(conn, "approved / total * 100", metrics)) == pytest.approx(66.666667, abs=1e-5)
    assert run(conn, "approved / total", metrics, where=t.c.id > 99) is None   # empty -> 0/0 -> NULL


def test_count_if_on_empty_set_is_zero_not_null(conn):
    assert run(conn, "COUNT_IF(ok)", where=t.c.id > 99) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/reporting/test_aggregates.py`
Expected: collection error, `ModuleNotFoundError: No module named 'app.reporting'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/reporting/aggregates.py
"""Aggregate formulas for metrics (spec §2.2).

Part 1's row-level grammar runs inside aggregate calls; outside them only numeric constants,
arithmetic, ROUND/COALESCE and other metric IDs are allowed.
"""
import ast
from collections.abc import Callable

from sqlalchemy import ColumnElement, case, cast, distinct, func, literal

from app.catalog.formula import DIVISION_TYPE, FormulaError, compile_formula, infer_type, parse_formula

AGGREGATES: dict[str, int] = {"COUNT": 0, "COUNT_IF": 1, "SUM": 1, "SUM_IF": 2, "AVG": 1, "AVG_IF": 2,
                              "MIN": 1, "MAX": 1, "COUNT_DISTINCT": 1}
NUMERIC = {"integer", "decimal"}


def _is_aggregate(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in AGGREGATES


def _row_tree(arg: ast.AST, field_types: dict[str, str]) -> ast.Expression:
    if any(_is_aggregate(n) for n in ast.walk(arg)):
        raise FormulaError("nested aggregates are not allowed")
    return parse_formula(ast.unparse(arg), set(field_types))


def parse_aggregate(formula: str, field_types: dict[str, str], metric_ids: set[str]) -> ast.Expression:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"syntax error: {exc.msg}") from None
    _check_outer(tree.body, field_types, metric_ids)
    return tree


def _check_outer(node: ast.AST, field_types: dict[str, str], metric_ids: set[str]) -> None:
    match node:
        case ast.Constant(value=v) if isinstance(v, (int, float)) and not isinstance(v, bool):
            return
        case ast.Name(id=name):
            if name in metric_ids:
                return
            if name in field_types:
                raise FormulaError(f"field '{name}' must be inside an aggregate such as SUM({name})")
            raise FormulaError(f"unknown metric '{name}'")
        case ast.BinOp(op=ast.Add() | ast.Sub() | ast.Mult() | ast.Div(), left=left, right=right):
            _check_outer(left, field_types, metric_ids)
            _check_outer(right, field_types, metric_ids)
            return
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            _check_outer(operand, field_types, metric_ids)
            return
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]):
            if name in AGGREGATES:
                _check_aggregate(name, args, field_types)
                return
            if name == "ROUND":
                if len(args) != 2 or not (isinstance(args[1], ast.Constant) and type(args[1].value) is int):
                    raise FormulaError("ROUND takes an expression and an integer number of digits")
                _check_outer(args[0], field_types, metric_ids)
                return
            if name == "COALESCE":
                if len(args) < 2:
                    raise FormulaError("COALESCE takes at least 2 arguments")
                for a in args:
                    _check_outer(a, field_types, metric_ids)
                return
            raise FormulaError(f"unknown function '{name}'")
    raise FormulaError(f"{type(node).__name__} not allowed outside aggregates")


def _check_aggregate(name: str, args: list[ast.AST], field_types: dict[str, str]) -> None:
    if len(args) != AGGREGATES[name]:
        raise FormulaError(f"{name} takes {AGGREGATES[name]} argument(s), got {len(args)}")
    kinds = [infer_type(_row_tree(a, field_types), field_types) for a in args]

    def need(kind: str, allowed: set[str], what: str) -> None:
        if kind not in allowed:
            raise FormulaError(f"{name} needs a {what} argument, got {kind}")

    if name == "COUNT_IF":
        need(kinds[0], {"boolean"}, "boolean")
    elif name in ("SUM", "AVG"):
        need(kinds[0], NUMERIC, "numeric")
    elif name in ("SUM_IF", "AVG_IF"):
        need(kinds[0], NUMERIC, "numeric")
        need(kinds[1], {"boolean"}, "boolean")
    elif name in ("MIN", "MAX"):
        need(kinds[0], NUMERIC | {"date"}, "numeric or date")


def metric_refs(tree: ast.Expression) -> set[str]:
    refs: set[str] = set()

    def visit(node: ast.AST) -> None:
        if _is_aggregate(node):
            return
        if isinstance(node, ast.Name):
            refs.add(node.id)
        for child in ast.iter_child_nodes(node):
            if not (isinstance(node, ast.Call) and child is node.func):
                visit(child)

    visit(tree.body)
    return refs


def compile_aggregate(tree: ast.Expression, field_types: dict[str, str],
                      resolve_field: Callable[[str], ColumnElement],
                      resolve_metric: Callable[[str], ColumnElement]) -> ColumnElement:
    def row(arg: ast.AST) -> ColumnElement:
        return compile_formula(_row_tree(arg, field_types), resolve_field)

    def c(node: ast.AST) -> ColumnElement:
        match node:
            case ast.Constant(value=v):
                return literal(v)
            case ast.Name(id=name):
                return resolve_metric(name)
            case ast.BinOp(left=left, op=op, right=right):
                lhs, rhs = c(left), c(right)
                if isinstance(op, ast.Add):
                    return lhs + rhs
                if isinstance(op, ast.Sub):
                    return lhs - rhs
                if isinstance(op, ast.Mult):
                    return lhs * rhs
                return cast(lhs, DIVISION_TYPE) / func.nullif(cast(rhs, DIVISION_TYPE), 0)
            case ast.UnaryOp(operand=operand):
                return -c(operand)
            case ast.Call(func=ast.Name(id="ROUND"), args=[x, digits]):
                return func.round(cast(c(x), DIVISION_TYPE), digits.value)
            case ast.Call(func=ast.Name(id="COALESCE"), args=args):
                return func.coalesce(*[c(a) for a in args])
            case ast.Call(func=ast.Name(id=name), args=args):
                xs = [row(a) for a in args]
                match name:
                    case "COUNT":
                        return func.count()
                    case "COUNT_IF":   # COALESCE: SUM over no rows is NULL, a count must be 0
                        return func.coalesce(func.sum(case((xs[0], 1), else_=0)), 0)
                    case "SUM":
                        return func.sum(xs[0])
                    case "SUM_IF":
                        return func.sum(case((xs[1], xs[0])))
                    case "AVG":
                        return func.avg(xs[0])
                    case "AVG_IF":
                        return func.avg(case((xs[1], xs[0])))
                    case "MIN":
                        return func.min(xs[0])
                    case "MAX":
                        return func.max(xs[0])
                    case "COUNT_DISTINCT":
                        return func.count(distinct(xs[0]))
        raise FormulaError(f"cannot compile {type(node).__name__}")

    return c(tree.body)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../.venv/bin/pytest -q tests/reporting/test_aggregates.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reporting backend/tests/reporting
git commit -m "feat(reporting): aggregate formula language for metrics

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Metric library

**Files:**
- Create: `catalog/metrics.yaml`, `backend/app/reporting/metrics.py`
- Modify: `backend/app/settings.py` (add `metrics_path` and `defaults_dir`)
- Test: `backend/tests/reporting/test_metrics.py`

**Interfaces:**
- **Consumes:** `parse_aggregate`, `metric_refs` and `compile_aggregate` (Task 1); `Catalog` (`app.catalog.models`) with `.fields`, `.field(id)`.
- **Produces:**
  - `Metric` (pydantic): `id, label, formula, unit, better, group, description`
  - `MetricError(errors: list[str])`
  - `MetricLibrary`:
    - `.ids: list[str]` and `.metrics: list[Metric]`
    - `.get(id) -> Metric` (raises `KeyError`)
    - `__contains__(id)`
    - `.compile(metric_id, resolve_field) -> ColumnElement`
  - `load_metrics(path, catalog) -> MetricLibrary`
  - `Settings.metrics_path: Path` (default `ROOT/catalog/metrics.yaml`, env `BANKREPORTER_METRICS`)
  - `Settings.defaults_dir: Path` (default `ROOT/catalog/defaults`)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/reporting/test_metrics.py
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.reporting.metrics import MetricError, load_metrics

ROOT = Path(__file__).parents[3]
CATALOG = load_catalog(ROOT / "catalog" / "fields.yaml")


def test_real_library_loads_all_22_metrics():
    lib = load_metrics(ROOT / "catalog" / "metrics.yaml", CATALOG)
    assert len(lib.ids) == 22
    assert lib.get("approval_rate").unit == "pct"
    assert lib.get("avg_end_to_end_tat").better == "lower"
    assert {m.group for m in lib.metrics} == {"volume", "rates", "amounts", "credit", "turnaround"}


def write(tmp_path, body):
    p = tmp_path / "metrics.yaml"
    p.write_text("version: 1\nmetrics:\n" + body)
    return p


def test_every_error_reported_together(tmp_path):
    p = write(tmp_path, """
  - {id: a, label: A, formula: "b + 1", unit: count, better: higher, group: volume}
  - {id: b, label: B, formula: "a * 2", unit: count, better: higher, group: volume}
  - {id: c, label: C, formula: "SUM(nope)", unit: INR, better: higher, group: amounts}
  - {id: d, label: D, formula: "COUNT()", unit: bananas, better: higher, group: volume}
  - {id: city, label: X, formula: "COUNT()", unit: count, better: higher, group: volume}
  - {id: c, label: C2, formula: "COUNT()", unit: count, better: higher, group: volume}
""")
    with pytest.raises(MetricError) as exc:
        load_metrics(p, CATALOG)
    errors = exc.value.errors
    assert any(e.startswith("a: metric cycle") or e.startswith("b: metric cycle") for e in errors)
    assert any(e.startswith("c: unknown field 'nope'") for e in errors)
    assert any(e.startswith("d: unit:") for e in errors)
    assert "city: id clashes with a catalog field" in errors
    assert "c: duplicate metric id" in errors


def test_compile_inlines_referenced_metrics(tmp_path):
    from sqlalchemy import column, table
    from sqlalchemy.dialects import postgresql
    p = write(tmp_path, """
  - {id: approved, label: A, formula: "COUNT_IF(is_approved)", unit: count, better: higher, group: volume}
  - {id: rate, label: R, formula: "approved / COUNT() * 100", unit: pct, better: higher, group: rates}
""")
    lib = load_metrics(p, CATALOG)
    view = table("applications", column("is_approved"))
    sql = str(lib.compile("rate", lambda f: view.c[f]).compile(dialect=postgresql.dialect()))
    assert "CASE WHEN applications.is_approved THEN" in sql and "count(*)" in sql
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/reporting/test_metrics.py`
Expected: collection error, `No module named 'app.reporting.metrics'`.

- [ ] **Step 3: Write `catalog/metrics.yaml`**

```yaml
# Lending KPIs as aggregate formulas over lending_rpt.applications (Part 3 spec §2).
version: 1
metrics:
  - {id: applications, label: "Applications", formula: "COUNT()", unit: count, better: higher, group: volume,
     description: "Applications received in the period."}
  - {id: decided, label: "Decided", formula: "COUNT_IF(decision_date is not None)", unit: count, better: neutral,
     group: volume, description: "Applications with a credit decision."}
  - {id: approved, label: "Approved", formula: "COUNT_IF(is_approved)", unit: count, better: higher, group: volume,
     description: "Approved applications (including those disbursed)."}
  - {id: rejected, label: "Rejected", formula: "COUNT_IF(is_rejected)", unit: count, better: lower, group: volume,
     description: "Rejected applications."}
  - {id: disbursed_count, label: "Disbursed loans", formula: "COUNT_IF(is_disbursed)", unit: count, better: higher,
     group: volume, description: "Loans disbursed."}
  - {id: approval_rate, label: "Approval rate", formula: "approved / decided * 100", unit: pct, better: higher,
     group: rates, description: "Approved ÷ decided applications."}
  - {id: rejection_rate, label: "Rejection rate", formula: "rejected / decided * 100", unit: pct, better: lower,
     group: rates, description: "Rejected ÷ decided applications."}
  - {id: disbursement_conversion, label: "Disbursement conversion", formula: "disbursed_count / approved * 100",
     unit: pct, better: higher, group: rates, description: "Disbursed ÷ approved applications."}
  - {id: kyc_failure_rate, label: "KYC failure rate", formula: "COUNT_IF(kyc_status == 'FAILED') / applications * 100",
     unit: pct, better: lower, group: rates, description: "Applications whose KYC failed."}
  - {id: auto_decision_share, label: "Auto-decision share", formula: "COUNT_IF(decision_mode == 'AUTO') / decided * 100",
     unit: pct, better: higher, group: rates, description: "Decisions made automatically (STP)."}
  - {id: ntc_share, label: "New-to-credit share", formula: "COUNT_IF(is_new_to_credit) / applications * 100",
     unit: pct, better: neutral, group: rates, description: "Applicants without a CIBIL score."}
  - {id: requested_amount_total, label: "Amount requested", formula: "SUM(requested_amount)", unit: INR,
     better: higher, group: amounts, description: "Total loan amount requested."}
  - {id: sanctioned_amount_total, label: "Amount sanctioned", formula: "SUM(approved_amount)", unit: INR,
     better: higher, group: amounts, description: "Total amount approved."}
  - {id: disbursed_amount_total, label: "Amount disbursed", formula: "SUM(disbursed_amount)", unit: INR,
     better: higher, group: amounts, description: "Total amount disbursed."}
  - {id: avg_ticket_size, label: "Average ticket size", formula: "disbursed_amount_total / disbursed_count",
     unit: INR, better: neutral, group: amounts, description: "Average disbursed loan amount."}
  - {id: processing_fee_income, label: "Processing fee income", formula: "SUM(processing_fee)", unit: INR,
     better: higher, group: amounts, description: "Processing fees collected at disbursement."}
  - {id: avg_cibil, label: "Average CIBIL score", formula: "AVG(cibil_score)", unit: score, better: higher,
     group: credit, description: "Average score of applicants with a CIBIL score."}
  - {id: avg_interest_rate, label: "Average interest rate", formula: "AVG_IF(interest_rate_pct, is_disbursed)",
     unit: pct, better: neutral, group: credit, description: "Average rate on disbursed loans."}
  - {id: avg_post_loan_foir, label: "Average FOIR (approved)", formula: "AVG_IF(post_loan_foir_pct, is_approved)",
     unit: pct, better: lower, group: credit, description: "Average post-loan FOIR of approved applications."}
  - {id: avg_decision_tat, label: "Decision TAT", formula: "AVG(decision_tat_days)", unit: days, better: lower,
     group: turnaround, description: "Average days from application to decision."}
  - {id: avg_disbursement_tat, label: "Disbursement TAT", formula: "AVG(disbursement_tat_days)", unit: days,
     better: lower, group: turnaround, description: "Average days from decision to disbursement."}
  - {id: avg_end_to_end_tat, label: "End-to-end TAT", formula: "AVG(end_to_end_tat_days)", unit: days,
     better: lower, group: turnaround, description: "Average days from application to disbursement."}
```

- [ ] **Step 4: Write `metrics.py` and the settings**

```python
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
```

In `backend/app/settings.py`, add after `catalog_path`:

```python
    metrics_path: Path = Field(ROOT / "catalog" / "metrics.yaml", validation_alias="BANKREPORTER_METRICS")
    defaults_dir: Path = Field(ROOT / "catalog" / "defaults", validation_alias="BANKREPORTER_DEFAULTS")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `../.venv/bin/pytest -q tests/reporting`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add catalog/metrics.yaml backend/app/reporting/metrics.py backend/app/settings.py backend/tests/reporting/test_metrics.py
git commit -m "feat(reporting): metric library of 22 lending KPIs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Periods

**Files:**
- Create: `backend/app/reporting/period.py`
- Test: `backend/tests/reporting/test_period.py`

**Interfaces:**
- **Produces:**
  - `Period` (frozen dataclass): `start: date`, `end: date` (exclusive), `prev_start: date`, `prev_end: date` (exclusive), `label: str`, and `.as_dict() -> dict` (inclusive ISO dates for the API)
  - `PeriodError(ValueError)`
  - `PRESETS: tuple[str, ...]`
  - `resolve_period(spec: dict, today: date) -> Period`
  - `sparkline_window(period: Period) -> tuple[date, date]` (6 calendar months ending with the month containing the period end; end exclusive)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/reporting/test_period.py
from datetime import date

import pytest

from app.reporting.period import PeriodError, resolve_period, sparkline_window

TODAY = date(2026, 10, 22)


def p(preset, today=TODAY, **kw):
    return resolve_period({"preset": preset, **kw}, today)


def test_last_month_is_default_shape():
    r = p("last_month")
    assert (r.start, r.end, r.prev_start, r.prev_end, r.label) == (
        date(2026, 9, 1), date(2026, 10, 1), date(2026, 8, 1), date(2026, 9, 1), "Sep 2026")


def test_this_month_and_previous_across_year():
    r = p("this_month", today=date(2026, 1, 15))
    assert (r.start, r.end, r.prev_start, r.prev_end) == (
        date(2026, 1, 1), date(2026, 2, 1), date(2025, 12, 1), date(2026, 1, 1))
    assert p("last_month", today=date(2026, 1, 15)).label == "Dec 2025"


def test_quarters():
    r = p("this_quarter")
    assert (r.start, r.end, r.prev_start, r.label) == (date(2026, 10, 1), date(2027, 1, 1), date(2026, 7, 1), "Q4 2026")
    r = p("last_quarter", today=date(2026, 2, 3))
    assert (r.start, r.end, r.prev_start, r.label) == (date(2025, 10, 1), date(2026, 1, 1), date(2025, 7, 1), "Q4 2025")


def test_ytd_and_leap_day():
    r = p("ytd")
    assert (r.start, r.end, r.prev_start, r.prev_end, r.label) == (
        date(2026, 1, 1), date(2026, 10, 23), date(2025, 1, 1), date(2025, 10, 23), "YTD 2026")
    leap = p("ytd", today=date(2028, 2, 29))
    assert leap.prev_end == date(2027, 3, 1)       # 28 Feb 2027 inclusive


def test_last_12_months():
    r = p("last_12_months")
    assert (r.start, r.end, r.prev_start, r.label) == (
        date(2025, 10, 1), date(2026, 10, 1), date(2024, 10, 1), "Oct 2025 – Sep 2026")


def test_custom_previous_window_has_same_length():
    r = p("custom", start="2026-03-01", end="2026-03-10")
    assert (r.start, r.end, r.prev_start, r.prev_end) == (
        date(2026, 3, 1), date(2026, 3, 11), date(2026, 2, 19), date(2026, 3, 1))
    assert r.label == "1 Mar 2026 – 10 Mar 2026"
    assert r.as_dict() == {"start": "2026-03-01", "end": "2026-03-10", "prev_start": "2026-02-19",
                           "prev_end": "2026-02-28", "label": "1 Mar 2026 – 10 Mar 2026"}


@pytest.mark.parametrize("spec, msg", [
    ({"preset": "custom", "start": "2026-03-10", "end": "2026-03-01"}, "start must not be after end"),
    ({"preset": "custom", "start": "2026-03-10"}, "custom periods need start and end"),
    ({"preset": "custom", "start": "10/03/2026", "end": "2026-03-11"}, "dates must be YYYY-MM-DD"),
    ({"preset": "fortnight"}, "unknown period preset 'fortnight'"),
    ({}, "unknown period preset 'None'"),
])
def test_errors(spec, msg):
    with pytest.raises(PeriodError, match=msg):
        resolve_period(spec, TODAY)


def test_sparkline_window_is_six_months_ending_with_period_end():
    assert sparkline_window(p("last_month")) == (date(2026, 4, 1), date(2026, 10, 1))
    assert sparkline_window(p("custom", start="2026-03-01", end="2026-03-10")) == (date(2025, 10, 1), date(2026, 4, 1))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/reporting/test_period.py`
Expected: `No module named 'app.reporting.period'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/reporting/period.py
"""Report/dashboard periods and their comparison periods (spec §4). End dates are exclusive."""
from dataclasses import dataclass
from datetime import date, timedelta

PRESETS = ("this_month", "last_month", "this_quarter", "last_quarter", "ytd", "last_12_months", "custom")
ONE_DAY = timedelta(days=1)


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    prev_start: date
    prev_end: date
    label: str

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": (self.end - ONE_DAY).isoformat(),
                "prev_start": self.prev_start.isoformat(), "prev_end": (self.prev_end - ONE_DAY).isoformat(),
                "label": self.label}


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    """d must be the 1st of a month."""
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _day_label(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _same_day_last_year(d: date) -> date:
    return d.replace(year=d.year - 1, day=28) if (d.month, d.day) == (2, 29) else d.replace(year=d.year - 1)


def resolve_period(spec: dict, today: date) -> Period:
    preset = spec.get("preset")
    this_month = month_start(today)
    quarter = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    match preset:
        case "this_month":
            return Period(this_month, add_months(this_month, 1), add_months(this_month, -1), this_month,
                          f"{this_month:%b %Y}")
        case "last_month":
            s = add_months(this_month, -1)
            return Period(s, this_month, add_months(s, -1), s, f"{s:%b %Y}")
        case "this_quarter" | "last_quarter":
            s = quarter if preset == "this_quarter" else add_months(quarter, -3)
            return Period(s, add_months(s, 3), add_months(s, -3), s, f"Q{(s.month - 1) // 3 + 1} {s.year}")
        case "ytd":
            s = date(today.year, 1, 1)
            return Period(s, today + ONE_DAY, date(today.year - 1, 1, 1), _same_day_last_year(today) + ONE_DAY,
                          f"YTD {today.year}")
        case "last_12_months":
            s = add_months(this_month, -12)
            return Period(s, this_month, add_months(s, -12), s,
                          f"{s:%b %Y} – {add_months(this_month, -1):%b %Y}")
        case "custom":
            if not spec.get("start") or not spec.get("end"):
                raise PeriodError("custom periods need start and end")
            try:
                s, last = date.fromisoformat(spec["start"]), date.fromisoformat(spec["end"])
            except (TypeError, ValueError):
                raise PeriodError("dates must be YYYY-MM-DD") from None
            if s > last:
                raise PeriodError("start must not be after end")
            length = (last - s).days + 1
            return Period(s, last + ONE_DAY, s - timedelta(days=length), s,
                          f"{_day_label(s)} – {_day_label(last)}")
    raise PeriodError(f"unknown period preset '{preset}'")


def sparkline_window(period: Period) -> tuple[date, date]:
    last_month = month_start(period.end - ONE_DAY)
    return add_months(last_month, -5), add_months(last_month, 1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../.venv/bin/pytest -q tests/reporting/test_period.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reporting/period.py backend/tests/reporting/test_period.py
git commit -m "feat(reporting): period presets with comparison periods

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Formatting

**Files:**
- Create: `backend/app/reporting/formatting.py`
- Test: `backend/tests/reporting/test_formatting.py`

**Interfaces:**
- **Produces** (module `app.reporting.formatting`, imported as `fmt`):
  - `indian(n: int) -> str`
  - `measure(v, unit: str) -> str` (units: `count INR pct days score ratio number`)
  - `val(v, unit) -> {"raw": float|None, "display": str}`
  - `delta(v, pv, unit, better) -> dict | None`
  - `dimension(v, field) -> {"raw", "display"}` (`field` is a catalog `Field`)
  - `month_label(v) -> str`
  - `datetime_label(dt) -> str`
  - `jsonable(v)`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/reporting/test_formatting.py
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.reporting import formatting as fmt

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")


@pytest.mark.parametrize("n, s", [(0, "0"), (999, "999"), (1000, "1,000"), (123456, "1,23,456"),
                                  (12345678, "1,23,45,678"), (-123456, "-1,23,456")])
def test_indian_grouping(n, s):
    assert fmt.indian(n) == s


@pytest.mark.parametrize("v, unit, s", [
    (None, "INR", "—"), (Decimal("45200000"), "INR", "₹4.52 Cr"), (3860000, "INR", "₹38.6 L"),
    (85400.4, "INR", "₹85,400"), (-3860000, "INR", "-₹38.6 L"), (123456, "count", "1,23,456"),
    (61.234, "pct", "61.2%"), (4.26, "days", "4.3 days"), (731.4, "score", "731"), (1.849, "ratio", "1.85"),
    (12.5, "number", "12.50"), (12, "number", "12"),
])
def test_measure(v, unit, s):
    assert fmt.measure(v, unit) == s


def test_val_raw_is_float_or_none():
    assert fmt.val(Decimal("12.50"), "pct") == {"raw": 12.5, "display": "12.5%"}
    assert fmt.val(None, "count") == {"raw": None, "display": "—"}


def test_delta_pct_is_points_and_good_follows_better():
    d = fmt.delta(61.2, 59.1, "pct", "higher")
    assert d["display"] == "+2.1 pts" and d["direction"] == "up" and d["good"] is True
    assert fmt.delta(5.0, 4.0, "days", "lower") == {"raw": 25.0, "display": "+25.0%", "direction": "up", "good": False}
    assert fmt.delta(10, 10, "count", "higher")["good"] is None              # flat
    assert fmt.delta(10, 12, "INR", "neutral")["good"] is None


def test_delta_null_cases():
    assert fmt.delta(None, 3, "count", "higher") is None
    assert fmt.delta(3, None, "count", "higher") is None
    assert fmt.delta(3, 0, "count", "higher") is None                          # % change undefined
    assert fmt.delta(3.0, 0.0, "pct", "higher")["display"] == "+3.0 pts"       # points are fine


def test_dimension_display():
    assert fmt.dimension(None, CATALOG.field("rejection_reason")) == {"raw": None, "display": "—"}
    assert fmt.dimension(1, CATALOG.field("is_disbursed"))["display"] == "Yes"
    assert fmt.dimension(False, CATALOG.field("has_writeoff"))["display"] == "No"
    assert fmt.dimension(date(2026, 9, 1), CATALOG.field("application_month")) == {"raw": "2026-09-01", "display": "Sep 2026"}
    assert fmt.dimension("2026-09-01", CATALOG.field("application_month"))["display"] == "Sep 2026"
    assert fmt.dimension("WEB", CATALOG.field("channel")) == {"raw": "WEB", "display": "WEB"}


def test_labels():
    assert fmt.month_label(datetime(2026, 3, 1, 0, 0)) == "Mar 2026"
    assert fmt.datetime_label(datetime(2026, 10, 22, 18, 5)) == "22 Oct 2026, 18:05"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/reporting/test_formatting.py`
Expected: `cannot import name 'formatting'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/reporting/formatting.py
"""One formatter for every displayed value (spec §5.4). Indian grouping; ₹ in lakh/crore."""
from datetime import date, datetime
from decimal import Decimal


def jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def indian(n: int) -> str:
    s = str(abs(int(n)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if n < 0 else "") + ",".join(groups + [tail])


def measure(v, unit: str) -> str:
    if v is None:
        return "—"
    x = float(v)
    if unit == "count" or unit == "score":
        return indian(round(x))
    if unit == "INR":
        sign, a = ("-" if x < 0 else ""), abs(x)
        if a >= 1e7:
            return f"{sign}₹{a / 1e7:.2f} Cr"
        if a >= 1e5:
            return f"{sign}₹{a / 1e5:.1f} L"
        return f"{sign}₹{indian(round(a))}"
    if unit == "pct":
        return f"{x:.1f}%"
    if unit == "days":
        return f"{x:.1f} days"
    if unit == "ratio":
        return f"{x:.2f}"
    return indian(round(x)) if x == int(x) else f"{x:.2f}"


def val(v, unit: str) -> dict:
    return {"raw": None if v is None else float(v), "display": measure(v, unit)}


def delta(v, pv, unit: str, better: str) -> dict | None:
    if v is None or pv is None:
        return None
    v, pv = float(v), float(pv)
    if unit == "pct":
        d = v - pv
        display = f"{d:+.1f} pts"
    else:
        if pv == 0:
            return None
        d = (v - pv) / abs(pv) * 100
        display = f"{d:+.1f}%"
    direction = "up" if d > 1e-9 else "down" if d < -1e-9 else "flat"
    good = None if better == "neutral" or direction == "flat" else (direction == "up") == (better == "higher")
    return {"raw": round(d, 6), "display": display, "direction": direction, "good": good}


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def month_label(v) -> str:
    d = _to_date(v)
    return f"{d:%b %Y}" if d else "—"


def datetime_label(dt: datetime) -> str:
    return f"{dt.day} {dt:%b %Y}, {dt:%H:%M}"


def dimension(v, field) -> dict:
    if v is None:
        return {"raw": None, "display": "—"}
    if field.type == "boolean":
        return {"raw": bool(v), "display": "Yes" if v else "No"}
    if field.type == "date":
        d = _to_date(v)
        return {"raw": d.isoformat(), "display": month_label(d) if field.id == "application_month" else d.isoformat()}
    raw = jsonable(v)
    return {"raw": raw, "display": str(raw)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../.venv/bin/pytest -q tests/reporting/test_formatting.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reporting/formatting.py backend/tests/reporting/test_formatting.py
git commit -m "feat(reporting): Indian number formatting, deltas and dimension labels

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 5: Block specs and validation

**Files:**
- Create: `backend/app/reporting/spec.py`
- Test: `backend/tests/reporting/test_spec.py`

**Interfaces:**
- **Consumes:** `Catalog` (`.fields`, `.field(id)`, `Field.role/type/values`); `MetricLibrary` (`__contains__`).
- **Produces:**
  - Pydantic models: `Measure`, `Sort`, `QuerySpec`, `KpiItem`, and blocks `HeadingBlock`, `TextBlock`, `KpiRowBlock`, `KpiBlock`, `TableBlock`, `ChartBlock`, `PageBreakBlock`, plus the union `Block`.
  - `Measure.key -> str`: the metric ID, or `f"{agg}_{field}"`.
  - `AGG_LABELS`, `PLACEHOLDER` (regex), `SIMPLE_PLACEHOLDERS`.
  - `parse_block(raw: dict) -> tuple[Block | None, list[str]]`
  - `validate_block(block, catalog, metrics) -> list[str]`
  - `check_blocks(raw_blocks: list[dict], catalog, metrics, allowed_types: set[str] | None = None) -> tuple[list[Block], list[dict]]`, where errors are `[{"block_id": str, "messages": [str]}]`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/reporting/test_spec.py
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.reporting.metrics import load_metrics
from app.reporting.spec import check_blocks, parse_block, validate_block

ROOT = Path(__file__).parents[3]
CATALOG = load_catalog(ROOT / "catalog" / "fields.yaml")
METRICS = load_metrics(ROOT / "catalog" / "metrics.yaml", CATALOG)


def errors(raw):
    block, errs = parse_block(raw)
    return errs if block is None else validate_block(block, CATALOG, METRICS)


def chart(**query):
    q = {"measures": [{"metric": "applications"}], "group_by": ["channel"], **query}
    return {"id": "c", "type": "chart", "chart": "bar", "query": q}


def test_valid_blocks():
    assert errors({"id": "h", "type": "heading", "text": "Hi {{client_name}}", "level": 2}) == []
    assert errors({"id": "k", "type": "kpi_row", "items": [{"measure": {"metric": "approval_rate"}},
                                                            {"measure": {"field": "cibil_score", "agg": "avg"}}]}) == []
    assert errors(chart(filters=[["employment_type", "eq", "SALARIED"], ["cibil_score", "gte", 700],
                                 ["is_disbursed", "eq", True], ["rejection_reason", "is_null"],
                                 ["cibil_band", "in", ["750-799", "800+"]], ["application_date", "lt", "2026-06-01"]],
                        sort={"by": "applications", "dir": "desc"}, limit=10)) == []
    assert errors({"id": "p", "type": "page_break"}) == []


def test_unknown_type_and_missing_fields_are_structural_errors():
    assert any("gauge" in e for e in errors({"id": "x", "type": "gauge"}))
    assert any("level" in e for e in errors({"id": "h", "type": "heading", "text": "x", "level": 9}))


@pytest.mark.parametrize("raw, msg", [
    (chart(measures=[{"metric": "nope"}]), "measure 1: unknown metric 'nope'"),
    (chart(measures=[{"field": "channel", "agg": "sum"}]), "measure 1: sum needs a measure field; channel is a dimension"),
    (chart(measures=[{"field": "cibil_score"}]), "measure 1: field measures need 'agg'"),
    (chart(measures=[{"metric": "applications", "field": "city", "agg": "count"}]), "measure 1: choose either a metric or a field"),
    (chart(group_by=["requested_amount"]), "group_by: requested_amount is a measure, not a dimension"),
    (chart(group_by=["nope"]), "group_by: unknown field 'nope'"),
    (chart(sort={"by": "approval_rate"}), "sort.by 'approval_rate' is not a measure or group-by of this block"),
    (chart(limit=0), "limit must be between 1 and 500"),
    (chart(filters=[["channel", "like", "W%"]]), "filter 1: unknown operator 'like'"),
    (chart(filters=[["channel", "eq", "FAX"]]), "filter 1: 'FAX' is not one of channel's values"),
    (chart(filters=[["channel", "in", []]]), "filter 1: in needs a non-empty list"),
    (chart(filters=[["city", "gt", "A"]]), "filter 1: gt needs a number or date field; city is string"),
    (chart(filters=[["rejection_reason", "is_null", "x"]]), "filter 1: is_null takes no value"),
    (chart(filters=[["application_date", "gte", "June"]]), "filter 1: 'June' is not a valid date for application_date"),
])
def test_semantic_errors(raw, msg):
    assert msg in errors(raw)


def test_filter_value_type_checked():
    # Review focus 5: a string "650" from the UI for an integer field is a validation error, not SQL.
    assert "filter 1: '650' is not a valid integer for cibil_score" in errors(chart(filters=[["cibil_score", "gte", "650"]]))
    assert "filter 1: True is not a valid integer for cibil_score" in errors(chart(filters=[["cibil_score", "eq", True]]))


@pytest.mark.parametrize("raw, msg", [
    ({**chart(), "chart": "pie", "query": {"measures": [{"metric": "applications"}, {"metric": "approved"}], "group_by": ["channel"]}},
     "pie charts need exactly 1 group-by and 1 measure"),
    ({**chart(), "chart": "line", "query": {"measures": [{"metric": "applications"}], "group_by": []}},
     "line charts need at least 1 group-by"),
    ({**chart(), "query": {"measures": [{"metric": "applications"}, {"metric": "approved"}],
                           "group_by": ["application_month", "channel"]}},
     "charts with 2 group-bys need exactly 1 measure"),
    ({"id": "t", "type": "table", "query": {"measures": [{"metric": "applications"}]}},
     "tables need at least 1 group-by"),
    ({"id": "t", "type": "text", "text": "{{metric:nope}} and {{period}}"}, "unknown metric 'nope' in placeholder"),
])
def test_chart_table_and_placeholder_rules(raw, msg):
    assert msg in errors(raw)


def test_check_blocks_collects_per_block_and_respects_allowed_types():
    blocks, errs = check_blocks([chart(), {"id": "h", "type": "heading", "text": "x"},
                                 chart(measures=[{"metric": "nope"}]) | {"id": "bad"}], CATALOG, METRICS,
                                allowed_types={"chart", "kpi", "table"})
    assert len(blocks) == 1
    assert errs == [{"block_id": "h", "messages": ["heading blocks are not allowed here"]},
                    {"block_id": "bad", "messages": ["measure 1: unknown metric 'nope'"]}]


def test_duplicate_block_ids_rejected():
    _, errs = check_blocks([chart(), chart()], CATALOG, METRICS)
    assert errs == [{"block_id": "c", "messages": ["duplicate block id"]}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/reporting/test_spec.py`
Expected: `No module named 'app.reporting.spec'`.

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../.venv/bin/pytest -q tests/reporting/test_spec.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reporting/spec.py backend/tests/reporting/test_spec.py
git commit -m "feat(reporting): block specs and validation against catalog and metrics

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Query builder and render engine (plus golden correctness)

**Files:**
- Create: `backend/app/reporting/query.py`, `backend/app/reporting/render.py`
- Test: `backend/tests/reporting/test_render.py` (SQLite), `backend/tests/reporting/test_golden.py` (db)

**Interfaces:**
- **Consumes:** Tasks 1–5; `mask_secrets` is optional. `RenderContext.mask` defaults to the identity function.
- **Produces:**
  - `query.py`:
    - `VIEW = "applications"`
    - `view_table(catalog, schema) -> TableClause`
    - `measure_expr(m, view, metrics) -> ColumnElement`
    - `filter_expr(flt, view, catalog) -> ColumnElement`
    - `scalar_select(measures, filters, start, end, view, catalog, metrics) -> Select`
    - `grouped_select(q: QuerySpec, start, end, view, catalog, metrics) -> Select`
  - `render.py`:
    - `NotPublished(Exception)`
    - `RenderContext(catalog, metrics, period, client_name, schema="lending_rpt", generated_at=now, mask=identity)`
    - `check_published(conn, ctx)`
    - `render_blocks(raw_blocks: list[dict], conn, ctx) -> list[dict]`
    - `measure_meta(m, ctx) -> (label, unit, better)`

**Block result shapes (from spec §5.2):**

| Type | Result |
|---|---|
| heading | `{id, type, text, level}` |
| text | `{id, type, text}` |
| kpi_row | `{id, type, title, items: [Kpi]}` |
| kpi | `{id, type, kpi: Kpi}` |
| table | `{id, type, title, columns, rows, totals, empty}` |
| chart | `{id, type, title, chart, columns, rows, empty}` |
| page_break | `{id, type}` |
| any error | `{id, type, error}` |

- [ ] **Step 1: Write the failing SQLite tests**

```python
# backend/tests/reporting/test_render.py
"""Render engine on SQLite: a table holding view-shaped rows, exposed as main.applications."""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.catalog.loader import load_catalog
from app.reporting.metrics import load_metrics
from app.reporting.period import resolve_period
from app.reporting.render import NotPublished, RenderContext, check_published, render_blocks

ROOT = Path(__file__).parents[3]
CATALOG = load_catalog(ROOT / "catalog" / "fields.yaml")
METRICS = load_metrics(ROOT / "catalog" / "metrics.yaml", CATALOG)
SEP = {"preset": "last_month"}                   # with TODAY: Sep 2026, previous Aug 2026
TODAY = date(2026, 10, 22)


def app_row(i, month, status, channel="WEB", amount=None, reason=None):
    approved = status in ("APPROVED", "DISBURSED")
    return {"application_id": f"A{i}", "application_date": f"2026-{month:02d}-10",
            "application_month": f"2026-{month:02d}-01", "application_status": status, "channel": channel,
            "decision_date": None if status == "SUBMITTED" else f"2026-{month:02d}-12",
            "is_approved": int(approved), "is_rejected": int(status == "REJECTED"),
            "is_disbursed": int(status == "DISBURSED"), "disbursed_amount": amount, "rejection_reason": reason,
            "cibil_score": 720, "is_new_to_credit": 0, "kyc_status": "VERIFIED", "decision_mode": "AUTO"}


ROWS = [
    app_row(1, 9, "DISBURSED", "WEB", 500000), app_row(2, 9, "APPROVED", "DSA"),
    app_row(3, 9, "REJECTED", "WEB", reason="LOW_CIBIL"), app_row(4, 9, "SUBMITTED", "BRANCH"),
    app_row(5, 8, "DISBURSED", "WEB", 300000), app_row(6, 8, "REJECTED", "DSA", reason="HIGH_FOIR"),
]


@pytest.fixture(scope="module")
def conn():
    engine = create_engine("sqlite://")
    cols = ", ".join(f'"{f.id}"' for f in CATALOG.fields)
    with engine.begin() as c:
        c.execute(text(f"CREATE TABLE data ({cols})"))
        c.execute(text("CREATE VIEW applications AS SELECT * FROM data"))
        for r in ROWS:
            keys = list(r)
            c.execute(text(f"INSERT INTO data ({', '.join(keys)}) VALUES ({', '.join(':' + k for k in keys)})"), r)
    with engine.connect() as c:
        yield c


def ctx(period=SEP):
    return RenderContext(CATALOG, METRICS, resolve_period(period, TODAY), "NovaBank", schema="main")


def render(conn, *blocks, period=SEP):
    return render_blocks(list(blocks), conn, ctx(period))


def test_kpi_row_values_previous_and_delta(conn):
    [r] = render(conn, {"id": "k", "type": "kpi_row", "items": [{"measure": {"metric": "approval_rate"}},
                                                                 {"measure": {"metric": "applications"}}]})
    rate, apps = r["items"]
    assert rate["value"] == {"raw": pytest.approx(66.666667, abs=1e-5), "display": "66.7%"}   # 2 of 3 decided
    assert rate["previous"]["display"] == "50.0%"
    assert rate["delta"]["display"] == "+16.7 pts" and rate["delta"]["good"] is True
    assert apps["value"]["display"] == "4" and apps["delta"]["display"] == "+100.0%"


def test_kpi_tile_has_sparkline(conn):
    [r] = render(conn, {"id": "k", "type": "kpi", "measure": {"metric": "applications"}})
    assert [p["month"] for p in r["kpi"]["sparkline"]] == ["Aug 2026", "Sep 2026"]
    assert [p["raw"] for p in r["kpi"]["sparkline"]] == [2.0, 4.0]


def test_grouped_table_with_totals_and_sort(conn):
    [r] = render(conn, {"id": "t", "type": "table", "totals": True, "query": {
        "measures": [{"metric": "applications"}, {"field": "disbursed_amount", "agg": "sum"}],
        "group_by": ["channel"], "sort": {"by": "applications", "dir": "desc"}}})
    assert [c["key"] for c in r["columns"]] == ["channel", "applications", "sum_disbursed_amount"]
    assert r["rows"][0]["channel"]["display"] == "WEB"          # 2 applications; DSA and BRANCH tie on 1
    assert r["totals"]["applications"]["display"] == "4"
    assert r["totals"]["sum_disbursed_amount"]["display"] == "₹5.0 L"


def test_null_group_key_renders_dash(conn):
    # Review focus 1
    [r] = render(conn, {"id": "t", "type": "table", "query": {"measures": [{"metric": "applications"}],
                                                              "group_by": ["rejection_reason"]}})
    labels = {row["rejection_reason"]["display"]: row["applications"]["raw"] for row in r["rows"]}
    assert labels == {"—": 3.0, "LOW_CIBIL": 1.0}


def test_zero_denominator_kpi_is_dash_without_delta(conn):
    # Review focus 2: no approvals among BRANCH applications in either period
    [r] = render(conn, {"id": "k", "type": "kpi", "measure": {"metric": "disbursement_conversion"},
                        "filters": [["channel", "eq", "BRANCH"]], "sparkline": False})
    assert r["kpi"]["value"] == {"raw": None, "display": "—"} and r["kpi"]["delta"] is None


def test_empty_period_renders_every_block(conn):
    # Review focus 3
    out = render(conn, {"id": "k", "type": "kpi_row", "items": [{"measure": {"metric": "applications"}},
                                                                 {"measure": {"metric": "approval_rate"}}]},
                 {"id": "c", "type": "chart", "chart": "bar",
                  "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"]}},
                 period={"preset": "this_month"})
    assert "error" not in out[0] and "error" not in out[1]
    assert out[0]["items"][0]["value"]["display"] == "0" and out[0]["items"][1]["value"]["display"] == "—"
    assert out[1]["empty"] is True and out[1]["rows"] == []


def test_stale_block_errors_alone(conn):
    # Review focus 4
    out = render(conn, {"id": "a", "type": "kpi", "measure": {"metric": "removed_metric"}},
                 {"id": "b", "type": "heading", "text": "OK"})
    assert out[0]["error"].startswith("invalid block: measure 1: unknown metric 'removed_metric'")
    assert out[1] == {"id": "b", "type": "heading", "text": "OK", "level": 1}


def test_sql_failure_in_one_block_does_not_stop_others(conn):
    from sqlalchemy.exc import OperationalError
    blocks = [{"id": "c", "type": "chart", "chart": "bar",
               "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"]}},
              {"id": "h", "type": "heading", "text": "after"}]
    c = ctx()
    c.schema = "nope"            # every query in the chart fails
    out = render_blocks(blocks, conn, c)
    assert "error" in out[0] and out[1]["text"] == "after"


def test_text_placeholders(conn):
    [r] = render(conn, {"id": "t", "type": "text",
                        "text": "{{client_name}} · {{period}} · {{metric:applications}} apps · {{metric:approval_rate}} · {{nope}}"})
    assert r["text"] == "NovaBank · Sep 2026 · 4 apps · 66.7% · [unknown: nope]"


def test_check_published(conn):
    check_published(conn, ctx())
    c = ctx()
    c.schema = "nope"
    with pytest.raises(NotPublished, match="NovaBank has no published views; publish its mapping first"):
        check_published(conn, c)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/reporting/test_render.py`
Expected: `No module named 'app.reporting.render'`.

- [ ] **Step 3: Write `query.py`**

```python
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
```

- [ ] **Step 4: Write `render.py`**

```python
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
```

- [ ] **Step 5: Run the SQLite tests to verify they pass**

Run: `../.venv/bin/pytest -q tests/reporting/test_render.py`
Expected: all pass.

- [ ] **Step 6: Write the golden correctness test (db)**

```python
# backend/tests/reporting/test_golden.py
"""Every metric and a grouped query give identical results on both clients and equal a plain-Python
calculation over the golden CSV (spec §10: "one template, any client")."""
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.mapping.introspect import introspect
from app.mapping.joins import plan_joins
from app.mapping.profile import profile_columns
from app.mapping.viewgen import build_base_select, build_view_ddl, publish
from app.reporting.metrics import load_metrics
from app.reporting.period import resolve_period
from app.reporting.query import grouped_select, scalar_select, view_table
from app.reporting.spec import Measure, QuerySpec
from mockdata import generate
from mockdata.golden import read_golden
from mockdata.writers import client1_pg, client2_mysql
from tests.mapping.conftest import CATALOG, answer_key_sources

EVAL = "lending_rpt_eval"
METRICS = load_metrics(Path(__file__).parents[3] / "catalog" / "metrics.yaml", CATALOG)
PERIOD = resolve_period({"preset": "custom", "start": "2026-01-01", "end": "2026-06-30"}, date(2026, 10, 22))
CLIENTS = {"client1": ("pg_engine", "los", client1_pg), "client2": ("mysql_engine", "bfs_core", client2_mysql)}


@pytest.fixture(scope="module", params=list(CLIENTS))
def published(request):
    engine_fixture, schema, writer = CLIENTS[request.param]
    engine = request.getfixturevalue(engine_fixture)
    if not generate.GOLDEN_PATH.exists():
        pytest.skip("golden CSV missing; run python -m mockdata.generate --reset")
    info = introspect(engine, [schema])
    plan = plan_joins(info, profile_columns(engine, info, CATALOG), lambda ref: 0.0)
    base = build_base_select(info, plan, answer_key_sources(writer, plan), CATALOG)
    publish(engine, build_view_ddl(engine.dialect.name, EVAL, base, CATALOG), plan.grain, EVAL)
    yield engine
    with engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {EVAL}.{v}"))


# ---- plain-Python reference over the golden CSV -------------------------------------------------

def num(x):
    return float(x) if x not in ("", None) else None


def day(x):
    return date.fromisoformat(x) if x else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def ratio(a, b):
    return None if not b else a / b * 100


def reference(rows: list[dict]) -> dict:
    approved = [r for r in rows if r["application_status"] in ("APPROVED", "DISBURSED")]
    disbursed = [r for r in rows if r["application_status"] == "DISBURSED"]
    decided = [r for r in rows if r["decision_date"]]
    rejected = [r for r in rows if r["application_status"] == "REJECTED"]

    def foir(r):
        net, emi = num(r["net_income_monthly"]), num(r["existing_emi_monthly"])
        if not net or emi is None:
            return None
        return (emi + (num(r["approved_emi"]) or 0)) / net * 100

    def tat(a, b, r):
        return (day(r[b]) - day(r[a])).days if r[a] and r[b] else None

    total = lambda rs, f: sum(num(r[f]) for r in rs if num(r[f]) is not None)
    return {
        "applications": len(rows), "decided": len(decided), "approved": len(approved),
        "rejected": len(rejected), "disbursed_count": len(disbursed),
        "approval_rate": ratio(len(approved), len(decided)), "rejection_rate": ratio(len(rejected), len(decided)),
        "disbursement_conversion": ratio(len(disbursed), len(approved)),
        "kyc_failure_rate": ratio(sum(r["kyc_status"] == "FAILED" for r in rows), len(rows)),
        "auto_decision_share": ratio(sum(r["decision_mode"] == "AUTO" for r in rows), len(decided)),
        "ntc_share": ratio(sum(r["cibil_score"] == "" for r in rows), len(rows)),
        "requested_amount_total": total(rows, "requested_amount"),
        "sanctioned_amount_total": total(rows, "approved_amount"),
        "disbursed_amount_total": total(rows, "disbursed_amount"),
        "avg_ticket_size": total(rows, "disbursed_amount") / len(disbursed) if disbursed else None,
        "processing_fee_income": total(rows, "processing_fee"),
        "avg_cibil": mean(num(r["cibil_score"]) for r in rows),
        "avg_interest_rate": mean(num(r["interest_rate_pct"]) for r in disbursed),
        "avg_post_loan_foir": mean(foir(r) for r in approved),
        "avg_decision_tat": mean(tat("application_date", "decision_date", r) for r in rows),
        "avg_disbursement_tat": mean(tat("decision_date", "disbursement_date", r) for r in rows),
        "avg_end_to_end_tat": mean(tat("application_date", "disbursement_date", r) for r in rows),
    }


def golden_in(start: date, end: date) -> list[dict]:
    return [r for r in read_golden(generate.GOLDEN_PATH) if start <= date.fromisoformat(r["application_date"]) < end]


@pytest.mark.db
def test_every_metric_matches_python_reference(published):
    view = view_table(CATALOG, EVAL)
    for start, end in [(PERIOD.start, PERIOD.end), (PERIOD.prev_start, PERIOD.prev_end)]:
        stmt = scalar_select([Measure(metric=m) for m in METRICS.ids], [], start, end, view, CATALOG, METRICS)
        with published.connect() as conn:
            got = dict(conn.execute(stmt).mappings().one())
        want = reference(golden_in(start, end))
        mismatches = {k: (got[k], want[k]) for k in METRICS.ids
                      if not (got[k] is None and want[k] is None)
                      and (got[k] is None or want[k] is None or float(got[k]) != pytest.approx(want[k], rel=1e-5))}
        assert mismatches == {}


@pytest.mark.db
def test_grouped_counts_match_python_reference(published):
    q = QuerySpec(measures=[Measure(metric="applications")], group_by=["channel", "application_status"], limit=500)
    stmt = grouped_select(q, PERIOD.start, PERIOD.end, view_table(CATALOG, EVAL), CATALOG, METRICS)
    with published.connect() as conn:
        got = {(r["channel"], r["application_status"]): r["applications"] for r in conn.execute(stmt).mappings()}
    want = Counter((r["channel"], r["application_status"]) for r in golden_in(PERIOD.start, PERIOD.end))
    assert got == dict(want)
```

- [ ] **Step 7: Run all reporting tests**

Run: `../.venv/bin/pytest -q tests/reporting`
Expected: all pass. The golden tests run on both Postgres and MySQL; none are skipped while Docker is up.

- [ ] **Step 8: Commit**

```bash
git add backend/app/reporting/query.py backend/app/reporting/render.py backend/tests/reporting/test_render.py backend/tests/reporting/test_golden.py
git commit -m "feat(reporting): query builder and block render engine, verified against golden data on both clients

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Storage, defaults and the reporting API

**Files:**
- Modify: `backend/app/store/__init__.py` (add models), `backend/app/api/__init__.py` (wiring)
- Create: `backend/app/reporting/defaults.py`, `backend/app/api/reporting.py`, `catalog/defaults/monthly_lending_mis.yaml`, `catalog/defaults/lending_kpis.yaml`
- Test: `backend/tests/api/test_reporting_api.py`

**Interfaces:**
- **Consumes:**
  - Tasks 1–6;
  - from `app.connections`: `decrypt_url`, `DecryptError`, `mask_secrets`;
  - the store models `Connection`, `MappingRun`, `Publication`;
  - `Settings.publish_schema`, `metrics_path`, `defaults_dir`.
- **Produces:**
  - Store models:
    - `ReportTemplate(id, name, description, blocks, created_at, updated_at)`
    - `Dashboard(id, name, default_period, tiles, created_at, updated_at)`
  - `seed_defaults(store, directory: Path) -> None`
  - `create_app(settings, embedder=None, llm=None, today=date.today)`, which also sets `app.state.metrics` and `app.state.today`
  - All endpoints in spec §7. Dashboard render results are the tiles' block results, matched by `block.id`.

- [ ] **Step 1: Write the defaults**

```yaml
# catalog/defaults/monthly_lending_mis.yaml
kind: report
name: Monthly Lending MIS
description: Monthly management information pack for personal-loan origination.
blocks:
  - {id: h1, type: heading, level: 1, text: "Personal Loans MIS — {{client_name}}"}
  - id: t1
    type: text
    text: "Period: {{period}}. {{metric:applications}} applications were received; the approval rate was {{metric:approval_rate}} and {{metric:disbursed_amount_total}} was disbursed. Generated {{generated_at}}."
  - id: k1
    type: kpi_row
    items:
      - {measure: {metric: applications}}
      - {measure: {metric: approval_rate}}
      - {measure: {metric: disbursed_amount_total}}
      - {measure: {metric: avg_ticket_size}}
  - {id: c1, type: chart, chart: line, title: "Applications and approvals by month",
     query: {measures: [{metric: applications}, {metric: approved}], group_by: [application_month]}}
  - {id: c2, type: chart, chart: bar, title: "Approval rate by channel",
     query: {measures: [{metric: approval_rate}], group_by: [channel]}}
  - {id: tb1, type: table, title: "Rejection reasons", totals: true,
     query: {measures: [{metric: rejected}], group_by: [rejection_reason],
             filters: [[application_status, eq, REJECTED]], sort: {by: rejected, dir: desc}}}
  - {id: c3, type: chart, chart: pie, title: "Applications by CIBIL band",
     query: {measures: [{metric: applications}], group_by: [cibil_band]}}
  - {id: h2, type: heading, level: 2, text: "Turnaround"}
  - id: k2
    type: kpi_row
    items:
      - {measure: {metric: avg_decision_tat}}
      - {measure: {metric: avg_disbursement_tat}}
      - {measure: {metric: avg_end_to_end_tat}}
  - {id: pb1, type: page_break}
  - {id: tb2, type: table, title: "Disbursals by state", totals: true,
     query: {measures: [{metric: disbursed_count}, {metric: disbursed_amount_total}, {metric: avg_ticket_size}],
             group_by: [state], filters: [[is_disbursed, eq, true]], sort: {by: disbursed_amount_total, dir: desc}}}
```

```yaml
# catalog/defaults/lending_kpis.yaml
kind: dashboard
name: Lending KPIs
default_period: {preset: last_month}
tiles:
  - {id: t1, width: 3, height: m, block: {id: b1, type: kpi, measure: {metric: applications}}}
  - {id: t2, width: 3, height: m, block: {id: b2, type: kpi, measure: {metric: approval_rate}}}
  - {id: t3, width: 3, height: m, block: {id: b3, type: kpi, measure: {metric: disbursement_conversion}}}
  - {id: t4, width: 3, height: m, block: {id: b4, type: kpi, measure: {metric: disbursed_amount_total}}}
  - {id: t5, width: 3, height: m, block: {id: b5, type: kpi, measure: {metric: avg_ticket_size}}}
  - {id: t6, width: 3, height: m, block: {id: b6, type: kpi, measure: {metric: avg_cibil}}}
  - {id: t7, width: 3, height: m, block: {id: b7, type: kpi, measure: {metric: ntc_share}}}
  - {id: t8, width: 3, height: m, block: {id: b8, type: kpi, measure: {metric: avg_end_to_end_tat}}}
  - {id: t9, width: 8, height: l, block: {id: b9, type: chart, chart: line, title: "Applications vs approvals",
                                          query: {measures: [{metric: applications}, {metric: approved}], group_by: [application_month]}}}
  - {id: t10, width: 4, height: l, block: {id: b10, type: chart, chart: pie, title: "Rejection reasons",
                                           query: {measures: [{metric: rejected}], group_by: [rejection_reason],
                                                   filters: [[application_status, eq, REJECTED]]}}}
  - {id: t11, width: 6, height: l, block: {id: b11, type: chart, chart: bar, title: "Disbursed amount by month",
                                           query: {measures: [{metric: disbursed_amount_total}], group_by: [application_month]}}}
  - {id: t12, width: 6, height: l, block: {id: b12, type: chart, chart: bar, title: "Approval rate by CIBIL band",
                                           query: {measures: [{metric: approval_rate}], group_by: [cibil_band]}}}
  - {id: t13, width: 6, height: l, block: {id: b13, type: chart, chart: stacked_bar, title: "Status by channel",
                                           query: {measures: [{metric: applications}], group_by: [channel, application_status]}}}
  - {id: t14, width: 6, height: l, block: {id: b14, type: table, title: "Top states by disbursed amount",
                                           query: {measures: [{metric: disbursed_amount_total}, {metric: disbursed_count}],
                                                   group_by: [state], sort: {by: disbursed_amount_total, dir: desc}, limit: 10}}}
```

- [ ] **Step 2: Write the failing API tests**

```python
# backend/tests/api/test_reporting_api.py
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import create_app
from app.mapping.matcher.embed import Embedder
from tests.api.conftest import PUBLISH_SCHEMA, client1_body, keyword_encoder

TODAY = date(2026, 10, 22)


@pytest.fixture
def rapi(settings):
    app = create_app(settings, embedder=Embedder(encode=keyword_encoder), today=lambda: TODAY)
    with TestClient(app) as client:
        yield client


def chart_block(bid="c1", **query):
    return {"id": bid, "type": "chart", "chart": "bar",
            "query": {"measures": [{"metric": "applications"}], "group_by": ["channel"], **query}}


def test_metrics_endpoint(rapi):
    metrics = rapi.get("/api/metrics").json()
    assert len(metrics) == 22 and {"id", "label", "unit", "better", "group", "description"} <= set(metrics[0])


def test_defaults_seeded_once_and_valid(rapi, settings):
    reports = rapi.get("/api/reports").json()
    dashboards = rapi.get("/api/dashboards").json()
    assert [r["name"] for r in reports] == ["Monthly Lending MIS"]
    assert [d["name"] for d in dashboards] == ["Lending KPIs"]
    create_app(settings, today=lambda: TODAY)          # second start: no duplicates
    assert len(rapi.get("/api/reports").json()) == 1
    template = rapi.get(f"/api/reports/{reports[0]['id']}").json()
    assert rapi.put(f"/api/reports/{template['id']}", json={k: template[k] for k in ("name", "description", "blocks")}).status_code == 200
    board = rapi.get(f"/api/dashboards/{dashboards[0]['id']}").json()
    assert rapi.put(f"/api/dashboards/{board['id']}",
                    json={k: board[k] for k in ("name", "default_period", "tiles")}).status_code == 200


def test_report_crud_and_validation(rapi):
    created = rapi.post("/api/reports", json={"name": "Mine", "blocks": [chart_block()]})
    assert created.status_code == 201
    rid = created.json()["id"]
    bad = rapi.put(f"/api/reports/{rid}", json={"name": "Mine", "blocks": [chart_block(measures=[{"metric": "nope"}])]})
    assert bad.status_code == 422
    assert bad.json()["detail"]["errors"] == [{"block_id": "c1", "messages": ["measure 1: unknown metric 'nope'"]}]
    assert rapi.post("/api/reports", json={"name": "Mine", "blocks": []}).status_code == 409
    assert rapi.delete(f"/api/reports/{rid}").status_code == 204
    assert rapi.get(f"/api/reports/{rid}").status_code == 404


def test_dashboard_tile_validation(rapi):
    body = {"name": "D", "tiles": [{"id": "t", "width": 5, "height": "m", "block": chart_block()},
                                    {"id": "u", "width": 6, "height": "m", "block": {"id": "h", "type": "heading", "text": "x"}}]}
    r = rapi.post("/api/dashboards", json=body)
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert {"block_id": "t", "messages": ["width must be one of 3, 4, 6, 8, 12"]} in errors
    assert {"block_id": "h", "messages": ["heading blocks are not allowed here"]} in errors


def test_render_unknown_connection_and_bad_period(rapi):
    rid = rapi.get("/api/reports").json()[0]["id"]
    assert rapi.post(f"/api/reports/{rid}/render", json={"connection_id": 999, "period": {"preset": "last_month"}}).status_code == 404
    cid = rapi.post("/api/connections", json=client1_body()).json()["id"]
    r = rapi.post(f"/api/reports/{rid}/render", json={"connection_id": cid, "period": {"preset": "custom", "start": "2026-05-01"}})
    assert r.status_code == 422 and "custom periods need start and end" in r.json()["detail"]


def test_render_unreachable_client_is_502(rapi):
    cid = rapi.post("/api/connections", json=client1_body(port=1, password="topsecret")).json()["id"]
    r = rapi.post("/api/render-blocks", json={"connection_id": cid, "period": {"preset": "last_month"}, "blocks": [chart_block()]})
    assert r.status_code == 502 and "topsecret" not in r.text


@pytest.fixture
def published_client(rapi, pg_engine):
    """Client 1 mapped and published to the eval schema through the API."""
    cid = rapi.post("/api/connections", json=client1_body()).json()["id"]
    rid = rapi.post(f"/api/connections/{cid}/mapping-runs", json={"layers": "A"}).json()["run_id"]
    detail = rapi.get(f"/api/mapping-runs/{rid}").json()
    rapi.put(f"/api/mapping-runs/{rid}/join-plan", json={"join_plan": detail["join_plan"], "confirmed": True})
    assert rapi.post(f"/api/mapping-runs/{rid}/publish").status_code == 200
    yield cid
    with pg_engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {PUBLISH_SCHEMA}.{v}"))


@pytest.mark.db
def test_render_default_report_and_dashboard(rapi, published_client):
    assert [c["id"] for c in rapi.get("/api/connections/published").json()] == [published_client]
    rid = rapi.get("/api/reports").json()[0]["id"]
    out = rapi.post(f"/api/reports/{rid}/render", json={"connection_id": published_client, "period": {"preset": "last_month"}}).json()
    assert out["client"]["name"] == "NovaBank" and out["period"]["label"] == "Sep 2026"
    assert [b.get("error") for b in out["blocks"]] == [None] * len(out["blocks"])
    assert out["blocks"][0]["text"] == "Personal Loans MIS — NovaBank"
    did = rapi.get("/api/dashboards").json()[0]["id"]
    board = rapi.post(f"/api/dashboards/{did}/render", json={"connection_id": published_client, "period": {"preset": "last_month"}}).json()
    assert len(board["blocks"]) == 14 and all("error" not in b for b in board["blocks"])
    assert board["blocks"][0]["kpi"]["sparkline"]


@pytest.mark.db
def test_render_blocks_stores_nothing(rapi, published_client):
    before = rapi.get("/api/reports").json()
    r = rapi.post("/api/render-blocks", json={"connection_id": published_client, "period": {"preset": "last_month"},
                                              "blocks": [chart_block()]})
    assert r.status_code == 200 and r.json()["blocks"][0]["rows"]
    assert rapi.get("/api/reports").json() == before


@pytest.mark.db
def test_render_unpublished_client_is_409(rapi, pg_engine):
    with pg_engine.begin() as conn:
        for v in ("applications", "applications_base"):
            conn.execute(text(f"DROP VIEW IF EXISTS {PUBLISH_SCHEMA}.{v}"))
    cid = rapi.post("/api/connections", json=client1_body()).json()["id"]
    r = rapi.post("/api/render-blocks", json={"connection_id": cid, "period": {"preset": "last_month"}, "blocks": [chart_block()]})
    assert r.status_code == 409 and r.json()["detail"] == "NovaBank has no published views; publish its mapping first"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `../.venv/bin/pytest -q tests/api/test_reporting_api.py`
Expected: `TypeError: create_app() got an unexpected keyword argument 'today'`.

- [ ] **Step 4: Add the store models.** Append to `backend/app/store/__init__.py`, before `class Store`:

```python
class ReportTemplate(Base):
    __tablename__ = "report_template"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(default="")
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Dashboard(Base):
    __tablename__ = "dashboard"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    default_period: Mapped[dict] = mapped_column(JSON, default=lambda: {"preset": "last_month"})
    tiles: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
```

- [ ] **Step 5: Write `defaults.py`**

```python
# backend/app/reporting/defaults.py
"""Ready-made report templates and dashboards (spec §6), added when missing by name."""
from pathlib import Path

import yaml

from app.store import Dashboard, ReportTemplate


def seed_defaults(store, directory: Path) -> None:
    for path in sorted(Path(directory).glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        with store.session() as s:
            if doc["kind"] == "report" and not s.query(ReportTemplate).filter_by(name=doc["name"]).first():
                s.add(ReportTemplate(name=doc["name"], description=doc.get("description", ""), blocks=doc["blocks"]))
            elif doc["kind"] == "dashboard" and not s.query(Dashboard).filter_by(name=doc["name"]).first():
                s.add(Dashboard(name=doc["name"], default_period=doc.get("default_period", {"preset": "last_month"}),
                                tiles=doc["tiles"]))
            s.commit()
```

- [ ] **Step 6: Write the router `backend/app/api/reporting.py`**

```python
# backend/app/api/reporting.py
"""Reporting & dashboards API (spec §7)."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.connections import DecryptError, decrypt_url, mask_secrets
from app.reporting.period import PeriodError, resolve_period
from app.reporting.render import NotPublished, RenderContext, check_published, render_blocks
from app.reporting.spec import check_blocks
from app.store import Connection, Dashboard, MappingRun, Publication, ReportTemplate

router = APIRouter(prefix="/api")
TILE_TYPES = {"kpi", "chart", "table"}
WIDTHS = (3, 4, 6, 8, 12)
HEIGHTS = ("s", "m", "l")


class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    blocks: list[dict]


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_period: dict = Field(default_factory=lambda: {"preset": "last_month"})
    tiles: list[dict]


class RenderIn(BaseModel):
    connection_id: int
    period: dict


class RenderBlocksIn(RenderIn):
    blocks: list[dict]


def _state(request: Request):
    return request.app.state


def _get(s, model, id_):
    obj = s.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__tablename__} {id_} not found")
    return obj


def _report_out(t: ReportTemplate) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "blocks": t.blocks,
            "updated_at": t.updated_at.isoformat()}


def _dashboard_out(d: Dashboard) -> dict:
    return {"id": d.id, "name": d.name, "default_period": d.default_period, "tiles": d.tiles,
            "updated_at": d.updated_at.isoformat()}


def _check_report(body: ReportIn, st) -> None:
    _, errors = check_blocks(body.blocks, st.catalog, st.metrics)
    if errors:
        raise HTTPException(422, {"errors": errors})


def _check_dashboard(body: DashboardIn, st) -> None:
    errors, seen = [], set()
    for tile in body.tiles:
        tid = tile.get("id")
        msgs = []
        if not tid or tid in seen:
            msgs.append("tiles need a unique id")
        if tile.get("width") not in WIDTHS:
            msgs.append("width must be one of 3, 4, 6, 8, 12")
        if tile.get("height") not in HEIGHTS:
            msgs.append("height must be one of s, m, l")
        if not isinstance(tile.get("block"), dict):
            msgs.append("tiles need a block")
        seen.add(tid)
        if msgs:
            errors.append({"block_id": tid, "messages": msgs})
    _, block_errors = check_blocks([t["block"] for t in body.tiles if isinstance(t.get("block"), dict)],
                                   st.catalog, st.metrics, allowed_types=TILE_TYPES)
    errors += block_errors
    try:
        resolve_period(body.default_period, st.today())
    except PeriodError as exc:
        errors.append({"block_id": None, "messages": [f"default_period: {exc}"]})
    if errors:
        raise HTTPException(422, {"errors": errors})


def _save(s, obj, conflict_name: str):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, f"the name {conflict_name!r} is already used") from None
    s.refresh(obj)


# ---- metrics & published clients -------------------------------------------------------------

@router.get("/metrics")
def list_metrics(request: Request):
    return [m.model_dump(exclude={"formula"}) for m in _state(request).metrics.metrics]


@router.get("/connections/published")
def published_connections(request: Request):
    st = _state(request)
    with st.store.session() as s:
        rows = (s.query(Connection, func.max(Publication.published_at))
                .join(MappingRun, MappingRun.connection_id == Connection.id)
                .join(Publication, Publication.run_id == MappingRun.id)
                .filter(Publication.schema == st.settings.publish_schema)
                .group_by(Connection.id).order_by(Connection.name).all())
        return [{"id": c.id, "name": c.name, "dialect": c.dialect, "published_at": at.isoformat()} for c, at in rows]


# ---- report templates ---------------------------------------------------------------------------

@router.get("/reports")
def list_reports(request: Request):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _report_out(t).items() if k != "blocks"}
                for t in s.query(ReportTemplate).order_by(ReportTemplate.name)]


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, request: Request):
    st = _state(request)
    _check_report(body, st)
    with st.store.session() as s:
        t = ReportTemplate(name=body.name, description=body.description, blocks=body.blocks)
        s.add(t)
        _save(s, t, body.name)
        return _report_out(t)


@router.get("/reports/{rid}")
def get_report(rid: int, request: Request):
    with _state(request).store.session() as s:
        return _report_out(_get(s, ReportTemplate, rid))


@router.put("/reports/{rid}")
def update_report(rid: int, body: ReportIn, request: Request):
    st = _state(request)
    _check_report(body, st)
    with st.store.session() as s:
        t = _get(s, ReportTemplate, rid)
        t.name, t.description, t.blocks = body.name, body.description, body.blocks
        _save(s, t, body.name)
        return _report_out(t)


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: int, request: Request):
    with _state(request).store.session() as s:
        s.delete(_get(s, ReportTemplate, rid))
        s.commit()
    return Response(status_code=204)


# ---- dashboards ----------------------------------------------------------------------------------

@router.get("/dashboards")
def list_dashboards(request: Request):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _dashboard_out(d).items() if k != "tiles"}
                for d in s.query(Dashboard).order_by(Dashboard.name)]


@router.post("/dashboards", status_code=201)
def create_dashboard(body: DashboardIn, request: Request):
    st = _state(request)
    _check_dashboard(body, st)
    with st.store.session() as s:
        d = Dashboard(name=body.name, default_period=body.default_period, tiles=body.tiles)
        s.add(d)
        _save(s, d, body.name)
        return _dashboard_out(d)


@router.get("/dashboards/{did}")
def get_dashboard(did: int, request: Request):
    with _state(request).store.session() as s:
        return _dashboard_out(_get(s, Dashboard, did))


@router.put("/dashboards/{did}")
def update_dashboard(did: int, body: DashboardIn, request: Request):
    st = _state(request)
    _check_dashboard(body, st)
    with st.store.session() as s:
        d = _get(s, Dashboard, did)
        d.name, d.default_period, d.tiles = body.name, body.default_period, body.tiles
        _save(s, d, body.name)
        return _dashboard_out(d)


@router.delete("/dashboards/{did}", status_code=204)
def delete_dashboard(did: int, request: Request):
    with _state(request).store.session() as s:
        s.delete(_get(s, Dashboard, did))
        s.commit()
    return Response(status_code=204)


# ---- rendering -----------------------------------------------------------------------------------

def _render(request: Request, connection_id: int, period_spec: dict, blocks: list[dict]) -> dict:
    st = _state(request)
    with st.store.session() as s:
        conn = _get(s, Connection, connection_id)
        try:
            url = decrypt_url(conn.url_encrypted, st.settings.secret_key)
        except DecryptError as exc:
            raise HTTPException(409, f"{exc}; re-enter the password") from None
        name = conn.name
    try:
        period = resolve_period(period_spec, st.today())
    except PeriodError as exc:
        raise HTTPException(422, str(exc)) from None
    ctx = RenderContext(st.catalog, st.metrics, period, name, schema=st.settings.publish_schema,
                        mask=lambda m: mask_secrets(m, url))
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            c = c.execution_options(isolation_level="AUTOCOMMIT")   # one failing block can't abort the rest
            check_published(c, ctx)
            results = render_blocks(blocks, c, ctx)
    except NotPublished as exc:
        raise HTTPException(409, str(exc)) from None
    except OperationalError as exc:
        raise HTTPException(502, f"cannot reach {name}: {mask_secrets(str(exc.orig), url)}") from None
    finally:
        engine.dispose()
    return {"client": {"id": connection_id, "name": name}, "period": period.as_dict(),
            "generated_at": ctx.generated_at.isoformat(), "blocks": results}


@router.post("/reports/{rid}/render")
def render_report(rid: int, body: RenderIn, request: Request):
    with _state(request).store.session() as s:
        blocks = _get(s, ReportTemplate, rid).blocks
    return _render(request, body.connection_id, body.period, blocks)


@router.post("/dashboards/{did}/render")
def render_dashboard(did: int, body: RenderIn, request: Request):
    with _state(request).store.session() as s:
        blocks = [t["block"] for t in _get(s, Dashboard, did).tiles]
    return _render(request, body.connection_id, body.period, blocks)


@router.post("/render-blocks")
def render_unsaved(body: RenderBlocksIn, request: Request):
    return _render(request, body.connection_id, body.period, body.blocks)
```

- [ ] **Step 7: Wire it into `backend/app/api/__init__.py`.** Change the imports and `create_app`:

```python
from datetime import date
from collections.abc import Callable

from app.reporting.defaults import seed_defaults
from app.reporting.metrics import MetricError, load_metrics
```

```python
def create_app(settings: Settings, embedder: Embedder | None = None, llm: LlmMatcher | None = None,
               today: Callable[[], date] = date.today) -> FastAPI:
    # ... existing secret-key checks unchanged ...
    from app.api.reporting import router as reporting_router
    from app.api.routes import router

    app = FastAPI(title="BankReporter")
    app.state.settings = settings
    app.state.catalog = load_catalog(settings.catalog_path)
    try:
        app.state.metrics = load_metrics(settings.metrics_path, app.state.catalog)
    except MetricError as exc:
        raise RuntimeError(str(exc)) from None
    app.state.store = Store(settings.db_url)
    _fail_interrupted_runs(app.state.store)
    seed_defaults(app.state.store, settings.defaults_dir)
    app.state.today = today
    # ... existing embedder / llm lines unchanged ...
    app.include_router(router)
    app.include_router(reporting_router)
    return app
```

- [ ] **Step 8: Run the full backend suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass, with only the `llm` test skipped.

- [ ] **Step 9: Commit**

```bash
git add catalog/defaults backend/app/reporting/defaults.py backend/app/api backend/app/store/__init__.py backend/tests/api/test_reporting_api.py
git commit -m "feat(api): report templates, dashboards, defaults and render endpoints

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 8: Frontend foundations (types, period/client selectors, block rendering, navigation, print CSS)

**Files:**
- Modify: `frontend/package.json` (dependencies), `frontend/src/api.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/pages/MappingPage.tsx` (import the shared `errorText`)
- Create: `frontend/src/blocks.ts`, `frontend/src/print.css`, `frontend/src/components/PeriodSelect.tsx`, `frontend/src/components/ClientSelect.tsx`, `frontend/src/components/BlockView.tsx`, `frontend/src/test/reporting.ts` (fixtures)
- Test: `frontend/src/components/BlockView.test.tsx`, `frontend/src/components/PeriodSelect.test.tsx`

**Interfaces:**
- **Consumes:** the API shapes from Task 7.
- **Produces:**
  - Types in `api.ts`: `Val`, `Delta`, `Kpi`, `ColumnMeta`, `BlockResult`, `Rendered`, `BlockType`, `ChartType`, `Measure`, `Filter`, `QuerySpec`, `Block`, `Tile`, `PeriodSpec`, `ReportTemplate`, `ReportSummary`, `Dashboard`, `DashboardSummary`, `Metric`, `PublishedConnection`, `CatalogField`; `Catalog` gains `fields`.
  - `errorText(err: unknown): string` (moved from `MappingPage`).
  - In `blocks.ts`: `uid()`, `newBlock(type)`, `cloneBlock(b)`, `describeBlock(b)`, `BLOCK_TYPES`.
  - `PeriodSelect({value, onChange})` and `periodReady(p)`.
  - `ClientSelect({value, onChange, label?})`, which auto-selects the first published client.
  - `BlockView({result})` and `KpiCard({kpi})`.

- [ ] **Step 1: Install the dependencies**

Run from `frontend/`:
```bash
npm install --save-exact @mantine/charts@7.17.8 @mantine/dates@7.17.8 recharts@2.15.4 dayjs@1.11.13
```
Expected: they're added to `package.json` with no peer-dependency errors.

- [ ] **Step 2: Write the types, `errorText` and `blocks.ts`.** Append to `frontend/src/api.ts`:

```ts
export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.detail as { blockers?: string[]; error?: string; errors?: { block_id: string | null; messages: string[] }[] }
      | string | (string | { msg?: string })[];
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (typeof x === "string" ? x : x.msg ?? JSON.stringify(x))).join("; ");
    if (d?.blockers) return `Cannot publish: ${d.blockers.join("; ")}`;
    if (d?.errors) return d.errors.map((e) => e.messages.join("; ")).join(" · ");
    if (d?.error) return d.error;
  }
  return String(err);
}

export interface Val { raw: number | string | boolean | null; display: string }
export interface Delta { raw: number; display: string; direction: "up" | "down" | "flat"; good: boolean | null }
export interface Kpi {
  key: string; label: string; unit: string; value: Val; previous: Val; delta: Delta | null;
  sparkline?: { month: string; raw: number | null }[];
}
export interface ColumnMeta { key: string; label: string; kind: "dimension" | "measure"; unit?: string }
export type BlockType = "heading" | "text" | "kpi_row" | "kpi" | "table" | "chart" | "page_break";
export type ChartType = "bar" | "stacked_bar" | "line" | "area" | "pie";
export interface BlockResult {
  id: string; type: BlockType; error?: string; text?: string; level?: number; title?: string | null;
  items?: Kpi[]; kpi?: Kpi; columns?: ColumnMeta[]; rows?: Record<string, Val>[];
  totals?: Record<string, Val> | null; empty?: boolean; chart?: ChartType;
}
export interface Rendered {
  client: { id: number; name: string };
  period: { start: string; end: string; prev_start: string; prev_end: string; label: string };
  generated_at: string;
  blocks: BlockResult[];
}
export type Agg = "count" | "count_distinct" | "sum" | "avg" | "min" | "max";
export interface Measure { metric?: string; field?: string; agg?: Agg; label?: string | null }
export type Filter = [string, string, unknown?];
export interface QuerySpec {
  measures: Measure[]; group_by: string[]; filters: Filter[];
  sort?: { by: string; dir: "asc" | "desc" } | null; limit?: number | null;
}
export interface Block {
  id: string; type: BlockType; text?: string; level?: number; title?: string | null;
  items?: { measure: Measure; label?: string | null }[]; measure?: Measure; label?: string | null;
  filters?: Filter[]; sparkline?: boolean; query?: QuerySpec; totals?: boolean; chart?: ChartType;
}
export interface Tile { id: string; block: Block; width: 3 | 4 | 6 | 8 | 12; height: "s" | "m" | "l" }
export interface PeriodSpec { preset: string; start?: string; end?: string }
export interface ReportSummary { id: number; name: string; description: string; updated_at: string }
export interface ReportTemplate extends ReportSummary { blocks: Block[] }
export interface DashboardSummary { id: number; name: string; default_period: PeriodSpec; updated_at: string }
export interface Dashboard extends DashboardSummary { tiles: Tile[] }
export interface Metric { id: string; label: string; unit: string; better: string; group: string; description: string }
export interface PublishedConnection { id: number; name: string; dialect: string; published_at: string }
export interface CatalogField {
  id: string; label: string; section: string; kind: string; type: string; role: string;
  values: string[] | null; unit: string | null;
}
```

Also change `export interface Catalog { sections: CatalogSection[] }` to `export interface Catalog { sections: CatalogSection[]; fields: CatalogField[] }`.

In `frontend/src/pages/MappingPage.tsx`, delete the local `errorText` function and add `errorText` to its `../api` import.

```ts
// frontend/src/blocks.ts
import type { Block, BlockType } from "./api";

export const uid = (): string =>
  globalThis.crypto?.randomUUID?.() ?? `b${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;

export const BLOCK_TYPES: { value: BlockType; label: string }[] = [
  { value: "heading", label: "Heading" }, { value: "text", label: "Text" }, { value: "kpi_row", label: "KPI row" },
  { value: "table", label: "Table" }, { value: "chart", label: "Chart" }, { value: "page_break", label: "Page break" },
];

export function newBlock(type: BlockType): Block {
  const id = uid();
  switch (type) {
    case "heading": return { id, type, text: "New section", level: 2 };
    case "text": return { id, type, text: "{{client_name}} · {{period}}" };
    case "kpi_row": return { id, type, filters: [],
      items: [{ measure: { metric: "applications" } }, { measure: { metric: "approval_rate" } }] };
    case "kpi": return { id, type, measure: { metric: "applications" }, filters: [], sparkline: true };
    case "table": return { id, type, title: "New table", totals: false,
      query: { measures: [{ metric: "applications" }], group_by: ["channel"], filters: [] } };
    case "chart": return { id, type, title: "New chart", chart: "bar",
      query: { measures: [{ metric: "applications" }], group_by: ["application_month"], filters: [] } };
    case "page_break": return { id, type };
  }
}

export const cloneBlock = (b: Block): Block => ({ ...structuredClone(b), id: uid() });

export function describeBlock(b: Block): string {
  switch (b.type) {
    case "heading": return `Heading: ${b.text ?? ""}`;
    case "text": return `Text: ${(b.text ?? "").slice(0, 40)}`;
    case "kpi_row": return `KPI row (${b.items?.length ?? 0})`;
    case "kpi": return `KPI: ${b.label || b.measure?.metric || b.measure?.field || ""}`;
    case "table": return `Table: ${b.title || "untitled"}`;
    case "chart": return `Chart (${b.chart}): ${b.title || "untitled"}`;
    case "page_break": return "Page break";
  }
}
```

- [ ] **Step 3: Write the test fixtures and failing tests**

```ts
// frontend/src/test/reporting.ts
import type { BlockResult, CatalogField, Kpi, Metric } from "../api";

export const kpi = (over: Partial<Kpi> = {}): Kpi => ({
  key: "approval_rate", label: "Approval rate", unit: "pct",
  value: { raw: 61.2, display: "61.2%" }, previous: { raw: 59.1, display: "59.1%" },
  delta: { raw: 2.1, display: "+2.1 pts", direction: "up", good: true }, ...over,
});

export const FIELDS: CatalogField[] = [
  { id: "channel", label: "Sourcing Channel", section: "application", kind: "raw", type: "enum", role: "dimension",
    values: ["BRANCH", "DSA", "WEB"], unit: null },
  { id: "application_month", label: "Application Month", section: "application", kind: "calculated", type: "date",
    role: "dimension", values: null, unit: null },
  { id: "disbursed_amount", label: "Disbursed Amount", section: "disbursement", kind: "raw", type: "decimal",
    role: "measure", values: null, unit: "INR" },
  { id: "cibil_score", label: "CIBIL Score", section: "bureau", kind: "raw", type: "integer", role: "measure",
    values: null, unit: null },
];

export const METRICS: Metric[] = [
  { id: "applications", label: "Applications", unit: "count", better: "higher", group: "volume", description: "" },
  { id: "approval_rate", label: "Approval rate", unit: "pct", better: "higher", group: "rates", description: "" },
];

/** A render-blocks mock: echoes each requested block back as a heading result. */
export const echoRender = (_url: string, init?: RequestInit) => {
  const { blocks } = JSON.parse(String(init!.body)) as { blocks: { id: string }[] };
  return {
    client: { id: 7, name: "NovaBank" },
    period: { start: "2026-09-01", end: "2026-09-30", prev_start: "2026-08-01", prev_end: "2026-08-31", label: "Sep 2026" },
    generated_at: "2026-10-22T18:05:00",
    blocks: blocks.map((b): BlockResult => ({ id: b.id, type: "heading", text: `rendered ${b.id}`, level: 2 })),
  };
};
```

```tsx
// frontend/src/components/BlockView.test.tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BlockView } from "./BlockView";
import { renderWithProviders } from "../test/render";
import { kpi } from "../test/reporting";

const goodOf = (text: RegExp) => screen.getByText(text).closest("[data-good]")?.getAttribute("data-good");

describe("BlockView", () => {
  it("colours KPI deltas by whether the change is good", () => {
    renderWithProviders(<>
      <BlockView result={{ id: "a", type: "kpi", kpi: kpi() }} />
      <BlockView result={{ id: "b", type: "kpi", kpi: kpi({ key: "tat", label: "TAT",
        delta: { raw: 5, display: "+5.0%", direction: "up", good: false } }) }} />
      <BlockView result={{ id: "c", type: "kpi", kpi: kpi({ key: "x", label: "Ticket",
        delta: { raw: 1, display: "+1.0%", direction: "up", good: null } }) }} />
    </>);
    expect(goodOf(/\+2\.1 pts/)).toBe("true");
    expect(goodOf(/\+5\.0%/)).toBe("false");
    expect(goodOf(/\+1\.0%/)).toBe("null");
    expect(screen.getByText("61.2%")).toBeInTheDocument();
    expect(screen.getAllByText(/prev 59\.1%/)).toHaveLength(3);
  });

  it("shows a failed block's error while its sibling still renders", () => {
    renderWithProviders(<>
      <BlockView result={{ id: "a", type: "chart", error: "invalid block: measure 1: unknown metric 'gone'" }} />
      <BlockView result={{ id: "b", type: "heading", text: "Turnaround", level: 2 }} />
    </>);
    expect(screen.getByText("invalid block: measure 1: unknown metric 'gone'")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Turnaround" })).toBeInTheDocument();
  });

  it("renders tables with totals, and empty results", () => {
    const columns = [{ key: "channel", label: "Channel", kind: "dimension" as const },
                     { key: "applications", label: "Applications", kind: "measure" as const, unit: "count" }];
    renderWithProviders(<>
      <BlockView result={{ id: "t", type: "table", title: "By channel", columns, empty: false,
        rows: [{ channel: { raw: "WEB", display: "WEB" }, applications: { raw: 12, display: "12" } }],
        totals: { applications: { raw: 12, display: "12" } } }} />
      <BlockView result={{ id: "e", type: "chart", chart: "bar", columns, rows: [], empty: true }} />
    </>);
    expect(screen.getByText("By channel")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("No applications in this period")).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/components/PeriodSelect.test.tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { PeriodSpec } from "../api";
import { PeriodSelect, periodReady } from "./PeriodSelect";
import { renderWithProviders } from "../test/render";

function Harness({ onChange }: { onChange: (p: PeriodSpec) => void }) {
  const [value, setValue] = useState<PeriodSpec>({ preset: "last_month" });
  return <PeriodSelect value={value} onChange={(p) => { setValue(p); onChange(p); }} />;
}

describe("PeriodSelect", () => {
  it("switches to a custom range and shows date pickers", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness onChange={onChange} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Period"));
    await user.click(await screen.findByRole("option", { name: "Custom range" }));
    expect(onChange).toHaveBeenLastCalledWith({ preset: "custom", start: undefined, end: undefined });
    expect(screen.getByText("Dates")).toBeInTheDocument();
  });

  it("knows when a period is complete", () => {
    expect(periodReady({ preset: "ytd" })).toBe(true);
    expect(periodReady({ preset: "custom", start: "2026-01-01" })).toBe(false);
    expect(periodReady({ preset: "custom", start: "2026-01-01", end: "2026-01-31" })).toBe(true);
  });
});
```

- [ ] **Step 4: Run them to verify they fail**

Run: `npx vitest run src/components`
Expected: import errors for `./BlockView` and `./PeriodSelect`.

- [ ] **Step 5: Write the components**

```tsx
// frontend/src/components/PeriodSelect.tsx
import { Group, Select } from "@mantine/core";
import { DatePickerInput, type DatesRangeValue } from "@mantine/dates";
import dayjs from "dayjs";
import type { PeriodSpec } from "../api";

const PRESETS = [
  { value: "this_month", label: "This month" }, { value: "last_month", label: "Last month" },
  { value: "this_quarter", label: "This quarter" }, { value: "last_quarter", label: "Last quarter" },
  { value: "ytd", label: "Year to date" }, { value: "last_12_months", label: "Last 12 months" },
  { value: "custom", label: "Custom range" },
];

export const periodReady = (p: PeriodSpec | null): boolean =>
  !!p && (p.preset !== "custom" || (!!p.start && !!p.end));

const toDate = (s?: string) => (s ? dayjs(s).toDate() : null);
const toIso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : undefined);

export function PeriodSelect({ value, onChange }: { value: PeriodSpec; onChange: (p: PeriodSpec) => void }) {
  return (
    <Group gap="xs" align="flex-end">
      <Select label="Period" w={170} data={PRESETS} value={value.preset} allowDeselect={false}
        onChange={(p) => onChange(p === "custom" ? { preset: "custom", start: value.start, end: value.end } : { preset: p! })} />
      {value.preset === "custom" && (
        <DatePickerInput type="range" label="Dates" w={260} placeholder="Pick dates"
          value={[toDate(value.start), toDate(value.end)]}
          onChange={([s, e]: DatesRangeValue) => onChange({ preset: "custom", start: toIso(s), end: toIso(e) })} />
      )}
    </Group>
  );
}
```

```tsx
// frontend/src/components/ClientSelect.tsx
import { Alert, Anchor, Select } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api, type PublishedConnection } from "../api";

export function ClientSelect({ value, onChange, label = "Client" }: {
  value: number | null; onChange: (id: number | null) => void; label?: string;
}) {
  const clients = useQuery({ queryKey: ["published"], queryFn: () => api<PublishedConnection[]>("/connections/published") });
  useEffect(() => {
    if (value === null && clients.data?.length) onChange(clients.data[0].id);
  }, [clients.data, value, onChange]);
  if (clients.data && clients.data.length === 0) {
    return (
      <Alert color="yellow" title="No published clients">
        Map a connection and publish its views first. <Anchor component={Link} to="/">Go to Connections</Anchor>
      </Alert>
    );
  }
  return (
    <Select label={label} w={220} placeholder="Choose client" allowDeselect={false}
      data={(clients.data ?? []).map((c) => ({ value: String(c.id), label: c.name }))}
      value={value === null ? null : String(value)} onChange={(v) => onChange(v ? Number(v) : null)} />
  );
}
```

```tsx
// frontend/src/components/BlockView.tsx
import { Alert, Badge, Card, Divider, Group, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { AreaChart, BarChart, LineChart, PieChart, Sparkline } from "@mantine/charts";
import type { BlockResult, Delta, Kpi } from "../api";

const PALETTE = ["blue.6", "teal.6", "orange.6", "grape.6", "red.6", "cyan.6", "lime.6", "pink.6", "indigo.6", "yellow.6"];
const deltaColor = (d: Delta) => (d.good === null ? "gray" : d.good ? "teal" : "red");
const arrow = { up: "▲", down: "▼", flat: "■" } as const;
const indian = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function Empty() {
  return <Text c="dimmed" size="sm" py="md" ta="center">No applications in this period</Text>;
}

export function KpiCard({ kpi }: { kpi: Kpi }) {
  return (
    <Card withBorder padding="sm" h="100%">
      <Text size="xs" c="dimmed">{kpi.label}</Text>
      <Text fw={700} fz={26}>{kpi.value.display}</Text>
      <Group gap="xs">
        {kpi.delta && (
          <Badge variant="light" color={deltaColor(kpi.delta)} data-good={String(kpi.delta.good)}>
            {arrow[kpi.delta.direction]} {kpi.delta.display}
          </Badge>
        )}
        <Text size="xs" c="dimmed">prev {kpi.previous.display}</Text>
      </Group>
      {kpi.sparkline && kpi.sparkline.length > 1 && (
        <Sparkline mt="xs" h={36} data={kpi.sparkline.map((p) => p.raw ?? 0)} curveType="linear" color="blue" />
      )}
    </Card>
  );
}

function TableView({ result }: { result: BlockResult }) {
  const cols = result.columns ?? [];
  return (
    <Stack gap={4}>
      {result.title && <Text fw={600}>{result.title}</Text>}
      {result.empty ? <Empty /> : (
        <Table striped withTableBorder fz="sm">
          <Table.Thead><Table.Tr>
            {cols.map((c) => <Table.Th key={c.key} ta={c.kind === "measure" ? "right" : undefined}>{c.label}</Table.Th>)}
          </Table.Tr></Table.Thead>
          <Table.Tbody>
            {(result.rows ?? []).map((r, i) => (
              <Table.Tr key={i}>
                {cols.map((c) => <Table.Td key={c.key} ta={c.kind === "measure" ? "right" : undefined}>{r[c.key]?.display}</Table.Td>)}
              </Table.Tr>
            ))}
            {result.totals && (
              <Table.Tr fw={700}>
                {cols.map((c, i) => (
                  <Table.Td key={c.key} ta={c.kind === "measure" ? "right" : undefined}>
                    {c.kind === "measure" ? result.totals![c.key]?.display : i === 0 ? "Total" : ""}
                  </Table.Td>
                ))}
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function ChartView({ result }: { result: BlockResult }) {
  const cols = result.columns ?? [];
  const dims = cols.filter((c) => c.kind === "dimension");
  const measures = cols.filter((c) => c.kind === "measure");
  const rows = result.rows ?? [];
  const num = (v: unknown) => (typeof v === "number" ? v : v === null || v === undefined ? 0 : Number(v));
  let chart = null;
  if (result.chart === "pie") {
    const data = rows.map((r, i) => ({ name: r[dims[0].key].display, value: num(r[measures[0].key].raw),
                                       color: PALETTE[i % PALETTE.length] }));
    chart = <PieChart h={260} data={data} withLabels withTooltip labelsType="percent" />;
  } else {
    let data: Record<string, string | number>[];
    let series: { name: string; label?: string; color: string }[];
    if (dims.length === 2) {   // pivot: x = first dimension, one series per second-dimension value
      const names = [...new Set(rows.map((r) => r[dims[1].key].display))];
      const byX = new Map<string, Record<string, string | number>>();
      for (const r of rows) {
        const x = r[dims[0].key].display;
        const point = byX.get(x) ?? { x };
        point[r[dims[1].key].display] = num(r[measures[0].key].raw);
        byX.set(x, point);
      }
      data = [...byX.values()];
      series = names.map((n, i) => ({ name: n, color: PALETTE[i % PALETTE.length] }));
    } else {
      data = rows.map((r) => ({ x: r[dims[0].key].display,
        ...Object.fromEntries(measures.map((m) => [m.key, num(r[m.key].raw)])) }));
      series = measures.map((m, i) => ({ name: m.key, label: m.label, color: PALETTE[i % PALETTE.length] }));
    }
    const common = { h: 260, data, dataKey: "x", series, valueFormatter: (v: number) => indian.format(v), withLegend: series.length > 1 };
    chart = result.chart === "line" ? <LineChart {...common} curveType="linear" />
      : result.chart === "area" ? <AreaChart {...common} curveType="linear" />
      : <BarChart {...common} type={result.chart === "stacked_bar" ? "stacked" : "default"} />;
  }
  return (
    <Stack gap={4}>
      {result.title && <Text fw={600}>{result.title}</Text>}
      {result.empty ? <Empty /> : chart}
    </Stack>
  );
}

export function BlockView({ result }: { result: BlockResult }) {
  if (result.error) {
    return <Alert color="red" title="This block could not be rendered">{result.error}</Alert>;
  }
  switch (result.type) {
    case "heading":
      return <Title order={((result.level ?? 1) + 1) as 2 | 3 | 4}>{result.text}</Title>;
    case "text":
      return <Text style={{ whiteSpace: "pre-wrap" }}>{result.text}</Text>;
    case "kpi_row":
      return (
        <Stack gap={4}>
          {result.title && <Text fw={600}>{result.title}</Text>}
          <SimpleGrid cols={{ base: 1, sm: Math.min(result.items?.length ?? 1, 3), md: result.items?.length ?? 1 }}>
            {(result.items ?? []).map((k) => <KpiCard key={k.key} kpi={k} />)}
          </SimpleGrid>
        </Stack>
      );
    case "kpi":
      return result.kpi ? <KpiCard kpi={result.kpi} /> : null;
    case "table":
      return <TableView result={result} />;
    case "chart":
      return <ChartView result={result} />;
    case "page_break":
      return <div className="page-break"><Divider className="screen-only" label="Page break" labelPosition="center" /></div>;
  }
}
```

```css
/* frontend/src/print.css */
.report-paper { max-width: 210mm; margin: 0 auto; padding: 14mm; background: var(--mantine-color-body);
                border: 1px solid var(--mantine-color-gray-3); }
.report-block { margin-bottom: 18px; }

@media print {
  @page { size: A4; margin: 15mm; }
  .no-print { display: none !important; }
  .mantine-AppShell-main { padding: 0 !important; }
  .report-paper { border: none; padding: 0; max-width: none; }
  .report-block { break-inside: avoid; }
  .page-break { break-before: page; }
  .screen-only { display: none !important; }
  .recharts-responsive-container { width: 170mm !important; }
}
```

- [ ] **Step 6: Wire up `main.tsx` and `App.tsx`.** In `frontend/src/main.tsx`, after `import "@mantine/core/styles.css";`, add:

```ts
import "@mantine/charts/styles.css";
import "@mantine/dates/styles.css";
import "./print.css";
```

Replace `frontend/src/App.tsx` with:

```tsx
import { AppShell, Group, NavLink as MantineNavLink, Title } from "@mantine/core";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { DashboardsPage } from "./pages/DashboardsPage";
import { MappingPage } from "./pages/MappingPage";
import { ReportEditorPage } from "./pages/ReportEditorPage";
import { ReportsPage } from "./pages/ReportsPage";

const NAV = [{ to: "/", label: "Connections", end: true }, { to: "/reports", label: "Reports" }, { to: "/dashboards", label: "Dashboards" }];

export function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header className="no-print">
        <Group h="100%" px="md" gap="lg">
          <Title order={3}><Link to="/" style={{ color: "inherit", textDecoration: "none" }}>BankReporter</Link></Title>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} style={{ textDecoration: "none" }}>
              {({ isActive }) => <MantineNavLink component="span" label={n.label} active={isActive} w="auto" />}
            </NavLink>
          ))}
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<ConnectionsPage />} />
          <Route path="/connections/:id/mapping" element={<MappingPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/new" element={<ReportEditorPage />} />
          <Route path="/reports/:id/edit" element={<ReportEditorPage />} />
          <Route path="/dashboards" element={<DashboardsPage />} />
          <Route path="/dashboards/:id" element={<DashboardsPage />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  );
}
```

Create placeholder pages so the app compiles until Tasks 10–11 replace them, each file containing only its export: `export function ReportsPage() { return null; }`, `export function ReportEditorPage() { return null; }` and `export function DashboardsPage() { return null; }`, in their own files under `src/pages/`.

- [ ] **Step 7: Run the tests and the typecheck**

Run: `npx vitest run && npx tsc -b --noEmit`
Expected: all tests pass, including the earlier Connections and Mapping suites, and there are no type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat(frontend): reporting types, period/client selectors, block rendering, navigation, print styles

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Block settings editor

**Files:**
- Create: `frontend/src/components/BlockSettings.tsx`
- Test: `frontend/src/components/BlockSettings.test.tsx`

**Interfaces:**
- **Consumes:** the `Block`, `Measure`, `Filter`, `CatalogField` and `Metric` types (Task 8).
- **Produces:** `BlockSettings({block, onChange, fields, metrics})`, a controlled form that always calls `onChange` with a complete `Block`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/BlockSettings.test.tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Block } from "../api";
import { BlockSettings } from "./BlockSettings";
import { renderWithProviders } from "../test/render";
import { FIELDS, METRICS } from "../test/reporting";

function Harness({ initial, onChange }: { initial: Block; onChange: (b: Block) => void }) {
  const [block, setBlock] = useState(initial);
  return <BlockSettings block={block} fields={FIELDS} metrics={METRICS}
    onChange={(b) => { setBlock(b); onChange(b); }} />;
}

const chart: Block = { id: "c", type: "chart", chart: "line", title: "T",
  query: { measures: [{ metric: "applications" }], group_by: ["application_month"], filters: [] } };

describe("BlockSettings", () => {
  it("changes the chart type and adds a typed filter", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness initial={chart} onChange={onChange} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Chart type"));
    await user.click(await screen.findByRole("option", { name: "Bar" }));
    expect(onChange.mock.lastCall![0].chart).toBe("bar");
    await user.click(screen.getByRole("button", { name: "Add filter" }));
    expect(onChange.mock.lastCall![0].query.filters).toEqual([["channel", "eq", "BRANCH"]]);
    await user.click(screen.getByLabelText("Filter 1 operator"));
    await user.click(await screen.findByRole("option", { name: "is one of" }));
    expect(onChange.mock.lastCall![0].query.filters).toEqual([["channel", "in", ["BRANCH"]]]);
  });

  it("switches a measure to a field aggregate", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness initial={chart} onChange={onChange} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Measure 1"));
    await user.click(await screen.findByRole("option", { name: "Field aggregate…" }));
    expect(onChange.mock.lastCall![0].query.measures).toEqual([{ field: "disbursed_amount", agg: "sum" }]);
  });

  it("adds and removes KPI items, capped at 6", async () => {
    const onChange = vi.fn();
    const row: Block = { id: "k", type: "kpi_row", filters: [], items: [{ measure: { metric: "applications" } }] };
    renderWithProviders(<Harness initial={row} onChange={onChange} />);
    const user = userEvent.setup();
    for (let i = 0; i < 6; i++) await user.click(screen.getByRole("button", { name: "Add KPI" }));
    expect(onChange.mock.lastCall![0].items).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Add KPI" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Remove KPI 1" }));
    expect(onChange.mock.lastCall![0].items).toHaveLength(5);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/components/BlockSettings.test.tsx`
Expected: `Failed to resolve import "./BlockSettings"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/BlockSettings.tsx
import {
  ActionIcon, Button, Group, MultiSelect, NumberInput, Select, Stack, Switch, TagsInput, Text, TextInput, Textarea,
} from "@mantine/core";
import type { Agg, Block, CatalogField, ChartType, Filter, Measure, Metric, QuerySpec } from "../api";

const GROUPS: [string, string][] = [["volume", "Volume"], ["rates", "Rates"], ["amounts", "Amounts"],
                                    ["credit", "Credit"], ["turnaround", "Turnaround"]];
const AGG_LABELS: Record<Agg, string> = { count: "Count", count_distinct: "Count distinct", sum: "Sum",
                                          avg: "Average", min: "Minimum", max: "Maximum" };
const CHARTS: { value: ChartType; label: string }[] = [
  { value: "bar", label: "Bar" }, { value: "stacked_bar", label: "Stacked bar" }, { value: "line", label: "Line" },
  { value: "area", label: "Area" }, { value: "pie", label: "Pie" },
];
const OPS = [
  { value: "eq", label: "=" }, { value: "ne", label: "≠" }, { value: "in", label: "is one of" },
  { value: "not_in", label: "is not one of" }, { value: "gt", label: ">" }, { value: "gte", label: "≥" },
  { value: "lt", label: "<" }, { value: "lte", label: "≤" }, { value: "is_null", label: "is empty" },
  { value: "not_null", label: "is not empty" },
];
const LIST_OPS = new Set(["in", "not_in"]);
const NULL_OPS = new Set(["is_null", "not_null"]);

interface Common { fields: CatalogField[]; metrics: Metric[] }

function defaultValue(f: CatalogField | undefined): unknown {
  if (!f) return "";
  if (f.type === "enum") return f.values?.[0] ?? "";
  if (f.type === "boolean") return true;
  if (f.type === "integer" || f.type === "decimal") return 0;
  return "";
}

function MeasurePicker({ value, onChange, fields, metrics, label }: Common & {
  value: Measure; onChange: (m: Measure) => void; label: string;
}) {
  const data = [
    ...GROUPS.map(([g, name]) => ({ group: name, items: metrics.filter((m) => m.group === g)
      .map((m) => ({ value: `m:${m.id}`, label: m.label })) })).filter((g) => g.items.length > 0),
    { group: "Other", items: [{ value: "field", label: "Field aggregate…" }] },
  ];
  const field = fields.find((f) => f.id === value.field);
  const aggs: Agg[] = field?.role === "measure" ? ["sum", "avg", "min", "max", "count", "count_distinct"] : ["count", "count_distinct"];
  return (
    <Stack gap={4}>
      <Select label={label} data={data} searchable allowDeselect={false}
        value={value.metric ? `m:${value.metric}` : "field"}
        onChange={(v) => onChange(v === "field"
          ? { field: fields.find((f) => f.role === "measure")?.id ?? fields[0].id, agg: "sum" }
          : { metric: v!.slice(2) })} />
      {!value.metric && (
        <Group grow>
          <Select label="Field" searchable allowDeselect={false} value={value.field ?? null}
            data={fields.map((f) => ({ value: f.id, label: f.label }))}
            onChange={(v) => {
              const f = fields.find((x) => x.id === v)!;
              onChange({ field: f.id, agg: f.role === "measure" ? (value.agg ?? "sum") : "count" });
            }} />
          <Select label="Aggregate" allowDeselect={false} value={value.agg ?? null}
            data={aggs.map((a) => ({ value: a, label: AGG_LABELS[a] }))}
            onChange={(v) => onChange({ ...value, agg: v as Agg })} />
        </Group>
      )}
    </Stack>
  );
}

function ValueInput({ field, op, value, onChange, index }: {
  field: CatalogField | undefined; op: string; value: unknown; onChange: (v: unknown) => void; index: number;
}) {
  const label = `Filter ${index} value`;
  if (!field || NULL_OPS.has(op)) return null;
  const list = LIST_OPS.has(op);
  if (field.type === "enum") {
    const data = field.values ?? [];
    return list
      ? <MultiSelect aria-label={label} data={data} value={(value as string[]) ?? []} onChange={onChange} />
      : <Select aria-label={label} data={data} value={(value as string) ?? null} allowDeselect={false} onChange={onChange} />;
  }
  if (field.type === "boolean") {
    return <Select aria-label={label} allowDeselect={false} data={[{ value: "true", label: "Yes" }, { value: "false", label: "No" }]}
      value={String(value ?? true)} onChange={(v) => onChange(v === "true")} />;
  }
  if (field.type === "integer" || field.type === "decimal") {
    return list
      ? <TagsInput aria-label={label} value={((value as number[]) ?? []).map(String)}
          onChange={(vs) => onChange(vs.map(Number).filter((n) => !Number.isNaN(n)))} />
      : <NumberInput aria-label={label} value={(value as number) ?? 0}
          onChange={(n) => onChange(typeof n === "number" ? n : Number(n))} />;
  }
  return list
    ? <TagsInput aria-label={label} value={(value as string[]) ?? []} onChange={onChange} />
    : <TextInput aria-label={label} value={(value as string) ?? ""} placeholder={field.type === "date" ? "YYYY-MM-DD" : undefined}
        onChange={(e) => onChange(e.currentTarget.value)} />;
}

function FiltersEditor({ filters, onChange, fields }: { filters: Filter[]; onChange: (f: Filter[]) => void; fields: CatalogField[] }) {
  const update = (i: number, f: Filter) => onChange(filters.map((x, j) => (j === i ? f : x)));
  const first = fields.find((f) => f.id === "channel") ?? fields[0];
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>Filters</Text>
      {filters.map(([fieldId, op, value], i) => {
        const field = fields.find((f) => f.id === fieldId);
        return (
          <Group key={i} gap="xs" align="flex-end" wrap="nowrap">
            <Select aria-label={`Filter ${i + 1} field`} searchable allowDeselect={false} w={150} value={fieldId}
              data={fields.map((f) => ({ value: f.id, label: f.label }))}
              onChange={(v) => { const f = fields.find((x) => x.id === v); update(i, [v!, "eq", defaultValue(f)]); }} />
            <Select aria-label={`Filter ${i + 1} operator`} allowDeselect={false} w={120} data={OPS} value={op}
              onChange={(next) => {
                const o = next!;
                if (NULL_OPS.has(o)) return update(i, [fieldId, o]);
                const v = LIST_OPS.has(o) ? (Array.isArray(value) ? value : [value ?? defaultValue(field)])
                                          : (Array.isArray(value) ? value[0] : value ?? defaultValue(field));
                update(i, [fieldId, o, v]);
              }} />
            <ValueInput field={field} op={op} value={value} index={i + 1} onChange={(v) => update(i, [fieldId, op, v])} />
            <ActionIcon variant="subtle" color="red" aria-label={`Remove filter ${i + 1}`}
              onClick={() => onChange(filters.filter((_, j) => j !== i))}>✕</ActionIcon>
          </Group>
        );
      })}
      <Button size="xs" variant="light" w="fit-content"
        onClick={() => onChange([...filters, [first.id, "eq", defaultValue(first)]])}>Add filter</Button>
    </Stack>
  );
}

function QueryEditor({ query, onChange, fields, metrics, chart }: Common & {
  query: QuerySpec; onChange: (q: QuerySpec) => void; chart?: ChartType;
}) {
  const set = (patch: Partial<QuerySpec>) => onChange({ ...query, ...patch });
  const keys = [...query.measures.map((m) => m.metric ?? `${m.agg}_${m.field}`), ...query.group_by];
  const dims = fields.filter((f) => f.role === "dimension");
  return (
    <Stack gap="sm">
      {query.measures.map((m, i) => (
        <Group key={i} align="flex-end" wrap="nowrap" gap="xs">
          <div style={{ flex: 1 }}>
            <MeasurePicker label={`Measure ${i + 1}`} value={m} fields={fields} metrics={metrics}
              onChange={(nm) => set({ measures: query.measures.map((x, j) => (j === i ? nm : x)) })} />
          </div>
          {query.measures.length > 1 && (
            <ActionIcon variant="subtle" color="red" aria-label={`Remove measure ${i + 1}`}
              onClick={() => set({ measures: query.measures.filter((_, j) => j !== i) })}>✕</ActionIcon>
          )}
        </Group>
      ))}
      <Button size="xs" variant="light" w="fit-content" disabled={query.measures.length >= 4 || chart === "pie"}
        onClick={() => set({ measures: [...query.measures, { metric: metrics[0].id }] })}>Add measure</Button>
      <MultiSelect label="Group by" maxValues={2} searchable value={query.group_by}
        data={dims.map((f) => ({ value: f.id, label: f.label }))} onChange={(v) => set({ group_by: v })} />
      <FiltersEditor filters={query.filters} fields={fields} onChange={(f) => set({ filters: f })} />
      <Group grow>
        <Select label="Sort by" clearable value={query.sort?.by ?? null} data={keys}
          onChange={(v) => set({ sort: v ? { by: v, dir: query.sort?.dir ?? "desc" } : null })} />
        <Select label="Direction" allowDeselect={false} disabled={!query.sort} value={query.sort?.dir ?? "desc"}
          data={[{ value: "desc", label: "Descending" }, { value: "asc", label: "Ascending" }]}
          onChange={(v) => query.sort && set({ sort: { ...query.sort, dir: v as "asc" | "desc" } })} />
        <NumberInput label="Limit" min={1} max={500} value={query.limit ?? ""}
          onChange={(n) => set({ limit: typeof n === "number" ? n : null })} />
      </Group>
    </Stack>
  );
}

export function BlockSettings({ block, onChange, fields, metrics }: Common & { block: Block; onChange: (b: Block) => void }) {
  const set = (patch: Partial<Block>) => onChange({ ...block, ...patch });
  switch (block.type) {
    case "heading":
      return (
        <Stack>
          <TextInput label="Text" value={block.text ?? ""} onChange={(e) => set({ text: e.currentTarget.value })} />
          <Select label="Level" allowDeselect={false} data={["1", "2", "3"]} value={String(block.level ?? 1)}
            onChange={(v) => set({ level: Number(v) })} />
        </Stack>
      );
    case "text":
      return (
        <Textarea label="Text" autosize minRows={4} value={block.text ?? ""}
          description="Placeholders: {{client_name}} {{period}} {{period_start}} {{period_end}} {{generated_at}} {{metric:approval_rate}}"
          onChange={(e) => set({ text: e.currentTarget.value })} />
      );
    case "kpi_row": {
      const items = block.items ?? [];
      return (
        <Stack>
          <TextInput label="Title" value={block.title ?? ""} onChange={(e) => set({ title: e.currentTarget.value || null })} />
          {items.map((it, i) => (
            <Group key={i} align="flex-end" wrap="nowrap" gap="xs">
              <div style={{ flex: 1 }}>
                <MeasurePicker label={`KPI ${i + 1}`} value={it.measure} fields={fields} metrics={metrics}
                  onChange={(m) => set({ items: items.map((x, j) => (j === i ? { ...x, measure: m } : x)) })} />
              </div>
              <ActionIcon variant="subtle" color="red" aria-label={`Remove KPI ${i + 1}`} disabled={items.length === 1}
                onClick={() => set({ items: items.filter((_, j) => j !== i) })}>✕</ActionIcon>
            </Group>
          ))}
          <Button size="xs" variant="light" w="fit-content" disabled={items.length >= 6}
            onClick={() => set({ items: [...items, { measure: { metric: metrics[0].id } }] })}>Add KPI</Button>
          <FiltersEditor filters={block.filters ?? []} fields={fields} onChange={(f) => set({ filters: f })} />
        </Stack>
      );
    }
    case "kpi":
      return (
        <Stack>
          <MeasurePicker label="Measure" value={block.measure ?? { metric: metrics[0].id }} fields={fields} metrics={metrics}
            onChange={(m) => set({ measure: m })} />
          <TextInput label="Label" placeholder="Default label" value={block.label ?? ""}
            onChange={(e) => set({ label: e.currentTarget.value || null })} />
          <Switch label="Show 6-month sparkline" checked={block.sparkline ?? true}
            onChange={(e) => set({ sparkline: e.currentTarget.checked })} />
          <FiltersEditor filters={block.filters ?? []} fields={fields} onChange={(f) => set({ filters: f })} />
        </Stack>
      );
    case "table":
    case "chart":
      return (
        <Stack>
          <TextInput label="Title" value={block.title ?? ""} onChange={(e) => set({ title: e.currentTarget.value || null })} />
          {block.type === "chart" && (
            <Select label="Chart type" allowDeselect={false} data={CHARTS} value={block.chart ?? "bar"}
              onChange={(v) => set({ chart: v as ChartType })} />
          )}
          {block.type === "table" && (
            <Switch label="Totals row" checked={block.totals ?? false} onChange={(e) => set({ totals: e.currentTarget.checked })} />
          )}
          <QueryEditor query={block.query!} fields={fields} metrics={metrics} chart={block.chart}
            onChange={(q) => set({ query: q })} />
        </Stack>
      );
    case "page_break":
      return <Text c="dimmed" size="sm">Starts a new page when the report is printed.</Text>;
  }
}
```

- [ ] **Step 4: Run the tests and the typecheck**

Run: `npx vitest run && npx tsc -b --noEmit`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BlockSettings.tsx frontend/src/components/BlockSettings.test.tsx
git commit -m "feat(frontend): block settings editor (measures, group-by, typed filters, chart options)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Reports pages (viewer and editor)

**Files:**
- Replace: `frontend/src/pages/ReportsPage.tsx`, `frontend/src/pages/ReportEditorPage.tsx`
- Test: `frontend/src/pages/ReportsPage.test.tsx`, `frontend/src/pages/ReportEditorPage.test.tsx`

**Interfaces:**
- **Consumes:** Tasks 8 and 9; the API endpoints `/reports`, `/reports/{id}`, `/reports/{id}/render`, `/render-blocks`, `/metrics`, `/catalog` and `/connections/published`.
- **Produces:** routes `/reports`, `/reports/new` and `/reports/:id/edit`.

**Note on unsaved changes:** the app uses `BrowserRouter`, where React Router's `useBlocker` isn't available. So "Discard changes?" guards the editor's own **Back to reports** button, not browser navigation. This is a deliberate simplification of spec §8.2.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/pages/ReportsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReportsPage } from "./ReportsPage";
import { mockApi, renderWithProviders } from "../test/render";

const rendered = {
  client: { id: 7, name: "NovaBank" },
  period: { start: "2026-09-01", end: "2026-09-30", prev_start: "2026-08-01", prev_end: "2026-08-31", label: "Sep 2026" },
  generated_at: "2026-10-22T18:05:00",
  blocks: [{ id: "h1", type: "heading", text: "Personal Loans MIS — NovaBank", level: 1 },
           { id: "bad", type: "chart", error: "invalid block: measure 1: unknown metric 'gone'" }],
};

describe("ReportsPage", () => {
  it("renders the first template for the first client and prints to PDF", async () => {
    const calls = mockApi({
      "GET /api/reports": [{ id: 1, name: "Monthly Lending MIS", description: "", updated_at: "" }],
      "GET /api/connections/published": [{ id: 7, name: "NovaBank", dialect: "postgresql", published_at: "" }],
      "POST /api/reports/1/render": rendered,
    });
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<ReportsPage />, { route: "/reports", path: "/reports" });
    expect(await screen.findByText("Personal Loans MIS — NovaBank")).toBeInTheDocument();
    expect(screen.getByText("invalid block: measure 1: unknown metric 'gone'")).toBeInTheDocument();
    expect(screen.getByText(/Sep 2026/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ connection_id: 7, period: { preset: "last_month" } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Download PDF" }));
    expect(print).toHaveBeenCalled();
  });

  it("deletes a template only after an in-page confirmation", async () => {
    const calls = mockApi({
      "GET /api/reports": [{ id: 1, name: "Mine", description: "", updated_at: "" }],
      "GET /api/connections/published": [],
      "DELETE /api/reports/1": undefined,
    });
    renderWithProviders(<ReportsPage />, { route: "/reports", path: "/reports" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete template" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
```

```tsx
// frontend/src/pages/ReportEditorPage.test.tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReportEditorPage } from "./ReportEditorPage";
import { mockApi, renderWithProviders } from "../test/render";
import { echoRender, FIELDS, METRICS } from "../test/reporting";

function setup() {
  const calls = mockApi({
    "GET /api/catalog": { sections: [], fields: FIELDS },
    "GET /api/metrics": METRICS,
    "GET /api/connections/published": [{ id: 7, name: "NovaBank", dialect: "postgresql", published_at: "" }],
    "POST /api/render-blocks": echoRender,
    "POST /api/reports": (_u: string, init?: RequestInit) => ({ id: 5, updated_at: "", ...JSON.parse(String(init!.body)) }),
  });
  renderWithProviders(<ReportEditorPage />, { route: "/reports/new", path: "/reports/new" });
  return calls;
}

const listItems = () => within(screen.getByTestId("block-list")).getAllByTestId("block-item").map((el) => el.textContent);

describe("ReportEditorPage", () => {
  it("adds, moves, duplicates and deletes blocks, previews them, and saves", async () => {
    const calls = setup();
    const user = userEvent.setup();
    const add = async (label: string) => {
      await user.click(await screen.findByRole("button", { name: "Add block" }));
      await user.click(await screen.findByRole("menuitem", { name: label }));
    };
    await add("Heading");
    await add("Page break");
    expect(listItems()).toEqual([expect.stringContaining("Heading: New section"), expect.stringContaining("Page break")]);

    await user.click(screen.getByRole("button", { name: "Move block 2 up" }));
    expect(listItems()[0]).toContain("Page break");
    await user.click(screen.getByRole("button", { name: "Duplicate block 2" }));
    expect(listItems()).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Delete block 1" }));
    expect(listItems()).toEqual([expect.stringContaining("Heading"), expect.stringContaining("Heading")]);

    expect((await screen.findAllByText(/^rendered /, {}, { timeout: 2000 })).length).toBeGreaterThan(0);
    expect(calls.some((c) => c.path === "/api/render-blocks")).toBe(true);

    await user.clear(screen.getByLabelText("Template name"));
    await user.type(screen.getByLabelText("Template name"), "Weekly pack");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "POST" && c.path === "/api/reports")?.body as { name: string; blocks: { type: string }[] };
      expect(body.name).toBe("Weekly pack");
      expect(body.blocks.map((b) => b.type)).toEqual(["heading", "heading"]);
    });
  });

  it("asks before discarding unsaved changes", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add block" }));
    await user.click(await screen.findByRole("menuitem", { name: "Text" }));
    await user.click(screen.getByRole("button", { name: "Back to reports" }));
    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/pages/Report`
Expected: failures, because the placeholder pages render nothing.

- [ ] **Step 3: Write `ReportsPage.tsx`**

```tsx
// frontend/src/pages/ReportsPage.tsx
import { Alert, Anchor, Button, Card, Group, Loader, Select, Stack, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText, type PeriodSpec, type Rendered, type ReportSummary } from "../api";
import { BlockView } from "../components/BlockView";
import { ClientSelect } from "../components/ClientSelect";
import { PeriodSelect, periodReady } from "../components/PeriodSelect";

export function ReportsPage() {
  const qc = useQueryClient();
  const reports = useQuery({ queryKey: ["reports"], queryFn: () => api<ReportSummary[]>("/reports") });
  const [selected, setSelected] = useState<number | null>(null);
  const [client, setClient] = useState<number | null>(null);
  const [period, setPeriod] = useState<PeriodSpec>({ preset: "last_month" });
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (reports.data?.length && (selected === null || !reports.data.some((r) => r.id === selected))) {
      setSelected(reports.data[0].id);
    }
  }, [reports.data, selected]);

  const rendered = useQuery({
    queryKey: ["render-report", selected, client, period],
    enabled: selected !== null && client !== null && periodReady(period),
    queryFn: () => api<Rendered>(`/reports/${selected}/render`, { method: "POST", json: { connection_id: client, period } }),
    retry: false,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<void>(`/reports/${id}`, { method: "DELETE" }),
    onSuccess: () => { setConfirming(false); setSelected(null); qc.invalidateQueries({ queryKey: ["reports"] }); },
  });
  const template = reports.data?.find((r) => r.id === selected);

  return (
    <Stack>
      <Group justify="space-between" className="no-print">
        <Title order={2}>Reports</Title>
        <Button component={Link} to="/reports/new">New template</Button>
      </Group>
      <Card withBorder className="no-print">
        <Group align="flex-end" wrap="wrap">
          <Select label="Template" w={260} allowDeselect={false} value={selected === null ? null : String(selected)}
            data={(reports.data ?? []).map((r) => ({ value: String(r.id), label: r.name }))}
            onChange={(v) => { setConfirming(false); setSelected(Number(v)); }} />
          <ClientSelect value={client} onChange={setClient} />
          <PeriodSelect value={period} onChange={setPeriod} />
          <Button variant="default" disabled={!rendered.data} onClick={() => window.print()}>Download PDF</Button>
          {template && (
            <Group gap="xs">
              <Anchor component={Link} to={`/reports/${template.id}/edit`} size="sm">Edit template</Anchor>
              {confirming ? (
                <>
                  <Button size="xs" color="red" loading={remove.isPending} onClick={() => remove.mutate(template.id)}>Confirm delete</Button>
                  <Button size="xs" variant="subtle" onClick={() => setConfirming(false)}>Cancel</Button>
                </>
              ) : (
                <Button size="xs" variant="subtle" color="red" onClick={() => setConfirming(true)}>Delete template</Button>
              )}
            </Group>
          )}
        </Group>
      </Card>
      {reports.data?.length === 0 && <Text c="dimmed">No report templates yet.</Text>}
      {rendered.isError && <Alert color="red" className="no-print">{errorText(rendered.error)}</Alert>}
      {rendered.isFetching && !rendered.data && <Loader />}
      {rendered.data && (
        <div className="report-paper">
          <Group justify="space-between" mb="md">
            <div>
              <Text fw={700}>{template?.name}</Text>
              <Text size="sm" c="dimmed">{rendered.data.client.name} · {rendered.data.period.label}</Text>
            </div>
            <Text size="xs" c="dimmed">Generated {rendered.data.generated_at.replace("T", " ").slice(0, 16)}</Text>
          </Group>
          {rendered.data.blocks.map((b) => <div key={b.id} className="report-block"><BlockView result={b} /></div>)}
        </div>
      )}
    </Stack>
  );
}
```

- [ ] **Step 4: Write `ReportEditorPage.tsx`**

```tsx
// frontend/src/pages/ReportEditorPage.tsx
import { ActionIcon, Alert, Badge, Button, Card, Grid, Group, Loader, Menu, Stack, Text, TextInput, UnstyledButton } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError, api, errorText, type Block, type BlockType, type Catalog, type Metric, type PeriodSpec, type Rendered,
  type ReportTemplate,
} from "../api";
import { BLOCK_TYPES, cloneBlock, describeBlock, newBlock } from "../blocks";
import { BlockSettings } from "../components/BlockSettings";
import { BlockView } from "../components/BlockView";
import { ClientSelect } from "../components/ClientSelect";
import { PeriodSelect, periodReady } from "../components/PeriodSelect";

interface Draft { name: string; description: string; blocks: Block[] }

export function ReportEditorPage() {
  const { id } = useParams();
  const isNew = id === undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<Catalog>("/catalog") });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metric[]>("/metrics") });
  const existing = useQuery({ queryKey: ["report", id], enabled: !isNew, queryFn: () => api<ReportTemplate>(`/reports/${id}`) });

  const [draft, setDraft] = useState<Draft | null>(isNew ? { name: "Untitled report", description: "", blocks: [] } : null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [client, setClient] = useState<number | null>(null);
  const [period, setPeriod] = useState<PeriodSpec>({ preset: "last_month" });
  const [blockErrors, setBlockErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<{ color: string; text: string } | null>(null);

  useEffect(() => {
    if (existing.data && draft === null) {
      const { name, description, blocks } = existing.data;
      setDraft({ name, description, blocks });
    }
  }, [existing.data, draft]);

  const [debounced] = useDebouncedValue(draft?.blocks ?? [], 600);
  const preview = useQuery({
    queryKey: ["render-blocks", debounced, client, period],
    enabled: client !== null && debounced.length > 0 && periodReady(period),
    queryFn: () => api<Rendered>("/render-blocks", { method: "POST", json: { blocks: debounced, connection_id: client, period } }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () => (isNew
      ? api<ReportTemplate>("/reports", { method: "POST", json: draft })
      : api<ReportTemplate>(`/reports/${id}`, { method: "PUT", json: draft })),
    onSuccess: (t) => {
      setDirty(false);
      setBlockErrors({});
      setMessage({ color: "teal", text: "Saved" });
      qc.invalidateQueries({ queryKey: ["reports"] });
      if (isNew) navigate(`/reports/${t.id}/edit`, { replace: true });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? (err.detail as { errors?: { block_id: string; messages: string[] }[] }) : null;
      setBlockErrors(Object.fromEntries((detail?.errors ?? []).map((e) => [e.block_id, e.messages])));
      setMessage({ color: "red", text: errorText(err) });
    },
  });

  if (!draft || !catalog.data || !metrics.data) return <Loader />;
  const blocks = draft.blocks;
  const update = (patch: Partial<Draft>) => { setDraft({ ...draft, ...patch }); setDirty(true); };
  const setBlocks = (next: Block[]) => update({ blocks: next });
  const move = (i: number, d: number) => { const next = [...blocks]; const [b] = next.splice(i, 1); next.splice(i + d, 0, b); setBlocks(next); };
  const add = (type: BlockType) => { const b = newBlock(type); setBlocks([...blocks, b]); setSelectedId(b.id); };
  const selected = blocks.find((b) => b.id === selectedId) ?? null;
  const results = new Map((preview.data?.blocks ?? []).map((r) => [r.id, r]));

  return (
    <Stack>
      {leaving && (
        <Alert color="yellow" title="Discard unsaved changes?">
          <Group gap="xs" mt="xs">
            <Button size="xs" color="red" onClick={() => navigate("/reports")}>Discard changes</Button>
            <Button size="xs" variant="default" onClick={() => setLeaving(false)}>Keep editing</Button>
          </Group>
        </Alert>
      )}
      <Group align="flex-end" wrap="wrap">
        <TextInput label="Template name" w={260} value={draft.name} onChange={(e) => update({ name: e.currentTarget.value })} />
        <TextInput label="Description" w={320} value={draft.description} onChange={(e) => update({ description: e.currentTarget.value })} />
        <ClientSelect label="Preview client" value={client} onChange={setClient} />
        <PeriodSelect value={period} onChange={setPeriod} />
        <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
        <Button variant="default" onClick={() => (dirty ? setLeaving(true) : navigate("/reports"))}>Back to reports</Button>
        {dirty && <Badge color="orange" variant="light">Unsaved changes</Badge>}
      </Group>
      {message && <Alert color={message.color} withCloseButton onClose={() => setMessage(null)}>{message.text}</Alert>}

      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Stack gap="xs" data-testid="block-list">
            <Menu>
              <Menu.Target><Button variant="light">Add block</Button></Menu.Target>
              <Menu.Dropdown>
                {BLOCK_TYPES.map((t) => <Menu.Item key={t.value} onClick={() => add(t.value)}>{t.label}</Menu.Item>)}
              </Menu.Dropdown>
            </Menu>
            {blocks.map((b, i) => (
              <Card key={b.id} withBorder padding="xs" data-testid="block-item"
                bg={b.id === selectedId ? "var(--mantine-color-blue-light)" : undefined}>
                <UnstyledButton onClick={() => setSelectedId(b.id)} w="100%">
                  <Text size="sm" truncate>{describeBlock(b)}</Text>
                </UnstyledButton>
                {blockErrors[b.id] && <Text size="xs" c="red">{blockErrors[b.id].join("; ")}</Text>}
                <Group gap={2} mt={4}>
                  <ActionIcon size="sm" variant="subtle" aria-label={`Move block ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</ActionIcon>
                  <ActionIcon size="sm" variant="subtle" aria-label={`Move block ${i + 1} down`} disabled={i === blocks.length - 1} onClick={() => move(i, 1)}>↓</ActionIcon>
                  <ActionIcon size="sm" variant="subtle" aria-label={`Duplicate block ${i + 1}`}
                    onClick={() => setBlocks([...blocks.slice(0, i + 1), cloneBlock(b), ...blocks.slice(i + 1)])}>⧉</ActionIcon>
                  <ActionIcon size="sm" variant="subtle" color="red" aria-label={`Delete block ${i + 1}`}
                    onClick={() => setBlocks(blocks.filter((x) => x.id !== b.id))}>✕</ActionIcon>
                </Group>
              </Card>
            ))}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <div className="report-paper">
            {client === null && <Text c="dimmed" size="sm">Choose a preview client to see live data.</Text>}
            {preview.isError && <Alert color="red">{errorText(preview.error)}</Alert>}
            {blocks.map((b) => (
              <div key={b.id} className="report-block">
                {results.get(b.id) ? <BlockView result={results.get(b.id)!} /> : <Text c="dimmed" size="sm">{describeBlock(b)}</Text>}
              </div>
            ))}
          </div>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 3 }}>
          {selected ? (
            <BlockSettings block={selected} fields={catalog.data.fields} metrics={metrics.data}
              onChange={(nb) => setBlocks(blocks.map((b) => (b.id === nb.id ? nb : b)))} />
          ) : (
            <Text c="dimmed" size="sm">Select a block to edit its settings.</Text>
          )}
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
```

- [ ] **Step 5: Run all frontend tests and the typecheck**

Run: `npx vitest run && npx tsc -b --noEmit`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ReportsPage.tsx frontend/src/pages/ReportEditorPage.tsx frontend/src/pages/Report*.test.tsx
git commit -m "feat(frontend): report viewer with print-to-PDF and block-based template editor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Dashboards page

**Files:**
- Replace: `frontend/src/pages/DashboardsPage.tsx`
- Test: `frontend/src/pages/DashboardsPage.test.tsx`

**Interfaces:**
- **Consumes:** Tasks 8 and 9; the API endpoints `/dashboards`, `/dashboards/{id}`, `/dashboards/{id}/render`, `/render-blocks`, `/catalog`, `/metrics` and `/connections/published`.
- **Produces:** routes `/dashboards` (redirects to the first dashboard) and `/dashboards/:id`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/DashboardsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Dashboard } from "../api";
import { DashboardsPage } from "./DashboardsPage";
import { mockApi, renderWithProviders } from "../test/render";
import { echoRender, FIELDS, METRICS } from "../test/reporting";

const board: Dashboard = {
  id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "",
  tiles: [
    { id: "t1", width: 3, height: "m", block: { id: "b1", type: "kpi", measure: { metric: "applications" }, filters: [] } },
    { id: "t2", width: 6, height: "l", block: { id: "b2", type: "chart", chart: "bar",
      query: { measures: [{ metric: "applications" }], group_by: ["channel"], filters: [] } } },
  ],
};

describe("DashboardsPage", () => {
  it("renders tiles, then edits width and order and saves them", async () => {
    const calls = mockApi({
      "GET /api/dashboards": [{ id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "" }],
      "GET /api/dashboards/1": board,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "GET /api/connections/published": [{ id: 7, name: "NovaBank", dialect: "postgresql", published_at: "" }],
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/render-blocks": echoRender,
      "PUT /api/dashboards/1": (_u: string, init?: RequestInit) => ({ ...board, ...JSON.parse(String(init!.body)) }),
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    expect(await screen.findByText("rendered b1")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/dashboards/1/render")?.body).toEqual({ connection_id: 7, period: { preset: "last_month" } });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByLabelText("Width of tile 1"));
    await user.click(await screen.findByRole("option", { name: "6" }));
    await user.click(screen.getByRole("button", { name: "Move tile 2 earlier" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "PUT")?.body as Dashboard;
      expect(body.tiles.map((t) => t.id)).toEqual(["t2", "t1"]);
      expect(body.tiles[1].width).toBe(6);
    });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/pages/DashboardsPage.test.tsx`
Expected: failure, because the placeholder renders nothing.

- [ ] **Step 3: Write `DashboardsPage.tsx`**

```tsx
// frontend/src/pages/DashboardsPage.tsx
import { ActionIcon, Alert, Button, Card, Drawer, Group, Loader, Menu, Select, Stack, TextInput, Title } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  api, errorText, type Catalog, type Dashboard, type DashboardSummary, type Metric, type PeriodSpec, type Rendered, type Tile,
} from "../api";
import { cloneBlock, newBlock, uid } from "../blocks";
import { BlockSettings } from "../components/BlockSettings";
import { BlockView } from "../components/BlockView";
import { ClientSelect } from "../components/ClientSelect";
import { PeriodSelect, periodReady } from "../components/PeriodSelect";

const HEIGHT = { s: 120, m: 260, l: 380 } as const;
const WIDTHS = ["3", "4", "6", "8", "12"];
const TILE_TYPES = [{ value: "kpi", label: "KPI" }, { value: "chart", label: "Chart" }, { value: "table", label: "Table" }] as const;

export function DashboardsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["dashboards"], queryFn: () => api<DashboardSummary[]>("/dashboards") });
  const board = useQuery({ queryKey: ["dashboard", id], enabled: !!id, queryFn: () => api<Dashboard>(`/dashboards/${id}`) });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<Catalog>("/catalog") });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metric[]>("/metrics") });

  const [client, setClient] = useState<number | null>(null);
  const [period, setPeriod] = useState<PeriodSpec | null>(null);
  const [editing, setEditing] = useState(false);
  const [tiles, setTiles] = useState<Tile[] | null>(null);      // working copy once edited
  const [editingTile, setEditingTile] = useState<string | null>(null);
  const [saveAsName, setSaveAsName] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!id && list.data?.length) navigate(`/dashboards/${list.data[0].id}`, { replace: true });
  }, [id, list.data, navigate]);
  useEffect(() => {
    if (board.data) { setPeriod(board.data.default_period); setTiles(null); setEditing(false); }
  }, [board.data?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const shown = tiles ?? board.data?.tiles ?? [];
  const [debounced] = useDebouncedValue(shown, 400);
  const rendered = useQuery({
    queryKey: ["render-dashboard", id, tiles === null ? "saved" : debounced, client, period],
    enabled: !!id && client !== null && periodReady(period) && shown.length > 0,
    queryFn: () => (tiles === null
      ? api<Rendered>(`/dashboards/${id}/render`, { method: "POST", json: { connection_id: client, period } })
      : api<Rendered>("/render-blocks", { method: "POST", json: { blocks: debounced.map((t) => t.block), connection_id: client, period } })),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const body = () => ({ name: board.data!.name, default_period: period ?? board.data!.default_period, tiles: shown });
  const save = useMutation({
    mutationFn: () => api<Dashboard>(`/dashboards/${id}`, { method: "PUT", json: body() }),
    onSuccess: () => { setTiles(null); setEditing(false); setMessage(null); qc.invalidateQueries({ queryKey: ["dashboard", id] }); },
    onError: (e) => setMessage(errorText(e)),
  });
  const saveAs = useMutation({
    mutationFn: (name: string) => api<Dashboard>("/dashboards", { method: "POST", json: { ...body(), name } }),
    onSuccess: (d) => { setSaveAsName(null); qc.invalidateQueries({ queryKey: ["dashboards"] }); navigate(`/dashboards/${d.id}`); },
    onError: (e) => setMessage(errorText(e)),
  });

  if (list.data?.length === 0) return <Alert color="yellow">No dashboards yet.</Alert>;
  if (!board.data || !catalog.data || !metrics.data || !period) return <Loader />;

  const update = (next: Tile[]) => setTiles(next);
  const patchTile = (i: number, patch: Partial<Tile>) => update(shown.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const move = (i: number, d: number) => { const next = [...shown]; const [t] = next.splice(i, 1); next.splice(i + d, 0, t); update(next); };
  const results = new Map((rendered.data?.blocks ?? []).map((r) => [r.id, r]));
  const tileBeingEdited = shown.find((t) => t.id === editingTile);

  return (
    <Stack>
      <Group align="flex-end" wrap="wrap">
        <Title order={2} mr="md">Dashboards</Title>
        <Select label="Dashboard" w={220} allowDeselect={false} value={id ?? null}
          data={(list.data ?? []).map((d) => ({ value: String(d.id), label: d.name }))}
          onChange={(v) => navigate(`/dashboards/${v}`)} />
        <ClientSelect value={client} onChange={setClient} />
        <PeriodSelect value={period} onChange={setPeriod} />
        <Button variant="default" onClick={() => rendered.refetch()}>Refresh</Button>
        <Button variant={editing ? "filled" : "default"} onClick={() => setEditing((e) => !e)}>{editing ? "Done" : "Edit"}</Button>
        {tiles !== null && <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>}
        {saveAsName === null ? (
          <Button variant="subtle" onClick={() => setSaveAsName(`${board.data!.name} (copy)`)}>Save as…</Button>
        ) : (
          <Group gap="xs" align="flex-end">
            <TextInput label="New dashboard name" value={saveAsName} onChange={(e) => setSaveAsName(e.currentTarget.value)} />
            <Button onClick={() => saveAs.mutate(saveAsName)} loading={saveAs.isPending}>Create</Button>
            <Button variant="subtle" onClick={() => setSaveAsName(null)}>Cancel</Button>
          </Group>
        )}
      </Group>
      {message && <Alert color="red" withCloseButton onClose={() => setMessage(null)}>{message}</Alert>}
      {rendered.isError && <Alert color="red">{errorText(rendered.error)}</Alert>}
      {editing && (
        <Menu>
          <Menu.Target><Button variant="light" w="fit-content">Add tile</Button></Menu.Target>
          <Menu.Dropdown>
            {TILE_TYPES.map((t) => (
              <Menu.Item key={t.value} onClick={() => update([...shown, { id: uid(), block: newBlock(t.value),
                width: t.value === "kpi" ? 3 : 6, height: t.value === "kpi" ? "m" : "l" }])}>{t.label}</Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(12, minmax(0, 1fr))", gap: 12 }}>
        {shown.map((t, i) => (
          <Card key={t.id} withBorder padding="sm" style={{ gridColumn: `span ${t.width}`, minHeight: HEIGHT[t.height] }}>
            {editing && (
              <Group gap={4} mb="xs" wrap="wrap">
                <Select aria-label={`Width of tile ${i + 1}`} w={70} size="xs" allowDeselect={false} data={WIDTHS}
                  value={String(t.width)} onChange={(v) => patchTile(i, { width: Number(v) as Tile["width"] })} />
                <Select aria-label={`Height of tile ${i + 1}`} w={70} size="xs" allowDeselect={false} data={["s", "m", "l"]}
                  value={t.height} onChange={(v) => patchTile(i, { height: v as Tile["height"] })} />
                <ActionIcon size="sm" variant="subtle" aria-label={`Edit tile ${i + 1}`} onClick={() => setEditingTile(t.id)}>✎</ActionIcon>
                <ActionIcon size="sm" variant="subtle" aria-label={`Move tile ${i + 1} earlier`} disabled={i === 0} onClick={() => move(i, -1)}>←</ActionIcon>
                <ActionIcon size="sm" variant="subtle" aria-label={`Move tile ${i + 1} later`} disabled={i === shown.length - 1} onClick={() => move(i, 1)}>→</ActionIcon>
                <ActionIcon size="sm" variant="subtle" aria-label={`Duplicate tile ${i + 1}`}
                  onClick={() => update([...shown.slice(0, i + 1), { ...t, id: uid(), block: cloneBlock(t.block) }, ...shown.slice(i + 1)])}>⧉</ActionIcon>
                <ActionIcon size="sm" variant="subtle" color="red" aria-label={`Delete tile ${i + 1}`}
                  onClick={() => update(shown.filter((x) => x.id !== t.id))}>✕</ActionIcon>
              </Group>
            )}
            {results.get(t.block.id) ? <BlockView result={results.get(t.block.id)!} /> : <Loader size="sm" />}
          </Card>
        ))}
      </div>
      <Drawer opened={!!tileBeingEdited} onClose={() => setEditingTile(null)} position="right" size="md" title="Tile settings">
        {tileBeingEdited && (
          <BlockSettings block={tileBeingEdited.block} fields={catalog.data.fields} metrics={metrics.data}
            onChange={(b) => update(shown.map((t) => (t.id === tileBeingEdited.id ? { ...t, block: b } : t)))} />
        )}
      </Drawer>
    </Stack>
  );
}
```

- [ ] **Step 4: Run all frontend tests and the typecheck**

Run: `npx vitest run && npx tsc -b --noEmit`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardsPage.tsx frontend/src/pages/DashboardsPage.test.tsx
git commit -m "feat(frontend): custom dashboards with KPI and chart tiles, editing and save-as

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Docs, full verification and smoke test

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README.**
  - In the parts table, change the Part 3 row to `| 3. Reporting & dashboards | done | docs/superpowers/specs/2026-10-22-reporting-dashboards-design.md |`.
  - Add this section after "Run the app":

```markdown
## Reports and dashboards

Reports and dashboards are available once at least one client is published.

- **Reports:**
  - Choose a template, a client and a period to see the report.
  - **Download PDF** opens the browser's print dialog; choose "Save as PDF". Pages are A4.
  - **New template** (or **Edit template**) opens the block editor: add blocks on the left, configure them on the right, and watch the live preview in the middle.
- **Dashboards:**
  - Choose a dashboard, a client and a period.
  - **Edit** lets you add tiles, change their width and height, reorder them, and open a tile's settings. **Save** keeps the changes; **Save as…** creates a copy.
- **Ready-made content:** a "Monthly Lending MIS" template and a "Lending KPIs" dashboard are recreated at startup if they are missing.
- **KPIs:** defined in `catalog/metrics.yaml` as aggregate formulas, for example `approved / decided * 100`. Add a metric there and restart the API to use it in blocks.
```

- [ ] **Step 2: Run the full backend and frontend suites**

```bash
(cd backend && ../.venv/bin/pytest -q)
(cd frontend && npx vitest run && npx tsc -b --noEmit && npm run build)
```
Expected:
- backend: all pass; only the `llm` test is skipped.
- frontend: all pass, with no type errors, and the build succeeds.

- [ ] **Step 3: Smoke-test the live app.** Restart the API, so it loads the metrics and seeds the defaults, then render the default report and dashboard for both published clients through the dev proxy:

```bash
kill $(lsof -ti tcp:8000); (cd backend && ../.venv/bin/uvicorn app.main:app --port 8000 &) ; sleep 4
.venv/bin/python - <<'EOF'
import json, urllib.request
B = "http://localhost:5173/api"
def call(method, path, body=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())
report = call("GET", "/reports")[0]["id"]; board = call("GET", "/dashboards")[0]["id"]
for c in call("GET", "/connections/published"):
    r = call("POST", f"/reports/{report}/render", {"connection_id": c["id"], "period": {"preset": "last_month"}})
    d = call("POST", f"/dashboards/{board}/render", {"connection_id": c["id"], "period": {"preset": "last_month"}})
    kpis = {i["key"]: i["value"]["display"] for i in r["blocks"][2]["items"]}
    errors = [b["id"] for b in r["blocks"] + d["blocks"] if "error" in b]
    print(c["name"], r["period"]["label"], kpis, "errors:", errors)
EOF
```
Expected: both clients print **identical** KPI values for Sep 2026 and `errors: []`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README for reports and dashboards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Request the final whole-branch review** (superpowers:requesting-code-review) against the spec, using the commit before Task 1 as the base.
