from datetime import date

from app.mapping.types import ColumnProfile, ColumnRef, Join, JoinPlan, dump, load_join_plan, load_profile


def test_column_ref_label():
    assert ColumnRef("los", "customer", "city").label == "los.customer.city"
    assert ColumnRef(None, "T", "C").label == "T.C"


def test_join_plan_round_trip():
    plan = JoinPlan(
        grain=ColumnRef("los", "loan_application", "application_id"),
        joins=[Join("los", "customer", "many_to_one", [("customer_id", "customer_id")])],
        excluded=[{"table": "los.audit", "reason": "no join path"}],
    )
    assert load_join_plan(dump(plan)) == plan


def test_profile_round_trip_with_dates():
    p = ColumnProfile(ref=ColumnRef("s", "t", "c"), sql_type="DATE", type="date", is_pk=False,
                      fk_to=None, null_pct=0.0, distinct_count=10, unique=False,
                      min=date(2025, 1, 1), max=date(2026, 1, 1))
    data = dump(p)
    assert data["min"] == "2025-01-01"
    assert load_profile(data).min == "2025-01-01"
