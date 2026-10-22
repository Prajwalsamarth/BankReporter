import json
import os
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.mapping.matcher.llm import FileCache, LlmMatcher, OpenAIChatClient, build_request
from app.mapping.types import Candidate, ColumnProfile, ColumnRef

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")
TABLE_COLUMNS = ["APPL_NO", "CIB_SCR", "ENQ_6M", "BS_AMB"]


def prof(column, type_="integer", **kw):
    return ColumnProfile(ColumnRef("bfs_core", "TBL_APPL_RISK", column), "INT", type_, False, None,
                         kw.pop("null_pct", 0.0), 50, False, **kw)


SCR = prof("CIB_SCR", min=300, max=900, null_pct=8.0)
ENQ = prof("ENQ_6M", min=0, max=7)
SHORTLISTS = {
    SCR.ref: [Candidate("cibil_score", 0.71, "B"), Candidate("enquiries_l6m", 0.69, "B")],
    ENQ.ref: [Candidate("enquiries_l6m", 0.72, "B"), Candidate("active_accounts", 0.70, "B")],
}


class FakeChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, schema, model):
        self.requests.append(messages)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return (r if isinstance(r, str) else json.dumps(r)), 100


def answer(*cols):
    return {"columns": [dict(column=c, field_id=f, confidence=conf, reason="because",
                             suspected_transform=t) for c, f, conf, t in cols]}


def matcher(chat, **kw):
    return LlmMatcher(chat, model="test-model", sleep=lambda s: None, **kw)


def test_valid_response_becomes_c_decisions():
    chat = FakeChat(answer(("CIB_SCR", "cibil_score", 0.95, None), ("ENQ_6M", "enquiries_l6m", 0.9, None)))
    result = matcher(chat).choose("TBL_APPL_RISK", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    d = result.decisions[SCR.ref]
    assert (d.field_id, d.score, d.layer, d.reason) == ("cibil_score", 0.95, "C", "because")
    assert (result.calls, result.tokens) == (1, 100)


def test_choice_outside_shortlist_becomes_null():
    chat = FakeChat(answer(("CIB_SCR", "pan_number", 0.9, None), ("ENQ_6M", "enquiries_l6m", 0.9, None)))
    d = matcher(chat).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG).decisions[SCR.ref]
    assert d.field_id is None
    assert "llm_invalid_choice" in d.warnings


def test_null_choice_is_kept_as_no_match():
    chat = FakeChat(answer(("CIB_SCR", None, 0.8, None), ("ENQ_6M", "enquiries_l6m", 0.9, None)))
    d = matcher(chat).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG).decisions[SCR.ref]
    assert (d.field_id, d.layer, d.warnings) == (None, "C", [])


def test_missing_column_falls_back_to_b():
    chat = FakeChat(answer(("CIB_SCR", "cibil_score", 0.95, None)))
    d = matcher(chat).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG).decisions[ENQ.ref]
    assert (d.field_id, d.score, d.layer) == ("enquiries_l6m", 0.72, "B")
    assert "llm_missing" in d.warnings


def test_confidence_is_clamped_and_transform_flagged():
    chat = FakeChat(answer(("CIB_SCR", "cibil_score", 1.7, "values look scaled"),
                           ("ENQ_6M", "enquiries_l6m", -1, None)))
    r = matcher(chat).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG).decisions
    assert r[SCR.ref].score == 1.0 and r[ENQ.ref].score == 0.0
    assert "suspected_transform: values look scaled" in r[SCR.ref].warnings


def test_malformed_json_is_retried():
    chat = FakeChat("not json", {"wrong": 1},
                    answer(("CIB_SCR", "cibil_score", 0.9, None), ("ENQ_6M", "enquiries_l6m", 0.9, None)))
    result = matcher(chat).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert result.decisions[SCR.ref].field_id == "cibil_score"
    assert result.calls == 3


def test_failure_after_retries_falls_back_to_b_for_whole_table():
    sleeps = []
    m = LlmMatcher(FakeChat(TimeoutError(), TimeoutError(), TimeoutError()), model="m", sleep=sleeps.append)
    r = m.choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG).decisions
    assert sleeps == [1, 4]
    assert {(d.field_id, d.layer) for d in r.values()} == {("cibil_score", "B"), ("enquiries_l6m", "B")}
    assert all("llm_failed" in d.warnings for d in r.values())


def test_request_payload_contains_only_allowed_profile_keys():
    pan = ColumnProfile(ColumnRef("s", "T", "PAN_NO"), "CHAR(10)", "string", False, None, 0.0, 2000, True,
                        len_min=10, len_max=10, patterns=[("AAAAA9999A", 1.0)],
                        enum_overlap={}, sampled=False)
    messages = build_request("T", ["PAN_NO"], [pan], {pan.ref: [Candidate("pan_number", 0.8, "B")]}, CATALOG)
    payload = json.loads(messages[1]["content"])
    col = payload["columns"][0]
    assert set(col) == {"column", "type", "sql_type", "null_pct", "distinct_count", "unique", "is_pk",
                        "fk_to", "min", "max", "len_min", "len_max", "patterns", "enum_overlap", "candidates"}
    assert set(col["candidates"][0]) == {"field_id", "label", "description", "type", "unit", "values", "cosine"}
    assert payload["table"] == "T" and payload["table_columns"] == ["PAN_NO"]


def test_enum_candidates_include_values_others_do_not():
    messages = build_request("T", ["X"], [prof("X", "string")],
                             {ColumnRef("bfs_core", "TBL_APPL_RISK", "X"):
                              [Candidate("application_status", 0.8, "B"), Candidate("city", 0.7, "B")]},
                             CATALOG)
    cands = json.loads(messages[1]["content"])["columns"][0]["candidates"]
    assert cands[0]["values"][0] == "SUBMITTED"
    assert cands[1]["values"] is None


def test_file_cache_avoids_second_call(tmp_path):
    good = answer(("CIB_SCR", "cibil_score", 0.9, None), ("ENQ_6M", "enquiries_l6m", 0.9, None))
    chat = FakeChat(good)
    cache = FileCache(tmp_path)
    first = matcher(chat, cache=cache).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    second = matcher(chat, cache=cache).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert len(chat.requests) == 1
    assert (first.calls, second.calls) == (1, 0)
    assert second.decisions[SCR.ref].field_id == "cibil_score"


@pytest.mark.llm
def test_live_openai_call():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    from app.settings import Settings
    s = Settings()
    m = LlmMatcher(OpenAIChatClient(s.openai_api_key), model=s.llm_model)
    r = m.choose("TBL_APPL_RISK", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert r.decisions[SCR.ref].field_id == "cibil_score"


def test_refresh_mode_skips_cache_reads_but_writes(tmp_path):
    good = answer(("CIB_SCR", "cibil_score", 0.9, None), ("ENQ_6M", "enquiries_l6m", 0.9, None))
    cache = FileCache(tmp_path)
    matcher(FakeChat(good), cache=cache).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    fresh = answer(("CIB_SCR", "enquiries_l6m", 0.6, None), ("ENQ_6M", "enquiries_l6m", 0.9, None))
    chat = FakeChat(fresh)
    r = matcher(chat, cache=cache, read_cache=False).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert len(chat.requests) == 1 and r.decisions[SCR.ref].field_id == "enquiries_l6m"
    again = matcher(FakeChat(), cache=cache).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert again.decisions[SCR.ref].field_id == "enquiries_l6m"   # the refreshed answer was stored


def test_non_retryable_errors_fail_fast():
    m = LlmMatcher(FakeChat(PermissionError("401 invalid api key")), model="m", sleep=lambda s: None)
    r = m.choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert r.calls == 1
    assert all("llm_failed" in d.warnings for d in r.decisions.values())


def test_bad_confidence_in_response_is_retried_not_fatal():
    bad = {"columns": [dict(column="CIB_SCR", field_id="cibil_score", confidence="high", reason="r",
                            suspected_transform=None)]}
    good = answer(("CIB_SCR", "cibil_score", 0.9, None), ("ENQ_6M", "enquiries_l6m", 0.9, None))
    r = matcher(FakeChat(bad, good)).choose("T", TABLE_COLUMNS, [SCR, ENQ], SHORTLISTS, CATALOG)
    assert r.calls == 2 and r.decisions[SCR.ref].score == 0.9
