from collections.abc import Callable

from sqlalchemy import ColumnElement

from app.catalog.formula import compile_formula, parse_formula
from app.catalog.models import Catalog


def calculated_expressions(catalog: Catalog,
                           resolve_raw: Callable[[str], ColumnElement]) -> dict[str, ColumnElement]:
    """SQL expression for every calculated field, keyed by field ID in calculation order.

    References to other calculated fields are inlined; raw fields come from `resolve_raw`.
    """
    known = {f.id for f in catalog.fields}
    exprs: dict[str, ColumnElement] = {}

    def resolve(fid: str) -> ColumnElement:
        return exprs[fid] if fid in exprs else resolve_raw(fid)

    for fid in catalog.calculation_order():
        tree = parse_formula(catalog.field(fid).formula, known)
        exprs[fid] = compile_formula(tree, resolve)
    return exprs
