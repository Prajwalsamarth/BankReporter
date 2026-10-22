"""Generate synthetic applications and load them into both mock client databases.

    python -m mockdata.generate [--n 2000] [--seed 42] [--reset] [--only client1|client2]
"""
import argparse
from pathlib import Path

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from app.catalog.loader import load_catalog
from mockdata.canonical import build_applications, check_invariants
from mockdata.config import CLIENT1_URL, CLIENT2_URL
from mockdata.golden import write_golden
from mockdata.writers import client1_pg, client2_mysql

ROOT = Path(__file__).parents[1]
CATALOG_PATH = ROOT / "catalog" / "fields.yaml"
GOLDEN_PATH = ROOT / "mockdata" / "golden" / "applications.csv"

WRITERS = {"client1": client1_pg, "client2": client2_mysql}
CLIENT_URLS = {"client1": CLIENT1_URL, "client2": CLIENT2_URL}


def run(n: int = 2000, seed: int = 42, reset: bool = False, only: str | None = None,
        write_golden_file: bool = True) -> list[dict]:
    apps = build_applications(n, seed)
    check_invariants(apps)

    clients = [only] if only else list(WRITERS)
    engines = {name: _connect(name) for name in clients}
    try:
        for name, engine in engines.items():
            writer = WRITERS[name]
            if writer.is_populated(engine) and not reset:
                raise SystemExit(f"{name} schema '{writer.SCHEMA}' not empty; rerun with --reset")
            views = writer.views_depending_on_schema(engine)
            if views:
                raise SystemExit(f"{name}: views outside '{writer.SCHEMA}' depend on it ({', '.join(views)});"
                                 " drop them before reloading")
        for name, engine in engines.items():
            WRITERS[name].write(engine, apps)
            print(f"{name}: loaded {len(apps)} applications into '{WRITERS[name].SCHEMA}'")
    finally:
        for engine in engines.values():
            engine.dispose()

    if write_golden_file:
        catalog = load_catalog(CATALOG_PATH)
        write_golden(GOLDEN_PATH, apps, {f.id: f.type for f in catalog.raw_fields})
        print(f"golden: {GOLDEN_PATH.relative_to(ROOT)}")
    return apps


def _connect(name: str):
    url = CLIENT_URLS[name]
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        engine.dispose()
        shown = make_url(url).render_as_string(hide_password=True)
        raise SystemExit(f"cannot connect to {name} at {shown}; is `docker compose up` running?") from None
    return engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reset", action="store_true", help="drop and recreate the client schemas")
    parser.add_argument("--only", choices=sorted(WRITERS))
    args = parser.parse_args()
    run(n=args.n, seed=args.seed, reset=args.reset, only=args.only)


if __name__ == "__main__":
    main()
