"""Calculated-field formula language: parse, type-check and compile to SQLAlchemy.

A formula is a restricted Python expression over catalog field IDs (spec §4).
"""
import ast

# name -> (min_args, max_args); max None = unbounded
FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "COALESCE": (2, None),
    "NULLIF": (2, 2),
    "ROUND": (2, 2),
    "ABS": (1, 1),
    "LEAST": (2, None),
    "GREATEST": (2, None),
    "IF": (3, 3),
    "CASE": (3, None),
    "DATE_DIFF_DAYS": (2, 2),
    "YEARS_BETWEEN": (2, 2),
    "MONTH_START": (1, 1),
}

_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_CMP_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


class FormulaError(Exception):
    def __init__(self, message: str, col: int | None = None):
        self.message = message
        self.col = col
        super().__init__(f"{message} (col {col})" if col is not None else message)


def _col(node: ast.AST) -> int | None:
    offset = getattr(node, "col_offset", None)
    return offset + 1 if offset is not None else None


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def parse_formula(formula: str, known_fields: set[str]) -> ast.Expression:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"syntax error: {exc.msg}", exc.offset) from None
    _check(tree.body, known_fields)
    return tree


def _check(node: ast.AST, known: set[str]) -> None:
    match node:
        case ast.Name(id=name):
            if name not in known:
                raise FormulaError(f"unknown field '{name}'", _col(node))
        case ast.Constant(value=value):
            if not (value is None or isinstance(value, (bool, int, float, str))):
                raise FormulaError(f"constant {value!r} not allowed", _col(node))
        case ast.BinOp(left=left, op=op, right=right):
            if not isinstance(op, _BIN_OPS):
                raise FormulaError(f"operator {type(op).__name__} not allowed", _col(node))
            _check(left, known)
            _check(right, known)
        case ast.UnaryOp(op=op, operand=operand):
            if not isinstance(op, (ast.USub, ast.Not)):
                raise FormulaError(f"operator {type(op).__name__} not allowed", _col(node))
            _check(operand, known)
        case ast.BoolOp(values=values):
            for v in values:
                _check(v, known)
        case ast.Compare():
            _check_compare(node, known)
        case ast.Call():
            _check_call(node, known)
        case _:
            raise FormulaError(f"{type(node).__name__} not allowed", _col(node))


def _check_compare(node: ast.Compare, known: set[str]) -> None:
    if len(node.ops) != 1:
        raise FormulaError("chained comparisons not allowed", _col(node))
    op, right = node.ops[0], node.comparators[0]
    _check(node.left, known)
    if isinstance(op, (ast.Is, ast.IsNot)):
        if not _is_none(right):
            raise FormulaError("'is' / 'is not' only allowed with None", _col(node))
    elif isinstance(op, ast.In):
        if not (isinstance(right, ast.List)
                and right.elts
                and all(isinstance(e, ast.Constant) and not _is_none(e) for e in right.elts)):
            raise FormulaError("'in' needs a list of constants", _col(node))
    elif isinstance(op, _CMP_OPS):
        if _is_none(right) or _is_none(node.left):
            raise FormulaError("use 'is None' / 'is not None' to compare with None", _col(node))
        _check(right, known)
    else:
        raise FormulaError(f"operator {type(op).__name__} not allowed", _col(node))


def _check_call(node: ast.Call, known: set[str]) -> None:
    if not isinstance(node.func, ast.Name):
        raise FormulaError("method calls not allowed", _col(node))
    name = node.func.id
    if name not in FUNCTIONS:
        raise FormulaError(f"unknown function '{name}'", _col(node))
    if node.keywords:
        raise FormulaError("keyword arguments not allowed", _col(node))
    n = len(node.args)
    lo, hi = FUNCTIONS[name]
    if name == "CASE":
        if n < 3 or n % 2 == 0:
            raise FormulaError("CASE takes an odd number of arguments (at least 3)", _col(node))
    elif hi is None and n < lo:
        raise FormulaError(f"{name} takes at least {lo} argument(s), got {n}", _col(node))
    elif hi is not None and not lo <= n <= hi:
        raise FormulaError(f"{name} takes {lo} argument(s), got {n}", _col(node))
    if name == "ROUND":
        digits = node.args[1]
        if not (isinstance(digits, ast.Constant) and type(digits.value) is int):
            raise FormulaError("ROUND digits must be an integer literal", _col(digits))
    for arg in node.args:
        _check(arg, known)


def referenced_fields(tree: ast.Expression) -> set[str]:
    func_names = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and id(n) not in func_names
    }
