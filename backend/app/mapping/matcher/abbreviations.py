"""Fixed, generic Indian-lending abbreviations used to enrich Layer B column text (spec §4.3).

Not tuned per client and never masked. Known bias: written knowing Client 2's naming style.
"""
from app.mapping.names import norm

ABBREVIATIONS: dict[str, str] = {
    "appl": "application", "app": "application", "dt": "date", "no": "number", "num": "number",
    "nm": "name", "cust": "customer", "amt": "amount", "req": "requested", "tnr": "tenure",
    "purp": "purpose", "sts": "status", "stat": "status", "chnl": "channel", "src": "source",
    "br": "branch", "cd": "code", "dob": "date of birth", "gndr": "gender", "mrtl": "marital",
    "edu": "education", "qual": "qualification", "res": "residence", "typ": "type", "yrs": "years",
    "mth": "monthly", "mths": "months", "inc": "income", "grs": "gross", "emp": "employment",
    "emplr": "employer", "cat": "category", "curr": "current", "tot": "total", "exp": "experience",
    "aadh": "aadhaar", "msk": "masked", "vrf": "verified", "cib": "cibil", "scr": "score",
    "act": "active", "acc": "accounts", "os": "outstanding", "obl": "obligation", "old": "oldest",
    "cc": "credit card", "util": "utilisation", "dpd": "days past due", "enq": "enquiries",
    "wo": "write off", "flg": "flag", "bs": "bank statement", "amb": "average monthly balance",
    "avg": "average", "cr": "credits", "dr": "debits", "bnc": "bounce", "cnt": "count",
    "sal": "salary", "reg": "regularity", "dcsn": "decision", "rej": "rejection", "rsn": "reason",
    "sanc": "sanctioned", "roi": "rate of interest", "disb": "disbursement", "pf": "processing fee",
    "pin": "pincode", "12m": "last 12 months", "6m": "last 6 months", "l12m": "last 12 months",
    "l6m": "last 6 months", "lan": "loan account number", "ln": "loan", "tbl": "table",
}


def expand(name: str) -> str:
    return " ".join(ABBREVIATIONS.get(tok, tok) for tok in norm(name).split("_") if tok)
