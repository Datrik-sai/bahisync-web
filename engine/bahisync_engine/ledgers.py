"""Ledger suggestions.

Priority, highest first:
  1. Client rules  — what the accountant chose last time for this counterparty
  2. Default rules — common Indian bank narrations (ATM, GST, charges, ...)
  3. AI            — optional, see ai_suggest.py
  4. Party guess   — counterparty name as a new party ledger, low confidence.
                     Small one-off merchant spends go to Miscellaneous Expenses
                     instead, so Tally isn't flooded with one-time ledgers.
  5. Suspense A/c  — nothing matched

Each row also gets its counterparty type (merchant / person / unknown, from
NPCI P2M / P2A markers, the VPA and the name), how often that counterparty
appears in the statement, and the instrument number (UPI RRN, UTR, cheque).

Anything below REVIEW_THRESHOLD confidence is flagged for the review screen.
Groups use TallyPrime's predefined group names so imports don't fail.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from .models import Transaction

REVIEW_THRESHOLD = 0.75
SUSPENSE = "Suspense A/c"
CASH = "Cash"
MISC_EXPENSES = "Miscellaneous Expenses"
SMALL_TICKET = Decimal("2000")  # one-off merchant spends up to this go to MISC_EXPENSES
CASH_BANK_GROUPS = {"Bank Accounts", "Cash-in-Hand", "Bank OD A/c"}


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
            if _looks_like_reference(p) or _IFSC.match(p.upper()) or p.upper() in ("CR", "DR", "NEFT CR", "NEFT DR"):
                continue
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


def _looks_like_reference(p: str) -> bool:
    """UTRs and reference numbers: mostly digits, no spaces (HDFCN52026102812345)."""
    q = p.strip()
    return q.isdigit() or (" " not in q and sum(c.isdigit() for c in q) >= 6)


def _title(s: str) -> str:
    s = _NAME_CLEAN.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    if not s or s.isdigit():
        return ""
    return " ".join(w if (len(w) <= 3 and w.isupper() and w in ("PVT", "LTD", "LLP")) else w.capitalize() for w in s.split())


_BUSINESS = re.compile(
    r"(?i)\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CORP(ORATION)?|STORES?|MART|ENTERPRISES?|TRADERS?|TRADING|AGENC(Y|IES)|"
    r"SERVICES?|SOLUTIONS?|INDUSTRIES|HOTELS?|RESTAURANT|CAFE|MEDICALS?|PHARMA(CY)?|HARDWARE|ELECTRONICS|FOODS?|"
    r"SUPERMARKET|BAZAAR|CENTRE|CENTER|MOTORS|TEXTILES|JEWELL?ERS|DIGITAL|RETAIL|TECHNOLOGIES|INFOTECH|ASSOCIATES|"
    r"CONSTRUCTIONS?|SUPPLIERS?|DISTRIBUTORS?|CO)\b"
)
_MERCHANT_VPA = re.compile(
    r"(?i)^(q\d{5,}|paytmqr|paytm-|bharatpe|razorpay|rzp|mab\.|pay\.|merchant|ezetap|pinelabs|cashfree|billdesk|gpay-1)|"
    r"(\.rzp|merchant|@paytm|@yesbank|@ikwik|@axisb|@hdfcbank|@icici)$"
)
_PERSON_VPA = re.compile(r"(?i)(^\d{10}@|@ok(sbi|axis|icici|hdfcbank)$|@(ybl|ibl|axl|apl|upi)$)")
_BRANDS = re.compile(r"(?i)\b(SWIGGY|ZOMATO|AMAZON|FLIPKART|MYNTRA|UBER|OLA|RAPIDO|IRCTC|BIGBASKET|BLINKIT|ZEPTO|DMART|RELIANCE|JIOMART|NETFLIX|GOOGLE|APPLE|MAKEMYTRIP)\b")


def counterparty_type(narration: str, name: str) -> str:
    """'merchant' (a business), 'person' or 'unknown'.

    Order: a business-looking name, then NPCI's own P2M / P2A marker, then the
    payee's UPI handle, then the payment rail.
    """
    up = narration.upper()
    tokens = {p.strip() for p in re.split(r"[/\- ]", up)}
    if (name and _BUSINESS.search(name)) or _BRANDS.search(up):
        return "merchant"
    if "P2M" in tokens:
        return "merchant"
    if "P2A" in tokens or "P2P" in tokens:
        return "person"
    vpa = next((p.strip() for p in re.split(r"[/ ]|(?<=\w)-(?=\S*@)", narration) if "@" in p), "")
    if up.startswith("UPI"):
        if vpa and _MERCHANT_VPA.search(vpa):
            return "merchant"
        if vpa and _PERSON_VPA.search(vpa):
            return "person"
        return "unknown"
    if re.match(r"(?i)^(POS|ACH|BIL|ECS|NACH)\b", up):
        return "merchant"
    if name and re.match(r"(?i)^(NEFT|RTGS|IMPS|CHQ|CHEQUE|CLG|TRF)", up):
        return "person"
    return "unknown"


_RRN = re.compile(r"(?<![\dA-Z])\d{12}(?![\dA-Z])")
_UTR = re.compile(r"(?<![A-Z0-9])([A-Z]{4}[A-Z0-9]\d{6,}[A-Z0-9]*)(?![A-Z0-9])")
_CHEQUE = re.compile(r"(?i)\b(?:CHQ|CHEQUE|CLG)\b\D{0,12}(\d{6})\b")


def instrument_no(narration: str, ref: str = "") -> str:
    """UPI / IMPS RRN (12 digits), NEFT / RTGS UTR, or cheque number."""
    up = narration.upper()
    if re.match(r"^(UPI|IMPS)", up):
        m = _RRN.search(up)
        if m:
            return m.group(0)
    if re.match(r"^(NEFT|RTGS)", up):
        for m in _UTR.finditer(up):
            v = m.group(1)
            if 12 <= len(v) <= 22 and not _IFSC.match(v):
                return v
    m = _CHEQUE.search(up)
    if m:
        return m.group(1)
    m = _RRN.search(up)
    if m:
        return m.group(0)
    r = ref.strip()
    return r if re.fullmatch(r"[A-Za-z0-9]{6,22}", r) else ""


def counterparty_key(t: Transaction) -> str:
    """Stable key for client rules: the counterparty, else the narration with numbers removed."""
    if t.match_key:
        return t.match_key
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
    """Contra for cash and bank-to-bank movements; otherwise by direction.

    A voucher type the accountant chose on the review screen is kept.
    """
    if "voucher_set" in t.flags and t.voucher_type in ("Payment", "Receipt", "Contra"):
        return t.voucher_type
    if t.ledger == CASH or t.group in CASH_BANK_GROUPS:
        return "Contra"
    return "Receipt" if t.direction == "credit" else "Payment"


def suggest(txns: list[Transaction], client: ClientRules | None = None, rules: list[Rule] | None = None) -> dict[str, str]:
    """Fill ledger fields on each transaction. Returns ledger -> group for every ledger used."""
    rules = rules if rules is not None else DEFAULT_RULES
    groups: dict[str, str] = {}
    for t in txns:
        t.counterparty = counterparty(t.narration)
        t.counterparty_type = counterparty_type(t.narration, t.counterparty)
        t.instrument_no = t.instrument_no or instrument_no(t.narration, t.ref)
        t.match_key = counterparty_key(t)
    counts = Counter(t.match_key for t in txns if t.counterparty)
    for t in txns:
        t.occurrence_count = counts.get(t.match_key, 0) if t.counterparty else 0
        t.flags = [f for f in t.flags if f not in ("one_off", "small_merchant")]
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
                one_off = t.occurrence_count <= 1
                if one_off:
                    t.flags.append("one_off")
                if t.direction == "debit" and t.counterparty_type == "merchant" and one_off and t.amount <= SMALL_TICKET:
                    t.ledger, group = MISC_EXPENSES, "Indirect Expenses"
                    t.flags.append("small_merchant")
                else:
                    t.ledger = t.counterparty
                    group = "Sundry Debtors" if t.direction == "credit" else "Sundry Creditors"
                t.ledger_source, t.confidence = "party_guess", 0.5
            else:
                t.ledger, group = SUSPENSE, "Suspense A/c"
                t.ledger_source, t.confidence = "suspense", 0.0
        t.group = group
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


def apply_user_choice(
    t: Transaction, ledger: str, client: ClientRules | None, group: str, voucher: str | None = None
) -> None:
    """Accountant picked a ledger (and optionally a voucher type) on the review screen."""
    t.ledger = ledger.strip()
    t.group = SUSPENSE if t.ledger == SUSPENSE else group
    t.ledger_source, t.confidence = "user", 1.0
    t.flags = [f for f in t.flags if f not in ("one_off", "small_merchant")]
    if voucher in ("Payment", "Receipt", "Contra"):
        t.voucher_type = voucher
        if "voucher_set" not in t.flags:
            t.flags.append("voucher_set")
    t.voucher_type = voucher_type(t)
    _refresh_flags(t)
    if client is not None and t.ledger != SUSPENSE:
        client.learn(t, t.ledger, t.group)
