# backend/tests/reporting/test_formatting.py
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.reporting import formatting as fmt

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")


@pytest.mark.parametrize("n, s", [(0, "0"), (999, "999"), (1000, "1,000"), (123456, "1,23,456"),
                                  (12345678, "1,23,45,678"), (-123456, "-1,23,456")])
def test_indian_grouping(n, s):
    assert fmt.indian(n) == s


@pytest.mark.parametrize("v, unit, s", [
    (None, "INR", "—"), (Decimal("45200000"), "INR", "₹4.52 Cr"), (3860000, "INR", "₹38.6 L"),
    (85400.4, "INR", "₹85,400"), (-3860000, "INR", "-₹38.6 L"), (123456, "count", "1,23,456"),
    (61.234, "pct", "61.2%"), (4.26, "days", "4.3 days"), (731.4, "score", "731"), (1.849, "ratio", "1.85"),
    (12.5, "number", "12.50"), (12, "number", "12"),
])
def test_measure(v, unit, s):
    assert fmt.measure(v, unit) == s


def test_val_raw_is_float_or_none():
    assert fmt.val(Decimal("12.50"), "pct") == {"raw": 12.5, "display": "12.5%"}
    assert fmt.val(None, "count") == {"raw": None, "display": "—"}


def test_delta_pct_is_points_and_good_follows_better():
    d = fmt.delta(61.2, 59.1, "pct", "higher")
    assert d["display"] == "+2.1 pts" and d["direction"] == "up" and d["good"] is True
    assert fmt.delta(5.0, 4.0, "days", "lower") == {"raw": 25.0, "display": "+25.0%", "direction": "up", "good": False}
    assert fmt.delta(10, 10, "count", "higher")["good"] is None              # flat
    assert fmt.delta(10, 12, "INR", "neutral")["good"] is None


def test_delta_null_cases():
    assert fmt.delta(None, 3, "count", "higher") is None
    assert fmt.delta(3, None, "count", "higher") is None
    assert fmt.delta(3, 0, "count", "higher") is None                          # % change undefined
    assert fmt.delta(3.0, 0.0, "pct", "higher")["display"] == "+3.0 pts"       # points are fine


def test_dimension_display():
    assert fmt.dimension(None, CATALOG.field("rejection_reason")) == {"raw": None, "display": "—"}
    assert fmt.dimension(1, CATALOG.field("is_disbursed"))["display"] == "Yes"
    assert fmt.dimension(False, CATALOG.field("has_writeoff"))["display"] == "No"
    assert fmt.dimension(date(2026, 9, 1), CATALOG.field("application_month")) == {"raw": "2026-09-01", "display": "Sep 2026"}
    assert fmt.dimension("2026-09-01", CATALOG.field("application_month"))["display"] == "Sep 2026"
    assert fmt.dimension("WEB", CATALOG.field("channel")) == {"raw": "WEB", "display": "WEB"}


def test_labels():
    assert fmt.month_label(datetime(2026, 3, 1, 0, 0)) == "Mar 2026"
    assert fmt.datetime_label(datetime(2026, 10, 22, 18, 5)) == "22 Oct 2026, 18:05"
