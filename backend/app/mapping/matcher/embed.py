"""Layer B: local embedding shortlist (spec §4.3)."""
from collections.abc import Callable

import numpy as np

from app.catalog.models import Catalog, Field
from app.mapping.compat import compatible
from app.mapping.matcher.abbreviations import expand
from app.mapping.types import Candidate, ColumnProfile, ColumnRef
from app.settings import ROOT

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DEFAULT_CACHE = ROOT / "data" / "models"


def column_text(p: ColumnProfile) -> str:
    """The expanded column name only. Statistics drowned out meaning for bge-small
    (top-1 89/116 with them, 111/116 without, all synonyms masked); Layer C gets them instead."""
    return expand(p.ref.column)


def field_text(f: Field, synonyms: list[str]) -> str:
    text = f"{f.label}. {f.description} Type {f.type}."
    if f.unit:
        text += f" Unit {f.unit}."
    if synonyms:
        text += f" Also known as: {', '.join(synonyms)}."
    return text


class Embedder:
    def __init__(self, model_name: str = MODEL_NAME, cache_dir=DEFAULT_CACHE,
                 encode: Callable[[list[str]], np.ndarray] | None = None):
        self._model_name, self._cache_dir = model_name, cache_dir
        self._encode, self._model = encode, None
        self._field_cache: dict[tuple, tuple[list[str], np.ndarray]] = {}

    def encode(self, texts: list[str]) -> np.ndarray:
        if self._encode is not None:
            vectors = np.asarray(self._encode(texts), dtype=float)
        else:
            if self._model is None:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(self._model_name, cache_dir=str(self._cache_dir))
            vectors = np.array(list(self._model.embed(texts)), dtype=float)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def _fields(self, catalog: Catalog, synonyms: dict[str, list[str]]) -> tuple[list[str], np.ndarray]:
        key = (catalog.version, tuple(sorted((k, tuple(v)) for k, v in synonyms.items())))
        if key not in self._field_cache:
            ids = [f.id for f in catalog.raw_fields]
            vecs = self.encode([field_text(f, synonyms.get(f.id, [])) for f in catalog.raw_fields])
            self._field_cache[key] = (ids, vecs)
        return self._field_cache[key]

    def shortlist_many(self, profiles: list[ColumnProfile], catalog: Catalog,
                       synonyms: dict[str, list[str]], k: int = 5) -> dict[ColumnRef, list[Candidate]]:
        if not profiles:
            return {}
        ids, field_vecs = self._fields(catalog, synonyms)
        fields = [catalog.field(fid) for fid in ids]
        sims = self.encode([column_text(p) for p in profiles]) @ field_vecs.T
        out = {}
        for p, row in zip(profiles, sims):
            allowed = [i for i, f in enumerate(fields) if compatible(p, f)]
            best = sorted(allowed, key=lambda i: -row[i])[:k]
            out[p.ref] = [Candidate(ids[i], round(float(row[i]), 4), "B") for i in best]
        return out
