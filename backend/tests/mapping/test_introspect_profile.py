import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.catalog.loader import load_catalog
from app.mapping.introspect import introspect, normalise_type
from app.mapping.profile import mask_pattern, profile_columns
from app.mapping.types import ColumnRef, dump

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")


@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE apps (id VARCHAR(10) PRIMARY KEY, status VARCHAR(12), "
                          "pan CHAR(10), score INTEGER, amount NUMERIC(14,2), applied DATE, flag INTEGER, "
                          "cust VARCHAR(10) REFERENCES custs(cid))"))
        conn.execute(text("CREATE TABLE custs (cid VARCHAR(10) PRIMARY KEY, nm VARCHAR(50))"))
        rows = [
            ("A1", "APPROVED", "ABCPK1234Z", 700, Decimal("1000.50"), date(2026, 1, 5), 1, "C1"),
            ("A2", "REJECTED", "XYZPQ9876A", 650, Decimal("250.00"), date(2026, 2, 1), 0, "C1"),
            ("A3", "approved ", "LMNPR5555B", None, Decimal("99.99"), date(2025, 12, 31), 0, "C2"),
            ("A4", "BOGUS", "QWEPT1111C", 810, None, date(2026, 3, 1), 1, "C2"),
        ]
        for r in rows:
            values = [str(v) if isinstance(v, (Decimal, date)) else v for v in r]   # SQLite stores text
            conn.execute(text("INSERT INTO apps VALUES (:a,:b,:c,:d,:e,:f,:g,:h)"),
                         dict(zip("abcdefgh", values)))
        conn.execute(text("INSERT INTO custs VALUES ('C1', 'Asha Rao'), ('C2', 'Vikram Singh')"))
    yield engine
    engine.dispose()


def test_mask_pattern():
    assert mask_pattern("ABCPK1234Z") == "AAAAA9999A"
    assert mask_pattern("XXXX-XXXX-1234") == "AAAA-AAAA-9999"
    assert mask_pattern("Chaudhary Enterprises Pvt") == "AAAAAAAAA AAAAAAAAAAA AAA"
    assert mask_pattern("Bhaktivedantaswami") == "AAAAAAAAAAAA…"   # runs over 12 are cut
    assert mask_pattern("Asha Rao") == "AAAA AAA"


def test_introspect_tables_keys_and_counts(sqlite_engine):
    info = introspect(sqlite_engine, ["main"])
    apps = info.table("main", "apps")
    assert apps.pk == ("id",)
    assert apps.row_count == 4
    assert apps.fks[0].ref_table == "custs"
    assert apps.column("amount").type == "decimal"
    assert apps.column("applied").type == "date"
    assert apps.column("pan").type == "string"
    assert info.dialect == "sqlite"


def test_profile_statistics(sqlite_engine):
    info = introspect(sqlite_engine, ["main"])
    profiles = {p.ref.column: p for p in profile_columns(sqlite_engine, info, CATALOG)
                if p.ref.table == "apps"}
    score = profiles["score"]
    assert (score.min, score.max) == (650, 810)
    assert score.null_pct == pytest.approx(25.0)
    assert score.distinct_count == 3
    assert profiles["id"].unique and profiles["id"].is_pk
    assert profiles["pan"].patterns == [("AAAAA9999A", 1.0)]
    assert (profiles["pan"].len_min, profiles["pan"].len_max) == (10, 10)
    assert profiles["cust"].fk_to == ColumnRef("main", "custs", "cid")
    assert str(profiles["applied"].min) == "2025-12-31"


def test_enum_overlap_is_case_and_space_insensitive(sqlite_engine):
    info = introspect(sqlite_engine, ["main"])
    status = next(p for p in profile_columns(sqlite_engine, info, CATALOG) if p.ref.column == "status")
    # APPROVED, REJECTED, "approved " -> APPROVED; BOGUS is not a valid status: 2 of 3 distinct normalised
    assert status.enum_overlap["application_status"] == pytest.approx(2 / 3, abs=1e-3)


def test_bool_like_integer_column(sqlite_engine):
    info = introspect(sqlite_engine, ["main"])
    profiles = {p.ref.column: p for p in profile_columns(sqlite_engine, info, CATALOG)}
    assert profiles["flag"].bool_like is True
    assert profiles["score"].bool_like is False


def test_sampling_flag_when_rows_exceed_limit(sqlite_engine):
    info = introspect(sqlite_engine, ["main"])
    profiles = profile_columns(sqlite_engine, info, CATALOG, row_limit=2)
    assert all(p.sampled for p in profiles if p.ref.table == "apps")
    assert not any(p.sampled for p in profiles if p.ref.table == "custs")


def test_serialised_profiles_contain_no_raw_string_values(sqlite_engine):
    info = introspect(sqlite_engine, ["main"])
    blob = json.dumps([dump(p) for p in profile_columns(sqlite_engine, info, CATALOG)])
    for raw in ["ABCPK1234Z", "XYZPQ9876A", "Asha Rao", "APPROVED", "REJECTED", "BOGUS", "A1", "C1"]:
        assert raw not in blob


def test_normalise_type_mysql_tinyint1_is_boolean():
    from sqlalchemy.dialects.mysql import TINYINT
    assert normalise_type(TINYINT(display_width=1)) == "boolean"
    assert normalise_type(TINYINT(display_width=4)) == "integer"


@pytest.mark.db
def test_introspect_client1(pg_engine):
    info = introspect(pg_engine, ["los"])
    assert {t.name for t in info.tables} == {
        "customer", "loan_application", "kyc_verification", "employment", "bureau_report",
        "bank_analysis", "credit_decision", "disbursement"}
    kyc = info.table("los", "kyc_verification")
    assert kyc.pk == ("application_id",)
    assert kyc.fks[0].ref_table == "loan_application"
    assert info.table("los", "bureau_report").column("has_writeoff").type == "boolean"


@pytest.mark.db
def test_introspect_client2_has_no_fks_and_tinyint_booleans(mysql_engine):
    info = introspect(mysql_engine, ["bfs_core"])
    assert {t.name for t in info.tables} == {"TBL_LOAN_APPL", "TBL_APPL_RISK", "TBL_SANCTION_DISB"}
    assert all(not t.fks for t in info.tables)
    assert info.table("bfs_core", "TBL_APPL_RISK").column("WO_FLG").type == "boolean"


@pytest.mark.db
def test_profile_client2_signals(mysql_engine):
    info = introspect(mysql_engine, ["bfs_core"])
    profiles = {p.ref.column: p for p in profile_columns(mysql_engine, info, CATALOG)}
    assert profiles["APPL_STS"].enum_overlap == {"application_status": 1.0}
    assert profiles["PAN_NO"].patterns[0] == ("AAAAA9999A", 1.0)
    assert 300 <= profiles["CIB_SCR"].min and profiles["CIB_SCR"].max <= 900
    assert profiles["APPL_NO"].unique
