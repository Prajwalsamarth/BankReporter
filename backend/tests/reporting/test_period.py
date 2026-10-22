# backend/tests/reporting/test_period.py
from datetime import date

import pytest

from app.reporting.period import PeriodError, resolve_period, sparkline_window

TODAY = date(2026, 10, 22)


def p(preset, today=TODAY, **kw):
    return resolve_period({"preset": preset, **kw}, today)


def test_last_month_is_default_shape():
    r = p("last_month")
    assert (r.start, r.end, r.prev_start, r.prev_end, r.label) == (
        date(2026, 9, 1), date(2026, 10, 1), date(2026, 8, 1), date(2026, 9, 1), "Sep 2026")


def test_this_month_and_previous_across_year():
    r = p("this_month", today=date(2026, 1, 15))
    assert (r.start, r.end, r.prev_start, r.prev_end) == (
        date(2026, 1, 1), date(2026, 2, 1), date(2025, 12, 1), date(2026, 1, 1))
    assert p("last_month", today=date(2026, 1, 15)).label == "Dec 2025"


def test_quarters():
    r = p("this_quarter")
    assert (r.start, r.end, r.prev_start, r.label) == (date(2026, 10, 1), date(2027, 1, 1), date(2026, 7, 1), "Q4 2026")
    r = p("last_quarter", today=date(2026, 2, 3))
    assert (r.start, r.end, r.prev_start, r.label) == (date(2025, 10, 1), date(2026, 1, 1), date(2025, 7, 1), "Q4 2025")


def test_ytd_and_leap_day():
    r = p("ytd")
    assert (r.start, r.end, r.prev_start, r.prev_end, r.label) == (
        date(2026, 1, 1), date(2026, 10, 23), date(2025, 1, 1), date(2025, 10, 23), "YTD 2026")
    leap = p("ytd", today=date(2028, 2, 29))
    assert leap.prev_end == date(2027, 3, 1)       # 28 Feb 2027 inclusive


def test_last_12_months():
    r = p("last_12_months")
    assert (r.start, r.end, r.prev_start, r.label) == (
        date(2025, 10, 1), date(2026, 10, 1), date(2024, 10, 1), "Oct 2025 – Sep 2026")


def test_custom_previous_window_has_same_length():
    r = p("custom", start="2026-03-01", end="2026-03-10")
    assert (r.start, r.end, r.prev_start, r.prev_end) == (
        date(2026, 3, 1), date(2026, 3, 11), date(2026, 2, 19), date(2026, 3, 1))
    assert r.label == "1 Mar 2026 – 10 Mar 2026"
    assert r.as_dict() == {"start": "2026-03-01", "end": "2026-03-10", "prev_start": "2026-02-19",
                           "prev_end": "2026-02-28", "label": "1 Mar 2026 – 10 Mar 2026"}


@pytest.mark.parametrize("spec, msg", [
    ({"preset": "custom", "start": "2026-03-10", "end": "2026-03-01"}, "start must not be after end"),
    ({"preset": "custom", "start": "2026-03-10"}, "custom periods need start and end"),
    ({"preset": "custom", "start": "10/03/2026", "end": "2026-03-11"}, "dates must be YYYY-MM-DD"),
    ({"preset": "fortnight"}, "unknown period preset 'fortnight'"),
    ({}, "unknown period preset 'None'"),
])
def test_errors(spec, msg):
    with pytest.raises(PeriodError, match=msg):
        resolve_period(spec, TODAY)


def test_sparkline_window_is_six_months_ending_with_period_end():
    assert sparkline_window(p("last_month")) == (date(2026, 4, 1), date(2026, 10, 1))
    assert sparkline_window(p("custom", start="2026-03-01", end="2026-03-10")) == (date(2025, 10, 1), date(2026, 4, 1))
