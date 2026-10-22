"""Per-client writers: map canonical applications onto each client's own tables."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, MetaData, Table, insert, inspect, text

DDL_DIR = Path(__file__).parents[1] / "ddl"
BATCH = 500


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: dict[str, str]                      # client column -> canonical field ID
    include: Callable[[dict], bool] = lambda a: True
    dedupe_on: str | None = None                 # write only the first row per value of this field


def run_ddl(conn: Connection, ddl_path: Path) -> None:
    for statement in ddl_path.read_text().split(";"):
        lines = [ln for ln in statement.splitlines() if not ln.strip().startswith("--")]
        if "".join(lines).strip():
            conn.execute(text("\n".join(lines)))


def write_tables(conn: Connection, schema: str, specs: list[TableSpec], apps: list[dict]) -> None:
    metadata = MetaData()
    for spec in specs:
        table = Table(spec.name, metadata, schema=schema, autoload_with=conn)
        seen: set = set()
        rows = []
        for a in apps:
            if not spec.include(a):
                continue
            if spec.dedupe_on:
                if a[spec.dedupe_on] in seen:
                    continue
                seen.add(a[spec.dedupe_on])
            rows.append({col: a[fid] for col, fid in spec.columns.items()})
        for i in range(0, len(rows), BATCH):
            conn.execute(insert(table), rows[i:i + BATCH])


def dependent_views(engine: Engine, schema: str) -> list[str]:
    """Views in other schemas that read from `schema` (e.g. Part 2's lending_rpt views)."""
    sql = text(
        "SELECT DISTINCT view_schema, view_name FROM information_schema.view_table_usage "
        "WHERE table_schema = :schema AND view_schema <> :schema ORDER BY 1, 2")
    with engine.connect() as conn:
        return [f"{vs}.{vn}" for vs, vn in conn.execute(sql, {"schema": schema})]


def has_tables(engine: Engine, schema: str) -> bool:
    insp = inspect(engine)
    return schema in insp.get_schema_names() and bool(insp.get_table_names(schema=schema))
