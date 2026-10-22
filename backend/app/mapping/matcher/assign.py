"""Global one-column-per-field assignment (spec §4.5)."""
from app.catalog.models import Catalog
from app.mapping.types import Candidate, ColumnRef, Decision, FieldMapping

LAYER_PRIORITY = {"A": 0, "C": 1, "B": 2}
FALLBACK_FACTOR = 0.9
MAX_ALTERNATIVES = 5


def assign(decisions: dict[ColumnRef, Decision], shortlists: dict[ColumnRef, list[Candidate]],
           fixed: dict[str, tuple[ColumnRef, str]], catalog: Catalog,
           column_order: list[ColumnRef]) -> dict[str, FieldMapping]:
    pool = []   # (score, priority, order, ref, field_id, decided_by, reason, warnings)
    for order, ref in enumerate(column_order):
        d = decisions.get(ref)
        if d is not None and d.field_id is not None:
            pool.append((d.score, LAYER_PRIORITY[d.layer], order, ref, d.field_id, d.layer, d.reason,
                         list(d.warnings)))
        if d is not None and d.layer == "C" and d.field_id is None:
            continue   # the LLM said this column matches nothing: no fallbacks
        chosen = d.field_id if d else None
        for c in shortlists.get(ref, []):
            if c.field_id != chosen:
                pool.append((round(c.score * FALLBACK_FACTOR, 4), LAYER_PRIORITY["B"], order, ref,
                             c.field_id, "B", "next-best embedding match", ["fallback_after_conflict"]))
    pool.sort(key=lambda e: (-e[0], e[1], e[2]))

    result: dict[str, FieldMapping] = {}
    used: set[ColumnRef] = set()
    for field_id, (ref, reason) in fixed.items():
        result[field_id] = FieldMapping(field_id, ref, 1.0, "key", reason)
        used.add(ref)
    for score, _, _, ref, field_id, layer, reason, warnings in pool:
        if field_id not in result and ref not in used:
            result[field_id] = FieldMapping(field_id, ref, score, layer, reason, warnings)
            used.add(ref)

    alternatives: dict[str, dict[ColumnRef, float]] = {}
    for score, _, _, ref, field_id, *_ in pool:
        best = alternatives.setdefault(field_id, {})
        best[ref] = max(best.get(ref, 0.0), score)

    out = {}
    for f in catalog.raw_fields:
        m = result.get(f.id) or FieldMapping(f.id, None, 0.0, "none")
        others = sorted(((r, s) for r, s in alternatives.get(f.id, {}).items() if r != m.source),
                        key=lambda x: -x[1])
        m.candidates = others[:MAX_ALTERNATIVES]
        out[f.id] = m
    return out
