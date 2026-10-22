import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.catalog.models import Catalog, Field, Section

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class CatalogError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid catalog:\n  " + "\n  ".join(errors))


def load_catalog(path: str | Path) -> Catalog:
    raw = yaml.safe_load(Path(path).read_text())
    errors: list[str] = []

    sections = [Section.model_validate(s) for s in raw.get("sections", [])]
    section_ids: set[str] = set()
    for s in sections:
        if s.id in section_ids:
            errors.append(f"section {s.id}: duplicate section id")
        section_ids.add(s.id)

    fields: list[Field] = []
    seen: set[str] = set()
    for entry in raw.get("fields", []):
        fid = entry.get("id", "<missing id>")
        try:
            field = Field.model_validate(entry)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors.append(f"{fid}: {loc}: {err['msg']}")
            continue
        if field.id in seen:
            errors.append(f"{fid}: duplicate field id")
            continue
        seen.add(field.id)
        errors.extend(f"{fid}: {msg}" for msg in _field_rule_errors(field, section_ids))
        fields.append(field)

    if errors:
        raise CatalogError(errors)
    return Catalog(version=raw["version"], sections=sections, fields=fields)


def _field_rule_errors(field: Field, section_ids: set[str]) -> list[str]:
    errors = []
    if not ID_RE.match(field.id):
        errors.append(f"id must match {ID_RE.pattern}")
    if field.section not in section_ids:
        errors.append(f"unknown section '{field.section}'")
    if field.type == "enum":
        if not field.values or len(set(field.values)) != len(field.values):
            errors.append("enum fields need a non-empty 'values' list")
    elif field.values is not None:
        errors.append("'values' is only allowed on enum fields")
    if field.role == "measure" and field.default_agg is None:
        errors.append("measures need 'default_agg'")
    if field.role == "dimension" and field.default_agg is not None:
        errors.append("'default_agg' is only allowed on measures")
    if field.kind == "calculated":
        if not field.formula:
            errors.append("calculated fields need a 'formula'")
        if field.required_for_mapping:
            errors.append("calculated fields cannot be required_for_mapping")
    elif field.formula is not None:
        errors.append("raw fields must not have a 'formula'")
    return errors
