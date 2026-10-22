-- Client 1 "NovaBank": modern, normalised schema with declared foreign keys.
CREATE SCHEMA los;

CREATE TABLE los.customer (
  customer_id VARCHAR(12) PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  date_of_birth DATE NOT NULL,
  gender VARCHAR(10),
  marital_status VARCHAR(10),
  education VARCHAR(20),
  residence_type VARCHAR(20),
  years_at_residence INTEGER,
  city VARCHAR(60),
  state VARCHAR(60),
  pincode CHAR(6)
);

CREATE TABLE los.loan_application (
  application_id VARCHAR(12) PRIMARY KEY,
  customer_id VARCHAR(12) NOT NULL REFERENCES los.customer (customer_id),
  applied_on DATE NOT NULL,
  channel VARCHAR(12),
  branch_code VARCHAR(10),
  requested_amount NUMERIC(14,2),
  requested_tenure_months INTEGER,
  loan_purpose VARCHAR(24),
  status VARCHAR(12) NOT NULL
);

CREATE TABLE los.kyc_verification (
  application_id VARCHAR(12) PRIMARY KEY REFERENCES los.loan_application (application_id),
  pan_number CHAR(10),
  aadhaar_masked CHAR(14),
  ckyc_number CHAR(14),
  kyc_status VARCHAR(10),
  verified_on DATE,
  verification_mode VARCHAR(12)
);

CREATE TABLE los.employment (
  application_id VARCHAR(12) PRIMARY KEY REFERENCES los.loan_application (application_id),
  employment_type VARCHAR(30),
  employer_category VARCHAR(15),
  employer_name VARCHAR(120),
  gross_monthly_income NUMERIC(14,2),
  net_monthly_income NUMERIC(14,2),
  years_in_current_job NUMERIC(5,2),
  total_experience_years NUMERIC(5,2)
);

CREATE TABLE los.bureau_report (
  application_id VARCHAR(12) PRIMARY KEY REFERENCES los.loan_application (application_id),
  cibil_score INTEGER,
  pulled_on DATE,
  active_accounts INTEGER,
  total_outstanding NUMERIC(14,2),
  monthly_emi_obligations NUMERIC(14,2),
  oldest_account_age_months INTEGER,
  card_utilization_pct NUMERIC(5,2),
  dpd30_l12m INTEGER,
  dpd90_l12m INTEGER,
  enquiries_l6m INTEGER,
  has_writeoff BOOLEAN
);

CREATE TABLE los.bank_analysis (
  application_id VARCHAR(12) PRIMARY KEY REFERENCES los.loan_application (application_id),
  months_analysed INTEGER,
  avg_monthly_balance NUMERIC(14,2),
  avg_monthly_credits NUMERIC(14,2),
  avg_monthly_debits NUMERIC(14,2),
  bounce_count INTEGER,
  salary_regularity VARCHAR(16)
);

CREATE TABLE los.credit_decision (
  application_id VARCHAR(12) PRIMARY KEY REFERENCES los.loan_application (application_id),
  decided_on DATE NOT NULL,
  decision_mode VARCHAR(8),
  rejection_reason VARCHAR(24),
  approved_amount NUMERIC(14,2),
  interest_rate NUMERIC(5,2),
  approved_tenure_months INTEGER,
  emi_amount NUMERIC(14,2)
);

CREATE TABLE los.disbursement (
  application_id VARCHAR(12) PRIMARY KEY REFERENCES los.loan_application (application_id),
  disbursed_on DATE NOT NULL,
  disbursed_amount NUMERIC(14,2) NOT NULL,
  processing_fee NUMERIC(14,2)
);
