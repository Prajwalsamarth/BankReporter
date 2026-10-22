# BankReporter — Part 3: Reporting & Dashboards

**Date:** 2026-10-22
**Status:** Draft for review
**Depends on:** Part 1 (catalog, formula compiler) and Part 2 (published `lending_rpt.applications` views, connections, app store, React app).

---

## 0. Goal and success criteria

Let a user build **custom report templates** (formatted MIS-style documents exported to PDF) and **custom dashboards** (grids of KPI and chart tiles). Both query the canonical views in the client's database **live**. Templates and dashboards are defined once against the 81 canonical columns, so **the same template runs unchanged on any mapped client**.

This is a proof of concept. Success means:
1. A user can build a report template in a block editor, view it for a chosen client and period, and save it as a PDF.
2. A user can build and edit a dashboard of KPI tiles (with comparison to the previous period and a sparkline) and charts.
3. For the same template and period, both mock clients produce **identical numbers**, and those numbers equal an independent calculation over the golden CSV.

---

## 1. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Report type | A formatted document (MIS pack): ordered blocks, rendered on screen, exported to PDF |
| Template authoring | A block editor in the app, with a live preview |
| Dashboards | Custom grids of KPI, chart and table tiles; the same block engine as reports |
| KPIs | A metric library in `catalog/metrics.yaml` (aggregate formulas) **plus** ad-hoc field aggregates |
| PDF | The browser's print-to-PDF with print styling; no server-side PDF |
| Time | A period selector on every report and dashboard; KPIs compare with the previous period |
| Query architecture | A backend query service: JSON block specs compiled to SQLAlchemy over `<schema>.applications`; one render call per report or dashboard |
| Charts | `@mantine/charts` 7.17 (Recharts) |
| Scope | One client per view. Out of scope: cross-client comparison, filters across a whole report or dashboard beyond the period, scheduled or emailed reports, server PDF, drag and drop, formula editing in the UI, access control |

---

## 2. Metric library (`catalog/metrics.yaml`)

### 2.1 Format
```yaml
version: 1
metrics:
  - id: approval_rate
    label: "Approval rate"
    formula: "approved / decided * 100"
    unit: pct            # count | INR | pct | days | score | ratio
    better: higher       # higher | lower | neutral   (colours the change)
    group: rates         # volume | rates | amounts | credit | turnaround   (picker grouping)
    description: "Approved ÷ decided applications."
```

### 2.2 Aggregate formula language
- **Base grammar:** the Part 1 grammar (Python `ast` with an allow-list).
- **Aggregate functions:**
  - `COUNT()`;
  - `COUNT_IF(cond)`;
  - `SUM(x)` and `SUM_IF(x, cond)`;
  - `AVG(x)` and `AVG_IF(x, cond)`;
  - `MIN(x)` and `MAX(x)`;
  - `COUNT_DISTINCT(x)`.
- **Inside an aggregate's arguments:** any row-level Part 1 expression over the 81 view columns (raw and calculated fields).
- **Outside aggregates:** only numeric constants, `+ - * /`, unary `-`, `ROUND`, `COALESCE` and other **metric IDs**.
- **Rejected:**
  - a bare field outside an aggregate;
  - nested aggregates;
  - unknown fields or metrics;
  - metric cycles;
  - a non-boolean `cond`;
  - a non-numeric `x` for `SUM`, `AVG` or `_IF` aggregates (`MIN` and `MAX` also accept dates).
- **Compilation:**

  | Formula | SQL |
  |---|---|
  | `COUNT()` | `COUNT(*)` |
  | `COUNT_IF(c)` | `SUM(CASE WHEN c THEN 1 ELSE 0 END)` |
  | `SUM_IF(x, c)` | `SUM(CASE WHEN c THEN x END)` |
  | `AVG_IF(x, c)` | `AVG(CASE WHEN c THEN x END)` |
  | `COUNT_DISTINCT(x)` | `COUNT(DISTINCT x)` |
  | a metric ID | inlined |

  Division reuses Part 1's `NULLIF` and `Numeric(20, 6)` semantics.

### 2.3 Metrics (22)

| id | formula | unit | better |
|---|---|---|---|
| applications | `COUNT()` | count | higher |
| decided | `COUNT_IF(decision_date is not None)` | count | neutral |
| approved | `COUNT_IF(is_approved)` | count | higher |
| rejected | `COUNT_IF(is_rejected)` | count | lower |
| disbursed_count | `COUNT_IF(is_disbursed)` | count | higher |
| approval_rate | `approved / decided * 100` | pct | higher |
| rejection_rate | `rejected / decided * 100` | pct | lower |
| disbursement_conversion | `disbursed_count / approved * 100` | pct | higher |
| kyc_failure_rate | `COUNT_IF(kyc_status == 'FAILED') / applications * 100` | pct | lower |
| auto_decision_share | `COUNT_IF(decision_mode == 'AUTO') / decided * 100` | pct | higher |
| ntc_share | `COUNT_IF(is_new_to_credit) / applications * 100` | pct | neutral |
| requested_amount_total | `SUM(requested_amount)` | INR | higher |
| sanctioned_amount_total | `SUM(approved_amount)` | INR | higher |
| disbursed_amount_total | `SUM(disbursed_amount)` | INR | higher |
| avg_ticket_size | `disbursed_amount_total / disbursed_count` | INR | neutral |
| processing_fee_income | `SUM(processing_fee)` | INR | higher |
| avg_cibil | `AVG(cibil_score)` | score | higher |
| avg_interest_rate | `AVG_IF(interest_rate_pct, is_disbursed)` | pct | neutral |
| avg_post_loan_foir | `AVG_IF(post_loan_foir_pct, is_approved)` | pct | lower |
| avg_decision_tat | `AVG(decision_tat_days)` | days | lower |
| avg_disbursement_tat | `AVG(disbursement_tat_days)` | days | lower |
| avg_end_to_end_tat | `AVG(end_to_end_tat_days)` | days | lower |

`load_metrics(path, catalog)` raises `MetricError(errors)` with every problem, prefixed by the metric ID. The API refuses to start if the metrics file is invalid.

---

## 3. Block query spec

```json
{
  "measures": [{"metric": "approval_rate"}, {"field": "disbursed_amount", "agg": "sum", "label": "Disbursed"}],
  "group_by": ["application_month", "channel"],
  "filters": [["employment_type", "eq", "SALARIED"], ["cibil_band", "in", ["750-799", "800+"]]],
  "sort": {"by": "approval_rate", "dir": "desc"},
  "limit": 20
}
```

| Key | Rules |
|---|---|
| `measures` | 1–4 items. Each is either `{metric}` or `{field, agg}`. `agg` is `count` or `count_distinct` on any field, or `sum`/`avg`/`min`/`max` on fields with `role: measure`. An optional `label` overrides the default. |
| `group_by` | 0–2 catalog fields with `role: dimension` |
| `filters` | `[field, op, value]`. `op` is one of `eq ne in not_in gt gte lt lte is_null not_null`. Values are checked against the field type, and for enums against `values`. `in`/`not_in` take a non-empty list. `is_null`/`not_null` take no value. |
| `sort` | `by` is a measure key or a group-by field; `dir` is `asc` or `desc`. The default sorts by the first group-by, ascending (months chronological). |
| `limit` | 1–500; default 100 for tables and charts |

- **Measure keys** are the metric ID, or `"{agg}_{field}"` for field aggregates (for example `sum_disbursed_amount`).
- **Validation** (`spec.validate(spec, catalog, metrics) -> list[str]`) runs on save (`422`) and at render, where it becomes a per-block error.

---

## 4. Periods (`reporting/period.py`)

- **Request shape:** `{"preset": "...", "start"?: "YYYY-MM-DD", "end"?: "YYYY-MM-DD"}`. `today` is the server date and is injectable for tests.
- **Filtering:** every query adds `application_date >= start AND application_date < end_exclusive`.

| Preset | Period | Previous period |
|---|---|---|
| `this_month` | 1st of the current month → end of the month | the previous calendar month |
| `last_month` *(default)* | the previous calendar month | the month before that |
| `this_quarter` | the current calendar quarter | the previous quarter |
| `last_quarter` | the previous calendar quarter | the quarter before that |
| `ytd` | 1 Jan → today | 1 Jan → the same day last year (29 Feb maps to 28 Feb) |
| `last_12_months` | the 12 calendar months before the current month | the 12 months before those |
| `custom` | `start` → `end`, inclusive | the same number of days immediately before `start` |

- **Result:** `Period(start, end_exclusive, prev_start, prev_end_exclusive, label)`. For example, `label` is "Sep 2026", "Q3 2026", "YTD 2026" or "1 Jan 2026 – 15 Mar 2026".
- **Errors:** `custom` with start after end, or a missing date, gives `PeriodError` and a 422.

---

## 5. Rendering (`reporting/query.py`, `reporting/render.py`)

### 5.1 Query building
`build_query(spec, period, catalog, metrics, schema) -> Select`, over `table("applications", schema=schema)` (the 81 columns are known from the catalog):
- **SELECT:** group-by columns plus measures, each labelled by its key.
- **WHERE:** the period, plus the filters.
- **GROUP BY:** the group-by columns.
- **ORDER BY / LIMIT:** from the spec.

It is executed through SQLAlchemy on the client engine. The default schema is `lending_rpt`; the tests pass `lending_rpt_eval`.

### 5.2 Block types and results

| Block | Config | Result |
|---|---|---|
| `heading` | `text`, `level` 1–3 | `{text}`, with placeholders resolved |
| `text` | `text` | `{text}`, with placeholders resolved |
| `kpi_row` | `items: [{measure, label?}]`, 1–6 items, optional shared `filters` | `{items: [Kpi]}` |
| `kpi` (dashboard tile) | `measure`, `label?`, `filters?`, `sparkline: bool` (default true) | `Kpi` |
| `table` | query spec with ≥ 1 group-by, `totals: bool` | `{columns, rows, totals?}` |
| `chart` | query spec plus `chart`: `bar`, `stacked_bar`, `line`, `area` or `pie` | `{columns, rows}` |
| `page_break` | — | `{}` |

- **Chart rules (checked on save):**
  - `pie` has exactly 1 group-by and 1 measure;
  - `line` and `area` have ≥ 1 group-by;
  - a chart with 2 group-bys has exactly 1 measure, where the 2nd group-by provides the series.
- **`Kpi`:**
  `{key, label, unit, value: Val, previous: Val, delta: {raw, display, direction: up|down|flat, good: true|false|null} | null, sparkline?: [{month, raw}]}`
  - **delta:** for a `pct` unit, `value − previous` in percentage points (display `"+2.1 pts"`). Otherwise `(value − previous) / previous × 100` (display `"+4.3%"`).
  - **`null` delta:** when either value is null, or `previous` is 0 for a non-`pct` unit.
  - **`good`:** follows `better`; it is `null` when `better` is neutral.
  - **sparkline:** the measure grouped by `application_month` over the 6 calendar months ending with the month that contains the period end.
- **`Val`:** `{raw: number|string|null, display: string}`. Every number the UI shows comes from `display`, and charts plot `raw`.
- **Placeholders:** `{{client_name}}`, `{{period}}` (the label), `{{period_start}}`, `{{period_end}}`, `{{generated_at}}`, and `{{metric:<id>}}` (the formatted value for the period). An unknown placeholder renders as `[unknown: name]`.

### 5.3 Render entry point
`render_blocks(blocks, engine, period, client_name, catalog, metrics, schema) -> list[BlockResult]`
- Uses **one connection** for all blocks.
- Each block is rendered inside its own try. A failure produces `{id, type, error}`, with the masked message, and the remaining blocks still render.
- Before rendering, it checks that `<schema>.applications` exists. If it doesn't, it raises `NotPublished`, which the API maps to 409: "NovaBank has no published views; publish its mapping first".

### 5.4 Formatting (`reporting/formatting.py`)

| Unit | Example display |
|---|---|
| count | `1,23,456` (Indian grouping) |
| INR | `₹4.52 Cr` (≥ 1 crore), `₹38.6 L` (≥ 1 lakh), `₹85,400` otherwise |
| pct | `61.2%` |
| days | `4.3 days` |
| score | `731` |
| ratio | `1.85` |
| null | `—` |

Dimension values display as they are. Booleans display as Yes/No. `application_month` displays as `Sep 2026`.

---

## 6. Storage and defaults

- **New SQLite tables:**
  - `report_template`: `id` (autoincrement), `name` (unique), `description`, `blocks` JSON, `created_at`, `updated_at`.
  - `dashboard`: `id` (autoincrement), `name` (unique), `default_period` JSON, `tiles` JSON, `created_at`, `updated_at`.
- **A block** is `{"id": "<uuid from client>", "type": ..., ...config}`.
- **A dashboard tile** is `{"id", "block": Block, "width": 3|4|6|8|12, "height": "s"|"m"|"l"}`. Tile blocks are limited to `kpi`, `chart` and `table`.
- **Defaults:** `catalog/defaults/monthly_lending_mis.yaml` and `catalog/defaults/lending_kpis.yaml` are added at API startup when no template or dashboard with that name exists, so deleting one recreates it on the next start. Their contents are as presented in brainstorming:
  - **"Monthly Lending MIS":** title; summary text; KPI row (applications, approval_rate, disbursed_amount_total, avg_ticket_size); monthly applications and approved line chart; approval rate by channel bar chart; rejection reasons table; applications by CIBIL band pie chart; turnaround KPI row; page break; disbursals by state table.
  - **"Lending KPIs":** 8 KPI tiles (width 3); monthly applications against approved line chart (8); rejection reasons pie chart (4); disbursed amount by month bar chart (6); approval rate by CIBIL band bar chart (6); status by channel stacked bar chart (6); top 10 states by disbursed amount table (6).

---

## 7. API (`/api`)

| Method & path | Body → response |
|---|---|
| `GET /metrics` | `[{id, label, unit, better, group, description}]` |
| `GET /connections/published` | connections that have ≥ 1 `publication` row: `[{id, name, dialect, published_at}]` |
| `GET /reports` | `[{id, name, description, updated_at}]` |
| `POST /reports` | `{name, description, blocks}` → template (`422` lists block errors; `409` for a duplicate name) |
| `GET /reports/{id}` | the template |
| `PUT /reports/{id}` | `{name, description, blocks}` → template |
| `DELETE /reports/{id}` | `204` |
| `POST /reports/{id}/render` | `{connection_id, period}` → `Rendered` |
| `GET /dashboards` | list |
| `POST /dashboards` | `{name, default_period, tiles}` → dashboard |
| `GET /dashboards/{id}` | the dashboard |
| `PUT /dashboards/{id}` | `{name, default_period, tiles}` → dashboard |
| `DELETE /dashboards/{id}` | `204` |
| `POST /dashboards/{id}/render` | `{connection_id, period}` → `Rendered` (results keyed by tile ID) |
| `POST /render-blocks` | `{blocks, connection_id, period}` → `Rendered`; used by both editors for unsaved content; stores nothing |

- **`Rendered`:** `{client: {id, name}, period: {start, end, prev_start, prev_end, label}, generated_at, blocks: [BlockResult]}`.
- **Errors:**
  - `404` for an unknown template, dashboard or connection;
  - `409` for not published;
  - `422` for a bad period or an invalid spec on save;
  - `502` when the client DB is unreachable (masked).

---

## 8. Frontend

- **Navigation:** Connections · Reports · Dashboards.
- **New dependencies:** `@mantine/charts@7.17.8`, `recharts@2.15.x` and `@mantine/dates@7.17.8` (with `dayjs`, for the custom date range).

### 8.1 Shared components
- **`PeriodSelect`:** the presets, plus custom start/end date pickers.
- **`ClientSelect`:** a list from `/connections/published`, with an empty state linking to Connections.
- **`BlockView`:** renders one `BlockResult`.
  - **Headings and text:** as typography.
  - **KPI:** a card with label, `value.display`, `previous.display` and a delta badge (green when `good`, red when not good, grey when `null`), plus a `Sparkline`.
  - **Table:** a Mantine Table with an optional totals row.
  - **Chart:** a `BarChart`, `LineChart`, `AreaChart` or `PieChart` from `@mantine/charts`.
  - **Page break:** a marker on screen, and a page break when printed.
  - **States:** a block error shows as an inline red Alert inside the block; empty results show "No applications in this period".
- **`BlockSettings`:** the form for one block's config.
  - **Measures:** a picker of library metrics grouped by `group`, plus "Field aggregate…".
  - **Group-by:** up to 2 dimension fields.
  - **Filters:** rows of field, op and value, where the value is a select for enums, a number for numbers, a date for dates, and Yes/No for booleans.
  - **Also:** chart type, sort, limit and totals.
  - **Output:** a spec that passes backend validation; the form uses the same rules.

### 8.2 Reports
- **`ReportsPage`:**
  - a list of templates (New, Edit, Delete with in-page confirm, View);
  - the viewer: `ClientSelect`, `PeriodSelect` and Render;
  - an A4-width "paper" with a header (template name, client, period label, generated at) and the blocks;
  - **Download PDF**, which calls `window.print()`.
- **`ReportEditorPage`:**
  - **header:** name, description, preview client and period, Save;
  - **left:** the block list (Add block ▾, select, move up/down, duplicate, delete);
  - **right:** `BlockSettings` for the selected block;
  - **centre:** a live preview through `/render-blocks`, debounced 600 ms.
  - Leaving the page with unsaved changes shows an in-page "Discard changes?" bar instead of `window.confirm`.
- **`print.css`:**
  - `@page { size: A4; margin: 15mm }`;
  - the app shell, sidebars and buttons are hidden;
  - `.report-block { break-inside: avoid }`;
  - `.page-break { break-before: page }`;
  - charts have a fixed print width.

### 8.3 Dashboards
- **`DashboardsPage`:**
  - **top bar:** dashboard select, `ClientSelect`, `PeriodSelect` (starting from the dashboard's `default_period`), Refresh, Edit, and "Save as…";
  - **grid:** a 12-column CSS grid. Height `s`/`m`/`l` is 120/260/380 px.
  - **Edit mode:** every tile gets settings (a drawer with `BlockSettings`), width and height selects, move earlier/later, duplicate and delete. "Add tile ▾" offers KPI, chart or table.
  - **Preview and save:** edits re-render through `/render-blocks`, and Save PUTs the dashboard.

---

## 9. Error handling

| Situation | Behaviour |
|---|---|
| `metrics.yaml` invalid | The API refuses to start, listing every error |
| Invalid block spec on save | `422 {errors: [{block_id, messages}]}`; the editor highlights the blocks |
| Invalid spec at render (e.g. saved before a catalog change) | A per-block `{error}` |
| Client has no published views | `409`, naming the client; the viewer links to its Mapping page |
| Client DB unreachable | `502`, masked message |
| One block's SQL fails | That block gets `{error}`; the others render |
| Bad custom period | `422` |
| Empty result | "No applications in this period" in the block; KPIs show `—` |

---

## 10. Testing

| Area | Tests |
|---|---|
| `aggregates.py` | parse/reject cases (bare field outside an aggregate, nested aggregate, non-boolean cond, unknown metric, cycle); compile and run on SQLite over a small table: `COUNT_IF`, `SUM_IF`, `AVG_IF`, ratio of metrics, division by zero gives null |
| `metrics.py` | the real `metrics.yaml` loads all 22 metrics; a broken file reports every error |
| `period.py` | every preset at fixed `today` values, including quarter boundaries, January (previous month across a year), `ytd` on 29 Feb, and custom previous-window length; error cases |
| `spec.py` | each rule in §3 and the chart rules in §5.2 |
| `formatting.py` | Indian grouping, ₹ L/Cr thresholds, pts versus %, nulls, month labels |
| **Correctness against golden data** (marked `db`) | publish the answer-key mapping to `lending_rpt_eval` on both clients. Render (a) all 22 metrics for a fixed custom period and the previous period, and (b) a `table` grouped by channel × status. **Assert both clients are equal to each other and to a plain-Python reference over `mockdata/golden/applications.csv`.** Drop the views afterwards. |
| `render.py` | a placeholder resolution; a failing block isolated from the others; `NotPublished` |
| API | template and dashboard CRUD, defaults added once, duplicate name `409`, `422` on an invalid spec, render `409`/`502`/`404`, `/render-blocks` stores nothing |
| Frontend (Vitest + RTL) | KPI tile delta colour follows `good`; `BlockView` shows the error of a failed block while siblings render; the report editor adds, moves, duplicates and deletes blocks and its preview calls `/render-blocks`; `BlockSettings` produces the expected spec for a chart with filters; dashboard edit changes width and order and Save PUTs the tiles; Download PDF calls `window.print`; `PeriodSelect` custom range |

---

## 11. Out of scope (Part 3)

- Comparing clients side by side.
- Filters across a whole report or dashboard beyond the period.
- Scheduled or emailed reports, and server-side PDF.
- Drag-and-drop layout.
- Editing formulas or metrics in the UI.
- Users and access control.
- Caching query results.
- Drill-down from charts.
