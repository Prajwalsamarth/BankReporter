"""Synthetic personal-loan applications in the canonical model (spec §5.4).

Records are dicts keyed by catalog raw field ID. Output is fully determined by (n, seed).
"""
import math
import random
import string
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker

START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 9, 30)

# Stored once per customer in Client 1, so repeat applicants must carry identical values.
CUSTOMER_FIELDS = (
    "customer_id", "applicant_name", "date_of_birth", "gender", "marital_status", "education",
    "residence_type", "years_at_residence", "city", "state", "pincode",
)
IDENTITY_FIELDS = ("pan_number", "aadhaar_masked", "ckyc_number")

UNDECIDED = ("SUBMITTED", "IN_REVIEW", "WITHDRAWN")
APPROVAL_FIELDS = ("approved_amount", "interest_rate_pct", "approved_tenure_months", "approved_emi")
DISBURSEMENT_FIELDS = ("disbursement_date", "disbursed_amount", "processing_fee")
DECISION_FIELDS = ("decision_date", "decision_mode", "rejection_reason") + APPROVAL_FIELDS

CENTS = Decimal("0.01")

# (city, state, PIN prefix) so city, state and pincode agree with each other.
CITIES = [
    ("Mumbai", "Maharashtra", "400"), ("Pune", "Maharashtra", "411"), ("Nagpur", "Maharashtra", "440"),
    ("Delhi", "Delhi", "110"), ("Bengaluru", "Karnataka", "560"), ("Mysuru", "Karnataka", "570"),
    ("Chennai", "Tamil Nadu", "600"), ("Coimbatore", "Tamil Nadu", "641"), ("Hyderabad", "Telangana", "500"),
    ("Kolkata", "West Bengal", "700"), ("Ahmedabad", "Gujarat", "380"), ("Surat", "Gujarat", "395"),
    ("Jaipur", "Rajasthan", "302"), ("Lucknow", "Uttar Pradesh", "226"), ("Noida", "Uttar Pradesh", "201"),
    ("Gurugram", "Haryana", "122"), ("Chandigarh", "Chandigarh", "160"), ("Indore", "Madhya Pradesh", "452"),
    ("Bhopal", "Madhya Pradesh", "462"), ("Kochi", "Kerala", "682"), ("Thiruvananthapuram", "Kerala", "695"),
    ("Bhubaneswar", "Odisha", "751"), ("Patna", "Bihar", "800"), ("Guwahati", "Assam", "781"),
]


def money(x: float) -> Decimal:
    return Decimal(str(round(x, 2))).quantize(CENTS)


def emi(principal: float, annual_rate_pct: float, months: int) -> float:
    r = annual_rate_pct / 1200
    growth = (1 + r) ** months
    return principal * r * growth / (growth - 1)


def rate_for_score(rng: random.Random, score: int | None) -> float:
    if score is None:
        lo, hi = 16.0, 22.0
    elif score >= 800:
        lo, hi = 10.5, 12.0
    elif score >= 750:
        lo, hi = 12.0, 14.0
    elif score >= 700:
        lo, hi = 14.0, 17.0
    else:
        lo, hi = 17.0, 24.0
    return round(rng.uniform(lo, hi), 2)


def build_applications(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)

    span = (END_DATE - START_DATE).days
    dates = sorted(START_DATE + timedelta(days=rng.randint(0, span)) for _ in range(n))
    customers: list[dict] = []
    apps = []
    for i, app_date in enumerate(dates, start=1):
        if customers and rng.random() < 0.05:
            customer = rng.choice(customers)
        else:
            customer = _new_customer(rng, fake, len(customers) + 1, app_date)
            customers.append(customer)
        apps.append(_application(rng, fake, f"APP{i:07d}", app_date, customer))
    return apps


def _new_customer(rng: random.Random, fake: Faker, number: int, app_date: date) -> dict:
    gender = rng.choices(["MALE", "FEMALE", "OTHER"], weights=[64, 35, 1])[0]
    first = fake.first_name_male() if gender == "MALE" else fake.first_name_female()
    age_days = rng.randint(21 * 365 + 6, 58 * 365)
    surname_letter = rng.choice(string.ascii_uppercase)
    city, state, pin_prefix = rng.choice(CITIES)
    return {
        "customer_id": f"CUST{number:06d}",
        "applicant_name": f"{first} {fake.last_name()}",
        "date_of_birth": app_date - timedelta(days=age_days),
        "gender": gender,
        "marital_status": rng.choices(["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"], weights=[38, 56, 4, 2])[0],
        "education": rng.choices(["BELOW_GRADUATE", "GRADUATE", "POST_GRADUATE", "PROFESSIONAL"],
                                 weights=[15, 50, 25, 10])[0],
        "residence_type": rng.choices(["OWNED", "RENTED", "PARENTAL", "COMPANY_PROVIDED"],
                                      weights=[30, 40, 25, 5])[0],
        "years_at_residence": rng.randint(0, 20),
        "city": city,
        "state": state,
        "pincode": f"{pin_prefix}{rng.randint(1, 99):03d}",
        "pan_number": ("".join(rng.choices(string.ascii_uppercase, k=3)) + "P" + surname_letter
                       + f"{rng.randint(0, 9999):04d}" + rng.choice(string.ascii_uppercase)),
        "aadhaar_masked": f"XXXX-XXXX-{rng.randint(0, 9999):04d}",
        "ckyc_number": None if rng.random() < 0.3 else f"{rng.randint(10**13, 10**14 - 1)}",
    }


def _application(rng: random.Random, fake: Faker, app_id: str, app_date: date, customer: dict) -> dict:
    a: dict = {k: customer[k] for k in CUSTOMER_FIELDS + IDENTITY_FIELDS}
    a["application_id"] = app_id
    a["application_date"] = app_date
    a["channel"] = rng.choices(["BRANCH", "DSA", "WEB", "MOBILE_APP", "PARTNER"], weights=[25, 30, 15, 20, 10])[0]
    a["branch_code"] = f"BR{rng.randint(1, 120):04d}"
    a["loan_purpose"] = rng.choice(["MEDICAL", "EDUCATION", "WEDDING", "HOME_RENOVATION", "TRAVEL",
                                    "DEBT_CONSOLIDATION", "CONSUMER_DURABLE", "OTHER"])

    _employment(rng, fake, a)
    net = float(a["net_income_monthly"])
    requested = min(max(round(net * rng.uniform(2, 10) / 5000) * 5000, 50000), 2_500_000)
    a["requested_amount"] = money(requested)
    a["requested_tenure_months"] = rng.choice([12, 24, 36, 48, 60])

    _bureau(rng, a)
    _banking(rng, a, net)

    status = rng.choices(["SUBMITTED", "IN_REVIEW", "WITHDRAWN", "DECIDED"], weights=[5, 5, 3, 87])[0]
    _kyc(rng, a, status)
    for f in DECISION_FIELDS + DISBURSEMENT_FIELDS:
        a[f] = None
    if status == "DECIDED":
        status = _decide(rng, a)
    a["application_status"] = status
    return a


def _employment(rng: random.Random, fake: Faker, a: dict) -> None:
    emp = rng.choices(["SALARIED", "SELF_EMPLOYED_PROFESSIONAL", "SELF_EMPLOYED_BUSINESS"], weights=[70, 12, 18])[0]
    a["employment_type"] = emp
    if emp == "SALARIED":
        a["employer_category"] = rng.choices(["GOVT", "PSU", "MNC", "LISTED_PVT", "UNLISTED_PVT"],
                                             weights=[10, 8, 22, 25, 35])[0]
    else:
        a["employer_category"] = "SELF"
    a["employer_name"] = fake.company()
    net = max(round(rng.lognormvariate(math.log(55000), 0.6), -2), 8000)
    a["net_income_monthly"] = money(net)
    a["gross_income_monthly"] = money(round(net * rng.uniform(1.15, 1.30), -2))
    total = round(rng.uniform(1, 30), 1)
    a["total_experience_years"] = Decimal(str(total)).quantize(CENTS)
    a["years_in_current_job"] = Decimal(str(round(rng.uniform(0.2, total), 1))).quantize(CENTS)


def _bureau(rng: random.Random, a: dict) -> None:
    net = float(a["net_income_monthly"])
    a["bureau_pull_date"] = a["application_date"] + timedelta(days=rng.randint(0, 1))
    a["enquiries_l6m"] = rng.choices(range(8), weights=[30, 25, 18, 10, 7, 5, 3, 2])[0]
    if rng.random() < 0.08:
        a.update(cibil_score=None, oldest_account_age_months=None, active_accounts=0,
                 total_outstanding=money(0), existing_emi_monthly=money(0), card_utilization_pct=None,
                 dpd30_count_l12m=0, dpd90_count_l12m=0, has_writeoff=False)
        return
    a["cibil_score"] = int(min(max(rng.gauss(730, 60), 300), 900))
    a["oldest_account_age_months"] = rng.randint(6, 240)
    a["active_accounts"] = rng.randint(1, 8)
    emi_total = 0 if rng.random() < 0.25 else round(net * rng.uniform(0, 0.45), -2)
    a["existing_emi_monthly"] = money(emi_total)
    a["total_outstanding"] = money(round(emi_total * rng.uniform(10, 40), -2))
    a["card_utilization_pct"] = None if rng.random() < 0.4 else money(rng.uniform(0, 100))
    a["dpd30_count_l12m"] = rng.choices(range(4), weights=[80, 12, 5, 3])[0]
    a["dpd90_count_l12m"] = rng.choices(range(3), weights=[93, 5, 2])[0]
    a["has_writeoff"] = rng.random() < 0.03


def _banking(rng: random.Random, a: dict, net: float) -> None:
    credits = net * rng.uniform(0.9, 1.3)
    a["bank_months_analysed"] = rng.choice([3, 6, 12])
    a["avg_monthly_credits"] = money(credits)
    a["avg_monthly_debits"] = money(credits * rng.uniform(0.8, 1.0))
    a["avg_monthly_balance"] = money(net * rng.uniform(0.1, 1.5))
    a["bounce_count"] = rng.choices(range(6), weights=[70, 15, 7, 4, 2, 2])[0]
    if a["employment_type"] == "SALARIED":
        a["salary_regularity"] = "REGULAR" if rng.random() < 0.9 else "IRREGULAR"
    else:
        a["salary_regularity"] = "NOT_APPLICABLE"


def _kyc(rng: random.Random, a: dict, status: str) -> None:
    a["kyc_mode"] = rng.choice(["VIDEO_KYC", "IN_PERSON", "DIGILOCKER", "OFFLINE_XML"])
    if status == "SUBMITTED" or (status in UNDECIDED and rng.random() < 0.3):
        a["kyc_status"], a["kyc_verified_date"] = "PENDING", None
        return
    a["kyc_status"] = "FAILED" if status == "DECIDED" and rng.random() < 0.02 else "VERIFIED"
    a["kyc_verified_date"] = a["application_date"] + timedelta(days=rng.randint(0, 3))


def _decide(rng: random.Random, a: dict) -> str:
    """Apply the rejection rules in order; returns the final status."""
    after = a["kyc_verified_date"] or a["application_date"]
    a["decision_date"] = after + timedelta(days=rng.randint(0, 7))
    a["decision_mode"] = "AUTO" if rng.random() < 0.6 else "MANUAL"

    net = float(a["net_income_monthly"])
    rate = rate_for_score(rng, a["cibil_score"])
    proposed_emi = emi(float(a["requested_amount"]), rate, a["requested_tenure_months"])
    post_foir = (float(a["existing_emi_monthly"]) + proposed_emi) / net * 100
    score = a["cibil_score"]

    reason = None
    if a["kyc_status"] == "FAILED":
        reason = "KYC_FAILED"
    elif a["has_writeoff"]:
        reason = "WRITEOFF_HISTORY"
    elif score is not None and score < 650:
        reason = "LOW_CIBIL"
    elif net < 15000:
        reason = "INSUFFICIENT_INCOME"
    elif post_foir > 60:
        reason = "HIGH_FOIR"
    elif rng.random() < 0.03:
        reason = "POLICY_OTHER"
    if reason:
        a["rejection_reason"] = reason
        return "REJECTED"

    requested = float(a["requested_amount"])
    approved = requested if rng.random() >= 0.3 else round(requested * rng.uniform(0.6, 1.0) / 1000) * 1000
    tenure = a["requested_tenure_months"]
    a["approved_amount"] = money(approved)
    a["interest_rate_pct"] = money(rate)
    a["approved_tenure_months"] = tenure
    a["approved_emi"] = money(emi(approved, rate, tenure))
    if rng.random() >= 0.85:
        return "APPROVED"
    a["disbursement_date"] = a["decision_date"] + timedelta(days=rng.randint(1, 10))
    a["disbursed_amount"] = a["approved_amount"]
    a["processing_fee"] = money(approved * rng.uniform(0.01, 0.025))
    return "DISBURSED"


def check_invariants(apps: list[dict]) -> None:
    """Raise AssertionError naming the application and rule on the first violation."""
    for a in apps:
        for msg in _violations(a):
            raise AssertionError(f"{a['application_id']}: {msg}")


def _violations(a: dict) -> list[str]:
    out = []
    status = a["application_status"]
    ordered = [a["application_date"], a["kyc_verified_date"], a["decision_date"], a["disbursement_date"]]
    present = [d for d in ordered if d is not None]
    if present != sorted(present):
        out.append("dates out of order (application <= kyc <= decision <= disbursement)")
    if a["bureau_pull_date"] < a["application_date"]:
        out.append("bureau pulled before application")

    if status in UNDECIDED:
        out += [f"undecided application has {f}" for f in DECISION_FIELDS + DISBURSEMENT_FIELDS
                if a[f] is not None]
    elif status == "REJECTED":
        out += [f"rejected application has {f}" for f in APPROVAL_FIELDS + DISBURSEMENT_FIELDS
                if a[f] is not None]
        if a["rejection_reason"] is None or a["decision_date"] is None:
            out.append("rejected application missing rejection_reason/decision_date")
    else:
        out += [f"{status.lower()} application missing {f}" for f in APPROVAL_FIELDS + ("decision_date",)
                if a[f] is None]
        if a["rejection_reason"] is not None:
            out.append(f"{status.lower()} application has rejection_reason")
        disb_present = [a[f] is not None for f in DISBURSEMENT_FIELDS]
        if status == "DISBURSED" and not all(disb_present):
            out.append("disbursed application missing disbursement fields")
        if status == "APPROVED" and any(disb_present):
            out.append("approved (not disbursed) application has disbursement fields")

    if a["approved_amount"] is not None and a["approved_amount"] > a["requested_amount"]:
        out.append("approved_amount > requested_amount")
    if a["disbursed_amount"] is not None and a["disbursed_amount"] > a["approved_amount"]:
        out.append("disbursed_amount > approved_amount")
    if a["cibil_score"] is None and a["oldest_account_age_months"] is not None:
        out.append("new-to-credit applicant has oldest_account_age_months")
    if a["kyc_status"] == "FAILED" and a["rejection_reason"] != "KYC_FAILED":
        out.append("failed KYC not rejected as KYC_FAILED")
    return out
