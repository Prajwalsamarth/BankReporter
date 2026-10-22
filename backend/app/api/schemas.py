from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dialect: Literal["postgresql", "mysql"]
    host: str
    port: int
    database: str
    user: str
    password: str | None = None
    schemas: list[str] = Field(min_length=1)
    client_id: int | None = None


class ClientRefOut(BaseModel):
    id: int
    name: str


class ConnectionOut(BaseModel):
    id: int
    name: str
    dialect: str
    url_masked: str | None
    schemas: list[str]
    needs_password: bool = False
    client: ClientRefOut | None = None


class TestResultOut(BaseModel):
    ok: bool
    tables: list[str] = []
    error: str | None = None


SchemaField = Annotated[str | None, Field(alias="schema", serialization_alias="schema")]


class ColumnOut(BaseModel):
    schema_: SchemaField
    table: str
    column: str
    type: str


class RunStart(BaseModel):
    layers: Literal["A", "AB", "ABC"] = "ABC"


class RunStarted(BaseModel):
    run_id: int
    status: str


class SourceOut(BaseModel):
    schema_: SchemaField
    table: str
    column: str


class CandidateOut(SourceOut):
    score: float


class EntryOut(BaseModel):
    field_id: str
    label: str
    section: str
    required: bool
    source: SourceOut | None
    score: float
    decided_by: str
    reason: str
    warnings: list[str]
    candidates: list[CandidateOut]
    status: str


class RunOut(BaseModel):
    id: int
    connection_id: int
    status: str
    layers: str
    warnings: list[str]
    error: str | None
    llm_calls: int
    llm_tokens: int
    join_plan_confirmed: bool
    created_at: datetime
    finished_at: datetime | None


class RunDetail(BaseModel):
    run: RunOut
    join_plan: dict | None
    entries: list[EntryOut]
    blockers: list[str]
    affected_calculated: list[str]


class EntryPatch(BaseModel):
    action: Literal["accept", "choose", "not_available", "reset"]
    schema_: SchemaField = None
    table: str | None = None
    column: str | None = None


class AcceptAbove(BaseModel):
    threshold: float = Field(ge=0, le=1)


class JoinPlanIn(BaseModel):
    join_plan: dict
    confirmed: bool


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[list]


class PublishOut(BaseModel):
    ddl: str
    row_count: int
    schema_: str = Field(alias="schema", serialization_alias="schema")
