import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from mockdata.canonical import CUSTOMER_FIELDS, build_applications, check_invariants

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")
N = 2000


@pytest.fixture(scope="module")
def apps():
    return build_applications(N, seed=42)


def test_same_seed_is_deterministic(apps):
    assert build_applications(N, seed=42) == apps


def test_different_seed_differs(apps):
    assert build_applications(N, seed=7) != apps


def test_records_have_exactly_the_catalog_raw_fields(apps):
    expected = {f.id for f in CATALOG.raw_fields}
    assert all(set(a) == expected for a in apps)


def test_application_ids_unique_and_ordered_by_date(apps):
    ids = [a["application_id"] for a in apps]
    assert len(set(ids)) == N
    assert [a["application_date"] for a in apps] == sorted(a["application_date"] for a in apps)


def test_values_match_catalog_types_and_enums(apps):
    py_types = {"string": str, "enum": str, "integer": int, "decimal": Decimal,
                "date": type(apps[0]["application_date"]), "boolean": bool}
    for f in CATALOG.raw_fields:
        for a in apps:
            v = a[f.id]
            if v is None:
                assert f.nullable, f"{f.id} is null but not nullable"
                continue
            assert type(v) is py_types[f.type], (f.id, v)
            if f.type == "enum":
                assert v in f.values, (f.id, v)


def test_decimals_have_two_places(apps):
    for a in apps:
        for k, v in a.items():
            if isinstance(v, Decimal):
                assert v == v.quantize(Decimal("0.01")), (k, v)


def test_identity_formats(apps):
    for a in apps:
        assert re.fullmatch(r"[A-Z]{3}P[A-Z]\d{4}[A-Z]", a["pan_number"])
        assert re.fullmatch(r"XXXX-XXXX-\d{4}", a["aadhaar_masked"])
        assert a["ckyc_number"] is None or re.fullmatch(r"\d{14}", a["ckyc_number"])
        assert re.fullmatch(r"\d{6}", a["pincode"])


def test_status_mix_within_3pp_of_targets(apps):
    share = {k: v / N for k, v in Counter(a["application_status"] for a in apps).items()}
    assert share["SUBMITTED"] == pytest.approx(0.05, abs=0.03)
    assert share["IN_REVIEW"] == pytest.approx(0.05, abs=0.03)
    assert share["WITHDRAWN"] == pytest.approx(0.03, abs=0.03)
    for status in ("APPROVED", "REJECTED", "DISBURSED"):
        assert share.get(status, 0) > 0.05


def test_every_rejection_reason_occurs(apps):
    reasons = {a["rejection_reason"] for a in apps if a["rejection_reason"]}
    assert reasons == {"LOW_CIBIL", "HIGH_FOIR", "WRITEOFF_HISTORY", "KYC_FAILED",
                       "INSUFFICIENT_INCOME", "POLICY_OTHER"}


def test_ntc_share_about_8pct(apps):
    ntc = sum(a["cibil_score"] is None for a in apps) / N
    assert ntc == pytest.approx(0.08, abs=0.03)


def test_disbursed_share_of_approved_about_85pct(apps):
    approved = [a for a in apps if a["application_status"] in ("APPROVED", "DISBURSED")]
    disbursed = sum(a["application_status"] == "DISBURSED" for a in approved)
    assert disbursed / len(approved) == pytest.approx(0.85, abs=0.05)


def test_repeat_customers_about_5pct_with_identical_applicant_data(apps):
    by_customer = defaultdict(list)
    for a in apps:
        by_customer[a["customer_id"]].append(a)
    repeats = sum(len(v) - 1 for v in by_customer.values())
    assert repeats / N == pytest.approx(0.05, abs=0.02)
    for records in by_customer.values():
        first = {k: records[0][k] for k in CUSTOMER_FIELDS}
        for r in records[1:]:
            assert {k: r[k] for k in CUSTOMER_FIELDS} == first


def test_invariants_hold(apps):
    check_invariants(apps)


def test_check_invariants_names_application_and_rule(apps):
    broken = dict(apps[0], application_status="REJECTED", rejection_reason="LOW_CIBIL",
                  approved_amount=Decimal("1000.00"))
    with pytest.raises(AssertionError, match=rf"{broken['application_id']}: rejected application has approved_amount"):
        check_invariants([broken])


def test_check_invariants_catches_amount_order(apps):
    disbursed = next(a for a in apps if a["application_status"] == "DISBURSED")
    broken = dict(disbursed, disbursed_amount=disbursed["approved_amount"] + 1)
    with pytest.raises(AssertionError, match="disbursed_amount > approved_amount"):
        check_invariants([broken])


def test_city_state_and_pincode_agree(apps):
    from mockdata.canonical import CITIES
    lookup = {city: (state, prefix) for city, state, prefix in CITIES}
    for a in apps:
        state, prefix = lookup[a["city"]]
        assert a["state"] == state
        assert a["pincode"].startswith(prefix)


def test_repeat_customers_apply_exactly_twice(apps):
    per_customer = Counter(a["customer_id"] for a in apps)
    assert max(per_customer.values()) == 2


def test_check_invariants_catches_bureau_pull_after_decision(apps):
    decided = next(a for a in apps if a["decision_date"] is not None)
    from datetime import timedelta
    broken = dict(decided, bureau_pull_date=decided["decision_date"] + timedelta(days=1))
    with pytest.raises(AssertionError, match="bureau pulled after decision"):
        check_invariants([broken])
