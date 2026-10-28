"""Bank detection from statement text. Detection is informational: the layout
parser works from column headers, so an unknown bank can still be parsed."""

from __future__ import annotations

import re

# IFSC prefix -> display name. Extend freely; order does not matter.
IFSC_PREFIXES = {
    "SBIN": "State Bank of India",
    "HDFC": "HDFC Bank",
    "ICIC": "ICICI Bank",
    "UTIB": "Axis Bank",
    "KKBK": "Kotak Mahindra Bank",
    "PUNB": "Punjab National Bank",
    "BARB": "Bank of Baroda",
    "CNRB": "Canara Bank",
    "UBIN": "Union Bank of India",
    "IOBA": "Indian Overseas Bank",
    "IDIB": "Indian Bank",
    "BKID": "Bank of India",
    "MAHB": "Bank of Maharashtra",
    "UCBA": "UCO Bank",
    "CBIN": "Central Bank of India",
    "PSIB": "Punjab & Sind Bank",
    "YESB": "Yes Bank",
    "INDB": "IndusInd Bank",
    "IDFB": "IDFC FIRST Bank",
    "FDRL": "Federal Bank",
    "KVBL": "Karur Vysya Bank",
    "TMBL": "Tamilnad Mercantile Bank",
    "SIBL": "South Indian Bank",
    "KARB": "Karnataka Bank",
    "CIUB": "City Union Bank",
    "DCBL": "DCB Bank",
    "RATN": "RBL Bank",
    "AUBL": "AU Small Finance Bank",
    "ESFB": "Equitas Small Finance Bank",
    "UJVN": "Ujjivan Small Finance Bank",
    "APGB": "Andhra Pradesh Grameena Vikas Bank",
    "APGV": "Andhra Pragathi Grameena Bank",
    "TGMB": "Telangana Grameena Bank",
    "TSAB": "Telangana State Co-op Apex Bank",
}

NAME_PATTERNS = [(re.compile(re.escape(name), re.I), name) for name in IFSC_PREFIXES.values()] + [
    (re.compile(r"\bstate bank of india\b|\bsbi\b", re.I), "State Bank of India"),
    (re.compile(r"\bhdfc\b", re.I), "HDFC Bank"),
    (re.compile(r"\bicici\b", re.I), "ICICI Bank"),
    (re.compile(r"\baxis bank\b", re.I), "Axis Bank"),
    (re.compile(r"\bkotak\b", re.I), "Kotak Mahindra Bank"),
]

_IFSC_RE = re.compile(r"\b([A-Z]{4})0[A-Z0-9]{6}\b")
_ACCOUNT_RE = re.compile(r"(?i)(?:a/c|account)\s*(?:no\.?|number)?\s*[:\-]?\s*([X\*\d]{6,20})")


def detect_bank(text: str) -> str:
    for m in _IFSC_RE.finditer(text):
        # Regional rural banks use their sponsor bank's IFSC with "RR" after the
        # zero (SBIN0RRDCGB); the printed bank name is the better signal there.
        if m.group(0)[5:7] == "RR":
            continue
        name = IFSC_PREFIXES.get(m.group(1))
        if name:
            return name
    for pattern, name in NAME_PATTERNS:
        if pattern.search(text):
            return name
    return "Unknown bank"


def account_hint(text: str) -> str:
    """Last four digits of the account number, if printed. Never store the full number."""
    m = _ACCOUNT_RE.search(text)
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    return f"XX{digits[-4:]}" if len(digits) >= 4 else ""
