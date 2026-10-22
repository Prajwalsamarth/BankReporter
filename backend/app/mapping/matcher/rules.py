"""Layer A: exact name/synonym rules (spec §4.2). Decides only when certain."""
from app.catalog.models import Catalog
from app.mapping.compat import compatible
from app.mapping.names import norm
from app.mapping.types import ColumnProfile, ColumnRef, Decision


def effective_synonyms(catalog: Catalog, masked: set[tuple[str, str]] = frozenset()) -> dict[str, list[str]]:
    """Raw-field synonyms with the masked (field_id, synonym) pairs removed."""
    return {f.id: [s for s in f.synonyms if (f.id, s) not in masked] for f in catalog.raw_fields}


def match_rules(profiles: list[ColumnProfile], catalog: Catalog, synonyms: dict[str, list[str]],
                exclude: set[ColumnRef] = frozenset()) -> dict[ColumnRef, Decision]:
    fields = {f.id: f for f in catalog.raw_fields}
    names: dict[str, list[tuple[str, str]]] = {}      # normalised name -> [(field_id, reason)]
    for fid in fields:
        names.setdefault(norm(fid), []).append((fid, "name matches field id"))
        for s in synonyms.get(fid, []):
            names.setdefault(norm(s), []).append((fid, f"name matches synonym '{norm(s)}'"))

    decisions = {}
    for p in profiles:
        if p.ref in exclude:
            continue
        hits = {fid: reason for fid, reason in names.get(norm(p.ref.column), [])
                if compatible(p, fields[fid])}
        if len(hits) == 1:
            (fid, reason), = hits.items()
            decisions[p.ref] = Decision(fid, 1.0, "A", reason)
    return decisions
