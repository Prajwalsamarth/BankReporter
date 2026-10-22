from datetime import date
from decimal import Decimal

import pytest

from mockdata.golden import format_value, read_golden, write_golden


@pytest.mark.parametrize("value, ftype, expected", [
    (None, "string", ""),
    (None, "decimal", ""),
    ("A", "string", "A"),
    (Decimal("1500.50"), "decimal", "1500.50"),
    (Decimal("1500.5"), "decimal", "1500.50"),
    (1500.5, "decimal", "1500.50"),
    (7, "integer", "7"),
    (date(2026, 3, 1), "date", "2026-03-01"),
    (True, "boolean", "true"),
    (False, "boolean", "false"),
    (1, "boolean", "true"),      # MySQL TINYINT(1)
    (0, "boolean", "false"),
    ("APPROVED", "enum", "APPROVED"),
])
def test_format_value(value, ftype, expected):
    assert format_value(value, ftype) == expected


def test_golden_round_trip(tmp_path):
    path = tmp_path / "sub" / "applications.csv"
    apps = [{"application_id": "APP1", "cibil_score": None, "has_writeoff": False,
             "applicant_name": "Asha, \"Rao\""}]
    types = {"application_id": "string", "cibil_score": "integer", "has_writeoff": "boolean",
             "applicant_name": "string"}
    write_golden(path, apps, types)
    rows = read_golden(path)
    assert list(rows[0]) == ["application_id", "cibil_score", "has_writeoff", "applicant_name"]
    assert rows == [{"application_id": "APP1", "cibil_score": "", "has_writeoff": "false",
                     "applicant_name": 'Asha, "Rao"'}]
