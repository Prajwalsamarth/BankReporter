"""Golden CSV of canonical applications: the expected answer for mapping tests (spec §5.4).

Values are serialised by catalog type so database readbacks can be compared as strings:
NULL -> "", boolean -> true/false, decimal -> 2 places, date -> ISO.
"""
import csv
from decimal import Decimal
from pathlib import Path


def format_value(value, field_type: str) -> str:
    if value is None:
        return ""
    if field_type == "boolean":
        return "true" if value else "false"
    if field_type == "decimal":
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    if field_type == "date":
        return value.isoformat()[:10]
    return str(value)


def write_golden(path: Path, apps: list[dict], field_types: dict[str, str]) -> None:
    """Write one row per application; columns in `field_types` order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(field_types))
        writer.writeheader()
        for a in apps:
            writer.writerow({k: format_value(a[k], t) for k, t in field_types.items()})


def read_golden(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))
