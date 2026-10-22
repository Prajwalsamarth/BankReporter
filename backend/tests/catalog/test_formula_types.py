import pytest

from app.catalog.formula import (
    FormulaError, infer_type, is_type_compatible, parse_formula, result_literals,
)

TYPES = {
    "i": "integer", "j": "integer", "x": "decimal", "s": "string",
    "e": "enum", "d": "date", "flag": "boolean",
}


def infer(formula: str) -> str:
    return infer_type(parse_formula(formula, set(TYPES)), TYPES)


@pytest.mark.parametrize("formula, expected", [
    ("i", "integer"),
    ("x", "decimal"),
    ("e", "string"),
    ("d", "date"),
    ("1", "integer"),
    ("1.5", "decimal"),
    ("'a'", "string"),
    ("True", "boolean"),
    ("None", "null"),
    ("i + j", "integer"),
    ("i * j - 1", "integer"),
    ("i + x", "decimal"),
    ("i / j", "decimal"),
    ("-i", "integer"),
    ("not flag", "boolean"),
    ("i > j", "boolean"),
    ("flag and i > 1", "boolean"),
    ("s is None", "boolean"),
    ("e in ['A']", "boolean"),
    ("COALESCE(i, 0)", "integer"),
    ("COALESCE(None, x)", "decimal"),
    ("NULLIF(i, 0)", "integer"),
    ("ROUND(i, 0)", "decimal"),
    ("ABS(x)", "decimal"),
    ("LEAST(i, j)", "integer"),
    ("GREATEST(i, x)", "decimal"),
    ("IF(flag, 'a', 'b')", "string"),
    ("IF(flag, None, i)", "integer"),
    ("CASE(i < 1, 'x', 'y')", "string"),
    ("CASE(i is None, None, i < 1, 'x', 'y')", "string"),
    ("DATE_DIFF_DAYS(d, d)", "integer"),
    ("YEARS_BETWEEN(d, d)", "integer"),
    ("MONTH_START(d)", "date"),
])
def test_infer_type(formula, expected):
    assert infer(formula) == expected


@pytest.mark.parametrize("formula, msg", [
    ("s + 1", "arithmetic needs numeric operands"),
    ("d - d", "arithmetic needs numeric operands"),
    ("-s", "arithmetic needs numeric operands"),
    ("DATE_DIFF_DAYS(i, d)", "DATE_DIFF_DAYS needs date arguments"),
    ("MONTH_START(s)", "MONTH_START needs date arguments"),
])
def test_type_errors(formula, msg):
    with pytest.raises(FormulaError) as exc:
        infer(formula)
    assert msg in str(exc.value)


@pytest.mark.parametrize("inferred, declared, ok", [
    ("integer", "integer", True),
    ("integer", "decimal", True),
    ("decimal", "integer", False),
    ("string", "enum", True),
    ("string", "string", True),
    ("null", "date", True),
    ("boolean", "integer", False),
    ("date", "date", True),
])
def test_is_type_compatible(inferred, declared, ok):
    assert is_type_compatible(inferred, declared) is ok


def test_result_literals_collects_case_and_if_results():
    tree = parse_formula("CASE(i < 1, 'A', i < 2, IF(flag, 'B', 'C'), 'D')", set(TYPES))
    assert result_literals(tree) == {"A", "B", "C", "D"}


def test_result_literals_ignores_condition_strings():
    tree = parse_formula("IF(s == 'zz', 'A', None)", set(TYPES))
    assert result_literals(tree) == {"A"}


@pytest.mark.parametrize("formula, msg", [
    ("i == 'abc'", "cannot compare integer with string"),
    ("d > 1", "cannot compare date with integer"),
    ("flag == 1", "cannot compare boolean with integer"),
    ("i in ['A']", "cannot compare integer with string"),
    ("not i", "'not' needs a boolean operand, got integer"),
    ("i and flag", "'and'/'or' need boolean operands, got integer"),
    ("IF(i, 1, 0)", "IF condition must be boolean, got integer"),
    ("CASE(s, 1, 0)", "CASE condition must be boolean, got string"),
    ("CASE(i > 1, 1, 'x')", "CASE results have incompatible types: integer, string"),
    ("IF(flag, d, 1)", "IF results have incompatible types: date, integer"),
    ("COALESCE(i, 'x')", "COALESCE arguments have incompatible types: integer, string"),
])
def test_operand_type_errors(formula, msg):
    with pytest.raises(FormulaError) as exc:
        infer(formula)
    assert msg in str(exc.value)


@pytest.mark.parametrize("formula, expected", [
    ("i == x", "boolean"),
    ("e == 'A'", "boolean"),
    ("s == e", "boolean"),
    ("i in [1, 2]", "boolean"),
    ("flag == True", "boolean"),
    ("IF(flag, i, x)", "decimal"),
    ("CASE(flag, 1, 2.5)", "decimal"),
    ("COALESCE(i, x)", "decimal"),
    ("IF(flag, None, None)", "null"),
])
def test_compatible_mixes(formula, expected):
    assert infer(formula) == expected


def test_result_literals_follow_coalesce_and_nested_calls():
    tree = parse_formula("COALESCE(IF(flag, 'A', NULLIF(s, 'Z')), 'B')", set(TYPES))
    assert result_literals(tree) == {"A", "B"}
