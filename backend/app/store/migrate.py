"""In-place upgrade of an existing app store (spec §2.3). Runs on every start; a second run changes nothing."""
from sqlalchemy import Engine, inspect
from sqlalchemy.schema import CreateTable

ADDED_COLUMNS = {"connection": "client_id", "report_template": "client_id", "dashboard": "client_id"}
REBUILT = ("connection", "report_template", "dashboard")   # tables that lose a global UNIQUE on name


def _unique_on_name(conn, table: str) -> bool:
    for row in conn.exec_driver_sql(f"PRAGMA index_list('{table}')").fetchall():
        index, unique = row[1], row[2]
        columns = [r[2] for r in conn.exec_driver_sql(f"PRAGMA index_info('{index}')").fetchall()]
        if unique and columns == ["name"]:
            return True
    return False


def _rebuild(engine: Engine, table: str) -> None:
    """Recreate `table` from the current model (no global UNIQUE on name), copying every row, atomically.

    Order matters: create <t>_new, copy, drop <t>, rename <t>_new to <t>. Renaming the *old* table instead would
    make SQLite rewrite other tables' foreign keys (mapping_run -> connection) to point at the dropped copy.
    The AUTOINCREMENT counter is carried over so ids of deleted rows are never reused.
    """
    from app.store import Base
    model = Base.metadata.tables[table]
    with engine.connect() as conn:
        old = [c["name"] for c in inspect(conn).get_columns(table)]
        seq = conn.exec_driver_sql("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).scalar()
    create = str(CreateTable(model).compile(engine)).strip()
    prefix = f"CREATE TABLE {table} ("
    assert create.startswith(prefix), create[:60]
    create = f'CREATE TABLE "{table}_new" (' + create[len(prefix):]
    cols = ", ".join(f'"{c}"' for c in old if c in model.c)
    keep_seq = (f'UPDATE sqlite_sequence SET seq = max(seq, {int(seq)}) WHERE name = "{table}"; '
                if seq is not None else "")
    script = (f'BEGIN; {create}; INSERT INTO "{table}_new" ({cols}) SELECT {cols} FROM "{table}"; '
              f'DROP TABLE "{table}"; ALTER TABLE "{table}_new" RENAME TO "{table}"; {keep_seq}COMMIT;')
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
        rebuild = [t for t in REBUILT if t in tables and _unique_on_name(conn, t)]
    for table in rebuild:
        _rebuild(engine, table)
    with engine.begin() as conn:
        insp = inspect(conn)
        for table, column in ADDED_COLUMNS.items():
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" INTEGER REFERENCES client(id)')
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ux_connection_client ON connection(client_id)")
