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


def build_ledger_masters_xml(company: str, bank_ledger: str, ledger_groups: dict[str, str], used: set[str]) -> bytes:
    env, data = _envelope(company, "All Masters")
    groups = dict(ledger_groups)
    groups.setdefault(bank_ledger, "Bank Accounts")
    for name in sorted(used | {bank_ledger}):
        msg = _sub(data, "TALLYMESSAGE", **UDF)
        led = _sub(msg, "LEDGER", NAME=name, ACTION="Create")
        _sub(_sub(led, "NAME.LIST"), "NAME", name)
        _sub(led, "PARENT", groups.get(name, "Suspense A/c"))
    return _serialise(env)


def _entry(voucher: ET.Element, ledger: str, debit: bool, amount: Decimal) -> None:
    e = _sub(voucher, "ALLLEDGERENTRIES.LIST")
    _sub(e, "LEDGERNAME", ledger)
    _sub(e, "ISDEEMEDPOSITIVE", "Yes" if debit else "No")
    _sub(e, "AMOUNT", f"{-amount if debit else amount:.2f}")


def build_vouchers_xml(txns: list[Transaction], company: str, bank_ledger: str) -> bytes:
    """Rows with a blank ledger or zero amount are skipped."""
    env, data = _envelope(company, "Vouchers")
    for t in txns:
        if not t.ledger or not t.amount:
            continue
        vtype = t.voucher_type or ("Receipt" if t.direction == "credit" else "Payment")
        msg = _sub(data, "TALLYMESSAGE", **UDF)
        v = _sub(msg, "VOUCHER", VCHTYPE=vtype, ACTION="Create", OBJVIEW="Accounting Voucher View")
        _sub(v, "DATE", t.txn_date.strftime("%Y%m%d"))
        _sub(v, "VOUCHERTYPENAME", vtype)
        narration = t.narration + (f" | Ref {t.ref}" if t.ref else "")
        _sub(v, "NARRATION", narration[:1000])
        if t.direction == "credit":  # money in: bank Dr, other side Cr
            _entry(v, bank_ledger, True, t.amount)
            _entry(v, t.ledger, False, t.amount)
        else:  # money out: other side Dr, bank Cr
            _entry(v, t.ledger, True, t.amount)
            _entry(v, bank_ledger, False, t.amount)
    return _serialise(env)
