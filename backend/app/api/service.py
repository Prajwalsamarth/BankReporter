"""Run execution and run-level rules (blockers, edits) shared by the API routes."""
from datetime import UTC, datetime

from sqlalchemy import create_engine

from app.catalog.formula import parse_formula, referenced_fields
from app.catalog.models import Catalog
from app.connections import decrypt_url, mask_secrets
from app.mapping.compat import compatible
from app.mapping.introspect import introspect
from app.mapping.matcher.pipeline import analyse_database
from app.mapping.matcher.rules import effective_synonyms
from app.mapping.types import ColumnRef, dump, load_join_plan, load_profile
from app.store import MappingEntry, MappingRun


class EditError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def _ref_dict(ref: ColumnRef | None) -> dict | None:
    return {"schema": ref.schema, "table": ref.table, "column": ref.column} if ref else None


def execute_run(store, run_id: int, catalog: Catalog, settings, embedder, llm) -> None:
    """Background task: analyse the client DB and store the suggestions on the run."""
    with store.session() as s:
        run = s.get(MappingRun, run_id)
        url = decrypt_url(run.connection.url_encrypted, settings.secret_key)
        schemas, layers = list(run.connection.schemas), run.layers
    engine = create_engine(url)
    try:
        analysis = analyse_database(engine, schemas, catalog, layers, effective_synonyms(catalog),
                                    embedder=embedder if "B" in layers else None,
                                    llm=llm if "C" in layers else None,
                                    b_accept=settings.b_accept, b_margin=settings.b_margin,
                                    row_limit=settings.profile_row_limit)
    except Exception as exc:
        with store.session() as s:
            run = s.get(MappingRun, run_id)
            run.status, run.error = "failed", mask_secrets(str(exc), url)
            run.finished_at = datetime.now(UTC)
            s.commit()
        return
    finally:
        engine.dispose()

    result = analysis.result
    with store.session() as s:
        run = s.get(MappingRun, run_id)
        run.profiles = [dump(p) for p in analysis.profiles]
        run.join_plan = dump(analysis.plan)
        run.warnings = list(result.warnings)
        run.llm_calls, run.llm_tokens = result.llm_calls, result.llm_tokens
        for position, f in enumerate(catalog.raw_fields):
            m = result.mappings[f.id]
            suggestion = {"source": _ref_dict(m.source), "score": m.score, "decided_by": m.decided_by,
                          "reason": m.reason, "warnings": m.warnings}
            entry = MappingEntry(run_id=run_id, field_id=f.id, position=position,
                                 candidates=[{**_ref_dict(r), "score": sc} for r, sc in m.candidates],
                                 suggestion=suggestion)
            _apply_suggestion(entry)
            s.add(entry)
        run.status, run.finished_at = "ready", datetime.now(UTC)
        s.commit()


def _apply_suggestion(entry: MappingEntry) -> None:
    sug = entry.suggestion
    src = sug["source"]
    entry.source_schema, entry.source_table, entry.source_column = (
        (src["schema"], src["table"], src["column"]) if src else (None, None, None))
    entry.score, entry.decided_by = sug["score"], sug["decided_by"]
    entry.reason, entry.warnings = sug["reason"], list(sug["warnings"])
    entry.status = "suggested" if src else "unmapped"


def entry_source(entry: MappingEntry) -> ColumnRef | None:
    if entry.status == "not_available" or entry.source_table is None:
        return None
    return ColumnRef(entry.source_schema, entry.source_table, entry.source_column)


def _plan_tables(run: MappingRun) -> set[tuple]:
    plan = load_join_plan(run.join_plan)
    return {(plan.grain.schema, plan.grain.table)} | {(j.schema, j.table) for j in plan.joins}


def blockers(run: MappingRun, catalog: Catalog) -> list[str]:
    if run.status not in ("ready", "published"):
        return [f"Run is not ready (status: {run.status})"]
    out = [] if run.join_plan_confirmed else ["Join plan not confirmed"]
    tables = _plan_tables(run)
    for e in run.entries:
        f = catalog.field(e.field_id)
        if f.required_for_mapping:
            if e.status == "not_available":
                out.append(f"Required field {f.label} is marked not available")
            elif e.source_table is None:
                out.append(f"Required field {f.label} is unmapped")
        src = entry_source(e)
        if src and (src.schema, src.table) not in tables:
            out.append(f"{f.label}: source table {src.table} is not in the join plan")
    return out


def affected_calculated(run: MappingRun, catalog: Catalog) -> list[str]:
    missing = {e.field_id for e in run.entries if entry_source(e) is None}
    known = {f.id for f in catalog.fields}
    raw_deps: dict[str, set[str]] = {}
    for fid in catalog.calculation_order():
        deps = set()
        for d in referenced_fields(parse_formula(catalog.field(fid).formula, known)):
            deps |= raw_deps.get(d, {d})
        raw_deps[fid] = deps
    return [fid for fid in catalog.calculation_order() if raw_deps[fid] & missing]


def edit_entry(run: MappingRun, field_id: str, action: str, ref: ColumnRef | None, catalog: Catalog) -> MappingEntry:
    entry = next((e for e in run.entries if e.field_id == field_id), None)
    if entry is None:
        raise EditError(404, f"unknown field {field_id}")
    if action == "accept":
        if entry.source_table is None:
            raise EditError(409, f"{field_id} has no source to accept")
        entry.status = "accepted"
    elif action == "not_available":
        entry.source_schema = entry.source_table = entry.source_column = None
        entry.status = "not_available"
    elif action == "reset":
        _apply_suggestion(entry)
    elif action == "choose":
        _choose(run, entry, ref, catalog)
    if run.status == "published":
        run.status = "ready"
    return entry


def _choose(run: MappingRun, entry: MappingEntry, ref: ColumnRef | None, catalog: Catalog) -> None:
    if ref is None or not ref.table or not ref.column:
        raise EditError(422, "choose needs schema, table and column")
    profile = next((load_profile(p) for p in run.profiles if load_profile(p).ref == ref), None)
    if profile is None:
        raise EditError(404, f"unknown column {ref.label}")
    field = catalog.field(entry.field_id)
    if not compatible(profile, field):
        raise EditError(409, f"{ref.label} ({profile.type}) is not compatible with {field.label} ({field.type})")
    if (ref.schema, ref.table) not in _plan_tables(run):
        raise EditError(409, f"table {ref.table} is not in the join plan")
    other = next((e for e in run.entries if e is not entry and entry_source(e) == ref), None)
    if other is not None:
        raise EditError(409, f"{ref.label} is already the source of {catalog.field(other.field_id).label}")
    entry.source_schema, entry.source_table, entry.source_column = ref.schema, ref.table, ref.column
    entry.score = next((c["score"] for c in entry.candidates
                        if (c["schema"], c["table"], c["column"]) == (ref.schema, ref.table, ref.column)), 1.0)
    entry.reason, entry.warnings, entry.status = "chosen by user", [], "overridden"


def current_info(url: str, run: MappingRun):
    engine = create_engine(url)
    try:
        return engine, introspect(engine, list(run.connection.schemas))
    except Exception:
        engine.dispose()
        raise
