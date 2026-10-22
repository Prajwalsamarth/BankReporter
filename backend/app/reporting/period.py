# backend/app/reporting/period.py
"""Report/dashboard periods and their comparison periods (spec §4). End dates are exclusive."""
from dataclasses import dataclass
from datetime import date, timedelta

PRESETS = ("this_month", "last_month", "this_quarter", "last_quarter", "ytd", "last_12_months", "custom")
ONE_DAY = timedelta(days=1)


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    prev_start: date
    prev_end: date
    label: str

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": (self.end - ONE_DAY).isoformat(),
                "prev_start": self.prev_start.isoformat(), "prev_end": (self.prev_end - ONE_DAY).isoformat(),
                "label": self.label}


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    """d must be the 1st of a month."""
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _day_label(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _same_day_last_year(d: date) -> date:
    return d.replace(year=d.year - 1, day=28) if (d.month, d.day) == (2, 29) else d.replace(year=d.year - 1)


def resolve_period(spec: dict, today: date) -> Period:
    preset = spec.get("preset")
    this_month = month_start(today)
    quarter = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    match preset:
        case "this_month":
            return Period(this_month, add_months(this_month, 1), add_months(this_month, -1), this_month,
                          f"{this_month:%b %Y}")
        case "last_month":
            s = add_months(this_month, -1)
            return Period(s, this_month, add_months(s, -1), s, f"{s:%b %Y}")
        case "this_quarter" | "last_quarter":
            s = quarter if preset == "this_quarter" else add_months(quarter, -3)
            return Period(s, add_months(s, 3), add_months(s, -3), s, f"Q{(s.month - 1) // 3 + 1} {s.year}")
        case "ytd":
            s = date(today.year, 1, 1)
            return Period(s, today + ONE_DAY, date(today.year - 1, 1, 1), _same_day_last_year(today) + ONE_DAY,
                          f"YTD {today.year}")
        case "last_12_months":
            s = add_months(this_month, -12)
            return Period(s, this_month, add_months(s, -12), s,
                          f"{s:%b %Y} – {add_months(this_month, -1):%b %Y}")
        case "custom":
            if not spec.get("start") or not spec.get("end"):
                raise PeriodError("custom periods need start and end")
            try:
                s, last = date.fromisoformat(spec["start"]), date.fromisoformat(spec["end"])
            except (TypeError, ValueError):
                raise PeriodError("dates must be YYYY-MM-DD") from None
            if s > last:
                raise PeriodError("start must not be after end")
            length = (last - s).days + 1
            return Period(s, last + ONE_DAY, s - timedelta(days=length), s,
                          f"{_day_label(s)} – {_day_label(last)}")
    raise PeriodError(f"unknown period preset '{preset}'")


def sparkline_window(period: Period) -> tuple[date, date]:
    last_month = month_start(period.end - ONE_DAY)
    return add_months(last_month, -5), add_months(last_month, 1)
