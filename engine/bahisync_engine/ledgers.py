"""Ledger suggestions.

Priority, highest first:
  1. Client rules  — what the accountant chose last time for this counterparty
  2. Default rules — common Indian bank narrations (ATM, GST, charges, ...)
  3. AI            — optional, see ai_suggest.py
  4. Party guess   — counterparty name as a new party ledger, low confidence
  5. Suspense A/c  — nothing matched

Anything below REVIEW_THRESHOLD confidence is flagged for the review screen.
Groups use TallyPrime's predefined group names so imports don't fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .models import Transaction

REVIEW_THRESHOLD = 0.75
SUSPENSE = "Suspense A/c"
CASH = "Cash"


@dataclass
class Rule:
    pattern: str
    ledger: str
    group: str
    direction: str | None = None  # "debit" | "credit" | None = both
    confidence: float = 0.85

    def __post_init__(self) -> None:
        self._re = re.compile(self.pattern, re.I)

    def matches(self, t: Transaction) -> bool:
        if self.direction and self.direction != t.direction:
            return False
        return bool(self._re.search(t.narration))


DEFAULT_RULES: list[Rule] = [
    Rule(r"\b(ATM\s*WDL|ATM\s*CASH|CASH\s*WDL|CASH\s*WITHDRAWAL|ATW|NFS\s*CASH)\b", CASH, "Cash-in-Hand", "debit", 0.9),
    Rule(r"\b(CASH\s*DEP(OSIT)?|BY\s*CASH|CDM\s*DEP)\b", CASH, "Cash-in-Hand", "credit", 0.9),
    Rule(r"\b(INT\.?\s*PD|INTEREST\s*(CREDIT|PAID)|INT\s*CR|SB\s*INT|CREDIT\s*INTEREST)\b", "Bank Interest Received", "Indirect Incomes", "credit", 0.9),
    Rule(r"\b(SMS\s*CHARGES|CHGS?|CHARGES|ANNUAL\s*FEE|DEBIT\s*CARD\s*FEE|MIN\s*BAL|AMC|GST\s*ON\s*CHG)\b", "Bank Charges", "Indirect Expenses", "debit", 0.88),
    Rule(r"\b(CBIC|GST\s*PAYMENT|GSTN|CPIN)\b", "GST Payable", "Duties & Taxes", "debit", 0.85),
    Rule(r"\b(CBDT|TDS\s*PAYMENT|ITNS\s*281|CHALLAN\s*281)\b", "TDS Payable", "Duties & Taxes", "debit", 0.82),
    Rule(r"\b(ADVANCE\s*TAX|SELF\s*ASSESSMENT\s*TAX|ITNS\s*280|CHALLAN\s*280)\b", "Income Tax", "Duties & Taxes", "debit", 0.8),
    Rule(r"\b(TSSPDCL|TSNPDCL|APSPDCL|APEPDCL|BESCOM|MSEDCL|TNEB|TANGEDCO|ELECTRICITY|ELEC\s*BILL)\b", "Electricity Charges", "Indirect Expenses", "debit", 0.85),
    Rule(r"\b(AIRTEL|JIO|VODAFONE|VI\s*POSTPAID|BSNL|ACT\s*FIBERNET)\b", "Telephone & Internet", "Indirect Expenses", "debit", 0.8),
    Rule(r"\b(HPCL|BPCL|IOCL|INDIAN\s*OIL|PETROL|FUEL)\b", "Fuel Expenses", "Indirect Expenses", "debit", 0.78),
    Rule(r"\bRENT\b", "Rent", "Indirect Expenses", "debit", 0.8),
    Rule(r"\b(LIC\s*OF\s*INDIA|INSURANCE|PREMIUM)\b", "Insurance", "Indirect Expenses", "debit", 0.78),
    Rule(r"\bSALARY\b", "Salary", "Indirect Expenses", "debit", 0.8),
    Rule(r"\bSALARY\b", "Salary Received", "Indirect Incomes", "credit", 0.8),
    Rule(r"\b(SWIGGY|ZOMATO)\b", "Staff Welfare", "Indirect Expenses", "debit", 0.6),
]

_NAME_CLEAN = re.compile(r"[^A-Za-z0-9&.\- ]+")
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_BANK_CODES = {"SBIN", "HDFC", "ICIC", "UTIB", "KKBK", "YESB", "PUNB", "BARB", "CNRB", "UBIN", "IDIB", "PYTM", "AIRP", "FDRL", "INDB", "IDFB"}


def counterparty(narration: str) -> str:
    """Best-effort counterparty name from a bank narration."""
    n = narration.strip()
    up = n.upper()
    parts: list[str]

    if up.startswith("UPI"):
        parts = re.split(r"[/\-]", n)
        # UPI/DR/<ref>/<NAME>/<BANK>/<vpa>/<note>  or  UPI-<NAME>-<vpa>-<IFSC>-<ref>-<note>
        for p in parts[1:]:
            p = p.strip()
            if not p or p.upper() in ("DR", "CR", "P2A", "P2M", "UPI") or p.isdigit() or "@" in p:
                continue
            if p.upper() in _BANK_CODES or _IFSC.match(p.upper()):
                continue
            return _title(p)
    if re.match(r"(?i)^(NEFT|RTGS)", up):
        parts = re.split(r"[-/]", n)
        cands = [p.strip() for p in parts[1:] if p.strip()]
        for i, p in enumerate(cands):
            if _IFSC.match(p.upper()) and i + 1 < len(cands):
                return _title(cands[i + 1])
        for p in cands:
            if not p.isdigit() and not _IFSC.match(p.upper()) and p.upper() not in ("CR", "DR", "NEFT CR", "NEFT DR"):
                return _title(p)
    if up.startswith("IMPS"):
        parts = [p.strip() for p in re.split(r"[/\-]", n) if p.strip()]
        # IMPS/P2A/<ref>/<remark>/<IFSC>/<NAME>: name usually follows the IFSC
        for i, p in enumerate(parts):
            if _IFSC.match(p.upper()) and i + 1 < len(parts):
                return _title(parts[i + 1])
        names = [p for p in parts[1:] if not p.isdigit() and p.upper() not in ("P2A", "P2M", "MOB", "IMPS")]
        if names:
            return _title(names[-1])
    m = re.match(r"(?i)^(CHQ|CHEQUE|CLG|TRF)\s*(PAID|DEP|DEPOSIT|TO|FROM|BY)?\s*\d*\s*(.+)$", n)
    if m and m.group(3):
        return _title(m.group(3))
    m = re.match(r"(?i)^POS\s+\S+\s+(.+)$", n)
    if m:
        return _title(re.sub(r"(?i)\b(HYD|BLR|MUM|DEL|CHN)\b.*$", "", m.group(1)))
    m = re.match(r"(?i)^ACH\s*[DC]?-?\s*(.+?)(?:-|$)", n)
    if m:
        return _title(m.group(1))
    return ""


def _title(s: str) -> str:
    s = _NAME_CLEAN.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    if not s or s.isdigit():
        return ""
    return " ".join(w if (len(w) <= 3 and w.isupper() and w in ("PVT", "LTD", "LLP")) else w.capitalize() for w in s.split())


def counterparty_key(t: Transaction) -> str:
    """Stable key for client rules: the counterparty, else the narration with numbers removed."""
    cp = t.counterparty or counterparty(t.narration)
    base = cp if cp else re.sub(r"\d+", "", t.narration)
    return re.sub(r"[^a-z]", "", base.lower())[:60]


@dataclass
class ClientRules:
    """Ledger choices remembered per client: key -> (ledger, group)."""

    mapping: dict[str, tuple[str, str]] = field(default_factory=dict)

    def learn(self, t: Transaction, ledger: str, group: str) -> None:
        key = counterparty_key(t)
        if key:
            self.mapping[f"{t.direction}:{key}"] = (ledger, group)

    def lookup(self, t: Transaction) -> tuple[str, str] | None:
        return self.mapping.get(f"{t.direction}:{counterparty_key(t)}")

    def to_json(self) -> dict[str, list[str]]:
        return {k: [v[0], v[1]] for k, v in self.mapping.items()}

    @classmethod
    def from_json(cls, data: dict[str, Iterable[str]] | None) -> "ClientRules":
        return cls({k: (list(v)[0], list(v)[1]) for k, v in (data or {}).items()})


def voucher_type(t: Transaction) -> str:
    if t.ledger == CASH:
        return "Contra"
    return "Receipt" if t.direction == "credit" else "Payment"


def suggest(txns: list[Transaction], client: ClientRules | None = None, rules: list[Rule] | None = None) -> dict[str, str]:
    """Fill ledger fields on each transaction. Returns ledger -> group for every ledger used."""
    rules = rules if rules is not None else DEFAULT_RULES
    groups: dict[str, str] = {}
    for t in txns:
        t.counterparty = counterparty(t.narration)
        hit = client.lookup(t) if client else None
        if hit:
            t.ledger, group = hit
            t.ledger_source, t.confidence = "client_rule", 0.95
        else:
            rule = next((r for r in rules if r.matches(t)), None)
            if rule:
                t.ledger, group = rule.ledger, rule.group
                t.ledger_source, t.confidence = "default_rule", rule.confidence
            elif t.counterparty:
                t.ledger = t.counterparty
                group = "Sundry Debtors" if t.direction == "credit" else "Sundry Creditors"
                t.ledger_source, t.confidence = "party_guess", 0.5
            else:
                t.ledger, group = SUSPENSE, "Suspense A/c"
                t.ledger_source, t.confidence = "suspense", 0.0
        groups[t.ledger] = group
        t.voucher_type = voucher_type(t)
        _refresh_flags(t)
    return groups


def _refresh_flags(t: Transaction) -> None:
    t.flags = [f for f in t.flags if f not in ("needs_review", "suspense")]
    if t.ledger == SUSPENSE:
        t.flags.append("suspense")
    if t.confidence < REVIEW_THRESHOLD or t.balance_ok is False:
        t.flags.append("needs_review")


def apply_user_choice(t: Transaction, ledger: str, client: ClientRules | None, group: str) -> None:
    """Accountant picked a ledger on the review screen."""
    t.ledger = ledger.strip()
    t.ledger_source, t.confidence = "user", 1.0
    t.voucher_type = voucher_type(t)
    _refresh_flags(t)
    if client is not None and t.ledger != SUSPENSE:
        client.learn(t, t.ledger, group)
