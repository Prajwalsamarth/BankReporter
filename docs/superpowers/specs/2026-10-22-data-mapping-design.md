# BankReporter — Part 2: Data Mapping

**Date:** 2026-10-22
**Status:** Draft for review
**Depends on:** Part 1 (`2026-10-22-catalog-and-mock-data-design.md`). Its project-wide decisions apply here unchanged.

---

## 0. Goal and success criteria

Connect to a client lending database, **suggest automatically** which client column feeds each canonical raw field, let a person review and correct the suggestions, and **publish views** in the client database that present the data in the canonical shape, without copying any client data.

This is a proof of concept. Success means two things:

1. **Measured matching quality.** We need numbers showing how well each layer (rules → embeddings → LLM) maps two differently-shaped schemas. That includes a *blind* test, where some of the easy synonym matches are hidden from the rules, so we see how the later layers cope with names they've never seen.
2. **A working end-to-end flow.** A user can go from connect → run → review → publish, and the published views reproduce the golden canonical data exactly.

Scope stays at mapping difficulty **L1 (naming) and L2 (structure)**. Transforms (L3+) are *flagged*, never applied.

---

## 1. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Matcher | Three layers. **A**: rules and synonyms, exact only. **B**: local embedding similarity, top-5 shortlist. **C**: an LLM chooses among the shortlist, for low-confidence columns only. |
| Direction | Column → field, then a global assignment. Join keys are resolved before matching. |
| LLM | **OpenAI API**. Key from the `OPENAI_API_KEY` environment variable; model from `MAPPER_LLM_MODEL`, default `gpt-4.1-mini`. |
| Data sent to the LLM | Table and column names, types, and aggregate statistics: null %, distinct count, numeric/date min and max, string length range, masked value patterns. **No raw string values.** |
| Embeddings | `fastembed` with `BAAI/bge-small-en-v1.5`, running locally (ONNX, no PyTorch). |
| Credentials | Stored in the app's SQLite file. URLs are encrypted with Fernet, using a key from `BANKREPORTER_SECRET_KEY`. The API never returns a password. |
| Mapping page | Field-centric: one row per canonical field. |
| Views | `lending_rpt.applications_base` (59 raw fields) and `lending_rpt.applications` (base + 22 calculated fields). |
| Evaluation | Ablation over the layers × synonym masking at 0%, 50% and 100%, plus an end-to-end comparison with the golden CSV. |
| Out of scope | Applying L3–L5 transforms; LLM-proposed derived metrics; auth and multiple users; automatic re-runs when a schema changes; any grain other than one row per application. |

---

## 2. Architecture

```
React (Vite + TS + Mantine)       FastAPI backend                          Client DB
Connections page ───────────▶ connections/  (CRUD, Fernet)              ┐
Mapping page ── run ────────▶ introspect → profile → joins → matcher    │ read-only:
               ◀── poll ────    (A → B → C via OpenAI) → assign         │ information_schema,
               ── edit ─────▶ store/ (SQLite: runs, entries)            │ aggregate SQL
               ── publish ──▶ viewgen/ ── DDL ─────────────────────────▶ │ lending_rpt.*
CLI: python -m app.mapping.evaluate (ablation + blind masking report)    ┘
```

### 2.1 Backend packages (`backend/app/`)

| Package | Responsibility | Public interface |
|---|---|---|
| `settings.py` | Environment config: secret key, DB path, OpenAI model, thresholds | `Settings` (pydantic-settings) |
| `store/` | App SQLite through SQLAlchemy ORM (§6) | `Store(url)`, ORM models |
| `connections/` | Encrypt/decrypt URLs, mask them, test connectivity | `encrypt_url`, `decrypt_url`, `mask_url`, `test_connection(url, schemas) -> TestResult` |
| `introspect/` | Schemas, tables, columns, PK/FK, row counts | `introspect(engine, schemas) -> SchemaInfo` |
| `profile/` | Per-column statistics through aggregate SQL; pattern masking; enum overlap | `profile_columns(engine, info, catalog) -> list[ColumnProfile]` |
| `joins/` | Grain table and LEFT JOIN plan, by rules | `plan_joins(info, profiles, key_scorer) -> JoinPlan` |
| `matcher/rules.py` | Layer A | `match_rules(profiles, catalog) -> dict[ColumnRef, Decision]` |
| `matcher/embed.py` | Layer B | `Embedder.shortlist(profile, catalog, k=5) -> list[Candidate]` |
| `matcher/llm.py` | Layer C | `LlmMatcher(client, model).choose(table, columns, shortlists) -> dict[ColumnRef, LlmChoice]` |
| `matcher/assign.py` | Global one-to-one assignment | `assign(candidates, key_columns, plan) -> list[FieldMapping]` |
| `matcher/pipeline.py` | Runs the stages in order | `run_matching(info, profiles, plan, catalog, layers, llm, embedder) -> MatchResult` |
| `matcher/abbreviations.py` | The fixed abbreviation list (§4.3) | `ABBREVIATIONS: dict[str, str]`, `expand(name) -> str` |
| `viewgen/` | Base and calculated view SQL, DDL, publish, preview | `build_base_select(...)`, `build_view_ddl(...) -> list[str]`, `publish(engine, ...) -> Publication` |
| `api/` | FastAPI app and routers (§7) | `create_app(settings) -> FastAPI` |
| `mapping/evaluate.py` | Evaluation CLI (§9) | `python -m app.mapping.evaluate` |

Core types live in `app/mapping/types.py`. They are frozen dataclasses: `ColumnRef(schema, table, column)`, `ColumnProfile`, `SchemaInfo`, `JoinPlan`, `Candidate`, `Decision`, `FieldMapping` and `MatchResult`.

New backend dependencies:
- `fastapi`, `uvicorn[standard]` and `pydantic-settings`;
- `cryptography`, for Fernet;
- `fastembed`, for the embeddings;
- `openai`;
- `httpx`, for tests.

### 2.2 Frontend (`frontend/`)

- **Stack:** Vite + React 18 + TypeScript + Mantine 7. The data layer is TanStack Query.
- **Pages:** `ConnectionsPage` and `MappingPage`.
- **Running it:** the Vite dev server sends `/api` to `http://localhost:8000`, and `npm run dev` starts the app.
- **Tests:** Vitest + React Testing Library.

---

## 3. Introspection and profiling

### 3.1 Introspection
`introspect(engine, schemas)` uses `sqlalchemy.inspect` to collect, for every table in the configured schemas:
- the columns, with their SQL type and nullability;
- the primary key and declared foreign keys;
- the row count, from `SELECT COUNT(*)`.

The `lending_rpt` and `lending_rpt_eval` schemas are always excluded.

### 3.2 Normalised types
SQL types are mapped to catalog types:

| SQL type | Catalog type |
|---|---|
| `VARCHAR`/`CHAR`/`TEXT` | string |
| `INTEGER`/`BIGINT`/`SMALLINT` | integer |
| MySQL `TINYINT(1)` and `BOOLEAN` | boolean |
| `NUMERIC`/`DECIMAL`/`FLOAT`/`DOUBLE` | decimal |
| `DATE`/`TIMESTAMP`/`DATETIME` | date |

Anything else becomes `other`, and an `other` column is never matched.

**Type compatibility (column → field):**
- types are equal; or
- integer → decimal; or
- string → enum; or
- integer → boolean, only when the column's distinct values are a subset of {0, 1}.

### 3.3 `ColumnProfile`
Each column's profile is computed with aggregate SQL over `(SELECT … FROM t LIMIT 50000)`. If that limit kicks in, `sampled = true`.

| Attribute | Meaning |
|---|---|
| `ref`, `sql_type`, `type`, `is_pk`, `fk_to` | identity and type |
| `null_pct`, `distinct_count` | completeness and cardinality |
| `unique` | `distinct_count == non-null count` |
| `min`, `max` | numeric and date columns only |
| `len_min`, `len_max` | string columns only |
| `patterns` | string columns: up to 3 `(pattern, share)` pairs over the most frequent masked forms. Letters become `A`, digits become `9`, other characters are kept, and runs longer than 12 are truncated with `…`. |
| `enum_overlap` | for columns with ≤ 20 distinct values: `{field_id: share}` for each catalog enum field, where share is the fraction of distinct values (compared upper-cased and trimmed) that are in the field's `values`; only shares ≥ 0.5 are kept |

The distinct values themselves are used only to compute `enum_overlap` and boolean compatibility. They are **never persisted, logged, or sent to the LLM**.

---

## 4. Matching

### 4.1 Join plan first (`joins/`)

1. **Choose the grain.** Candidates are tables with a single-column PK. Each candidate's score is the sum of:
   - **3 ×** the number of other tables linked to it. A table counts as linked if it has a declared FK to the candidate, or a unique column whose normalised name equals the candidate's PK name;
   - **2 ×** `row_count / max_row_count`;
   - **1 ×** `key_scorer(pk_column, "application_id")`, which is Layer A's score, else Layer B's cosine.

   The highest score wins. Ties are broken by column count, then by table name.
2. **Choose the joins.** For each other table:
   - **one-to-one LEFT JOIN:** the table has a unique column linked to the grain PK (by FK or by the same normalised name);
   - **many-to-one LEFT JOIN:** the grain has an FK to the table's PK, or a column whose normalised name equals that PK name, for example `customer_id`.
   - **Excluded with a warning:** any other table, including tables whose link column isn't unique, since joining them would duplicate rows.
3. **Key columns.**
   - The grain PK is fixed as the source of `application_id`.
   - The *non-grain side* of every join condition is a key column and is left out of matching. That covers `kyc_verification.application_id`, `TBL_APPL_RISK.APPL_NO`, and `customer.customer_id`.
   - Grain-side columns of a many-to-one join (`loan_application.customer_id`) are ordinary data columns and are matched normally. So `customer_id` is sourced from the grain table, and the view needs no join just to read it.

`JoinPlan = {grain: ColumnRef, joins: [{table, kind: one_to_one|many_to_one, on: [(grain_col, table_col)]}], excluded: [{table, reason}]}`.

### 4.2 Layer A: rules and synonyms
`norm(s)` lower-cases the name, splits camelCase, and joins words with `_` (`NetMthInc` → `net_mth_inc`).

A column is **decided by A** when all three of these hold:
- `norm(column)` equals `norm(field.id)` or `norm(s)` for a *non-masked* synonym `s`;
- the types are compatible (§3.2);
- exactly one field satisfies this.

A's score is 1.0 and its reason is `"name matches synonym 'cib_scr'"`. A does no abbreviation expansion and no fuzzy matching.

### 4.3 Layer B: embedding shortlist
- **Column text:**
  `"column {COLUMN} in table {TABLE} ({expand(column)}). {type}{, range MIN–MAX}{, length A–B}{, pattern P}{, X% null}{, unique}"`
- **`expand`** splits the normalised name on `_` and replaces each token found in `ABBREVIATIONS`. The list is fixed: about 70 generic Indian-lending abbreviations in `matcher/abbreviations.py`, for example `appl→application`, `dt→date`, `no→number`, `nm→name`, `cust→customer`, `amt→amount`, `req→requested`, `tnr→tenure`, `sts→status`, `chnl→channel`, `mth→monthly`, `inc→income`, `grs→gross`, `emplr→employer`, `cib→cibil`, `scr→score`, `os→outstanding`, `obl→obligation`, `dpd→days past due`, `enq→enquiries`, `wo→write off`, `bs→bank statement`, `amb→average monthly balance`, `bnc→bounce`, `sanc→sanctioned`, `roi→rate of interest`, `disb→disbursement`, `pf→processing fee`.
- **Field text:**
  `"{label}. {description} Type {type}{, unit}. Also known as: {non-masked synonyms}."`
- **Shortlist:** only raw fields with a compatible type are scored. They're ranked by cosine similarity between the normalised embeddings, and the top **k = 5** are kept.
- **When B decides:** if `top1 ≥ MAPPER_B_ACCEPT` (default **0.85**) and `top1 − top2 ≥ MAPPER_B_MARGIN` (default **0.05**). Otherwise the column goes to C.
  - If C is disabled (missing key, or the evaluation config is A or A+B), B decides with its top candidate, and warns `low_confidence` if it fell below the thresholds.
- **Caching:** field embeddings are cached in memory, keyed by `(catalog version, masked-synonym set)`.

**Known limitation.** The abbreviation list was written knowing Client 2's naming style. The blind test (§9) measures what happens when synonyms are lost, not how the matcher handles unfamiliar abbreviations. The evaluation report states this.

### 4.4 Layer C: LLM choice
- **Batching:** one request per source table, covering the columns B didn't decide.
- **Model settings:** OpenAI Chat Completions, `temperature=0`, with `response_format` set to a strict JSON schema.
- **Request content:**
  - **system:** the role, the rules (choose only from the candidates or null; explain briefly; report suspected transforms; never invent a field);
  - **user:** the table name, all column names in the table (names only, for context), and for each undecided column:
    - its profile, minus anything that isn't listed in §3.3;
    - its `enum_overlap`;
    - its candidate list `[{field_id, label, description, type, unit, values (enum only), cosine}]`.
- **Response schema:**
  `{"columns": [{"column": str, "field_id": str|null, "confidence": number, "reason": str, "suspected_transform": str|null}]}`
- **Validation:**
  - a `field_id` that isn't in that column's shortlist becomes `null`, with the warning `llm_invalid_choice`;
  - a missing column falls back to B's top candidate, with the warning `llm_missing`;
  - confidence is clamped to [0, 1].
- **Failures:** two retries with backoff (1 s, 4 s) on timeouts, 5xx errors, 429s and schema errors. After that, the whole table's undecided columns fall back to B's top candidate with the warning `llm_failed`.
- **The key:**
  - `OPENAI_API_KEY` is read only by `settings.py`;
  - it is never logged and never stored;
  - if it's missing, Layer C is disabled and the run records the warning `llm_disabled`.
- **Testability:** the client is injected through a small `ChatClient` protocol, so tests use a fake.

### 4.5 Assignment
1. **Collect candidates:** every (non-key column, field, score) triple:
   - A decisions give score 1.0;
   - B decisions give their cosine;
   - C choices give `confidence`;
   - the remaining shortlist entries of each column are kept, with their B cosine × 0.9, as fallbacks.
2. **Assign greedily:** sort by score descending, with ties broken by A > C > B, then by column order. Assign a pair when the field is still free and the column is still unused. A column whose chosen field is already taken moves on to its next candidate.
3. **Add key columns:** they're added as fixed mappings (§4.1) before step 2, so they take priority.
4. **Output:** a `FieldMapping` for each of the 59 raw fields, holding:
   - `source: ColumnRef | None` and `score`;
   - `decided_by: A|B|C|key|none` and `reason`;
   - `warnings: list[str]`;
   - `candidates: list[{ColumnRef, score}]`, up to 5 alternatives from any columns that listed this field.

---

## 5. Views and publishing (`viewgen/`)

### 5.1 Base view `lending_rpt.applications_base`
SQLAlchemy Core:
- `FROM` the grain table, then a `LEFT OUTER JOIN` for each join in the plan;
- a SELECT list of exactly the 59 raw fields, in catalog order:
  - **mapped field:** `src.col` if the types match exactly, otherwise `CAST(src.col AS <catalog SQL type>)`;
  - **unmapped or `not_available` field:** `CAST(NULL AS <catalog SQL type>)`.

Catalog SQL types:

| Catalog type | SQL type |
|---|---|
| string / enum | `String(255)` |
| integer | `Integer` |
| decimal | `Numeric(18, 4)` |
| date | `Date` |
| boolean | `Boolean` on Postgres; on MySQL, booleans pass through uncast and NULL becomes `CAST(NULL AS SIGNED)` |

### 5.2 Calculated view `lending_rpt.applications`
`SELECT b.*, <calculated_expressions(catalog, lambda fid: b.c[fid])> FROM lending_rpt.applications_base AS b`, giving 81 columns. A calculated field whose inputs are NULL evaluates to NULL; Part 1 guarantees this.

### 5.3 DDL and publish
- **SQL generation:** both SELECTs are compiled with `literal_binds` for the connection's dialect. The Part 1 test suite already guards that this works on both databases.
- **Postgres** (one transaction):
  1. `CREATE SCHEMA IF NOT EXISTS lending_rpt`
  2. `DROP VIEW IF EXISTS lending_rpt.applications`
  3. `DROP VIEW IF EXISTS lending_rpt.applications_base`
  4. create the base view
  5. create the calculated view
- **MySQL:**
  1. `CREATE DATABASE IF NOT EXISTS lending_rpt`
  2. `CREATE OR REPLACE VIEW` for the base view
  3. `CREATE OR REPLACE VIEW` for the calculated view

  This is not atomic (MySQL DDL isn't transactional). Postgres doesn't need the same compromise.
- **Checks after creating:**
  1. `COUNT(*)` of the base view equals `COUNT(*)` of the grain table;
  2. `SELECT * FROM lending_rpt.applications LIMIT 1` runs.

  If either fails, Postgres rolls back, MySQL drops both views, and the publish fails with the reason.
- **Preconditions** (otherwise `409` with a list of blockers):
  - the run's status is `ready` or `published`;
  - the join plan is confirmed;
  - all 16 `required_for_mapping` fields have a source and are not `not_available`.
- **Record:** a `publication` row stores the DDL text, row count and timestamp, and the run's status becomes `published`.
- **Schema parameter:** `publish(..., schema="lending_rpt")`. The evaluation passes `lending_rpt_eval`.
- **Preview:** `preview(engine, run, limit)` executes the base SELECT plus the calculated expressions with `LIMIT`, without creating anything. Rows are returned to the caller only.

**Infrastructure change:**
- `docker/mysql-init/01-grants.sql` gains ``GRANT ALL ON `lending_rpt_eval`.* TO 'bfs'@'%'``.
- The README documents the one-off command for an already-initialised container:
  `docker compose exec client2 mysql -uroot -prootpw -e "GRANT ALL ON lending_rpt_eval.* TO 'bfs'@'%'"`
- Postgres needs nothing; `novabank` owns its database.

---

## 6. App storage (`store/`)

The SQLite path comes from `BANKREPORTER_DB`, default `data/bankreporter.sqlite`. `data/` is git-ignored. Tables are created at startup with `create_all`; there are no migrations in the POC.

| Table | Columns |
|---|---|
| `connection` | `id`, `name` (unique), `dialect`, `url_encrypted`, `schemas` (JSON list), `created_at`, `updated_at` |
| `mapping_run` | `id`, `connection_id`, `catalog_version`, `layers` (e.g. `"ABC"`), `status` (running / ready / failed / published), `join_plan` (JSON), `join_plan_confirmed`, `profiles` (JSON, statistics and patterns only), `warnings` (JSON), `error`, `llm_calls`, `llm_tokens`, `created_at`, `finished_at` |
| `mapping_entry` | `run_id`, `field_id` (PK together), `source_schema`, `source_table`, `source_column`, `score`, `decided_by`, `reason`, `warnings` (JSON), `candidates` (JSON), `status` (suggested / accepted / overridden / not_available / unmapped) |
| `publication` | `id`, `run_id`, `schema`, `ddl`, `row_count`, `published_at` |

Runs are snapshots. Re-running creates a new run, and the page shows the latest one.

---

## 7. API (`/api`)

| Method & path | Body → response |
|---|---|
| `GET /catalog` | the catalog as JSON: sections, fields |
| `GET /connections` | `[{id, name, dialect, url_masked, schemas}]` |
| `POST /connections` | `{name, dialect, host, port, database, user, password, schemas}` → connection (masked). Dialect is `postgresql` or `mysql`. |
| `PUT /connections/{id}` | same body as POST; an omitted `password` keeps the existing one |
| `DELETE /connections/{id}` | `204`; deletes its runs too, but the published views remain in the client DB |
| `POST /connections/{id}/test` | `{ok: true, tables: [...]}` or `{ok: false, error}` (masked) |
| `GET /connections/{id}/columns` | `[{schema, table, column, type}]` for the column search |
| `POST /connections/{id}/mapping-runs` | `{layers?: "ABC"}` → `{run_id, status: "running"}`; the pipeline runs in a FastAPI background task |
| `GET /mapping-runs/{id}` | `{run, join_plan, entries[], blockers[], affected_calculated[]}` |
| `GET /connections/{id}/mapping-runs/latest` | same as above, for the latest run |
| `PATCH /mapping-runs/{id}/entries/{field_id}` | `{action: accept\|choose\|not_available\|reset, schema?, table?, column?}` → the entry |
| `POST /mapping-runs/{id}/accept-above` | `{threshold}` → `{accepted: n}` |
| `PUT /mapping-runs/{id}/join-plan` | `{join_plan, confirmed}`; the plan is re-validated for unique join columns |
| `GET /mapping-runs/{id}/preview?limit=20` | `{columns, rows}` |
| `POST /mapping-runs/{id}/publish` | `{ddl, row_count, schema}`, or `409 {blockers}` |

**Field semantics:**
- `blockers` is a list of human-readable strings, such as "Required field CIBIL Score is unmapped" or "Join plan not confirmed".
- `affected_calculated` lists the calculated fields that will always be NULL because one of their raw inputs is unmapped. It's computed through `referenced_fields`, following references transitively.

**Editing rules:**
- `choose` validates that the column exists, that its type is compatible, and that it isn't already the source of another field. A conflict returns `409` naming that field.
- Edits on a `published` run set its status back to `ready`. The views stay as they are until the next publish.

---

## 8. Frontend

### 8.1 Connections page
- **List:** the connections, with their masked URL and buttons for Test, Edit, Delete and "Open mapping".
- **Add/edit form:** name, dialect, host, port, database, user, password and schemas (multiple values). When editing, the password field is empty and labelled "leave blank to keep".

### 8.2 Mapping page
- **Header:**
  - the connection, run number and status;
  - counts: mapped x/59, required y/16, and how many fields each of A/B/C/key/none decided;
  - buttons: Re-run, "Accept all ≥ 0.90", Preview (opens a modal table), and Publish. Publish is disabled while there are blockers, and its tooltip lists them.
  - Banners: "LLM layer off" when the run has `llm_disabled`, and a run error when there is one.
- **Join plan card:**
  - shows the grain and each join on a readable line, plus the excluded tables with their reasons;
  - Edit lets the user pick the grain from the single-PK tables and toggle joins;
  - Confirm sets `confirmed`.
- **Field table:**
  - grouped by catalog section, in collapsible groups;
  - columns: Field (label, id, `*` if required), Source (`table.column`), Confidence (a bar plus the number), By (A/B/C/key chip), Reason (truncated, with a tooltip), Warnings (an icon with a tooltip), and Actions;
  - actions: ✓ accept; ▾ menu with the other candidates plus "Search all columns…" (a searchable select from `/columns`); ⊘ not available; ↺ reset;
  - filters: All, Needs review (score < 0.9 and not accepted, or has warnings), Unmapped, Required.
- **Calculated fields panel:** lists `affected_calculated`.
- **Polling:** while a run is `running`, the page polls `GET /mapping-runs/{id}` every 2 seconds and shows a progress state.

---

## 9. Evaluation (`python -m app.mapping.evaluate`)

### 9.1 Options
```
--clients client1,client2 --mask 0,0.5,1.0 --seeds 1,2,3 --layers A,AB,ABC
[--refresh-llm] [--no-llm] [--out docs/eval]
```

### 9.2 Answer key
For each client, the key is built from that writer's `TABLES`: `field_id → {(table, column), …}`. Any listed column counts as correct for that field; for example, both `customer_id` columns in Client 1 count. The expected grain is `loan_application` for Client 1 and `TBL_LOAN_APPL` for Client 2.

### 9.3 Masking
- **Exact-match synonyms for client X** are the synonyms `s` where `norm(s)` equals the normalised name of any column in X.
- **Masking:** for ratio `r` and seed `t`, remove `round(r × n)` of them, chosen with `random.Random(t)`. The result is a masked catalog copy used by both A and B.
- **Seeds:** ratios 0 and 1.0 are deterministic and run once; the ratios in between run once per seed.

### 9.4 Per-run metrics

| Metric | Definition |
|---|---|
| `field_accuracy` | correct / 59; an unmapped field counts as wrong unless the key also has no column for it |
| `required_accuracy` | correct / 16 |
| per layer | decided count, and precision (correct / decided) |
| errors | `wrong` (mapped to an incorrect column), `unmapped` |
| `join_plan_correct` | the grain matches and every expected table is joined |
| LLM cost | `llm_calls`, `llm_tokens` |

### 9.5 End-to-end check
For layers ABC at each mask level (first seed only):
1. accept every suggestion unchanged;
2. publish to `lending_rpt_eval`;
3. read the whole base view;
4. compare every cell with the golden CSV using `format_value`.

This reports the cell match rate overall, and per field for the fields below 100%.

### 9.6 LLM cache
Responses are stored in `eval/llm-cache/<sha256(model + request JSON)>.json` and reused on later runs; `--refresh-llm` bypasses the cache. `--no-llm` skips the ABC configuration.

### 9.7 Output
- A printed summary table.
- `docs/eval/<date>-mapping-eval.md`: the tables, the per-field errors, the end-to-end results, and a *Threats to validity* section covering the abbreviation-list bias (§4.3), the two synthetic clients, and the cached LLM responses.
- `docs/eval/<date>-mapping-eval.json`.

---

## 10. Error handling

| Situation | Behaviour |
|---|---|
| `BANKREPORTER_SECRET_KEY` missing or invalid | The API refuses to start, with a message including the command to generate a key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| Stored URL can't be decrypted (the key changed) | The connection is shown with `needs_password: true`; editing it requires re-entering the password. |
| Connection or test failure | `{ok: false, error}`, with the URL masked through `mask_url`. |
| Introspection or profiling failure (permissions, timeout) | The run is marked `failed`, its `error` is set (masked), and the page shows it. |
| `OPENAI_API_KEY` missing | Layer C is disabled, the warning `llm_disabled` is recorded, and the run completes with A+B. |
| LLM failure after retries | Per table: the columns fall back to B, with `llm_failed`. |
| Embedding model can't be loaded (first download fails) | The run fails, with a message naming the model and the cache directory. |
| Publish precondition not met | `409 {blockers}`. |
| DDL or check failure on publish | Rolled back (Postgres) or views dropped (MySQL); `500 {error, ddl}` with the masked error. |
| Missing permission on `lending_rpt` | `409`: "user X cannot create objects in lending_rpt on <host>; grant CREATE on that schema". |

---

## 11. Testing

| Area | Tests |
|---|---|
| `connections/` | encrypt/decrypt round trip; the wrong key gives the needs-password state; `mask_url` hides passwords in every URL form |
| `profile/` | patterns, length/min/max, null %, uniqueness, `enum_overlap` and boolean detection, on an SQLite fixture; `sampled` set above the row limit; **no raw values appear in the serialised profile** (an assertion over the JSON) |
| `introspect/` + `profile/` (db) | both clients produce the expected tables, PKs, FKs (Client 1 only) and types |
| `joins/` | handmade `SchemaInfo` shapes: Client 1 style (FKs), Client 2 style (same-name keys, no FKs), an ambiguous tie, a non-unique child table (excluded), an unlinked table (excluded) |
| `matcher/rules.py` | exact synonym hit; a masked synonym gives no decision; an ambiguous synonym gives no decision; type incompatibility blocks a match |
| `matcher/embed.py` (marked `embed`) | real model: `NET_MTH_INC` ranks `net_income_monthly` in the top 1 and `CIB_SCR` ranks `cibil_score` in the top 3 with synonyms masked; type filtering; skipped if the model is unavailable |
| `matcher/llm.py` | fake `ChatClient`: a valid response; a choice outside the shortlist becomes null with `llm_invalid_choice`; a missing column; a malformed JSON retry; failure after retries gives the `llm_failed` fallback; the request payload contains no values outside §3.3 (assertion) |
| `matcher/assign.py` | conflicts resolve by score; the loser falls back to its next candidate; key columns take priority; the `candidates` list is populated |
| `viewgen/` (db) | publishing the **answer-key mapping** on each client produces a base view equal to the golden CSV in every cell; the calculated view returns 81 columns; a not-available field is a typed NULL; a non-unique join fails the row-count check and is rolled back; preview creates nothing |
| `api/` | `TestClient` + temporary SQLite + fake LLM + a fixed embedder stub: connection CRUD (the password is never echoed); run lifecycle; edits (`choose` conflict gives 409); publish blockers give 409; a successful publish (db) |
| `evaluate` | answer-key construction; deterministic masking for a seed; the metric arithmetic on a hand-made result |
| live OpenAI (marked `llm`) | one real call on a small table; skipped without `OPENAI_API_KEY` |
| frontend | Vitest + RTL: the field table renders the groups and filters; the accept/choose/not-available actions call the API; Publish is disabled with the blockers in its tooltip; the connection form never pre-fills the password |

The README gets a manual end-to-end walkthrough:
1. start Docker, the API and the frontend;
2. add both connections;
3. run the mapping;
4. review it;
5. publish;
6. run `SELECT COUNT(*) FROM lending_rpt.applications`.

---

## 12. Out of scope (Part 2)

- Applying transforms (L3–L5). They're detected only as `suspected_transform` warnings.
- Derived metrics proposed by the LLM.
- Authentication, roles and multiple users.
- Detecting schema changes and re-running automatically.
- Grains other than one row per application; one-to-many detail tables (excluded with a warning).
- Reports and dashboards (Part 3).
