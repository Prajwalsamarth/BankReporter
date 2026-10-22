# backend/app/reporting/aggregates.py
"""Aggregate formulas for metrics (spec §2.2).

Part 1's row-level grammar runs inside aggregate calls; outside them only numeric constants,
arithmetic, ROUND/COALESCE and other metric IDs are allowed.
"""
import ast
from collections.abc import Callable

from sqlalchemy import ColumnElement, case, cast, distinct, func, literal

from app.catalog.formula import DIVISION_TYPE, FormulaError, compile_formula, infer_type, parse_formula

AGGREGATES: dict[str, int] = {"COUNT": 0, "COUNT_IF": 1, "SUM": 1, "SUM_IF": 2, "AVG": 1, "AVG_IF": 2,
                              "MIN": 1, "MAX": 1, "COUNT_DISTINCT": 1}
NUMERIC = {"integer", "decimal"}


def _is_aggregate(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in AGGREGATES


def _row_tree(arg: ast.AST, field_types: dict[str, str]) -> ast.Expression:
    if any(_is_aggregate(n) for n in ast.walk(arg)):
        raise FormulaError("nested aggregates are not allowed")
    return parse_formula(ast.unparse(arg), set(field_types))


def parse_aggregate(formula: str, field_types: dict[str, str], metric_ids: set[str]) -> ast.Expression:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"syntax error: {exc.msg}") from None
    _check_outer(tree.body, field_types, metric_ids)
    return tree


def _check_outer(node: ast.AST, field_types: dict[str, str], metric_ids: set[str]) -> None:
    match node:
        case ast.Constant(value=v) if isinstance(v, (int, float)) and not isinstance(v, bool):
            return
        case ast.Name(id=name):
            if name in metric_ids:
                return
            if name in field_types:
                raise FormulaError(f"field '{name}' must be inside an aggregate such as SUM({name})")
            raise FormulaError(f"unknown metric '{name}'")
        case ast.BinOp(op=ast.Add() | ast.Sub() | ast.Mult() | ast.Div(), left=left, right=right):
            _check_outer(left, field_types, metric_ids)
            _check_outer(right, field_types, metric_ids)
            return
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            _check_outer(operand, field_types, metric_ids)
            return
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]):
            if name in AGGREGATES:
                _check_aggregate(name, args, field_types)
                return
            if name == "ROUND":
                if len(args) != 2 or not (isinstance(args[1], ast.Constant) and type(args[1].value) is int):
                    raise FormulaError("ROUND takes an expression and an integer number of digits")
                _check_outer(args[0], field_types, metric_ids)
                return
            if name == "COALESCE":
                if len(args) < 2:
                    raise FormulaError("COALESCE takes at least 2 arguments")
                for a in args:
                    _check_outer(a, field_types, metric_ids)
                return
            raise FormulaError(f"unknown function '{name}'")
    raise FormulaError(f"{type(node).__name__} not allowed outside aggregates")


def _check_aggregate(name: str, args: list[ast.AST], field_types: dict[str, str]) -> None:
    if len(args) != AGGREGATES[name]:
        raise FormulaError(f"{name} takes {AGGREGATES[name]} argument(s), got {len(args)}")
    kinds = [infer_type(_row_tree(a, field_types), field_types) for a in args]

    def need(kind: str, allowed: set[str], what: str) -> None:
        if kind not in allowed:
            raise FormulaError(f"{name} needs a {what} argument, got {kind}")

    if name == "COUNT_IF":
        need(kinds[0], {"boolean"}, "boolean")
    elif name in ("SUM", "AVG"):
        need(kinds[0], NUMERIC, "numeric")
    elif name in ("SUM_IF", "AVG_IF"):
        need(kinds[0], NUMERIC, "numeric")
        need(kinds[1], {"boolean"}, "boolean")
    elif name in ("MIN", "MAX"):
        need(kinds[0], NUMERIC | {"date"}, "numeric or date")


def metric_refs(tree: ast.Expression) -> set[str]:
    refs: set[str] = set()

    def visit(node: ast.AST) -> None:
        if _is_aggregate(node):
            return
        if isinstance(node, ast.Name):
            refs.add(node.id)
        for child in ast.iter_child_nodes(node):
            if not (isinstance(node, ast.Call) and child is node.func):
                visit(child)

    visit(tree.body)
    return refs


def compile_aggregate(tree: ast.Expression, field_types: dict[str, str],
                      resolve_field: Callable[[str], ColumnElement],
                      resolve_metric: Callable[[str], ColumnElement]) -> ColumnElement:
    def row(arg: ast.AST) -> ColumnElement:
        return compile_formula(_row_tree(arg, field_types), resolve_field)

    def c(node: ast.AST) -> ColumnElement:
        match node:
            case ast.Constant(value=v):
                return literal(v)
            case ast.Name(id=name):
                return resolve_metric(name)
            case ast.BinOp(left=left, op=op, right=right):
                lhs, rhs = c(left), c(right)
                if isinstance(op, ast.Add):
                    return lhs + rhs
                if isinstance(op, ast.Sub):
                    return lhs - rhs
                if isinstance(op, ast.Mult):
                    return lhs * rhs
                return cast(lhs, DIVISION_TYPE) / func.nullif(cast(rhs, DIVISION_TYPE), 0)
            case ast.UnaryOp(operand=operand):
                return -c(operand)
            case ast.Call(func=ast.Name(id="ROUND"), args=[x, digits]):
                return func.round(cast(c(x), DIVISION_TYPE), digits.value)
            case ast.Call(func=ast.Name(id="COALESCE"), args=args):
                return func.coalesce(*[c(a) for a in args])
            case ast.Call(func=ast.Name(id=name), args=args):
                xs = [row(a) for a in args]
                match name:
                    case "COUNT":
                        return func.count()
                    case "COUNT_IF":   # COALESCE: SUM over no rows is NULL, a count must be 0
                        return func.coalesce(func.sum(case((xs[0], 1), else_=0)), 0)
                    case "SUM":
                        return func.sum(xs[0])
                    case "SUM_IF":
                        return func.sum(case((xs[1], xs[0])))
                    case "AVG":
                        return func.avg(xs[0])
                    case "AVG_IF":
                        return func.avg(case((xs[1], xs[0])))
                    case "MIN":
                        return func.min(xs[0])
                    case "MAX":
                        return func.max(xs[0])
                    case "COUNT_DISTINCT":
                        return func.count(distinct(xs[0]))
        raise FormulaError(f"cannot compile {type(node).__name__}")

    return c(tree.body)
