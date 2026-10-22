from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.mapping.compat import compatible
from app.mapping.matcher.abbreviations import ABBREVIATIONS, expand
from app.mapping.matcher.rules import effective_synonyms, match_rules
from app.mapping.types import ColumnProfile, ColumnRef

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")


def prof(column, type_="string", table="T", **kw):
    return ColumnProfile(ColumnRef("s", table, column), "X", type_, False, None, 0.0, 10, False, **kw)


def test_exact_synonym_decides():
    decisions = match_rules([prof("CIB_SCR", "integer")], CATALOG, effective_synonyms(CATALOG))
    d = decisions[ColumnRef("s", "T", "CIB_SCR")]
    assert (d.field_id, d.score, d.layer) == ("cibil_score", 1.0, "A")
    assert d.reason == "name matches synonym 'cib_scr'"


def test_field_id_match_decides():
    d = match_rules([prof("cibil_score", "integer")], CATALOG, effective_synonyms(CATALOG))
    assert d[ColumnRef("s", "T", "cibil_score")].reason == "name matches field id"


def test_masked_synonym_gives_no_decision():
    synonyms = effective_synonyms(CATALOG, masked={("cibil_score", "cib_scr")})
    assert match_rules([prof("CIB_SCR", "integer")], CATALOG, synonyms) == {}


def test_type_incompatibility_blocks():
    # PAN_NO is a synonym of pan_number (string); an integer column must not match it
    assert match_rules([prof("PAN_NO", "integer")], CATALOG, effective_synonyms(CATALOG)) == {}


def test_ambiguous_synonym_gives_no_decision():
    synonyms = effective_synonyms(CATALOG)
    synonyms["approved_amount"] = synonyms["approved_amount"] + ["amt"]
    synonyms["requested_amount"] = synonyms["requested_amount"] + ["amt"]
    assert match_rules([prof("AMT", "decimal")], CATALOG, synonyms) == {}


def test_excluded_columns_skipped():
    ref = ColumnRef("s", "T", "APPL_NO")
    assert match_rules([prof("APPL_NO")], CATALOG, effective_synonyms(CATALOG), exclude={ref}) == {}


def test_only_raw_fields_considered():
    assert match_rules([prof("foir_pct", "decimal")], CATALOG, effective_synonyms(CATALOG)) == {}


@pytest.mark.parametrize("col_type, field_type, extra, ok", [
    ("integer", "integer", {}, True),
    ("integer", "decimal", {}, True),
    ("decimal", "integer", {}, False),
    ("string", "enum", {}, True),
    ("string", "date", {}, False),
    ("integer", "boolean", {"bool_like": True}, True),
    ("integer", "boolean", {"bool_like": False}, False),
    ("boolean", "boolean", {}, True),
    ("other", "string", {}, False),
])
def test_compatible(col_type, field_type, extra, ok):
    field = next(f for f in CATALOG.raw_fields if f.type == field_type)
    assert compatible(prof("c", col_type, **extra), field) is ok


def test_expand_abbreviations():
    assert expand("NET_MTH_INC") == "net monthly income"
    assert expand("CIB_SCR") == "cibil score"
    assert expand("BS_AMB") == "bank statement average monthly balance"
    assert expand("full_name") == "full name"


def test_abbreviation_list_is_generic_sized():
    assert 50 <= len(ABBREVIATIONS) <= 90
    assert all(k == k.lower() and "_" not in k for k in ABBREVIATIONS)
