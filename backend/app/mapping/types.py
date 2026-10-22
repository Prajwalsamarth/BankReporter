"""Core value types shared by introspection, profiling, join planning, matching and view generation."""
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class ColumnRef:
    schema: str | None
    table: str
    column: str

    @property
    def label(self) -> str:
        return ".".join(p for p in (self.schema, self.table, self.column) if p)


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    ref_schema: str | None
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    sql_type: str
    type: str          # normalised: string|integer|decimal|date|boolean|other
    nullable: bool


@dataclass(frozen=True)
class TableInfo:
    schema: str | None
    name: str
    columns: tuple[ColumnInfo, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...]
    row_count: int

    @property
    def label(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    def column(self, name: str) -> ColumnInfo:
        return next(c for c in self.columns if c.name == name)


@dataclass(frozen=True)
class SchemaInfo:
    dialect: str
    tables: tuple[TableInfo, ...]

    def table(self, schema: str | None, name: str) -> TableInfo:
        return next(t for t in self.tables if t.schema == schema and t.name == name)


@dataclass
class ColumnProfile:
    ref: ColumnRef
    sql_type: str
    type: str
    is_pk: bool
    fk_to: ColumnRef | None
    null_pct: float
    distinct_count: int
    unique: bool
    min: object = None
    max: object = None
    len_min: int | None = None
    len_max: int | None = None
    patterns: list[tuple[str, float]] = field(default_factory=list)
    enum_overlap: dict[str, float] = field(default_factory=dict)
    bool_like: bool = False      # distinct values are a subset of {0, 1}
    sampled: bool = False


@dataclass(frozen=True)
class Join:
    schema: str | None
    table: str
    kind: str                            # one_to_one | many_to_one
    on: list[tuple[str, str]]            # (grain column, joined-table column)

    def __hash__(self):
        return hash((self.schema, self.table, self.kind, tuple(map(tuple, self.on))))


@dataclass
class JoinPlan:
    grain: ColumnRef
    joins: list[Join]
    excluded: list[dict] = field(default_factory=list)   # {"table": label, "reason": str}


@dataclass(frozen=True)
class Candidate:
    field_id: str
    score: float
    layer: str                           # A | B | C


@dataclass
class Decision:
    field_id: str | None
    score: float
    layer: str
    reason: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class FieldMapping:
    field_id: str
    source: ColumnRef | None
    score: float
    decided_by: str                      # A | B | C | key | none
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    candidates: list[tuple[ColumnRef, float]] = field(default_factory=list)


@dataclass
class MatchResult:
    mappings: dict[str, FieldMapping]
    column_decisions: dict[ColumnRef, Decision]
    warnings: list[str] = field(default_factory=list)
    llm_calls: int = 0
    llm_tokens: int = 0


def jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if type(value) is date else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(obj) -> dict:
    """JSON-safe dict of a dataclass (dates as ISO strings, Decimals as floats)."""
    return jsonable(asdict(obj))


def _ref(d: dict | None) -> ColumnRef | None:
    return ColumnRef(**d) if d else None


def load_join_plan(d: dict) -> JoinPlan:
    return JoinPlan(
        grain=_ref(d["grain"]),
        joins=[Join(j["schema"], j["table"], j["kind"], [tuple(p) for p in j["on"]]) for j in d["joins"]],
        excluded=list(d.get("excluded", [])),
    )


def load_profile(d: dict) -> ColumnProfile:
    return ColumnProfile(**{**d, "ref": _ref(d["ref"]), "fk_to": _ref(d["fk_to"]),
                            "patterns": [tuple(p) for p in d["patterns"]]})
