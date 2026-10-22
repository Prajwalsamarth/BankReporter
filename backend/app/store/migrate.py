"""In-place upgrade of an existing app store (spec §2.3). Runs on every start; a second run changes nothing."""
from sqlalchemy import Engine, inspect
from sqlalchemy.schema import CreateTable

ADDED_COLUMNS = {"connection": "client_id", "report_template": "client_id", "dashboard": "client_id"}
OWNED = ("report_template", "dashboard")


def _unique_on_name(conn, table: str) -> bool:
    for row in conn.exec_driver_sql(f"PRAGMA index_list('{table}')").fetchall():
        index, unique = row[1], row[2]
        columns = [r[2] for r in conn.exec_driver_sql(f"PRAGMA index_info('{index}')").fetchall()]
        if unique and columns == ["name"]:
            return True
    return False


def _rebuild(engine: Engine, table: str) -> None:
    """Recreate `table` from the current model (no global UNIQUE on name), copying every row, atomically."""
    from app.store import Base
    model = Base.metadata.tables[table]
    with engine.connect() as conn:
        old = [c["name"] for c in inspect(conn).get_columns(table)]
    create = str(CreateTable(model).compile(engine)).strip()
    cols = ", ".join(f'"{c}"' for c in old if c in model.c)
    script = (f'BEGIN; ALTER TABLE "{table}" RENAME TO "{table}_old"; {create}; '
              f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM "{table}_old"; '
              f'DROP TABLE "{table}_old"; COMMIT;')
    raw = engine.raw_connection()
    try:
        driver = raw.driver_connection
        try:
            driver.executescript(script)
        except Exception:
            if driver.in_transaction:
                driver.execute("ROLLBACK")
            raise
    finally:
        raw.close()


def upgrade(engine: Engine) -> None:
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        rebuild = [t for t in OWNED if t in tables and _unique_on_name(conn, t)]
    for table in rebuild:
        _rebuild(engine, table)
    with engine.begin() as conn:
        insp = inspect(conn)
        for table, column in ADDED_COLUMNS.items():
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" INTEGER REFERENCES client(id)')
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ux_connection_client ON connection(client_id)")
