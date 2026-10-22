from sqlalchemy import Engine, func, inspect, select, table
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.types import Boolean, Date, DateTime, Integer, Numeric, String, TypeEngine

from app.mapping.types import ColumnInfo, ForeignKey, SchemaInfo, TableInfo

EXCLUDED_SCHEMAS = {"lending_rpt", "lending_rpt_eval"}


def normalise_type(sql_type: TypeEngine) -> str:
    """Map a reflected SQL type to a catalog type (spec §3.2); 'other' is never matched."""
    if isinstance(sql_type, TINYINT) and getattr(sql_type, "display_width", None) == 1:
        return "boolean"
    if isinstance(sql_type, Boolean):
        return "boolean"
    if isinstance(sql_type, Integer):
        return "integer"
    if isinstance(sql_type, Numeric):
        return "decimal"
    if isinstance(sql_type, (Date, DateTime)):
        return "date"
    if isinstance(sql_type, String):
        return "string"
    return "other"


def introspect(engine: Engine, schemas: list[str]) -> SchemaInfo:
    insp = inspect(engine)
    tables = []
    with engine.connect() as conn:
        for schema in schemas:
            if schema in EXCLUDED_SCHEMAS:
                continue
            for name in insp.get_table_names(schema=schema):
                columns = tuple(
                    ColumnInfo(c["name"], str(c["type"]), normalise_type(c["type"]), c["nullable"])
                    for c in insp.get_columns(name, schema=schema)
                )
                pk = tuple(insp.get_pk_constraint(name, schema=schema)["constrained_columns"] or ())
                fks = tuple(
                    ForeignKey(tuple(fk["constrained_columns"]), fk.get("referred_schema") or schema,
                               fk["referred_table"], tuple(fk["referred_columns"]))
                    for fk in insp.get_foreign_keys(name, schema=schema)
                )
                count = conn.execute(select(func.count()).select_from(table(name, schema=schema))).scalar_one()
                tables.append(TableInfo(schema, name, columns, pk, fks, count))
    return SchemaInfo(engine.dialect.name, tuple(tables))
