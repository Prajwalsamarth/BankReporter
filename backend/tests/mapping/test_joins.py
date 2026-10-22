import pytest

from app.mapping.joins import key_columns, plan_joins, validate_join_plan
from app.mapping.names import norm
from app.mapping.types import (
    ColumnInfo, ColumnProfile, ColumnRef, ForeignKey, Join, JoinPlan, SchemaInfo, TableInfo,
)


@pytest.mark.parametrize("raw, expected", [
    ("NET_MTH_INC", "net_mth_inc"), ("NetMthInc", "net_mth_inc"), ("applicationId", "application_id"),
    ("APPL-NO", "appl_no"), ("  cust id ", "cust_id"), ("PAN_NO", "pan_no"),
])
def test_norm(raw, expected):
    assert norm(raw) == expected


def make(schema, tables):
    """tables: {name: (pk, rows, [(col, unique)], [fk tuples (col, ref_table, ref_col)])}"""
    infos, profiles = [], []
    for name, (pk, rows, cols, fks) in tables.items():
        infos.append(TableInfo(
            schema, name, tuple(ColumnInfo(c, "VARCHAR", "string", True) for c, _ in cols),
            tuple(pk), tuple(ForeignKey((c,), schema, rt, (rc,)) for c, rt, rc in fks), rows))
        for c, unique in cols:
            profiles.append(ColumnProfile(ColumnRef(schema, name, c), "VARCHAR", "string", c in pk,
                                          None, 0.0, rows if unique else 3, unique))
    return SchemaInfo("postgresql", tuple(infos)), profiles


def no_key_signal(ref):
    return 0.0


CLIENT1_LIKE = {
    "customer": (["customer_id"], 1900, [("customer_id", True), ("full_name", False)], []),
    "loan_application": (["application_id"], 2000,
                         [("application_id", True), ("customer_id", False), ("status", False)],
                         [("customer_id", "customer", "customer_id")]),
    "kyc_verification": (["application_id"], 2000, [("application_id", True), ("pan_number", True)],
                         [("application_id", "loan_application", "application_id")]),
    "credit_decision": (["application_id"], 1700, [("application_id", True), ("decided_on", False)],
                        [("application_id", "loan_application", "application_id")]),
}

CLIENT2_LIKE = {
    "TBL_LOAN_APPL": (["APPL_NO"], 2000, [("APPL_NO", True), ("CUST_ID", False), ("APPL_STS", False),
                                          ("CUST_NM", False)], []),
    "TBL_APPL_RISK": (["APPL_NO"], 2000, [("APPL_NO", True), ("PAN_NO", True), ("CIB_SCR", False)], []),
    "TBL_SANCTION_DISB": (["APPL_NO"], 1700, [("APPL_NO", True), ("SANC_AMT", False)], []),
}


def test_client1_shape_uses_fks():
    info, profiles = make("los", CLIENT1_LIKE)
    plan = plan_joins(info, profiles, no_key_signal)
    assert plan.grain == ColumnRef("los", "loan_application", "application_id")
    assert {(j.table, j.kind, tuple(j.on[0])) for j in plan.joins} == {
        ("customer", "many_to_one", ("customer_id", "customer_id")),
        ("kyc_verification", "one_to_one", ("application_id", "application_id")),
        ("credit_decision", "one_to_one", ("application_id", "application_id")),
    }
    assert plan.excluded == []


def test_client2_shape_uses_same_name_unique_keys_and_breaks_tie_by_columns():
    info, profiles = make("bfs_core", CLIENT2_LIKE)
    plan = plan_joins(info, profiles, no_key_signal)
    assert plan.grain == ColumnRef("bfs_core", "TBL_LOAN_APPL", "APPL_NO")
    assert {(j.table, j.kind) for j in plan.joins} == {
        ("TBL_APPL_RISK", "one_to_one"), ("TBL_SANCTION_DISB", "one_to_one")}


def test_key_scorer_decides_between_otherwise_equal_tables():
    info, profiles = make("s", {
        "a": (["a_id"], 100, [("a_id", True), ("x", False)], []),
        "b": (["b_id"], 100, [("b_id", True), ("y", False)], []),
    })
    plan = plan_joins(info, profiles, lambda ref: 1.0 if ref.column == "b_id" else 0.0)
    assert plan.grain.table == "b"


def test_non_unique_child_is_excluded():
    tables = dict(CLIENT2_LIKE)
    tables["TBL_TXN"] = (["TXN_ID"], 9000, [("TXN_ID", True), ("APPL_NO", False)], [])
    info, profiles = make("bfs_core", tables)
    plan = plan_joins(info, profiles, no_key_signal)
    assert plan.grain.table == "TBL_LOAN_APPL"
    assert {"table": "bfs_core.TBL_TXN",
            "reason": "join column APPL_NO is not unique (would duplicate application rows)"} in plan.excluded


def test_unlinked_table_is_excluded():
    tables = dict(CLIENT1_LIKE)
    tables["audit_log"] = (["log_id"], 50, [("log_id", True), ("msg", False)], [])
    info, profiles = make("los", tables)
    plan = plan_joins(info, profiles, no_key_signal)
    assert {"table": "los.audit_log", "reason": "no join path to the grain table"} in plan.excluded


def test_key_columns_are_grain_pk_and_non_grain_join_sides():
    info, profiles = make("los", CLIENT1_LIKE)
    keys = key_columns(plan_joins(info, profiles, no_key_signal))
    assert keys == {
        ColumnRef("los", "loan_application", "application_id"),
        ColumnRef("los", "customer", "customer_id"),
        ColumnRef("los", "kyc_verification", "application_id"),
        ColumnRef("los", "credit_decision", "application_id"),
    }
    assert ColumnRef("los", "loan_application", "customer_id") not in keys


def test_validate_join_plan_rejects_non_unique_join_column():
    info, profiles = make("los", CLIENT1_LIKE)
    bad = JoinPlan(ColumnRef("los", "loan_application", "application_id"),
                   [Join("los", "customer", "one_to_one", [("application_id", "full_name")])])
    assert validate_join_plan(bad, info, profiles) == [
        "los.customer.full_name is not unique; joining on it would duplicate application rows"]


def test_validate_join_plan_rejects_unknown_column():
    info, profiles = make("los", CLIENT1_LIKE)
    bad = JoinPlan(ColumnRef("los", "loan_application", "application_id"),
                   [Join("los", "kyc_verification", "one_to_one", [("application_id", "nope")])])
    assert validate_join_plan(bad, info, profiles) == ["unknown column los.kyc_verification.nope"]


@pytest.mark.db
@pytest.mark.parametrize("engine_fixture, schema, grain, joined", [
    ("pg_engine", "los", "loan_application",
     {"customer", "kyc_verification", "employment", "bureau_report", "bank_analysis",
      "credit_decision", "disbursement"}),
    ("mysql_engine", "bfs_core", "TBL_LOAN_APPL", {"TBL_APPL_RISK", "TBL_SANCTION_DISB"}),
])
def test_plan_on_real_clients(request, engine_fixture, schema, grain, joined):
    from pathlib import Path
    from app.catalog.loader import load_catalog
    from app.mapping.introspect import introspect
    from app.mapping.profile import profile_columns

    engine = request.getfixturevalue(engine_fixture)
    catalog = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")
    info = introspect(engine, [schema])
    plan = plan_joins(info, profile_columns(engine, info, catalog), no_key_signal)
    assert plan.grain.table == grain
    assert {j.table for j in plan.joins} == joined
    assert plan.excluded == []
