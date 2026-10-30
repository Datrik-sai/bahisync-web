"""TallyPrime XML export.

Two files, imported in this order:
  1. Ledger masters  (Import > Masters)       — creates any ledger that doesn't exist yet
  2. Vouchers        (Import > Transactions)  — Payment / Receipt / Contra entries

Both can also be POSTed to Tally's HTTP port (default 9000) when TallyPrime is
set to act as a server.

Tally sign convention: a debit entry has ISDEEMEDPOSITIVE=Yes and a negative
AMOUNT; a credit entry has ISDEEMEDPOSITIVE=No and a positive AMOUNT. Every
voucher's entries sum to zero.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from .models import Transaction

UDF = {"xmlns:UDF": "TallyUDF"}


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def _envelope(company: str, report: str) -> tuple[ET.Element, ET.Element]:
    env = ET.Element("ENVELOPE")
    header = _sub(env, "HEADER")
    _sub(header, "TALLYREQUEST", "Import Data")
    imp = _sub(_sub(env, "BODY"), "IMPORTDATA")
    desc = _sub(imp, "REQUESTDESC")
    _sub(desc, "REPORTNAME", report)
    _sub(_sub(desc, "STATICVARIABLES"), "SVCURRENTCOMPANY", company)
    return env, _sub(imp, "REQUESTDATA")


def _serialise(env: ET.Element) -> bytes:
    ET.indent(env)
    return ET.tostring(env, encoding="utf-8", xml_declaration=True)


def build_ledger_masters_xml(
    company: str, bank_ledger: str, ledger_groups: dict[str, str], used: set[str], existing: set[str] | None = None
) -> bytes:
    """`existing` = ledger names already in the client's Tally (from their masters
    export); they are left out so the import never touches them."""
    env, data = _envelope(company, "All Masters")
    groups = dict(ledger_groups)
    groups.setdefault(bank_ledger, "Bank Accounts")
    skip = {e.strip().lower() for e in (existing or set())}
    for name in sorted(used | {bank_ledger}):
        if name.strip().lower() in skip:
            continue
        msg = _sub(data, "TALLYMESSAGE", **UDF)
        led = _sub(msg, "LEDGER", NAME=name, ACTION="Create")
        _sub(_sub(led, "NAME.LIST"), "NAME", name)
        _sub(led, "PARENT", groups.get(name, "Suspense A/c"))
    return _serialise(env)


def _entry(voucher: ET.Element, ledger: str, debit: bool, amount: Decimal, bank: Transaction | None = None, vdate: str = "") -> None:
    e = _sub(voucher, "ALLLEDGERENTRIES.LIST")
    _sub(e, "LEDGERNAME", ledger)
    _sub(e, "ISDEEMEDPOSITIVE", "Yes" if debit else "No")
    _sub(e, "AMOUNT", f"{-amount if debit else amount:.2f}")
    if bank is not None and bank.instrument_no:
        # Bank allocation: carries the UTR / RRN / cheque number into Tally's
        # bank reconciliation instead of leaving it only in the narration.
        b = _sub(e, "BANKALLOCATIONS.LIST")
        _sub(b, "DATE", vdate)
        _sub(b, "INSTRUMENTDATE", vdate)
        is_cheque = bool(re.match(r"(?i)^(CHQ|CHEQUE|CLG)", bank.narration.strip()))
        _sub(b, "TRANSACTIONTYPE", "Cheque" if is_cheque else "Others")
        _sub(b, "INSTRUMENTNUMBER", bank.instrument_no)
        _sub(b, "AMOUNT", f"{-amount if debit else amount:.2f}")


EDUCATIONAL_DAYS = (1, 2, 31)


def educational_date(d: date) -> date:
    """TallyPrime Educational mode accepts vouchers only on the 1st, 2nd and 31st.

    Other dates move to the 1st (days 3-15) or the 2nd (days 16-30) of the same
    month, which keeps the month and the rough order within it.
    """
    if d.day in EDUCATIONAL_DAYS and d.day <= calendar.monthrange(d.year, d.month)[1]:
        return d
    return d.replace(day=1 if d.day <= 15 else 2)


def build_vouchers_xml(txns: list[Transaction], company: str, bank_ledger: str, educational_mode: bool = False) -> bytes:
    """Rows with a blank ledger, zero amount or review_state "excluded" are skipped.

    educational_mode remaps dates for TallyPrime Educational mode and keeps the
    real date at the start of the narration.
    """
    env, data = _envelope(company, "Vouchers")
    for t in txns:
        if not t.ledger or not t.amount or t.review_state == "excluded":
            continue
        vtype = t.voucher_type or ("Receipt" if t.direction == "credit" else "Payment")
        vdate_d = educational_date(t.txn_date) if educational_mode else t.txn_date
        vdate = vdate_d.strftime("%Y%m%d")
        msg = _sub(data, "TALLYMESSAGE", **UDF)
        v = _sub(msg, "VOUCHER", VCHTYPE=vtype, ACTION="Create", OBJVIEW="Accounting Voucher View")
        _sub(v, "DATE", vdate)
        _sub(v, "VOUCHERTYPENAME", vtype)
        parts = []
        if educational_mode and vdate_d != t.txn_date:
            parts.append(f"[Actual Date: {t.txn_date.strftime('%d/%m/%Y')}]")
        parts.append(t.narration)
        if t.note:
            parts.append(f"| Note: {t.note}")
        ref = t.instrument_no or t.ref
        if ref:
            parts.append(f"| Ref {ref}")
        _sub(v, "NARRATION", " ".join(parts)[:1000])
        if t.direction == "credit":  # money in: bank Dr, other side Cr
            _entry(v, bank_ledger, True, t.amount, t, vdate)
            _entry(v, t.ledger, False, t.amount)
        else:  # money out: other side Dr, bank Cr
            _entry(v, t.ledger, True, t.amount)
            _entry(v, bank_ledger, False, t.amount, t, vdate)
    return _serialise(env)
