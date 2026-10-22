"""Client 1 "NovaBank" (Postgres, schema los): normalised, FKs declared."""
from sqlalchemy import Engine, text

from mockdata.writers import DDL_DIR, TableSpec, has_tables, run_ddl, write_tables

SCHEMA = "los"
DDL_PATH = DDL_DIR / "client1_postgres.sql"

TABLES = [
    TableSpec("customer", {
        "customer_id": "customer_id", "full_name": "applicant_name", "date_of_birth": "date_of_birth",
        "gender": "gender", "marital_status": "marital_status", "education": "education",
        "residence_type": "residence_type", "years_at_residence": "years_at_residence",
        "city": "city", "state": "state", "pincode": "pincode",
    }, dedupe_on="customer_id"),
    TableSpec("loan_application", {
        "application_id": "application_id", "customer_id": "customer_id",
        "applied_on": "application_date", "channel": "channel", "branch_code": "branch_code",
        "requested_amount": "requested_amount", "requested_tenure_months": "requested_tenure_months",
        "loan_purpose": "loan_purpose", "status": "application_status",
    }),
    TableSpec("kyc_verification", {
        "application_id": "application_id", "pan_number": "pan_number",
        "aadhaar_masked": "aadhaar_masked", "ckyc_number": "ckyc_number", "kyc_status": "kyc_status",
        "verified_on": "kyc_verified_date", "verification_mode": "kyc_mode",
    }),
    TableSpec("employment", {
        "application_id": "application_id", "employment_type": "employment_type",
        "employer_category": "employer_category", "employer_name": "employer_name",
        "gross_monthly_income": "gross_income_monthly", "net_monthly_income": "net_income_monthly",
        "years_in_current_job": "years_in_current_job", "total_experience_years": "total_experience_years",
    }),
    TableSpec("bureau_report", {
        "application_id": "application_id", "cibil_score": "cibil_score", "pulled_on": "bureau_pull_date",
        "active_accounts": "active_accounts", "total_outstanding": "total_outstanding",
        "monthly_emi_obligations": "existing_emi_monthly",
        "oldest_account_age_months": "oldest_account_age_months",
        "card_utilization_pct": "card_utilization_pct", "dpd30_l12m": "dpd30_count_l12m",
        "dpd90_l12m": "dpd90_count_l12m", "enquiries_l6m": "enquiries_l6m", "has_writeoff": "has_writeoff",
    }),
    TableSpec("bank_analysis", {
        "application_id": "application_id", "months_analysed": "bank_months_analysed",
        "avg_monthly_balance": "avg_monthly_balance", "avg_monthly_credits": "avg_monthly_credits",
        "avg_monthly_debits": "avg_monthly_debits", "bounce_count": "bounce_count",
        "salary_regularity": "salary_regularity",
    }),
    TableSpec("credit_decision", {
        "application_id": "application_id", "decided_on": "decision_date", "decision_mode": "decision_mode",
        "rejection_reason": "rejection_reason", "approved_amount": "approved_amount",
        "interest_rate": "interest_rate_pct", "approved_tenure_months": "approved_tenure_months",
        "emi_amount": "approved_emi",
    }, include=lambda a: a["decision_date"] is not None),
    TableSpec("disbursement", {
        "application_id": "application_id", "disbursed_on": "disbursement_date",
        "disbursed_amount": "disbursed_amount", "processing_fee": "processing_fee",
    }, include=lambda a: a["application_status"] == "DISBURSED"),
]


def is_populated(engine: Engine) -> bool:
    return has_tables(engine, SCHEMA)


def write(engine: Engine, applications: list[dict]) -> None:
    """Drop and recreate schema `los`, then load the applications (one transaction)."""
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        run_ddl(conn, DDL_PATH)
        write_tables(conn, SCHEMA, TABLES, applications)
