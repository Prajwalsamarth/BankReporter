"""Client 2 "Bharat Finserv" (MySQL, database bfs_core): wide legacy tables, no FKs."""
from sqlalchemy import Engine, text

from mockdata.writers import DDL_DIR, TableSpec, dependent_views, has_tables, run_ddl, write_tables

SCHEMA = "bfs_core"
DDL_PATH = DDL_DIR / "client2_mysql.sql"

TABLES = [
    TableSpec("TBL_LOAN_APPL", {
        "APPL_NO": "application_id", "CUST_ID": "customer_id", "APPL_DT": "application_date",
        "SRC_CHNL": "channel", "BR_CD": "branch_code", "CUST_NM": "applicant_name",
        "CUST_DOB": "date_of_birth", "GNDR": "gender", "MRTL_STS": "marital_status",
        "EDU_QUAL": "education", "RES_TYP": "residence_type", "YRS_RES": "years_at_residence",
        "CITY_NM": "city", "STATE_NM": "state", "PIN_CD": "pincode", "LN_AMT_REQ": "requested_amount",
        "LN_TNR_REQ": "requested_tenure_months", "LN_PURP": "loan_purpose",
        "APPL_STS": "application_status", "EMP_TYP": "employment_type",
        "EMPLR_CAT": "employer_category", "EMPLR_NM": "employer_name",
        "GRS_MTH_INC": "gross_income_monthly", "NET_MTH_INC": "net_income_monthly",
        "YRS_CURR_JOB": "years_in_current_job", "TOT_EXP_YRS": "total_experience_years",
    }),
    TableSpec("TBL_APPL_RISK", {
        "APPL_NO": "application_id", "PAN_NO": "pan_number", "AADH_MSK": "aadhaar_masked",
        "CKYC_NO": "ckyc_number", "KYC_STS": "kyc_status", "KYC_VRF_DT": "kyc_verified_date",
        "KYC_MODE": "kyc_mode", "CIB_SCR": "cibil_score", "CIB_PULL_DT": "bureau_pull_date",
        "CIB_ACT_ACC": "active_accounts", "CIB_TOT_OS": "total_outstanding",
        "CIB_EMI_OBL": "existing_emi_monthly", "CIB_OLD_ACC_MTHS": "oldest_account_age_months",
        "CIB_CC_UTIL": "card_utilization_pct", "DPD30_12M": "dpd30_count_l12m",
        "DPD90_12M": "dpd90_count_l12m", "ENQ_6M": "enquiries_l6m", "WO_FLG": "has_writeoff",
        "BS_MTHS": "bank_months_analysed", "BS_AMB": "avg_monthly_balance",
        "BS_AVG_CR": "avg_monthly_credits", "BS_AVG_DR": "avg_monthly_debits",
        "BS_BNC_CNT": "bounce_count", "BS_SAL_REG": "salary_regularity",
    }),
    TableSpec("TBL_SANCTION_DISB", {
        "APPL_NO": "application_id", "DCSN_DT": "decision_date", "DCSN_MODE": "decision_mode",
        "REJ_RSN": "rejection_reason", "SANC_AMT": "approved_amount", "ROI": "interest_rate_pct",
        "SANC_TNR": "approved_tenure_months", "EMI_AMT": "approved_emi",
        "DISB_DT": "disbursement_date", "DISB_AMT": "disbursed_amount", "PF_AMT": "processing_fee",
    }, include=lambda a: a["decision_date"] is not None),
]


def is_populated(engine: Engine) -> bool:
    return has_tables(engine, SCHEMA)


def views_depending_on_schema(engine: Engine) -> list[str]:
    """MySQL's DROP DATABASE would leave such views broken, so callers must check first."""
    return dependent_views(engine, SCHEMA)


def write(engine: Engine, applications: list[dict]) -> None:
    """Drop and recreate database `bfs_core`, then load the applications.

    MySQL DDL is not transactional; the row inserts are.
    """
    with engine.begin() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCHEMA}"))
        conn.execute(text(f"CREATE DATABASE {SCHEMA}"))
        conn.execute(text(f"USE {SCHEMA}"))
        run_ddl(conn, DDL_PATH)
        write_tables(conn, SCHEMA, TABLES, applications)
