"""The real catalog/fields.yaml: shape, and every calculated field evaluated end to end."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import (
    Boolean, Column, Date, Integer, MetaData, Numeric, String, Table, create_engine, insert, select,
)

from app.catalog.expressions import calculated_expressions
from app.catalog.loader import load_catalog

CATALOG_PATH = Path(__file__).parents[3] / "catalog" / "fields.yaml"
SQL_TYPES = {"string": String, "enum": String, "integer": Integer,
             "decimal": lambda: Numeric(14, 2), "date": Date, "boolean": Boolean}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(CATALOG_PATH)


def test_counts(catalog):
    assert len(catalog.raw_fields) == 59
    assert len(catalog.calculated_fields) == 22


def test_sections(catalog):
    assert [s.id for s in catalog.sections] == [
        "application", "applicant", "kyc", "employment", "bureau", "banking", "decision", "disbursement",
    ]


def test_required_for_mapping(catalog):
    assert {f.id for f in catalog.fields if f.required_for_mapping} == {
        "application_id", "application_date", "channel", "requested_amount", "application_status",
        "customer_id", "date_of_birth", "state", "kyc_status", "employment_type",
        "net_income_monthly", "cibil_score", "existing_emi_monthly", "decision_date",
        "approved_amount", "disbursed_amount",
    }


def test_pii_fields(catalog):
    assert {f.id for f in catalog.fields if f.pii} == {
        "applicant_name", "date_of_birth", "pan_number", "aadhaar_masked", "ckyc_number",
    }


def test_every_raw_field_has_synonyms_and_description(catalog):
    for f in catalog.raw_fields:
        assert f.synonyms, f.id
        assert f.description, f.id


@pytest.fixture(scope="module")
def evaluate(catalog):
    """Return fn(row: dict) -> {calculated_field_id: value} computed by SQLite."""
    metadata = MetaData()
    table = Table("app", metadata, Column("_row", Integer, primary_key=True),
                  *[Column(f.id, SQL_TYPES[f.type]()) for f in catalog.raw_fields])
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    exprs = calculated_expressions(catalog, lambda fid: table.c[fid])

    def run(row: dict) -> dict:
        with engine.begin() as conn:
            conn.execute(table.delete())
            conn.execute(insert(table), [{"_row": 1, **row}])
            result = conn.execute(select(*[e.label(k) for k, e in exprs.items()])).mappings().one()
        return dict(result)

    yield run
    engine.dispose()


DISBURSED_APP = {
    "application_date": date(2026, 3, 10), "date_of_birth": date(1990, 6, 15),
    "net_income_monthly": Decimal("50000"), "existing_emi_monthly": Decimal("10000"),
    "approved_emi": Decimal("5000"), "requested_amount": Decimal("600000"),
    "approved_amount": Decimal("500000"), "cibil_score": 742, "application_status": "DISBURSED",
    "kyc_verified_date": date(2026, 3, 11), "decision_date": date(2026, 3, 12),
    "disbursement_date": date(2026, 3, 15), "disbursed_amount": Decimal("500000"),
    "processing_fee": Decimal("10000"), "avg_monthly_credits": Decimal("55000"),
    "avg_monthly_balance": Decimal("20000"), "dpd30_count_l12m": 0, "dpd90_count_l12m": 0,
}


def test_calculated_fields_for_disbursed_application(evaluate):
    r = evaluate(DISBURSED_APP)
    assert r["age_at_application"] == 35
    assert r["age_band"] == "35-44"
    assert r["income_band"] == "50K-1L"
    assert r["is_new_to_credit"] == 0
    assert r["cibil_band"] == "700-749"
    assert r["has_delinquency_l12m"] == 0
    assert float(r["foir_pct"]) == pytest.approx(20.0)
    assert float(r["post_loan_foir_pct"]) == pytest.approx(30.0)
    assert float(r["loan_to_income_ratio"]) == pytest.approx(1.0)
    assert float(r["bank_credit_to_income_pct"]) == pytest.approx(110.0)
    assert float(r["balance_to_emi_ratio"]) == pytest.approx(4.0)
    assert r["is_approved"] == 1
    assert r["is_rejected"] == 0
    assert r["is_disbursed"] == 1
    assert float(r["approved_to_requested_pct"]) == pytest.approx(83.333333, abs=1e-5)
    assert float(r["net_disbursed_amount"]) == pytest.approx(490000)
    assert float(r["processing_fee_pct"]) == pytest.approx(2.0)
    assert r["kyc_tat_days"] == 1
    assert r["decision_tat_days"] == 2
    assert r["disbursement_tat_days"] == 3
    assert r["end_to_end_tat_days"] == 5
    assert str(r["application_month"]) == "2026-03-01"


def test_missing_inputs_give_null_not_a_wrong_band(evaluate):
    r = evaluate({})
    assert r.pop("is_new_to_credit") == 1
    assert r.pop("cibil_band") == "NTC"
    assert r == {k: None for k in r}


@pytest.mark.parametrize("age_dob, band", [
    (date(2002, 3, 11), "<25"), (date(2001, 3, 10), "25-34"), (date(1971, 3, 11), "45-54"),
    (date(1950, 1, 1), "55+"),
])
def test_age_band_edges(evaluate, age_dob, band):
    assert evaluate({"application_date": date(2026, 3, 10), "date_of_birth": age_dob})["age_band"] == band


@pytest.mark.parametrize("income, band", [
    (24999, "<25K"), (25000, "25-50K"), (100000, "1-2L"), (200000, "2L+"),
])
def test_income_band_edges(evaluate, income, band):
    assert evaluate({"net_income_monthly": Decimal(income)})["income_band"] == band


@pytest.mark.parametrize("score, band", [(649, "<650"), (650, "650-699"), (799, "750-799"), (800, "800+")])
def test_cibil_band_edges(evaluate, score, band):
    assert evaluate({"cibil_score": score})["cibil_band"] == band


def test_rejected_application_flags(evaluate):
    r = evaluate({"application_status": "REJECTED", "existing_emi_monthly": Decimal("1000"),
                  "net_income_monthly": Decimal("20000")})
    assert (r["is_approved"], r["is_rejected"], r["is_disbursed"]) == (0, 1, 0)
    assert float(r["post_loan_foir_pct"]) == pytest.approx(5.0)   # no approved EMI -> counts as 0
    assert r["balance_to_emi_ratio"] is None


def test_zero_income_gives_null_ratios(evaluate):
    r = evaluate({"net_income_monthly": Decimal("0"), "existing_emi_monthly": Decimal("100"),
                  "requested_amount": Decimal("1000")})
    assert r["foir_pct"] is None
    assert r["loan_to_income_ratio"] is None
