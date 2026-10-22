from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.mapping.types import ColumnRef, JoinPlan

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")


def answer_key_sources(writer, plan: JoinPlan) -> dict[str, ColumnRef]:
    """field_id -> the column the mock writer actually put it in (grain-side copy preferred)."""
    sources: dict[str, ColumnRef] = {}
    for spec in writer.TABLES:
        for column, field_id in spec.columns.items():
            ref = ColumnRef(writer.SCHEMA, spec.name, column)
            if field_id not in sources or spec.name == plan.grain.table:
                sources[field_id] = ref
    sources["application_id"] = plan.grain
    return sources


@pytest.fixture(scope="session")
def catalog():
    return CATALOG
