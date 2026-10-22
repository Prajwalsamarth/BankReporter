import textwrap

import pytest

from app.catalog.loader import CatalogError, load_catalog

SECTIONS = """
version: 1
sections:
  - id: application
    label: Application
fields:
"""


def write_catalog(tmp_path, fields_yaml: str):
    path = tmp_path / "fields.yaml"
    path.write_text(SECTIONS + textwrap.indent(textwrap.dedent(fields_yaml), "  "))
    return path


def load_errors(tmp_path, fields_yaml: str) -> list[str]:
    with pytest.raises(CatalogError) as exc:
        load_catalog(write_catalog(tmp_path, fields_yaml))
    return exc.value.errors


def test_valid_catalog_loads_with_defaults(tmp_path):
    catalog = load_catalog(write_catalog(tmp_path, """
        - id: application_id
          label: Application ID
          section: application
          kind: raw
          type: string
          role: dimension
          required_for_mapping: true
        - id: requested_amount
          label: Requested Amount
          section: application
          kind: raw
          type: decimal
          role: measure
          default_agg: sum
          unit: INR
    """))
    assert [f.id for f in catalog.fields] == ["application_id", "requested_amount"]
    amount = catalog.field("requested_amount")
    assert amount.nullable is True
    assert amount.pii is False
    assert amount.required_for_mapping is False
    assert amount.synonyms == []
    assert catalog.field("application_id").required_for_mapping is True


def test_duplicate_field_id(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: string, role: dimension}
        - {id: a, label: A2, section: application, kind: raw, type: string, role: dimension}
    """)
    assert "a: duplicate field id" in errors


def test_bad_id_format(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: BadId, label: A, section: application, kind: raw, type: string, role: dimension}
    """)
    assert any(e.startswith("BadId: id must match") for e in errors)


def test_unknown_section(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: nope, kind: raw, type: string, role: dimension}
    """)
    assert "a: unknown section 'nope'" in errors


def test_enum_requires_values(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: enum, role: dimension}
    """)
    assert "a: enum fields need a non-empty 'values' list" in errors


def test_values_only_on_enum(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: string, role: dimension, values: [X]}
    """)
    assert "a: 'values' is only allowed on enum fields" in errors


def test_measure_requires_default_agg(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: integer, role: measure}
    """)
    assert "a: measures need 'default_agg'" in errors


def test_dimension_rejects_default_agg(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: string, role: dimension, default_agg: sum}
    """)
    assert "a: 'default_agg' is only allowed on measures" in errors


def test_calculated_requires_formula(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: calculated, type: integer, role: dimension}
    """)
    assert "a: calculated fields need a 'formula'" in errors


def test_raw_rejects_formula(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: integer, role: dimension, formula: "1"}
    """)
    assert "a: raw fields must not have a 'formula'" in errors


def test_calculated_cannot_be_required_for_mapping(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: b, label: B, section: application, kind: raw, type: integer, role: dimension}
        - {id: a, label: A, section: application, kind: calculated, type: integer, role: dimension,
           formula: "b", required_for_mapping: true}
    """)
    assert "a: calculated fields cannot be required_for_mapping" in errors


def test_invalid_enum_value_for_type_is_reported_with_field_id(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: money, role: dimension}
    """)
    assert any(e.startswith("a: type:") for e in errors)


def test_multiple_defects_reported_together(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: nope, kind: raw, type: enum, role: dimension}
        - {id: b, label: B, section: application, kind: raw, type: integer, role: measure}
    """)
    assert "a: unknown section 'nope'" in errors
    assert "a: enum fields need a non-empty 'values' list" in errors
    assert "b: measures need 'default_agg'" in errors


def test_error_message_lists_all_errors(tmp_path):
    with pytest.raises(CatalogError) as exc:
        load_catalog(write_catalog(tmp_path, """
            - {id: a, label: A, section: nope, kind: raw, type: string, role: dimension}
            - {id: b, label: B, section: nope, kind: raw, type: string, role: dimension}
        """))
    assert "a: unknown section 'nope'" in str(exc.value)
    assert "b: unknown section 'nope'" in str(exc.value)


def test_duplicate_section_id(tmp_path):
    path = tmp_path / "fields.yaml"
    path.write_text("""
version: 1
sections:
  - {id: application, label: A}
  - {id: application, label: B}
fields: []
""")
    with pytest.raises(CatalogError) as exc:
        load_catalog(path)
    assert "section application: duplicate section id" in exc.value.errors


RAW_INCOME = """
    - {id: income, label: I, section: application, kind: raw, type: decimal, role: measure, default_agg: avg}
    - {id: score, label: S, section: application, kind: raw, type: integer, role: measure, default_agg: avg}
"""


def test_formula_unknown_field_reported_with_field_id(tmp_path):
    errors = load_errors(tmp_path, RAW_INCOME + """
    - {id: c, label: C, section: application, kind: calculated, type: decimal, role: measure,
       default_agg: avg, formula: "incom * 2"}
    """)
    assert "c: unknown field 'incom' (col 1)" in errors


def test_formula_cycle_detected(tmp_path):
    errors = load_errors(tmp_path, RAW_INCOME + """
    - {id: c1, label: C1, section: application, kind: calculated, type: decimal, role: measure,
       default_agg: avg, formula: "c2 + 1"}
    - {id: c2, label: C2, section: application, kind: calculated, type: decimal, role: measure,
       default_agg: avg, formula: "c1 + income"}
    """)
    assert any(e.startswith("c1: formula cycle") or e.startswith("c2: formula cycle") for e in errors)


def test_self_reference_is_a_cycle(tmp_path):
    errors = load_errors(tmp_path, RAW_INCOME + """
    - {id: c, label: C, section: application, kind: calculated, type: integer, role: measure,
       default_agg: avg, formula: "c + 1"}
    """)
    assert "c: formula cycle: c -> c" in errors


def test_formula_type_mismatch(tmp_path):
    errors = load_errors(tmp_path, RAW_INCOME + """
    - {id: c, label: C, section: application, kind: calculated, type: integer, role: measure,
       default_agg: avg, formula: "income / 2"}
    """)
    assert "c: formula returns decimal but field is declared integer" in errors


def test_formula_type_error(tmp_path):
    errors = load_errors(tmp_path, RAW_INCOME + """
    - {id: c, label: C, section: application, kind: calculated, type: integer, role: measure,
       default_agg: avg, formula: "MONTH_START(score)"}
    """)
    assert any(e.startswith("c: MONTH_START needs date arguments") for e in errors)


def test_enum_formula_literals_must_be_declared_values(tmp_path):
    errors = load_errors(tmp_path, RAW_INCOME + """
    - {id: band, label: B, section: application, kind: calculated, type: enum, role: dimension,
       values: [LOW, HIGH], formula: "IF(score < 700, 'LOW', 'MID')"}
    """)
    assert "band: formula can return 'MID' which is not in values" in errors


def test_calculated_may_reference_calculated(tmp_path):
    catalog = load_catalog(write_catalog(tmp_path, RAW_INCOME + """
    - {id: annual, label: A, section: application, kind: calculated, type: decimal, role: measure,
       default_agg: avg, formula: "income * 12"}
    - {id: band, label: B, section: application, kind: calculated, type: enum, role: dimension,
       values: [LOW, HIGH], formula: "IF(annual < 600000, 'LOW', 'HIGH')"}
    """))
    assert catalog.field("band").kind == "calculated"


def test_calculation_order_puts_dependencies_first(tmp_path):
    catalog = load_catalog(write_catalog(tmp_path, RAW_INCOME + """
    - {id: band, label: B, section: application, kind: calculated, type: enum, role: dimension,
       values: [LOW, HIGH], formula: "IF(annual < 600000, 'LOW', 'HIGH')"}
    - {id: annual, label: A, section: application, kind: calculated, type: decimal, role: measure,
       default_agg: avg, formula: "income * 12"}
    """))
    assert catalog.calculation_order() == ["annual", "band"]


def write_raw(tmp_path, body: str):
    path = tmp_path / "fields.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def errors_for(path) -> list[str]:
    with pytest.raises(CatalogError) as exc:
        load_catalog(path)
    return exc.value.errors


def test_section_id_format(tmp_path):
    errors = errors_for(write_raw(tmp_path, """
        version: 1
        sections: [{id: Bad-Sec, label: B}]
        fields: []
    """))
    assert any(e.startswith("section Bad-Sec: id must match") for e in errors)


def test_invalid_section_is_collected_with_other_errors(tmp_path):
    errors = errors_for(write_raw(tmp_path, """
        version: 1
        sections: [{id: application}]
        fields:
          - {id: a, label: A, section: application, kind: raw, type: enum, role: dimension}
    """))
    assert any(e.startswith("section application: label:") for e in errors)
    assert "a: enum fields need a non-empty 'values' list" in errors


def test_missing_version(tmp_path):
    errors = errors_for(write_raw(tmp_path, """
        sections: []
        fields: []
    """))
    assert "catalog: 'version' must be an integer" in errors


def test_top_level_must_be_mapping(tmp_path):
    errors = errors_for(write_raw(tmp_path, "- just a list\n"))
    assert errors == ["catalog: top level must be a mapping with version, sections, fields"]


def test_duplicate_enum_values_message(tmp_path):
    errors = load_errors(tmp_path, """
        - {id: a, label: A, section: application, kind: raw, type: enum, role: dimension, values: [X, X]}
    """)
    assert "a: duplicate enum values" in errors
