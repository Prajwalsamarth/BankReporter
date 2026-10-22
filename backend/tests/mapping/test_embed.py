from datetime import date
from pathlib import Path

import numpy as np
import pytest

from app.catalog.loader import load_catalog
from app.mapping.matcher.embed import Embedder, column_text, field_text
from app.mapping.matcher.rules import effective_synonyms
from app.mapping.types import ColumnProfile, ColumnRef

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")
NO_SYNONYMS = {f.id: [] for f in CATALOG.raw_fields}


def prof(column, type_="string", table="TBL_X", **kw):
    return ColumnProfile(ColumnRef("s", table, column), "X", type_, False, None, kw.pop("null_pct", 0.0),
                         10, kw.pop("unique", False), **kw)


def test_column_text_is_the_expanded_name_only():
    # Statistics drown out meaning for bge-small (measured: top-1 89/116 with stats vs 111/116 without);
    # they are given to Layer C instead.
    p = prof("CIB_SCR", "integer", table="TBL_APPL_RISK", min=300, max=900, null_pct=8.0)
    assert column_text(p) == "cibil score"
    assert column_text(prof("NetMthInc", "decimal")) == "net monthly income"


def test_field_text_respects_masking():
    field = CATALOG.field("cibil_score")
    assert field_text(field, ["cib_scr", "credit_score"]) == (
        "CIBIL Score. CIBIL TransUnion score at application (300-900); null if new-to-credit. "
        "Type integer. Also known as: cib_scr, credit_score.")
    assert "Also known as" not in field_text(field, [])
    assert "Unit INR" in field_text(CATALOG.field("requested_amount"), [])


def fake_encoder(texts):
    """Deterministic vectors: hash words into 64 buckets (bag of words), L2-normalised."""
    out = np.zeros((len(texts), 64))
    for i, t in enumerate(texts):
        for w in t.lower().replace(".", " ").split():
            out[i, hash(w) % 64] += 1
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def test_shortlist_filters_by_type_and_limits_k():
    emb = Embedder(encode=fake_encoder)
    p = prof("SOME_DATE", "date", min=date(2025, 1, 1), max=date(2026, 1, 1))
    cands = emb.shortlist_many([p], CATALOG, NO_SYNONYMS, k=5)[p.ref]
    assert len(cands) == 5
    assert all(CATALOG.field(c.field_id).type == "date" for c in cands)
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)
    assert all(c.layer == "B" for c in cands)


def test_field_embeddings_cached_per_synonym_set():
    calls = []

    def counting(texts):
        calls.append(len(texts))
        return fake_encoder(texts)

    emb = Embedder(encode=counting)
    p = prof("X", "integer")
    emb.shortlist_many([p], CATALOG, NO_SYNONYMS)
    emb.shortlist_many([p], CATALOG, NO_SYNONYMS)
    emb.shortlist_many([p], CATALOG, effective_synonyms(CATALOG))
    field_batches = [n for n in calls if n == len(CATALOG.raw_fields)]
    assert len(field_batches) == 2


@pytest.fixture(scope="module")
def real_embedder():
    try:
        emb = Embedder()
        emb.encode(["warm up"])
    except Exception as exc:  # model download / load failure
        pytest.skip(f"embedding model unavailable: {exc}")
    return emb


@pytest.mark.embed
def test_real_model_ranks_obvious_fields_with_synonyms_masked(real_embedder):
    inc = prof("NET_MTH_INC", "decimal", table="TBL_LOAN_APPL", min=8000, max=900000)
    scr = prof("CIB_SCR", "integer", table="TBL_APPL_RISK", min=300, max=900, null_pct=8.0)
    result = real_embedder.shortlist_many([inc, scr], CATALOG, NO_SYNONYMS)
    assert result[inc.ref][0].field_id == "net_income_monthly"
    assert "cibil_score" in [c.field_id for c in result[scr.ref][:3]]
