import json

import pytest

from app.mapping import evaluate as ev
from app.mapping.types import ColumnRef, FieldMapping, JoinPlan
from mockdata.writers import client1_pg, client2_mysql
from tests.mapping.conftest import CATALOG


def test_answer_key_lists_every_copy_of_a_field():
    key = ev.answer_key(client1_pg)
    assert key["customer_id"] == {("customer", "customer_id"), ("loan_application", "customer_id")}
    assert key["cibil_score"] == {("bureau_report", "cibil_score")}
    assert set(key) == {f.id for f in CATALOG.raw_fields}


def test_exact_match_synonyms_for_client2():
    pairs = ev.exact_match_synonyms(CATALOG, ["CIB_SCR", "APPL_NO", "NOT_A_SYNONYM"])
    assert ("cibil_score", "cib_scr") in pairs
    assert ("application_id", "appl_no") in pairs
    assert all(s != "not_a_synonym" for _, s in pairs)


def test_mask_is_deterministic_and_sized():
    pairs = [("f", f"s{i}") for i in range(10)]
    assert ev.mask(pairs, 0.5, seed=1) == ev.mask(pairs, 0.5, seed=1)
    assert ev.mask(pairs, 0.5, seed=1) != ev.mask(pairs, 0.5, seed=2)
    assert len(ev.mask(pairs, 0.5, seed=1)) == 5
    assert ev.mask(pairs, 0.0, seed=1) == set() and ev.mask(pairs, 1.0, seed=1) == set(pairs)


def test_score_run_arithmetic():
    key = {f.id: {("t", f.id)} for f in CATALOG.raw_fields}
    R = lambda c: ColumnRef("s", "t", c)
    mappings = {f.id: FieldMapping(f.id, R(f.id), 1.0, "A") for f in CATALOG.raw_fields}
    mappings["cibil_score"] = FieldMapping("cibil_score", R("wrong"), 0.7, "C")      # wrong (required)
    mappings["city"] = FieldMapping("city", None, 0.0, "none")                          # unmapped
    mappings["pan_number"] = FieldMapping("pan_number", R("pan_number"), 0.9, "B")    # right via B
    plan = JoinPlan(ColumnRef("s", "t", "application_id"), [])
    m = ev.score_run(mappings, key, plan, expected_grain="t", expected_tables={"t"}, catalog=CATALOG)
    assert m["field_accuracy"] == pytest.approx(57 / 59)
    assert m["required_accuracy"] == pytest.approx(15 / 16)
    assert (m["wrong"], m["unmapped"]) == (1, 1)
    assert m["by_layer"]["C"] == {"decided": 1, "correct": 0}
    assert m["by_layer"]["B"] == {"decided": 1, "correct": 1}
    assert m["join_plan_correct"] is True
    assert ("cibil_score", "t.wrong") in [(e["field"], e["got"]) for e in m["errors"]]


@pytest.mark.db
@pytest.mark.embed
def test_cli_smoke_without_llm(tmp_path, pg_engine, mysql_engine):
    ev.main(["--mask", "0,1.0", "--seeds", "1", "--layers", "A,AB,ABC", "--no-llm", "--out", str(tmp_path)])
    data = json.loads(next(tmp_path.glob("*-mapping-eval.json")).read_text())
    runs = {(r["client"], r["mask"], r["layers"]): r for r in data["runs"]}
    assert runs[("client1", 0.0, "A")]["field_accuracy"] == 1.0
    assert runs[("client2", 0.0, "A")]["field_accuracy"] == 1.0
    assert runs[("client2", 1.0, "A")]["by_layer"]["A"]["decided"] < 10
    assert {e["client"] for e in data["end_to_end"]} == {"client1", "client2"}
    report = next(tmp_path.glob("*-mapping-eval.md")).read_text()
    assert "Threats to validity" in report and "ABC skipped" in report
