# BankReporter — Part 1: Canonical Field Catalog & Mock Client Databases

**Date:** 2026-10-22
**Status:** Draft for review
**Project root:** `/Users/psamarth/Desktop/BankReporter` (local git repo, no remote)

---

## 0. Context: the whole project

BankReporter is an **internal proof-of-concept** reporting tool for retail lending (personal loans) at banks. The question it answers: *can we connect to an arbitrary client lending database, automatically map its columns onto a standard field catalog, and then build reports/dashboards on top — without ever copying client data?*

Success = mapping quality on two deliberately different client schemas, demonstrated by an end-to-end flow: connect DB → auto-map → review → create report/dashboard.

The project is split into three sub-projects, each with its own spec → plan → implementation cycle:

| Part | Scope | Depends on |
|---|---|---|
| **1 (this spec)** | Canonical field catalog, formula compiler, two mock client DBs, synthetic data generator | — |
| 2 | Data mapping: connect, introspect, auto-suggest column→field, review page, generate views in client DB | Part 1 |
| 3 | Reporting & dashboarding: template-based reports and dashboards over the canonical views | Parts 1, 2 |

### Project-wide decisions (binding on all parts)

- **Domain scope:** personal loans only; lifecycle from application through disbursement. No post-disbursement performance (EMI schedule, DPD on the loan itself, NPA). One primary applicant per application; no co-applicants.
- **Stack:** Python 3.12 backend (FastAPI, SQLAlchemy 2.x, Pydantic 2), React frontend (Part 3).
- **No client data at rest in the app.** The app creates **views** in a dedicated `lending_rpt` schema (Postgres) / database (MySQL) inside each client DB, and reports query those views live. The app's own config (catalog, mappings, templates, dashboards) lives in a local SQLite file. No client rows are ever copied into it.
- **"Any DB"** means any SQLAlchemy-supported SQL database; the POC proves it with Postgres 16 and MySQL 8.
- **Calculated fields** are defined once in a dialect-neutral formula language over canonical field IDs and compiled to SQLAlchemy expressions per dialect. Calculated fields are **row-level within one application**. Aggregations over detail tables (if a future client has them) are handled in Part 2's base view, not in formulas.
- **Mapping difficulty:** the POC's two clients differ only in **naming (L1)** and **structure (L2)**. Levels 3–5 are documented (see §6), not built.

---

## 1. Part 1 deliverables

1. `catalog/fields.yaml` — the canonical field catalog (59 raw + 22 calculated fields, §3).
2. `backend/app/catalog/` — Pydantic models, loader + validator, formula parser/compiler.
3. `docker-compose.yml` — Postgres 16 (Client 1) and MySQL 8 (Client 2).
4. `mockdata/` — DDL for both clients, a seeded synthetic data generator, per-client writers, and a golden CSV for tests.
5. `docs/mapping-difficulty-levels.md` — the L3–L5 expansion guide (§6).

Out of scope for Part 1: schema introspection, auto-matching, view generation (Part 2); any UI, reports, dashboards (Part 3).

---

## 2. Repository layout

```
BankReporter/
  docker-compose.yml
  .gitignore                        # mockdata/golden/, .venv, __pycache__, *.sqlite
  backend/
    pyproject.toml                  # python 3.12; sqlalchemy>=2.0, pyyaml, pydantic>=2,
                                    # psycopg[binary], pymysql, faker, pytest
    app/__init__.py
    app/catalog/
      __init__.py
      models.py                     # Section, Field, Catalog (Pydantic)
      loader.py                     # load_catalog(path) -> Catalog; raises CatalogError
      formula.py                    # parse_formula(), infer_type(), compile_formula()
      dialect_funcs.py              # DATE_DIFF_DAYS, YEARS_BETWEEN, MONTH_START per dialect
    tests/
      conftest.py                   # db fixtures; @pytest.mark.db skipped if DBs unreachable
      catalog/test_loader.py
      catalog/test_formula.py
      mockdata/test_generate.py
  catalog/fields.yaml
  mockdata/
    __init__.py
    config.py                       # connection URLs (env-overridable)
    canonical.py                    # build_applications(n, seed) -> list[dict] keyed by field id
    generate.py                     # CLI entry: python -m mockdata.generate [--n 2000] [--seed 42] [--reset]
    ddl/client1_postgres.sql
    ddl/client2_mysql.sql
    writers/client1_pg.py
    writers/client2_mysql.py
    golden/applications.csv         # generated; git-ignored
  docs/
    superpowers/specs/              # this spec
    mapping-difficulty-levels.md
  frontend/                         # Part 3
```

---

## 3. Canonical field catalog

### 3.1 YAML format

```yaml
version: 1
sections:
  - id: application
    label: "Application"
  # ... one entry per section in §3.3

fields:
  - id: cibil_score              # snake_case, unique, immutable once used
    label: "CIBIL Score"
    section: bureau              # must reference a declared section
    kind: raw                    # raw | calculated
    type: integer                # string | integer | decimal | date | boolean | enum
    values: null                 # required (non-empty list) iff type == enum
    role: measure                # dimension | measure
    default_agg: avg             # required iff role == measure: sum|avg|min|max|count|count_distinct
    unit: null                   # optional: INR | months | days | years | pct | ratio
    nullable: true
    pii: false                   # report builder masks pii fields by default
    required_for_mapping: true   # raw only; mapping is "complete" only when all such fields are mapped
    synonyms: [cibil, bureau_score, credit_score, cb_score]   # hints for Part 2 matcher
    description: "CIBIL TransUnion score at application (300–900); null if new-to-credit."

  - id: foir_pct
    kind: calculated
    formula: "existing_emi_monthly / net_income_monthly * 100"   # required iff kind == calculated
    # ... other keys as above; calculated fields omit required_for_mapping
```

Defaults when omitted: `values: null`, `unit: null`, `nullable: true`, `pii: false`, `required_for_mapping: false`, `synonyms: []`, `description: ""`.

### 3.2 Validation rules (all errors collected, reported together)

1. Field and section IDs unique; IDs match `^[a-z][a-z0-9_]*$`.
2. Every `field.section` references a declared section.
3. `type == enum` ⇔ `values` is a non-empty list of unique strings.
4. `role == measure` ⇔ `default_agg` set.
5. `kind == calculated` ⇔ `formula` set; calculated fields must not set `required_for_mapping: true`.
6. Every formula parses under §4 rules, references only existing field IDs, and the dependency graph over calculated fields is acyclic.
7. Inferred formula result type is compatible with declared `type` (§4.4).

`load_catalog(path)` raises `CatalogError(errors: list[str])`, where each message is prefixed with the field ID, e.g. `foir_pct: unknown field 'net_incom_monthly' (col 24)`.

### 3.3 Field list

`Req` = `required_for_mapping`. `D`/`M` = dimension/measure (with default agg). PII marked †.

**Application (`application`)**

| id | type | role | Req | notes |
|---|---|---|---|---|
| application_id | string | D | ✓ | primary key of the canonical grain |
| application_date | date | D | ✓ | |
| channel | enum | D | ✓ | BRANCH, DSA, WEB, MOBILE_APP, PARTNER |
| branch_code | string | D | | |
| requested_amount | decimal (INR) | M sum | ✓ | |
| requested_tenure_months | integer | M avg | | |
| loan_purpose | enum | D | | MEDICAL, EDUCATION, WEDDING, HOME_RENOVATION, TRAVEL, DEBT_CONSOLIDATION, CONSUMER_DURABLE, OTHER |
| application_status | enum | D | ✓ | SUBMITTED, IN_REVIEW, APPROVED, REJECTED, DISBURSED, WITHDRAWN |

**Applicant (`applicant`)**

| id | type | role | Req | notes |
|---|---|---|---|---|
| customer_id | string | D | ✓ | |
| applicant_name † | string | D | | |
| date_of_birth † | date | D | ✓ | |
| gender | enum | D | | MALE, FEMALE, OTHER |
| marital_status | enum | D | | SINGLE, MARRIED, DIVORCED, WIDOWED |
| education | enum | D | | BELOW_GRADUATE, GRADUATE, POST_GRADUATE, PROFESSIONAL |
| residence_type | enum | D | | OWNED, RENTED, PARENTAL, COMPANY_PROVIDED |
| years_at_residence | integer | M avg | | |
| city | string | D | | |
| state | string | D | ✓ | |
| pincode | string | D | | |

**KYC (`kyc`)**

| id | type | role | Req | notes |
|---|---|---|---|---|
| pan_number † | string | D | | format `AAAAA9999A` |
| aadhaar_masked † | string | D | | `XXXX-XXXX-1234` |
| ckyc_number † | string | D | | 14 digits; nullable |
| kyc_status | enum | D | ✓ | VERIFIED, PENDING, FAILED |
| kyc_verified_date | date | D | | |
| kyc_mode | enum | D | | VIDEO_KYC, IN_PERSON, DIGILOCKER, OFFLINE_XML |

**Employment & income (`employment`)**

| id | type | role | Req | notes |
|---|---|---|---|---|
| employment_type | enum | D | ✓ | SALARIED, SELF_EMPLOYED_PROFESSIONAL, SELF_EMPLOYED_BUSINESS |
| employer_category | enum | D | | GOVT, PSU, MNC, LISTED_PVT, UNLISTED_PVT, SELF |
| employer_name | string | D | | |
| gross_income_monthly | decimal (INR) | M avg | | |
| net_income_monthly | decimal (INR) | M avg | ✓ | |
| years_in_current_job | decimal (years) | M avg | | |
| total_experience_years | decimal (years) | M avg | | |

**Bureau (`bureau`)**

| id | type | role | Req | notes |
|---|---|---|---|---|
| cibil_score | integer | M avg | ✓ | 300–900; null = new-to-credit |
| bureau_pull_date | date | D | | |
| active_accounts | integer | M avg | | |
| total_outstanding | decimal (INR) | M sum | | |
| existing_emi_monthly | decimal (INR) | M avg | ✓ | 0 if none |
| oldest_account_age_months | integer | M avg | | null if NTC |
| card_utilization_pct | decimal (pct) | M avg | | null if no cards |
| dpd30_count_l12m | integer | M avg | | |
| dpd90_count_l12m | integer | M avg | | |
| enquiries_l6m | integer | M avg | | |
| has_writeoff | boolean | D | | |

**Bank statement analysis (`banking`)** — stored pre-summarised in both clients.

| id | type | role | Req | notes |
|---|---|---|---|---|
| bank_months_analysed | integer | M avg | | |
| avg_monthly_balance | decimal (INR) | M avg | | |
| avg_monthly_credits | decimal (INR) | M avg | | |
| avg_monthly_debits | decimal (INR) | M avg | | |
| bounce_count | integer | M sum | | |
| salary_regularity | enum | D | | REGULAR, IRREGULAR, NOT_APPLICABLE |

**Decision (`decision`)** — null for SUBMITTED / IN_REVIEW / WITHDRAWN.

| id | type | role | Req | notes |
|---|---|---|---|---|
| decision_date | date | D | ✓ | |
| decision_mode | enum | D | | AUTO, MANUAL |
| rejection_reason | enum | D | | LOW_CIBIL, HIGH_FOIR, WRITEOFF_HISTORY, KYC_FAILED, INSUFFICIENT_INCOME, POLICY_OTHER; null unless REJECTED |
| approved_amount | decimal (INR) | M sum | ✓ | null unless APPROVED/DISBURSED |
| interest_rate_pct | decimal (pct) | M avg | | |
| approved_tenure_months | integer | M avg | | |
| approved_emi | decimal (INR) | M avg | | |

**Disbursement (`disbursement`)** — null unless DISBURSED.

| id | type | role | Req | notes |
|---|---|---|---|---|
| disbursement_date | date | D | | |
| disbursed_amount | decimal (INR) | M sum | ✓ | |
| processing_fee | decimal (INR) | M sum | | |

Total: **59 raw fields**, 16 with `required_for_mapping`.

**Calculated fields (22)**

| id | section | type | formula |
|---|---|---|---|
| age_at_application | applicant | integer | `YEARS_BETWEEN(date_of_birth, application_date)` |
| age_band | applicant | enum(<25, 25-34, 35-44, 45-54, 55+) | `CASE(age_at_application < 25, '<25', age_at_application < 35, '25-34', age_at_application < 45, '35-44', age_at_application < 55, '45-54', '55+')` |
| income_band | employment | enum(<25K, 25-50K, 50K-1L, 1-2L, 2L+) | `CASE(net_income_monthly < 25000, '<25K', net_income_monthly < 50000, '25-50K', net_income_monthly < 100000, '50K-1L', net_income_monthly < 200000, '1-2L', '2L+')` |
| is_new_to_credit | bureau | boolean | `cibil_score is None` |
| cibil_band | bureau | enum(NTC, <650, 650-699, 700-749, 750-799, 800+) | `CASE(cibil_score is None, 'NTC', cibil_score < 650, '<650', cibil_score < 700, '650-699', cibil_score < 750, '700-749', cibil_score < 800, '750-799', '800+')` |
| has_delinquency_l12m | bureau | boolean | `dpd30_count_l12m > 0 or dpd90_count_l12m > 0` |
| foir_pct | decision | decimal | `existing_emi_monthly / net_income_monthly * 100` |
| post_loan_foir_pct | decision | decimal | `(existing_emi_monthly + COALESCE(approved_emi, 0)) / net_income_monthly * 100` |
| loan_to_income_ratio | decision | decimal | `requested_amount / (net_income_monthly * 12)` |
| bank_credit_to_income_pct | banking | decimal | `avg_monthly_credits / net_income_monthly * 100` |
| balance_to_emi_ratio | banking | decimal | `avg_monthly_balance / approved_emi` |
| is_approved | decision | boolean | `application_status in ['APPROVED', 'DISBURSED']` |
| is_rejected | decision | boolean | `application_status == 'REJECTED'` |
| is_disbursed | disbursement | boolean | `application_status == 'DISBURSED'` |
| approved_to_requested_pct | decision | decimal | `approved_amount / requested_amount * 100` |
| net_disbursed_amount | disbursement | decimal | `disbursed_amount - COALESCE(processing_fee, 0)` |
| processing_fee_pct | disbursement | decimal | `processing_fee / disbursed_amount * 100` |
| kyc_tat_days | kyc | integer | `DATE_DIFF_DAYS(application_date, kyc_verified_date)` |
| decision_tat_days | decision | integer | `DATE_DIFF_DAYS(application_date, decision_date)` |
| disbursement_tat_days | disbursement | integer | `DATE_DIFF_DAYS(decision_date, disbursement_date)` |
| end_to_end_tat_days | disbursement | integer | `DATE_DIFF_DAYS(application_date, disbursement_date)` |
| application_month | application | date | `MONTH_START(application_date)` |

Roles: bands, flags and `application_month` are dimensions; ratios/pcts/TATs are measures with `default_agg: avg`; `net_disbursed_amount` is `sum`. Boolean flags additionally support `count`-style aggregation in Part 3 (out of scope here).

---

## 4. Formula language

### 4.1 Syntax

A formula is a Python expression parsed with `ast.parse(formula, mode="eval")`. Only these node types are accepted; any other raises `FormulaError`:

- `Name` — must be a catalog field ID.
- `Constant` — int, float, str, `True`, `False`, `None`.
- `BinOp` with `+ - * /`.
- `UnaryOp` with `-`, `not`.
- `BoolOp` with `and`, `or`.
- `Compare` with **one** operator from `== != < <= > >=`, or `is None` / `is not None` (right-hand side must be the `None` constant), or `in [list of constants]`.
- `Call` to an allow-listed function name (§4.2) with positional args only.

### 4.2 Functions

| Function | Args | Result type | SQL |
|---|---|---|---|
| `COALESCE(a, b, ...)` | ≥2 | type of first arg | `coalesce` |
| `NULLIF(a, b)` | 2 | type of a | `nullif` |
| `ROUND(x, n)` | 2, n int literal | decimal | `round` |
| `ABS(x)` | 1 | type of x | `abs` |
| `LEAST(a, b, ...)` / `GREATEST(...)` | ≥2 | numeric | `least`/`greatest` (MySQL & PG both native) |
| `IF(cond, a, b)` | 3 | type of a | `CASE WHEN cond THEN a ELSE b END` |
| `CASE(c1, v1, c2, v2, ..., else)` | odd ≥3 | type of v1 | `CASE WHEN ... ELSE ... END` |
| `DATE_DIFF_DAYS(start, end)` | 2 dates | integer | PG: `(end - start)`; MySQL: `DATEDIFF(end, start)` |
| `YEARS_BETWEEN(start, end)` | 2 dates | integer (completed years) | PG: `date_part('year', age(end, start))::int`; MySQL: `TIMESTAMPDIFF(YEAR, start, end)` |
| `MONTH_START(d)` | 1 date | date | PG: `date_trunc('month', d)::date`; MySQL: `DATE_SUB(d, INTERVAL DAYOFMONTH(d) - 1 DAY)` |

Dialect-specific functions are SQLAlchemy `FunctionElement` subclasses with `@compiles` per dialect (`postgresql`, `mysql`, `sqlite` for tests). Any other dialect raises `UnsupportedDialect` at compile time with the function name.

### 4.3 Semantics

- **Division** `a / b` always compiles to `a / NULLIF(b, 0)`, and both sides are cast to `Numeric` so integer division never truncates.
- `x == None` is rejected (use `is None`).
- Calculated fields may reference other calculated fields. Compilation resolves references by inlining the referenced field's compiled expression (Part 2 may instead reference a column of the base view; the compiler takes a `resolve(field_id) -> ColumnElement` callback so both work).
- Cycles are detected at load time (rule 6).

### 4.4 Type inference

- Field reference → declared type (enum counts as string).
- Int constant → integer; float → decimal; str → string; bool → boolean; `None` → null (compatible with anything).
- `+ - *` on integer/integer → integer; any decimal involved → decimal. `/` → decimal.
- Compare / `and` / `or` / `not` / `is None` / `in` → boolean.
- Functions per §4.2.
- Compatibility with declared type: exact match, or integer→decimal, or string→enum (and, for enum, every string literal in result positions of `CASE`/`IF` must be in `values`).

### 4.5 Public API (`app/catalog/formula.py`)

```python
class FormulaError(Exception):
    def __init__(self, message: str, col: int | None = None): ...

def parse_formula(formula: str, known_fields: set[str]) -> ast.Expression
def referenced_fields(tree: ast.Expression) -> set[str]
def infer_type(tree: ast.Expression, field_types: dict[str, str]) -> str
def compile_formula(tree: ast.Expression,
                    resolve: Callable[[str], ColumnElement]) -> ColumnElement
```

---

## 5. Mock client databases

### 5.1 Shared rules

- Both clients hold the **same ~2,000 applications** with identical values.
- Same value representation as the catalog: INR amounts as `NUMERIC(14,2)`/`DECIMAL(14,2)`, real `DATE` columns, enum values as the exact catalog strings, booleans as native boolean (PG) / `TINYINT(1)` (MySQL).
- Every catalog raw field exists in both clients; no extra columns (L5 excluded).
- Decision/sanction rows exist only for decided applications; disbursement data only for disbursed ones. Canonical joins are therefore **LEFT JOINs from the application table** (Part 2 must honour this).

### 5.2 Client 1 — "NovaBank" (Postgres 16, schema `los`, normalised, FKs declared)

```sql
customer          (customer_id PK, full_name, date_of_birth, gender, marital_status, education,
                   residence_type, years_at_residence, city, state, pincode)
loan_application  (application_id PK, customer_id FK→customer, applied_on, channel, branch_code,
                   requested_amount, requested_tenure_months, loan_purpose, status)
kyc_verification  (application_id PK FK, pan_number, aadhaar_masked, ckyc_number, kyc_status,
                   verified_on, verification_mode)
employment        (application_id PK FK, employment_type, employer_category, employer_name,
                   gross_monthly_income, net_monthly_income, years_in_current_job, total_experience_years)
bureau_report     (application_id PK FK, cibil_score, pulled_on, active_accounts, total_outstanding,
                   monthly_emi_obligations, oldest_account_age_months, card_utilization_pct,
                   dpd30_l12m, dpd90_l12m, enquiries_l6m, has_writeoff)
bank_analysis     (application_id PK FK, months_analysed, avg_monthly_balance, avg_monthly_credits,
                   avg_monthly_debits, bounce_count, salary_regularity)
credit_decision   (application_id PK FK, decided_on, decision_mode, rejection_reason, approved_amount,
                   interest_rate, approved_tenure_months, emi_amount)
disbursement      (application_id PK FK, disbursed_on, disbursed_amount, processing_fee)
```

About 5% of customers have two applications (exercises the 1-to-many customer→application join).

### 5.3 Client 2 — "Bharat Finserv" (MySQL 8, database `bfs_core`, wide legacy, **no FKs declared**)

```sql
TBL_LOAN_APPL     (APPL_NO PK, CUST_ID, APPL_DT, SRC_CHNL, BR_CD, CUST_NM, CUST_DOB, GNDR, MRTL_STS,
                   EDU_QUAL, RES_TYP, YRS_RES, CITY_NM, STATE_NM, PIN_CD, LN_AMT_REQ, LN_TNR_REQ,
                   LN_PURP, APPL_STS, EMP_TYP, EMPLR_CAT, EMPLR_NM, GRS_MTH_INC, NET_MTH_INC,
                   YRS_CURR_JOB, TOT_EXP_YRS)
TBL_APPL_RISK     (APPL_NO PK, PAN_NO, AADH_MSK, CKYC_NO, KYC_STS, KYC_VRF_DT, KYC_MODE,
                   CIB_SCR, CIB_PULL_DT, CIB_ACT_ACC, CIB_TOT_OS, CIB_EMI_OBL, CIB_OLD_ACC_MTHS,
                   CIB_CC_UTIL, DPD30_12M, DPD90_12M, ENQ_6M, WO_FLG,
                   BS_MTHS, BS_AMB, BS_AVG_CR, BS_AVG_DR, BS_BNC_CNT, BS_SAL_REG)
TBL_SANCTION_DISB (APPL_NO PK, DCSN_DT, DCSN_MODE, REJ_RSN, SANC_AMT, ROI, SANC_TNR, EMI_AMT,
                   DISB_DT, DISB_AMT, PF_AMT)
```

Joins are discoverable only by the shared `APPL_NO` column name.

The exact DDL (types, PKs) lives in `mockdata/ddl/*.sql` and is the source of truth for the writers.

### 5.4 Data generator

`python -m mockdata.generate [--n 2000] [--seed 42] [--reset] [--only client1|client2]`

1. **`canonical.build_applications(n, seed)`** returns a list of dicts keyed by catalog raw field ID. It uses `random.Random(seed)` and `Faker("en_IN")` seeded identically, so the output is deterministic. Distributions:
   - Application dates are uniform over 2025-01-01 → 2026-09-30.
   - Status mix: ~5% SUBMITTED, ~5% IN_REVIEW, ~3% WITHDRAWN; the rest are decided by the rules below.
   - CIBIL: ~8% NTC (null score, null oldest account age); otherwise a clipped normal distribution, mean 730, sd 60, range [300, 900].
   - Net income is log-normal, median ₹55,000; gross ≈ net × U(1.15, 1.30).
   - Existing EMI ≈ net × U(0, 0.45), and 0 for ~25% of applicants.
   - KYC: ~2% FAILED.
2. **Decision rules**, applied in order. The first match rejects, with that reason:
   - KYC FAILED → KYC_FAILED
   - `has_writeoff` → WRITEOFF_HISTORY
   - score < 650 → LOW_CIBIL
   - net income < 15,000 → INSUFFICIENT_INCOME
   - post-loan FOIR (with the EMI computed from the requested amount at the offered rate) > 60% → HIGH_FOIR
   - ~3% random → POLICY_OTHER

   Otherwise APPROVED. The approved amount is the requested amount, or less (×U(0.6, 1.0)) for ~30% of approvals. The rate is 10.5–24% based on the CIBIL band, and the EMI uses the standard amortisation formula. ~85% of approved applications become DISBURSED, with a disbursement date 1–10 days after the decision, the disbursed amount equal to the approved amount, and a processing fee of 1–2.5%.
3. **Invariants (asserted by the generator before writing):**
   - Dates are ordered: application ≤ kyc ≤ decision ≤ disbursement.
   - Rejected applications have no approved, sanction or disbursement fields.
   - disbursed_amount ≤ approved_amount ≤ requested_amount.
   - NTC applicants have a null score.
4. **Writers.** `writers/client1_pg.py` and `writers/client2_mysql.py` each expose `write(engine, applications: list[dict]) -> None`. They map canonical IDs to client columns through a module-level `COLUMN_MAP` and insert using SQLAlchemy Core in batches of 500.
5. **Golden file.** The generator writes `mockdata/golden/applications.csv`: one row per application, with columns equal to the raw field IDs in catalog order. It is used only by tests in Parts 1 and 2 and is git-ignored.
6. **Safety.**
   - The generator checks it can connect, and fails with a clear message naming the URL if it can't.
   - If the target schema already has rows and `--reset` isn't given, it stops with `"client1 schema 'los' not empty; rerun with --reset"`.
   - `--reset` drops and recreates only `los` (Client 1) or `bfs_core` (Client 2).

Connection URLs default to the docker-compose services and can be overridden with `CLIENT1_URL` and `CLIENT2_URL`:
- Client 1: `postgresql+psycopg://novabank:novabank@localhost:5433/novabank`
- Client 2: `mysql+pymysql://bfs:bfs@localhost:3307/bfs_core`

Non-default ports avoid clashing with databases already running locally.

---

## 6. Mapping difficulty levels (documentation deliverable)

`docs/mapping-difficulty-levels.md` describes each level, what to change in Client 2's DDL and writer to introduce it, and what the Part 2 matcher would need:

| Level | Introduce in Client 2 | Matcher capability required |
|---|---|---|
| L1 Naming *(built)* | cryptic upper-case abbreviations | synonym + token similarity on names/descriptions |
| L2 Structure *(built)* | wide tables, no FKs | join-path inference from key-name equality and FK metadata |
| L3 Representation | amounts in lakhs (`LN_AMT_REQ_LAKH`), `GNDR` as `1/2/3`, dates as `VARCHAR 'DD/MM/YYYY'`, status as lookup ID to `MST_STATUS` | per-mapping transform (scale factor, date parse pattern, value map, lookup join); value sampling to detect units/codes |
| L4 Split/merge | `CUST_FNAME/CUST_MNAME/CUST_LNAME`; `ANNUAL_INC` only | many-to-one concat transform; derived-unit transform (`/12`) |
| L5 Missing/extra | drop `CKYC_NO`, add `CRTD_BY`, `LST_UPD_TS` | coverage report; unmapped-required warnings; ignore list |

---

## 7. Error handling

- **Catalog:** if `load_catalog` fails, the app (and tests) fail with every problem listed together, not one at a time.
- **Formulas:** `FormulaError` carries the message and column offset, and the loader adds the field ID in front.
- **Dialects:** `UnsupportedDialect` names the function and dialect.
- **Generator:**
  - A connection failure gives a clear message naming the URL.
  - A non-empty schema without `--reset` stops the run.
  - An invariant violation is an `AssertionError` that names the application ID and the rule broken.

---

## 8. Testing

All tests use pytest under `backend/tests`. Tests marked `@pytest.mark.db` need `docker compose up` and are skipped automatically if the databases are unreachable.

- **Loader**
  - The real `catalog/fields.yaml` loads with 59 raw and 22 calculated fields.
  - One small hand-built YAML per validation rule (§3.2) produces the expected error message.
  - A catalog with several defects reports all of them together.
- **Formula: parsing**
  - Each allowed node and function parses.
  - Disallowed constructs are rejected with the correct column: attribute access, lambdas, subscripts, keyword arguments, unknown functions, chained comparisons, and `== None`.
- **Formula: types**
  - The inference table in §4.4 holds.
  - Enum literals outside `values` are rejected.
- **Formula: execution**
  - Compiled expressions run against SQLite in memory over a small hand-written table and return the expected values.
  - Division by zero returns NULL.
  - Integer division doesn't truncate (`7 / 2 = 3.5`).
- **Formula: dialects** (`db`)
  - `DATE_DIFF_DAYS`, `YEARS_BETWEEN` and `MONTH_START` return the same results on Postgres and MySQL for fixed dates, including a leap-day birthday and a month boundary.
- **Generator: determinism**
  - The same seed gives identical canonical output.
  - A different seed gives different output.
- **Generator: invariants**
  - All §5.4(3) invariants hold over n = 2000.
  - The status mix is within ±3 percentage points of its targets.
- **Writers** (`db`)
  - After generating, both clients' row counts match the canonical counts per table.
  - A spot-check of 20 random applications, read back through hand-written join SQL per client, equals the golden CSV.
  - Running again without `--reset` fails with the expected message.

---

## 9. Out of scope (Part 1)

- Schema introspection, auto-matching, the mapping review page, view DDL generation (Part 2).
- FastAPI endpoints, React UI, report and dashboard builders (Part 3).
- Co-applicants and post-disbursement loan performance.
- Building mapping levels L3–L5 (documented only).
- Authentication and secrets management. Connection URLs are plain environment variables in this POC.
