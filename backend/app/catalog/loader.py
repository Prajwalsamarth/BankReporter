import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.catalog.formula import (
    FormulaError, infer_type, is_type_compatible, parse_formula, referenced_fields, result_literals,
)
from app.catalog.models import Catalog, Field, Section

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class CatalogError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid catalog:\n  " + "\n  ".join(errors))


def load_catalog(path: str | Path) -> Catalog:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise CatalogError(["catalog: top level must be a mapping with version, sections, fields"])
    errors: list[str] = []
    version = raw.get("version")
    if type(version) is not int:
        errors.append("catalog: 'version' must be an integer")

    sections: list[Section] = []
    section_ids: set[str] = set()
    for entry in raw.get("sections") or []:
        sid = entry.get("id", "<missing id>") if isinstance(entry, dict) else "<invalid>"
        try:
            section = Section.model_validate(entry)
        except ValidationError as exc:
            errors.extend(f"section {sid}: {_loc(err)}: {err['msg']}" for err in exc.errors())
            section_ids.add(sid)   # don't also report its fields as "unknown section"
            continue
        if section.id in section_ids:
            errors.append(f"section {section.id}: duplicate section id")
        if not ID_RE.match(section.id):
            errors.append(f"section {section.id}: id must match {ID_RE.pattern}")
        section_ids.add(section.id)
        sections.append(section)

    fields: list[Field] = []
    seen: set[str] = set()
    for entry in raw.get("fields") or []:
        fid = entry.get("id", "<missing id>") if isinstance(entry, dict) else "<invalid>"
        try:
            field = Field.model_validate(entry)
        except ValidationError as exc:
            errors.extend(f"{fid}: {_loc(err)}: {err['msg']}" for err in exc.errors())
            continue
        if field.id in seen:
            errors.append(f"{fid}: duplicate field id")
            continue
        seen.add(field.id)
        errors.extend(f"{fid}: {msg}" for msg in _field_rule_errors(field, section_ids))
        fields.append(field)

    errors.extend(_formula_errors(fields))

    if errors:
        raise CatalogError(errors)
    return Catalog(version=version, sections=sections, fields=fields)


def _loc(err: dict) -> str:
    return ".".join(str(p) for p in err["loc"])


def _field_rule_errors(field: Field, section_ids: set[str]) -> list[str]:
    errors = []
    if not ID_RE.match(field.id):
        errors.append(f"id must match {ID_RE.pattern}")
    if field.section not in section_ids:
        errors.append(f"unknown section '{field.section}'")
    if field.type == "enum":
        if not field.values:
            errors.append("enum fields need a non-empty 'values' list")
        elif len(set(field.values)) != len(field.values):
            errors.append("duplicate enum values")
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


def _formula_errors(fields: list[Field]) -> list[str]:
    errors: list[str] = []
    known = {f.id for f in fields}
    types = {f.id: f.type for f in fields}
    deps: dict[str, set[str]] = {}

    for f in fields:
        if f.kind != "calculated" or not f.formula:
            continue
        try:
            tree = parse_formula(f.formula, known)
            deps[f.id] = referenced_fields(tree)
            inferred = infer_type(tree, types)
        except FormulaError as exc:
            errors.append(f"{f.id}: {exc}")
            continue
        if not is_type_compatible(inferred, f.type):
            errors.append(f"{f.id}: formula returns {inferred} but field is declared {f.type}")
        if f.type == "enum":
            for value in sorted(result_literals(tree) - set(f.values or [])):
                errors.append(f"{f.id}: formula can return '{value}' which is not in values")

    errors.extend(_cycle_errors(deps))
    return errors


def _cycle_errors(deps: dict[str, set[str]]) -> list[str]:
    errors: list[str] = []
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            cycle = path[path.index(node):] + [node]
            errors.append(f"{cycle[0]}: formula cycle: {' -> '.join(cycle)}")
            return
        if node in done or node not in deps:
            return
        for dep in sorted(deps[node]):
            visit(dep, path + [node])
        done.add(node)

    for node in sorted(deps):
        visit(node, [])
    return errors
