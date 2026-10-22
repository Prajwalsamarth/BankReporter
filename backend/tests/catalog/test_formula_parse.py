import pytest

from app.catalog.formula import FormulaError, parse_formula, referenced_fields

KNOWN = {"a", "b", "c", "status", "d1", "d2"}


@pytest.mark.parametrize("formula", [
    "a + b - c * 2 / 3.5",
    "-a",
    "not (a > b)",
    "a > 1 and b <= 2 or c != 3",
    "a == b",
    "a >= b",
    "a < b",
    "a is None",
    "a is not None",
    "status in ['X', 'Y']",
    "'text'",
    "True",
    "None",
    "COALESCE(a, b, 0)",
    "NULLIF(a, 0)",
    "ROUND(a, 2)",
    "ABS(a)",
    "LEAST(a, b)",
    "GREATEST(a, b, c)",
    "IF(a > 0, b, c)",
    "CASE(a < 1, 'x', a < 2, 'y', 'z')",
    "DATE_DIFF_DAYS(d1, d2)",
    "YEARS_BETWEEN(d1, d2)",
    "MONTH_START(d1)",
])
def test_allowed_formulas_parse(formula):
    parse_formula(formula, KNOWN)


def reject(formula: str) -> FormulaError:
    with pytest.raises(FormulaError) as exc:
        parse_formula(formula, KNOWN)
    return exc.value


def test_unknown_field():
    err = reject("a + nope")
    assert "unknown field 'nope'" in str(err)
    assert err.col == 5


def test_syntax_error():
    err = reject("a +")
    assert "syntax error" in str(err)


def test_attribute_access_rejected():
    err = reject("a.real")
    assert "not allowed" in str(err)
    assert err.col == 1


@pytest.mark.parametrize("formula", [
    "a[0]",
    "lambda: 1",
    "a ** 2",
    "a % 2",
    "[a, b]",
    "a if b else c",
])
def test_disallowed_constructs(formula):
    assert "not allowed" in str(reject(formula))


def test_unknown_function():
    assert "unknown function 'SQRT'" in str(reject("SQRT(a)"))


def test_keyword_arguments_rejected():
    assert "keyword arguments" in str(reject("ROUND(a, n=2)"))


def test_method_call_rejected():
    assert "not allowed" in str(reject("a.lower()"))


@pytest.mark.parametrize("formula, msg", [
    ("ABS(a, b)", "ABS takes 1 argument(s), got 2"),
    ("COALESCE(a)", "COALESCE takes at least 2 argument(s), got 1"),
    ("CASE(a, b)", "CASE takes an odd number of arguments (at least 3)"),
    ("CASE(a, b, c, d)", "CASE takes an odd number of arguments (at least 3)"),
    ("IF(a, b)", "IF takes 3 argument(s), got 2"),
])
def test_function_arity(formula, msg):
    assert msg in str(reject(formula))


def test_round_digits_must_be_int_literal():
    assert "ROUND digits must be an integer literal" in str(reject("ROUND(a, b)"))


def test_chained_comparison_rejected():
    assert "chained comparisons" in str(reject("a < b < c"))


def test_eq_none_rejected():
    assert "use 'is None'" in str(reject("a == None"))


def test_is_requires_none():
    assert "'is' / 'is not' only allowed with None" in str(reject("a is b"))


def test_in_requires_list_of_constants():
    assert "'in' needs a list of constants" in str(reject("status in [a, 'X']"))
    assert "'in' needs a list of constants" in str(reject("status in a"))


def test_referenced_fields():
    tree = parse_formula("COALESCE(a, 0) + IF(b is None, c, 1)", KNOWN)
    assert referenced_fields(tree) == {"a", "b", "c"}
