from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.catalog.formula import parse_formula, referenced_fields

FieldType = Literal["string", "integer", "decimal", "date", "boolean", "enum"]
Agg = Literal["sum", "avg", "min", "max", "count", "count_distinct"]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class Field(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    section: str
    kind: Literal["raw", "calculated"]
    type: FieldType
    values: list[str] | None = None
    role: Literal["dimension", "measure"]
    default_agg: Agg | None = None
    unit: str | None = None
    nullable: bool = True
    pii: bool = False
    required_for_mapping: bool = False
    synonyms: list[str] = []
    description: str = ""
    formula: str | None = None


class Catalog(BaseModel):
    version: int
    sections: list[Section]
    fields: list[Field]

    def field(self, field_id: str) -> Field:
        for f in self.fields:
            if f.id == field_id:
                return f
        raise KeyError(field_id)

    def calculation_order(self) -> list[str]:
        """Calculated field IDs, each after the calculated fields it references.

        Assumes a validated (acyclic) catalog.
        """
        calculated = {f.id: f for f in self.calculated_fields}
        known = {f.id for f in self.fields}
        order: list[str] = []

        def visit(fid: str) -> None:
            if fid in order:
                return
            tree = parse_formula(calculated[fid].formula, known)
            for dep in sorted(referenced_fields(tree)):
                if dep in calculated:
                    visit(dep)
            order.append(fid)

        for fid in calculated:
            visit(fid)
        return order

    @property
    def raw_fields(self) -> list[Field]:
        return [f for f in self.fields if f.kind == "raw"]

    @property
    def calculated_fields(self) -> list[Field]:
        return [f for f in self.fields if f.kind == "calculated"]
