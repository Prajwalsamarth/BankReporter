"""Runs introspection -> profiling -> join plan -> layers A/B/C -> assignment."""
from dataclasses import dataclass

from sqlalchemy import Engine

from app.catalog.models import Catalog
from app.mapping.introspect import introspect
from app.mapping.joins import key_columns, plan_joins
from app.mapping.matcher.assign import assign
from app.mapping.matcher.embed import Embedder
from app.mapping.matcher.llm import LlmMatcher
from app.mapping.matcher.rules import match_rules
from app.mapping.names import norm
from app.mapping.profile import profile_columns
from app.mapping.types import ColumnProfile, ColumnRef, Decision, JoinPlan, MatchResult, SchemaInfo

GRAIN_FIELD = "application_id"


def run_matching(profiles: list[ColumnProfile], plan: JoinPlan, catalog: Catalog, layers: str,
                 synonyms: dict[str, list[str]], embedder: Embedder | None, llm: LlmMatcher | None,
                 b_accept: float = 0.85, b_margin: float = 0.05) -> MatchResult:
    keys = key_columns(plan)
    fixed = {GRAIN_FIELD: (plan.grain, "grain table primary key")}
    matchable = [p for p in profiles if p.ref not in keys and p.type != "other"]
    warnings: list[str] = []

    decisions: dict[ColumnRef, Decision] = match_rules(matchable, catalog, synonyms)
    rest = [p for p in matchable if p.ref not in decisions]
    shortlists = {}
    calls = tokens = 0
    if "B" in layers and embedder is not None and rest:
        use_llm = "C" in layers and llm is not None
        if "C" in layers and llm is None:
            warnings.append("llm_disabled")
        shortlists = embedder.shortlist_many(rest, catalog, synonyms)
        to_llm: dict[str, list[ColumnProfile]] = {}
        for p in rest:
            cands = shortlists[p.ref]
            if not cands:
                continue
            top, second = cands[0], (cands[1].score if len(cands) > 1 else 0.0)
            confident = top.score >= b_accept and top.score - second >= b_margin
            if confident or not use_llm:
                decisions[p.ref] = Decision(top.field_id, top.score, "B", f"embedding similarity {top.score:.2f}",
                                            [] if confident else ["low_confidence"])
            else:
                to_llm.setdefault(p.ref.table, []).append(p)
        for table, cols in to_llm.items():
            table_columns = [p.ref.column for p in profiles if p.ref.table == table]
            res = llm.choose(table, table_columns, cols, shortlists, catalog)
            decisions.update(res.decisions)
            calls, tokens = calls + res.calls, tokens + res.tokens

    mappings = assign(decisions, shortlists, fixed, catalog, [p.ref for p in matchable])
    return MatchResult(mappings, decisions, warnings, calls, tokens)


@dataclass
class Analysis:
    info: SchemaInfo
    profiles: list[ColumnProfile]
    plan: JoinPlan
    result: MatchResult


def grain_key_scorer(profiles: list[ColumnProfile], catalog: Catalog, synonyms: dict[str, list[str]],
                     embedder: Embedder | None):
    """How well a PK column matches application_id: 1.0 on an exact name/synonym hit, else B's cosine."""
    names = {norm(GRAIN_FIELD), *(norm(s) for s in synonyms.get(GRAIN_FIELD, []))}
    pks = [p for p in profiles if p.is_pk]
    scores = {p.ref: 1.0 for p in pks if norm(p.ref.column) in names}
    if embedder is not None:
        rest = [p for p in pks if p.ref not in scores]
        for ref, cands in embedder.shortlist_many(rest, catalog, synonyms, k=len(catalog.raw_fields)).items():
            scores[ref] = next((c.score for c in cands if c.field_id == GRAIN_FIELD), 0.0)
    return lambda ref: scores.get(ref, 0.0)


def analyse_database(engine: Engine, schemas: list[str], catalog: Catalog, layers: str,
                     synonyms: dict[str, list[str]], embedder: Embedder | None, llm: LlmMatcher | None,
                     b_accept: float = 0.85, b_margin: float = 0.05, row_limit: int = 50_000) -> Analysis:
    info = introspect(engine, schemas)
    profiles = profile_columns(engine, info, catalog, row_limit=row_limit)
    plan = plan_joins(info, profiles, grain_key_scorer(profiles, catalog, synonyms, embedder))
    result = run_matching(profiles, plan, catalog, layers, synonyms, embedder, llm, b_accept, b_margin)
    return Analysis(info, profiles, plan, result)
