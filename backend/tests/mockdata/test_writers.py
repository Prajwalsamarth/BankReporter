"""Writers load the canonical applications into each client schema faithfully.

The db tests run the real generator with its defaults (n=2000, seed=42, --reset), so the
databases end up exactly as `python -m mockdata.generate --reset` leaves them.
"""
import random
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.catalog.loader import load_catalog
from mockdata import generate
from mockdata.canonical import build_applications
from mockdata.golden import format_value, read_golden
from mockdata.writers import client1_pg, client2_mysql

CATALOG = load_catalog(Path(__file__).parents[3] / "catalog" / "fields.yaml")
RAW_IDS = {f.id for f in CATALOG.raw_fields}
TYPES = {f.id: f.type for f in CATALOG.raw_fields}


@pytest.mark.parametrize("writer", [client1_pg, client2_mysql])
def test_column_map_covers_every_raw_field(writer):
    mapped = {fid for spec in writer.TABLES for fid in spec.columns.values()}
    assert mapped == RAW_IDS


@pytest.mark.parametrize("writer", [client1_pg, client2_mysql])
def test_ddl_columns_match_column_map(writer):
    ddl = writer.DDL_PATH.read_text()
    for spec in writer.TABLES:
        for column in spec.columns:
            assert f"\n  {column} " in ddl, f"{spec.name}.{column} missing from {writer.DDL_PATH.name}"


CLIENT1_SQL = """
SELECT a.application_id, a.applied_on AS application_date, a.channel, a.branch_code,
       a.requested_amount, a.requested_tenure_months, a.loan_purpose, a.status AS application_status,
       c.customer_id, c.full_name AS applicant_name, c.date_of_birth, c.gender, c.marital_status,
       c.education, c.residence_type, c.years_at_residence, c.city, c.state, c.pincode,
       k.pan_number, k.aadhaar_masked, k.ckyc_number, k.kyc_status, k.verified_on AS kyc_verified_date,
       k.verification_mode AS kyc_mode,
       e.employment_type, e.employer_category, e.employer_name,
       e.gross_monthly_income AS gross_income_monthly, e.net_monthly_income AS net_income_monthly,
       e.years_in_current_job, e.total_experience_years,
       b.cibil_score, b.pulled_on AS bureau_pull_date, b.active_accounts, b.total_outstanding,
       b.monthly_emi_obligations AS existing_emi_monthly, b.oldest_account_age_months,
       b.card_utilization_pct, b.dpd30_l12m AS dpd30_count_l12m, b.dpd90_l12m AS dpd90_count_l12m,
       b.enquiries_l6m, b.has_writeoff,
       s.months_analysed AS bank_months_analysed, s.avg_monthly_balance, s.avg_monthly_credits,
       s.avg_monthly_debits, s.bounce_count, s.salary_regularity,
       d.decided_on AS decision_date, d.decision_mode, d.rejection_reason, d.approved_amount,
       d.interest_rate AS interest_rate_pct, d.approved_tenure_months, d.emi_amount AS approved_emi,
       x.disbursed_on AS disbursement_date, x.disbursed_amount, x.processing_fee
FROM los.loan_application a
JOIN los.customer c ON c.customer_id = a.customer_id
LEFT JOIN los.kyc_verification k ON k.application_id = a.application_id
LEFT JOIN los.employment e ON e.application_id = a.application_id
LEFT JOIN los.bureau_report b ON b.application_id = a.application_id
LEFT JOIN los.bank_analysis s ON s.application_id = a.application_id
LEFT JOIN los.credit_decision d ON d.application_id = a.application_id
LEFT JOIN los.disbursement x ON x.application_id = a.application_id
WHERE a.application_id IN :ids
"""

CLIENT2_SQL = """
SELECT l.APPL_NO AS application_id, l.APPL_DT AS application_date, l.SRC_CHNL AS channel,
       l.BR_CD AS branch_code, l.LN_AMT_REQ AS requested_amount, l.LN_TNR_REQ AS requested_tenure_months,
       l.LN_PURP AS loan_purpose, l.APPL_STS AS application_status, l.CUST_ID AS customer_id,
       l.CUST_NM AS applicant_name, l.CUST_DOB AS date_of_birth, l.GNDR AS gender,
       l.MRTL_STS AS marital_status, l.EDU_QUAL AS education, l.RES_TYP AS residence_type,
       l.YRS_RES AS years_at_residence, l.CITY_NM AS city, l.STATE_NM AS state, l.PIN_CD AS pincode,
       l.EMP_TYP AS employment_type, l.EMPLR_CAT AS employer_category, l.EMPLR_NM AS employer_name,
       l.GRS_MTH_INC AS gross_income_monthly, l.NET_MTH_INC AS net_income_monthly,
       l.YRS_CURR_JOB AS years_in_current_job, l.TOT_EXP_YRS AS total_experience_years,
       r.PAN_NO AS pan_number, r.AADH_MSK AS aadhaar_masked, r.CKYC_NO AS ckyc_number,
       r.KYC_STS AS kyc_status, r.KYC_VRF_DT AS kyc_verified_date, r.KYC_MODE AS kyc_mode,
       r.CIB_SCR AS cibil_score, r.CIB_PULL_DT AS bureau_pull_date, r.CIB_ACT_ACC AS active_accounts,
       r.CIB_TOT_OS AS total_outstanding, r.CIB_EMI_OBL AS existing_emi_monthly,
       r.CIB_OLD_ACC_MTHS AS oldest_account_age_months, r.CIB_CC_UTIL AS card_utilization_pct,
       r.DPD30_12M AS dpd30_count_l12m, r.DPD90_12M AS dpd90_count_l12m, r.ENQ_6M AS enquiries_l6m,
       r.WO_FLG AS has_writeoff, r.BS_MTHS AS bank_months_analysed, r.BS_AMB AS avg_monthly_balance,
       r.BS_AVG_CR AS avg_monthly_credits, r.BS_AVG_DR AS avg_monthly_debits,
       r.BS_BNC_CNT AS bounce_count, r.BS_SAL_REG AS salary_regularity,
       s.DCSN_DT AS decision_date, s.DCSN_MODE AS decision_mode, s.REJ_RSN AS rejection_reason,
       s.SANC_AMT AS approved_amount, s.ROI AS interest_rate_pct, s.SANC_TNR AS approved_tenure_months,
       s.EMI_AMT AS approved_emi, s.DISB_DT AS disbursement_date, s.DISB_AMT AS disbursed_amount,
       s.PF_AMT AS processing_fee
FROM bfs_core.TBL_LOAN_APPL l
LEFT JOIN bfs_core.TBL_APPL_RISK r ON r.APPL_NO = l.APPL_NO
LEFT JOIN bfs_core.TBL_SANCTION_DISB s ON s.APPL_NO = l.APPL_NO
WHERE l.APPL_NO IN :ids
"""


@pytest.fixture(scope="module")
def loaded(pg_engine, mysql_engine):
    """Default data (n=2000, seed=42) in both clients plus the golden CSV.

    Reuses what is already loaded when it matches, so views published by the app (which make
    --reset refuse) don't break the suite.
    """
    apps = build_applications(2000, 42)
    if not _default_data_loaded(pg_engine, mysql_engine):
        generate.run(n=2000, seed=42, reset=True)
    return apps, {row["application_id"]: row for row in read_golden(generate.GOLDEN_PATH)}


def _default_data_loaded(pg_engine, mysql_engine) -> bool:
    if not generate.GOLDEN_PATH.exists():
        return False
    golden_ids = [row["application_id"] for row in read_golden(generate.GOLDEN_PATH)]
    if golden_ids != [a["application_id"] for a in build_applications(2000, 42)]:
        return False
    for engine, sql in [(pg_engine, "SELECT COUNT(*) FROM los.loan_application"),
                        (mysql_engine, "SELECT COUNT(*) FROM bfs_core.TBL_LOAN_APPL")]:
        try:
            with engine.connect() as conn:
                if conn.execute(text(sql)).scalar_one() != 2000:
                    return False
        except Exception:
            return False
    return True


def counts(engine, schema, tables):
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{t}")).scalar_one() for t in tables}


@pytest.mark.db
def test_client1_row_counts(loaded, pg_engine):
    apps, _ = loaded
    decided = sum(a["decision_date"] is not None for a in apps)
    disbursed = sum(a["application_status"] == "DISBURSED" for a in apps)
    customers = len({a["customer_id"] for a in apps})
    assert customers < len(apps)   # repeat applicants exercise the 1-to-many join
    assert counts(pg_engine, "los", [s.name for s in client1_pg.TABLES]) == {
        "customer": customers, "loan_application": 2000, "kyc_verification": 2000, "employment": 2000,
        "bureau_report": 2000, "bank_analysis": 2000, "credit_decision": decided,
        "disbursement": disbursed,
    }


@pytest.mark.db
def test_client2_row_counts(loaded, mysql_engine):
    apps, _ = loaded
    decided = sum(a["decision_date"] is not None for a in apps)
    assert counts(mysql_engine, "bfs_core", [s.name for s in client2_mysql.TABLES]) == {
        "TBL_LOAN_APPL": 2000, "TBL_APPL_RISK": 2000, "TBL_SANCTION_DISB": decided,
    }


@pytest.mark.db
@pytest.mark.parametrize("client, sql", [("client1", CLIENT1_SQL), ("client2", CLIENT2_SQL)])
def test_sample_reads_back_equal_to_golden(loaded, pg_engine, mysql_engine, client, sql):
    _, golden = loaded
    engine = pg_engine if client == "client1" else mysql_engine
    ids = random.Random(1).sample(sorted(golden), 20)
    id_list = "(" + ", ".join(f"'{i}'" for i in ids) + ")"   # generated IDs like APP0000123
    with engine.connect() as conn:
        rows = conn.execute(text(sql.replace(":ids", id_list))).mappings().all()
    assert len(rows) == 20
    for row in rows:
        actual = {k: format_value(v, TYPES[k]) for k, v in row.items()}
        assert actual == golden[row["application_id"]]


@pytest.mark.db
@pytest.mark.parametrize("only, message", [
    ("client1", "client1 schema 'los' not empty; rerun with --reset"),
    ("client2", "client2 schema 'bfs_core' not empty; rerun with --reset"),
])
def test_rerun_without_reset_refuses(loaded, only, message):
    with pytest.raises(SystemExit, match=message):
        generate.run(n=10, seed=1, reset=False, only=only, write_golden_file=False)


def test_unreachable_database_message_names_url(monkeypatch):
    monkeypatch.setitem(generate.CLIENT_URLS, "client1", "postgresql+psycopg://u:secret@localhost:1/x")
    with pytest.raises(SystemExit, match=r"cannot connect to client1 at postgresql\+psycopg://u:\*\*\*@localhost:1/x"):
        generate.run(n=10, seed=1, reset=True, only="client1", write_golden_file=False)


def test_generator_refuses_data_that_breaks_invariants(monkeypatch):
    def broken(n, seed):
        apps = build_applications(n, seed)
        apps[0]["application_status"] = "SUBMITTED"
        apps[0]["decision_date"] = apps[0]["application_date"] + timedelta(days=30)
        return apps

    monkeypatch.setattr(generate, "build_applications", broken)
    with pytest.raises(AssertionError, match="undecided application has decision_date"):
        generate.run(n=10, seed=1, reset=True, only="client1", write_golden_file=False)


@pytest.mark.db
@pytest.mark.parametrize("only, engine_fixture, create_schema, view_sql", [
    ("client1", "pg_engine", "CREATE SCHEMA IF NOT EXISTS lending_rpt",
     "CREATE VIEW lending_rpt.probe_v AS SELECT application_id FROM los.loan_application"),
    ("client2", "mysql_engine", "CREATE DATABASE IF NOT EXISTS lending_rpt",
     "CREATE VIEW lending_rpt.probe_v AS SELECT APPL_NO FROM bfs_core.TBL_LOAN_APPL"),
])
def test_reset_refuses_while_views_elsewhere_depend_on_client_schema(
        loaded, request, only, engine_fixture, create_schema, view_sql):
    engine = request.getfixturevalue(engine_fixture)
    with engine.begin() as conn:
        conn.execute(text(create_schema))
        conn.execute(text(view_sql))
    try:
        with pytest.raises(SystemExit, match=r"views outside .* depend on it \(lending_rpt\.probe_v\)"):
            generate.run(n=10, seed=1, reset=True, only=only, write_golden_file=False)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP VIEW lending_rpt.probe_v"))
