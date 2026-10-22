from typing import Literal

from pydantic import BaseModel, ConfigDict

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

    @property
    def raw_fields(self) -> list[Field]:
        return [f for f in self.fields if f.kind == "raw"]

    @property
    def calculated_fields(self) -> list[Field]:
        return [f for f in self.fields if f.kind == "calculated"]
