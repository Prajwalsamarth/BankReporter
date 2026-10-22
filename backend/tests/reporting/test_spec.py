# backend/tests/reporting/test_spec.py
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.reporting.metrics import load_metrics
from app.reporting.spec import check_blocks, parse_block, validate_block

ROOT = Path(__file__).parents[3]
CATALOG = load_catalog(ROOT / "catalog" / "fields.yaml")
METRICS = load_metrics(ROOT / "catalog" / "metrics.yaml", CATALOG)


def errors(raw):
    block, errs = parse_block(raw)
    return errs if block is None else validate_block(block, CATALOG, METRICS)


def chart(**query):
    q = {"measures": [{"metric": "applications"}], "group_by": ["channel"], **query}
    return {"id": "c", "type": "chart", "chart": "bar", "query": q}


def test_valid_blocks():
    assert errors({"id": "h", "type": "heading", "text": "Hi {{client_name}}", "level": 2}) == []
    assert errors({"id": "k", "type": "kpi_row", "items": [{"measure": {"metric": "approval_rate"}},
                                                            {"measure": {"field": "cibil_score", "agg": "avg"}}]}) == []
    assert errors(chart(filters=[["employment_type", "eq", "SALARIED"], ["cibil_score", "gte", 700],
                                 ["is_disbursed", "eq", True], ["rejection_reason", "is_null"],
                                 ["cibil_band", "in", ["750-799", "800+"]], ["application_date", "lt", "2026-06-01"]],
                        sort={"by": "applications", "dir": "desc"}, limit=10)) == []
    assert errors({"id": "p", "type": "page_break"}) == []


def test_unknown_type_and_missing_fields_are_structural_errors():
    assert any("gauge" in e for e in errors({"id": "x", "type": "gauge"}))
    assert any("level" in e for e in errors({"id": "h", "type": "heading", "text": "x", "level": 9}))


@pytest.mark.parametrize("raw, msg", [
    (chart(measures=[{"metric": "nope"}]), "measure 1: unknown metric 'nope'"),
    (chart(measures=[{"field": "channel", "agg": "sum"}]), "measure 1: sum needs a measure field; channel is a dimension"),
    (chart(measures=[{"field": "cibil_score"}]), "measure 1: field measures need 'agg'"),
    (chart(measures=[{"metric": "applications", "field": "city", "agg": "count"}]), "measure 1: choose either a metric or a field"),
    (chart(group_by=["requested_amount"]), "group_by: requested_amount is a measure, not a dimension"),
    (chart(group_by=["nope"]), "group_by: unknown field 'nope'"),
    (chart(sort={"by": "approval_rate"}), "sort.by 'approval_rate' is not a measure or group-by of this block"),
    (chart(limit=0), "limit must be between 1 and 500"),
    (chart(filters=[["channel", "like", "W%"]]), "filter 1: unknown operator 'like'"),
    (chart(filters=[["channel", "eq", "FAX"]]), "filter 1: 'FAX' is not one of channel's values"),
    (chart(filters=[["channel", "in", []]]), "filter 1: in needs a non-empty list"),
    (chart(filters=[["city", "gt", "A"]]), "filter 1: gt needs a number or date field; city is string"),
    (chart(filters=[["rejection_reason", "is_null", "x"]]), "filter 1: is_null takes no value"),
    (chart(filters=[["application_date", "gte", "June"]]), "filter 1: 'June' is not a valid date for application_date"),
])
def test_semantic_errors(raw, msg):
    assert msg in errors(raw)


def test_filter_value_type_checked():
    # Review focus 5: a string "650" from the UI for an integer field is a validation error, not SQL.
    assert "filter 1: '650' is not a valid integer for cibil_score" in errors(chart(filters=[["cibil_score", "gte", "650"]]))
    assert "filter 1: True is not a valid integer for cibil_score" in errors(chart(filters=[["cibil_score", "eq", True]]))


@pytest.mark.parametrize("raw, msg", [
    ({**chart(), "chart": "pie", "query": {"measures": [{"metric": "applications"}, {"metric": "approved"}], "group_by": ["channel"]}},
     "pie charts need exactly 1 group-by and 1 measure"),
    ({**chart(), "chart": "line", "query": {"measures": [{"metric": "applications"}], "group_by": []}},
     "line charts need at least 1 group-by"),
    ({**chart(), "query": {"measures": [{"metric": "applications"}, {"metric": "approved"}],
                           "group_by": ["application_month", "channel"]}},
     "charts with 2 group-bys need exactly 1 measure"),
    ({"id": "t", "type": "table", "query": {"measures": [{"metric": "applications"}]}},
     "tables need at least 1 group-by"),
    ({"id": "t", "type": "text", "text": "{{metric:nope}} and {{period}}"}, "unknown metric 'nope' in placeholder"),
])
def test_chart_table_and_placeholder_rules(raw, msg):
    assert msg in errors(raw)


def test_check_blocks_collects_per_block_and_respects_allowed_types():
    blocks, errs = check_blocks([chart(), {"id": "h", "type": "heading", "text": "x"},
                                 chart(measures=[{"metric": "nope"}]) | {"id": "bad"}], CATALOG, METRICS,
                                allowed_types={"chart", "kpi", "table"})
    assert len(blocks) == 1
    assert errs == [{"block_id": "h", "messages": ["heading blocks are not allowed here"]},
                    {"block_id": "bad", "messages": ["measure 1: unknown metric 'nope'"]}]


def test_duplicate_block_ids_rejected():
    _, errs = check_blocks([chart(), chart()], CATALOG, METRICS)
    assert errs == [{"block_id": "c", "messages": ["duplicate block id"]}]
