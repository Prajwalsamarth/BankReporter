# BankReporter

An internal proof of concept: a reporting tool for retail personal-loan applications. It connects to a client's database, maps its columns onto a standard field catalog, and builds reports on the mapped data **without copying client data**. Reports read views the tool creates in the client's own database.

| Part | Status | Spec |
|---|---|---|
| 1. Field catalog, formula compiler, mock client DBs | done | `docs/superpowers/specs/2026-10-22-catalog-and-mock-data-design.md` |
| 2. Data mapping (matcher, views, API, UI, evaluation) | done | `docs/superpowers/specs/2026-10-22-data-mapping-design.md` |
| 3. Reporting & dashboards | done | `docs/superpowers/specs/2026-10-22-reporting-dashboards-design.md` |

## Sample logins

Open **http://localhost:5173** and sign in. The users are created by `python -m app.auth.seed` (see [Sign in](#sign-in)).

| Username | Password | Sees |
|---|---|---|
| `admin` | `admin123` | every client; switch with the **Client** menu in the header |
| `nova.analyst` | `nova123` | NovaBank only |
| `bharat.analyst` | `bharat123` | Bharat Finserv only |

These are sample passwords for a proof of concept; don't reuse them anywhere real.

## Setup

Requires Python 3.12, Node 18 or later, and Docker.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e "backend[dev]"
(cd frontend && npm install)
docker compose up -d --wait          # Postgres 16 on :5433 (client1), MySQL 8.4 on :3307 (client2)
.venv/bin/python -m mockdata.generate --reset
```

Local settings live in a git-ignored `.env` file in the repo root:

```bash
BANKREPORTER_SECRET_KEY=...   # required; encrypts stored DB passwords. Generate one with:
                              # .venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
OPENAI_API_KEY=sk-...         # optional; enables Layer C (the LLM). Without it, Layers A and B still run.
MAPPER_LLM_MODEL=gpt-4.1-mini # optional
```

**One-off step for a MySQL container created before Part 2.** The setup script only runs when the container is first created, so grant the evaluation schema by hand:
`docker compose exec client2 mysql -uroot -prootpw -e "GRANT ALL ON lending_rpt_eval.* TO 'bfs'@'%'"`

## Run the app

```bash
(cd backend && ../.venv/bin/uvicorn app.main:app --port 8000)   # API
(cd frontend && npm run dev)                                    # UI on http://localhost:5173
```

### Sign in

Create the sample clients and users once. Run this from `backend/`; it's safe to repeat:

```bash
../.venv/bin/python -m app.auth.seed      # --admin-password / --client-password to choose your own
```

| User | Password | Sees |
|---|---|---|
| `admin` | `admin123` | every client: pick one in the header's **Client** menu; creates connections and shared templates |
| `nova.analyst` | `nova123` | NovaBank only |
| `bharat.analyst` | `bharat123` | Bharat Finserv only |

These are sample passwords for a proof of concept. The seed sets a password only when it creates a user; it never changes an existing user's password.

- **Shared and private items:**
  - Shared templates and dashboards are visible to every client, but a client user can only **Save as copy**.
  - Private ones are visible only to their own client.
- **Existing connections:** the seed attaches the "NovaBank" and "Bharat Finserv" connections to their clients by name.
- **Sessions and lockout:** sessions last 12 hours (`BANKREPORTER_SESSION_HOURS`). Five wrong passwords lock an account for 5 minutes.

Walkthrough:
1. **Sign in** as `admin`. **Connections:** add NovaBank (postgresql, localhost:5433, database/user/password `novabank`, schema `los`) and Bharat Finserv (mysql, localhost:3307, database `bfs_core`, user/password `bfs`, schema `bfs_core`). Choose each connection's client, then press **Test** on each.
2. **Open mapping**, then **Run mapping**.
3. Review the field table. Use the **Needs review** and **Unmapped** filters, ✓ to accept, ▾ for other columns, and ⊘ for "not available".
4. **Confirm join plan**, then **Preview**, then **Publish**.
5. Check the result: `SELECT COUNT(*) FROM lending_rpt.applications;` should return the same row count on both clients.

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

## Mock data

`mockdata.generate` loads the same 2,000 synthetic applications into both clients, each in its own schema:

| Client | Database | Schema |
|---|---|---|
| 1 "NovaBank" | Postgres | `los` (normalised) |
| 2 "Bharat Finserv" | MySQL | `bfs_core` (wide, legacy) |

It also writes `mockdata/golden/applications.csv`, the expected canonical data.

Options:
- `--n` and `--seed` control the volume and the random seed.
- `--only client1|client2` loads one client.
- Without `--reset`, it refuses to overwrite a schema that already has data.
- It also refuses while views in another schema read from the client schema, for example the published `lending_rpt` views, because reloading would drop or break them. Drop those views first.
- `CLIENT1_URL` and `CLIENT2_URL` override the connection URLs.

## Mapping evaluation

Run this **from the repo root**, because it imports `mockdata/`:

```bash
.venv/bin/python -m app.mapping.evaluate                 # layers A, AB, ABC × 0/50/100% synonyms masked
.venv/bin/python -m app.mapping.evaluate --no-llm        # skip the LLM layer
```

It writes `docs/eval/<date>-mapping-eval.md` and a `.json` file with the same results. LLM answers are cached in `eval/llm-cache/`; use `--refresh-llm` for fresh ones. The report covers:
- accuracy for each client, layer set and masking level;
- the remaining errors;
- an end-to-end check that the published views match the golden CSV cell for cell;
- threats to validity.

## Tests

```bash
cd backend && ../.venv/bin/pytest -q      # backend
cd frontend && npm test                   # frontend (Vitest)
```

Markers:
- `db` needs the Docker databases.
- `embed` needs the local embedding model, which downloads to `data/models/` on first use.
- `llm` needs `OPENAI_API_KEY`.

Tests whose requirements aren't met are skipped. The writer tests reuse the default data if it's already loaded; otherwise they reload both clients with `--n 2000 --seed 42 --reset`.

## Layout

- `catalog/fields.yaml`: the canonical fields (59 raw + 22 calculated) and their formulas.
- `backend/app/catalog/`: loads and validates the catalog, and parses and compiles formulas to SQL for Postgres, MySQL and SQLite.
- `backend/app/mapping/`:
  - introspection, profiling and the join planner;
  - `matcher/`: Layer A rules, Layer B embeddings, Layer C OpenAI, and the assignment step;
  - view generation, publishing, and the evaluation tool.
- `backend/app/auth/`: passwords, sessions, the seed command and the visibility rules.
- `backend/app/api/`: the FastAPI app (`app.main:app`). `backend/app/store/` is the app's SQLite file (`data/bankreporter.sqlite`), which holds metadata only.
- `frontend/`: Vite + React + Mantine, with the Connections and Mapping pages.
- `mockdata/`: the synthetic data generator, the client DDL and the per-client writers.
- `docs/mapping-difficulty-levels.md`: how to make the mock clients harder (levels 3–5).
