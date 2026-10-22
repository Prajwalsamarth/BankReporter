import json
from pathlib import Path

import numpy as np
import pytest

from app.catalog.loader import load_catalog
from app.mapping.matcher.assign import assign
from app.mapping.matcher.embed import Embedder
from app.mapping.matcher.llm import LlmMatcher
from app.mapping.matcher.pipeline import analyse_database, run_matching
from app.mapping.matcher.rules import effective_synonyms
from app.mapping.types import Candidate, ColumnProfile, ColumnRef, Decision, Join, JoinPlan

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")
R = lambda col, table="T": ColumnRef("s", table, col)


def test_conflict_resolved_by_score_and_loser_falls_back():
    decisions = {R("X"): Decision("net_income_monthly", 0.9, "B", "b"),
                 R("Y"): Decision("net_income_monthly", 0.8, "B", "b")}
    shortlists = {R("X"): [Candidate("net_income_monthly", 0.9, "B")],
                  R("Y"): [Candidate("net_income_monthly", 0.8, "B"), Candidate("gross_income_monthly", 0.7, "B")]}
    m = assign(decisions, shortlists, {}, CATALOG, column_order=[R("X"), R("Y")])
    assert m["net_income_monthly"].source == R("X")
    gross = m["gross_income_monthly"]
    assert (gross.source, gross.decided_by) == (R("Y"), "B")
    assert gross.score == pytest.approx(0.63)
    assert "fallback_after_conflict" in gross.warnings


def test_layer_priority_breaks_score_ties():
    decisions = {R("X"): Decision("city", 1.0, "C", "c"), R("Y"): Decision("city", 1.0, "A", "a")}
    m = assign(decisions, {}, {}, CATALOG, column_order=[R("X"), R("Y")])
    assert m["city"].source == R("Y")


def test_fixed_key_mappings_take_priority():
    decisions = {R("OTHER"): Decision("application_id", 1.0, "A", "a")}
    m = assign(decisions, {}, {"application_id": (R("APPL_NO"), "grain table primary key")}, CATALOG,
               column_order=[R("OTHER")])
    assert (m["application_id"].source, m["application_id"].decided_by) == (R("APPL_NO"), "key")


def test_llm_no_match_is_respected():
    decisions = {R("JUNK"): Decision(None, 0.9, "C", "audit column")}
    shortlists = {R("JUNK"): [Candidate("city", 0.6, "B")]}
    assert assign(decisions, shortlists, {}, CATALOG, column_order=[R("JUNK")])["city"].source is None


def test_every_raw_field_present_and_candidates_listed():
    decisions = {R("X"): Decision("city", 0.95, "B", "b")}
    shortlists = {R("X"): [Candidate("city", 0.95, "B"), Candidate("state", 0.8, "B")],
                  R("Z"): [Candidate("city", 0.7, "B")]}
    m = assign(decisions, shortlists, {}, CATALOG, column_order=[R("X"), R("Z")])
    assert set(m) == {f.id for f in CATALOG.raw_fields}
    assert m["pan_number"].decided_by == "none" and m["pan_number"].source is None
    assert [ref for ref, _ in m["city"].candidates] == [R("Z")]


# ---- pipeline ---------------------------------------------------------------

def prof(col, type_, table="T", **kw):
    return ColumnProfile(R(col, table), "X", type_, False, None, 0.0, 10, kw.pop("unique", False), **kw)


def keyword_encoder(texts):
    """Fake embedding: one dimension per keyword, so 'cibil score' text is near the CIBIL field."""
    words = ["cibil", "score", "income", "net", "monthly", "pan", "permanent", "city", "residence"]
    out = np.array([[t.lower().count(w) for w in words] for t in texts], dtype=float) + 1e-3
    return out


PLAN = JoinPlan(grain=R("APPL_NO"), joins=[])


def profiles():
    return [prof("APPL_NO", "string", unique=True), prof("CIB_SCR", "integer"),
            prof("NET_MTH_INC", "decimal"), prof("PAN_NO", "string")]


class OneShotChat:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete(self, messages, schema, model):
        self.calls += 1
        asked = [c["column"] for c in json.loads(messages[1]["content"])["columns"]]
        return json.dumps({"columns": [r for r in self.reply if r["column"] in asked]}), 50


def test_pipeline_layer_a_only_with_full_synonyms():
    result = run_matching(profiles(), PLAN, CATALOG, "A", effective_synonyms(CATALOG),
                          embedder=None, llm=None)
    m = result.mappings
    assert m["application_id"].decided_by == "key"
    assert (m["cibil_score"].source, m["cibil_score"].decided_by) == (R("CIB_SCR"), "A")
    assert m["pan_number"].source == R("PAN_NO")


def test_pipeline_masked_synonyms_go_to_b_then_c():
    no_syn = {f.id: [] for f in CATALOG.raw_fields}
    reply = [{"column": c, "field_id": f, "confidence": 0.9, "reason": "r", "suspected_transform": None}
             for c, f in [("CIB_SCR", "cibil_score"), ("NET_MTH_INC", "net_income_monthly"),
                          ("PAN_NO", "pan_number")]]
    chat = OneShotChat(reply)
    result = run_matching(profiles(), PLAN, CATALOG, "ABC", no_syn, embedder=Embedder(encode=keyword_encoder),
                          llm=LlmMatcher(chat, "m", sleep=lambda s: None), b_accept=1.01, b_margin=0.5)  # unreachable: forces the low-confidence path
    m = result.mappings
    assert {m[f].decided_by for f in ("cibil_score", "net_income_monthly", "pan_number")} == {"C"}
    assert m["cibil_score"].source == R("CIB_SCR")
    assert result.llm_calls == chat.calls == 1


def test_pipeline_without_llm_records_llm_disabled_and_uses_b():
    no_syn = {f.id: [] for f in CATALOG.raw_fields}
    result = run_matching(profiles(), PLAN, CATALOG, "ABC", no_syn, embedder=Embedder(encode=keyword_encoder),
                          llm=None, b_accept=1.01, b_margin=0.5)  # unreachable: forces the low-confidence path
    assert "llm_disabled" in result.warnings
    assert result.mappings["cibil_score"].decided_by == "B"
    assert "low_confidence" in result.mappings["cibil_score"].warnings


@pytest.mark.db
@pytest.mark.embed
@pytest.mark.parametrize("engine_fixture, schema", [("pg_engine", "los"), ("mysql_engine", "bfs_core")])
def test_analyse_real_client_with_full_synonyms_is_exact(request, engine_fixture, schema):
    from mockdata.writers import client1_pg, client2_mysql
    writer = client1_pg if schema == "los" else client2_mysql
    truth = {fid: {(s.name, c) for s in writer.TABLES for c, f in s.columns.items() if f == fid}
             for fid in {f.id for f in CATALOG.raw_fields}}
    engine = request.getfixturevalue(engine_fixture)
    analysis = analyse_database(engine, [schema], CATALOG, "AB", effective_synonyms(CATALOG),
                                embedder=Embedder(), llm=None)
    wrong = {fid: m.source for fid, m in analysis.result.mappings.items()
             if m.source is None or (m.source.table, m.source.column) not in truth[fid]}
    assert wrong == {}
