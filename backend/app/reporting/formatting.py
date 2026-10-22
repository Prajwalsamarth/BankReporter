# backend/app/reporting/formatting.py
"""One formatter for every displayed value (spec §5.4). Indian grouping; ₹ in lakh/crore."""
from datetime import date, datetime
from decimal import Decimal


def jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def indian(n: int) -> str:
    s = str(abs(int(n)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if n < 0 else "") + ",".join(groups + [tail])


def measure(v, unit: str) -> str:
    if v is None:
        return "—"
    x = float(v)
    if unit == "count" or unit == "score":
        return indian(round(x))
    if unit == "INR":
        sign, a = ("-" if x < 0 else ""), abs(x)
        if a >= 1e7:
            return f"{sign}₹{a / 1e7:.2f} Cr"
        if a >= 1e5:
            return f"{sign}₹{a / 1e5:.1f} L"
        return f"{sign}₹{indian(round(a))}"
    if unit == "pct":
        return f"{x:.1f}%"
    if unit == "days":
        return f"{x:.1f} days"
    if unit == "ratio":
        return f"{x:.2f}"
    return indian(round(x)) if x == int(x) else f"{x:.2f}"


def val(v, unit: str) -> dict:
    return {"raw": None if v is None else float(v), "display": measure(v, unit)}


def delta(v, pv, unit: str, better: str) -> dict | None:
    if v is None or pv is None:
        return None
    v, pv = float(v), float(pv)
    if unit == "pct":
        d = v - pv
        display = f"{d:+.1f} pts"
    else:
        if pv == 0:
            return None
        d = (v - pv) / abs(pv) * 100
        display = f"{d:+.1f}%"
    direction = "up" if d > 1e-9 else "down" if d < -1e-9 else "flat"
    good = None if better == "neutral" or direction == "flat" else (direction == "up") == (better == "higher")
    return {"raw": round(d, 6), "display": display, "direction": direction, "good": good}


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def month_label(v) -> str:
    d = _to_date(v)
    return f"{d:%b %Y}" if d else "—"


def datetime_label(dt: datetime) -> str:
    return f"{dt.day} {dt:%b %Y}, {dt:%H:%M}"


def dimension(v, field) -> dict:
    if v is None:
        return {"raw": None, "display": "—"}
    if field.type == "boolean":
        return {"raw": bool(v), "display": "Yes" if v else "No"}
    if field.type == "date":
        d = _to_date(v)
        return {"raw": d.isoformat(), "display": month_label(d) if field.id == "application_month" else d.isoformat()}
    raw = jsonable(v)
    return {"raw": raw, "display": str(raw)}
