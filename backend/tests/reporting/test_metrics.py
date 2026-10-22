# backend/tests/reporting/test_metrics.py
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.reporting.metrics import MetricError, load_metrics

ROOT = Path(__file__).parents[3]
CATALOG = load_catalog(ROOT / "catalog" / "fields.yaml")


def test_real_library_loads_all_22_metrics():
    lib = load_metrics(ROOT / "catalog" / "metrics.yaml", CATALOG)
    assert len(lib.ids) == 22
    assert lib.get("approval_rate").unit == "pct"
    assert lib.get("avg_end_to_end_tat").better == "lower"
    assert {m.group for m in lib.metrics} == {"volume", "rates", "amounts", "credit", "turnaround"}


def write(tmp_path, body):
    p = tmp_path / "metrics.yaml"
    p.write_text("version: 1\nmetrics:\n" + body)
    return p


def test_every_error_reported_together(tmp_path):
    p = write(tmp_path, """
  - {id: a, label: A, formula: "b + 1", unit: count, better: higher, group: volume}
  - {id: b, label: B, formula: "a * 2", unit: count, better: higher, group: volume}
  - {id: c, label: C, formula: "SUM(nope)", unit: INR, better: higher, group: amounts}
  - {id: d, label: D, formula: "COUNT()", unit: bananas, better: higher, group: volume}
  - {id: city, label: X, formula: "COUNT()", unit: count, better: higher, group: volume}
  - {id: c, label: C2, formula: "COUNT()", unit: count, better: higher, group: volume}
""")
    with pytest.raises(MetricError) as exc:
        load_metrics(p, CATALOG)
    errors = exc.value.errors
    assert any(e.startswith("a: metric cycle") or e.startswith("b: metric cycle") for e in errors)
    assert any(e.startswith("c: unknown field 'nope'") for e in errors)
    assert any(e.startswith("d: unit:") for e in errors)
    assert "city: id clashes with a catalog field" in errors
    assert "c: duplicate metric id" in errors


def test_compile_inlines_referenced_metrics(tmp_path):
    from sqlalchemy import column, table
    from sqlalchemy.dialects import postgresql
    p = write(tmp_path, """
  - {id: approved, label: A, formula: "COUNT_IF(is_approved)", unit: count, better: higher, group: volume}
  - {id: rate, label: R, formula: "approved / COUNT() * 100", unit: pct, better: higher, group: rates}
""")
    lib = load_metrics(p, CATALOG)
    view = table("applications", column("is_approved"))
    sql = str(lib.compile("rate", lambda f: view.c[f]).compile(dialect=postgresql.dialect()))
    assert "CASE WHEN applications.is_approved THEN" in sql and "count(*)" in sql
