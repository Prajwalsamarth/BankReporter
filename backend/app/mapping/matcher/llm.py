"""Layer C: an LLM chooses among Layer B's shortlist for low-confidence columns (spec §4.4).

Only names, types and aggregate statistics are sent; never raw values.
"""
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.catalog.models import Catalog
from app.mapping.types import Candidate, ColumnProfile, ColumnRef, Decision, jsonable

RETRY_DELAYS = (1, 4)          # seconds before the 2nd and 3rd attempt

SYSTEM_PROMPT = """You map columns of a bank's personal-loan database to a canonical field catalog.
For each column you get its name, type and aggregate statistics, plus up to 5 candidate fields.
Rules:
- Choose field_id ONLY from that column's candidates, or null if none fits.
- confidence is 0..1. reason is at most 25 words.
- If values look like they need a transform to fit the field (different unit, scale, code set or
  date format), describe it in suspected_transform; otherwise null. Never invent fields."""

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["columns"],
    "properties": {
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["column", "field_id", "confidence", "reason", "suspected_transform"],
                "properties": {
                    "column": {"type": "string"},
                    "field_id": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "suspected_transform": {"type": ["string", "null"]},
                },
            },
        }
    },
}


class ChatClient(Protocol):
    def complete(self, messages: list[dict], schema: dict, model: str) -> tuple[str, int]:
        """Return (JSON content, total tokens)."""


class OpenAIChatClient:
    def __init__(self, api_key: str, timeout: float = 60.0):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    def complete(self, messages: list[dict], schema: dict, model: str) -> tuple[str, int]:
        resp = self._client.chat.completions.create(
            model=model, temperature=0, messages=messages,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "column_mapping", "strict": True, "schema": schema}},
        )
        return resp.choices[0].message.content, resp.usage.total_tokens if resp.usage else 0


class FileCache:
    """Responses keyed by sha256(model + request); makes evaluation re-runs free and repeatable."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)

    @staticmethod
    def key(model: str, messages: list[dict]) -> str:
        return hashlib.sha256((model + json.dumps(messages, sort_keys=True)).encode()).hexdigest()

    def get(self, key: str) -> str | None:
        path = self.dir / f"{key}.json"
        return path.read_text() if path.exists() else None

    def put(self, key: str, content: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{key}.json").write_text(content)


@dataclass
class TableResult:
    decisions: dict[ColumnRef, Decision]
    calls: int = 0
    tokens: int = 0
    warnings: list[str] = field(default_factory=list)


def _profile_payload(p: ColumnProfile) -> dict:
    return jsonable({
        "column": p.ref.column, "type": p.type, "sql_type": p.sql_type, "null_pct": p.null_pct,
        "distinct_count": p.distinct_count, "unique": p.unique, "is_pk": p.is_pk,
        "fk_to": p.fk_to.label if p.fk_to else None,
        "min": p.min, "max": p.max, "len_min": p.len_min, "len_max": p.len_max,
        "patterns": [list(x) for x in p.patterns], "enum_overlap": p.enum_overlap,
    })


def build_request(table: str, table_columns: list[str], columns: list[ColumnProfile],
                  shortlists: dict[ColumnRef, list[Candidate]], catalog: Catalog) -> list[dict]:
    payload = {"table": table, "table_columns": table_columns, "columns": []}
    for p in columns:
        entry = _profile_payload(p)
        entry["candidates"] = []
        for c in shortlists[p.ref]:
            f = catalog.field(c.field_id)
            entry["candidates"].append({
                "field_id": f.id, "label": f.label, "description": f.description, "type": f.type,
                "unit": f.unit, "values": f.values if f.type == "enum" else None, "cosine": c.score,
            })
        payload["columns"].append(entry)
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _parse(content: str) -> list[dict]:
    data = json.loads(content)
    cols = data["columns"] if isinstance(data, dict) else None
    if not isinstance(cols, list):
        raise ValueError("response has no 'columns' list")
    required = set(RESPONSE_SCHEMA["properties"]["columns"]["items"]["required"])
    for c in cols:
        if not isinstance(c, dict) or not required <= set(c):
            raise ValueError("response column entry is missing keys")
    return cols


class LlmMatcher:
    def __init__(self, client: ChatClient, model: str, sleep: Callable[[float], None] = time.sleep,
                 cache: FileCache | None = None, read_cache: bool = True):
        """read_cache=False: always ask the model, but still store answers (eval --refresh-llm)."""
        self.client, self.model, self.sleep, self.cache = client, model, sleep, cache
        self.read_cache = read_cache

    def choose(self, table: str, table_columns: list[str], columns: list[ColumnProfile],
               shortlists: dict[ColumnRef, list[Candidate]], catalog: Catalog) -> TableResult:
        result = TableResult(decisions={})
        messages = build_request(table, table_columns, columns, shortlists, catalog)
        answers = self._ask(messages, result)
        if answers is None:
            for p in columns:
                result.decisions[p.ref] = _fallback(shortlists[p.ref], "llm_failed",
                                                    "LLM unavailable; using embedding match")
            return result

        by_column = {a["column"]: a for a in answers}
        for p in columns:
            a = by_column.get(p.ref.column)
            if a is None:
                result.decisions[p.ref] = _fallback(shortlists[p.ref], "llm_missing",
                                                    "LLM gave no answer; using embedding match")
                continue
            allowed = {c.field_id for c in shortlists[p.ref]}
            warnings = [f"suspected_transform: {a['suspected_transform']}"] if a["suspected_transform"] else []
            field_id = a["field_id"]
            if field_id is not None and field_id not in allowed:
                field_id = None
                warnings.append("llm_invalid_choice")
            confidence = min(max(float(a["confidence"]), 0.0), 1.0)
            result.decisions[p.ref] = Decision(field_id, confidence, "C", str(a["reason"]), warnings)
        return result

    def _ask(self, messages: list[dict], result: TableResult) -> list[dict] | None:
        key = FileCache.key(self.model, messages) if self.cache else None
        if key and self.read_cache and (cached := self.cache.get(key)) is not None:
            try:
                return _parse(cached)
            except (ValueError, KeyError, TypeError):
                pass
        for attempt in range(len(RETRY_DELAYS) + 1):
            if attempt:
                self.sleep(RETRY_DELAYS[attempt - 1])
            try:
                result.calls += 1
                content, tokens = self.client.complete(messages, RESPONSE_SCHEMA, self.model)
                result.tokens += tokens
                answers = _parse(content)
            except Exception:  # timeouts, 5xx, 429, malformed or off-schema JSON: all retried
                continue
            if key:
                self.cache.put(key, content)
            return answers
        return None


def _fallback(shortlist: list[Candidate], warning: str, reason: str) -> Decision:
    if not shortlist:
        return Decision(None, 0.0, "B", reason, [warning])
    top = shortlist[0]
    return Decision(top.field_id, top.score, "B", reason, [warning])
