# BankReporter

An internal proof of concept: a reporting tool for retail personal-loan applications. It connects to a client's database, maps its columns onto a standard field catalog, and builds reports on the mapped data **without copying client data**.

| Part | Status | Spec |
|---|---|---|
| 1. Field catalog, formula compiler, mock client DBs | done | `docs/superpowers/specs/2026-10-22-catalog-and-mock-data-design.md` |
| 2. Data mapping | not started | — |
| 3. Reporting & dashboards | not started | — |

## Setup

Requires Python 3.12 and Docker.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e "backend[dev]"
docker compose up -d --wait          # Postgres 16 on :5433 (client1), MySQL 8.4 on :3307 (client2)
.venv/bin/python -m mockdata.generate --reset
```

`generate` loads the same 2,000 synthetic applications into both clients, each in its own schema:

| Client | Database | Schema |
|---|---|---|
| 1 "NovaBank" | Postgres | `los` (normalised) |
| 2 "Bharat Finserv" | MySQL | `bfs_core` (wide, legacy) |

It also writes `mockdata/golden/applications.csv`, the expected canonical data.

Options:
- `--n` and `--seed` control the volume and the random seed.
- `--only client1|client2` loads one client.
- Without `--reset`, it refuses to overwrite a schema that already has data.
- It also refuses while views in another schema read from the client schema (for example Part 2's `lending_rpt` views), because reloading would drop or break them.
- `CLIENT1_URL` and `CLIENT2_URL` override the connection URLs.

## Tests

```bash
cd backend && ../.venv/bin/pytest -q
```

Tests marked `db` need the Docker databases and are skipped if they aren't reachable. **The writer tests reload both client databases** with the default data (`--n 2000 --seed 42 --reset`).

## Layout

- `catalog/fields.yaml`: the canonical fields (59 raw + 22 calculated) and their formulas.
- `backend/app/catalog/`: loads and validates the catalog, and parses formulas and compiles them to SQL for Postgres, MySQL and SQLite.
- `mockdata/`: the synthetic data generator, the client DDL and the per-client writers.
- `docs/mapping-difficulty-levels.md`: how to make the mock clients harder (levels 3–5).
