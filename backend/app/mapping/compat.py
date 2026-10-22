from app.catalog.models import Field
from app.mapping.types import ColumnProfile


def compatible(profile: ColumnProfile, field: Field) -> bool:
    """Can this column feed this catalog field without a transform (spec §3.2)?"""
    col, target = profile.type, field.type
    if col == "other":
        return False
    if col == target or (col, target) in {("integer", "decimal"), ("string", "enum")}:
        return True
    return col == "integer" and target == "boolean" and profile.bool_like
