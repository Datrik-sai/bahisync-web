"""Builds the public demo statement shown at /app/review/sample-hdfc.

A synthetic HDFC-style statement for a fictional client, Sri Lakshmi Traders,
rendered to PDF and run through the real parser and ledger engine. The JSON is
written to web/src/lib/sample-hdfc.json. No real data is involved.

    python -m tests.fixtures.make_sample
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from bahisync_engine.ledgers import ClientRules, suggest
from bahisync_engine.parser import parse_statement
from tests.fixtures.make_statements import LAYOUTS, Layout, Truth, render

OPENING = Decimal("1,84,250.00".replace(",", ""))

# (day, narration, debit, credit, ref)
ROWS = [
    (1, "NEFT CR-HDFC0000123-MEGHA FOODS PVT LTD-INV 1182", "", "64,800.00", "N091260012345"),
    (2, "RENT APRIL 2026 SHOP NO 14 BALANAGAR", "28,000.00", "", "000412"),
    (3, "UPI/DR/409312345671/RAJESH KUMAR/SBIN/9849012345@ybl/Loading", "1,500.00", "", "409312345671"),
    (4, "TSSPDCL ELECTRICITY BILL 1102938", "6,214.00", "", "210938"),
    (5, "ATM WDL/HYDERABAD AMEERPET/ATM ID S1AW0123", "20,000.00", "", "551203"),
    (6, "UPI/CR/409612345672/PRIYA SHARMA/ICIC/priya.s@okicici/Advance", "", "2,300.00", "161681"),
    (6, "GST PAYMENT CBIC CPIN 26043600123456", "18,450.00", "", "600123"),
    (8, "SMS CHARGES QTR ENDED MAR", "17.70", "", "000000"),
    (8, "UPI/P2M/409812345673/SRI SAI TEA STALL/q901234567@ybl", "240.00", "", "409812345673"),
    (9, "CASH DEPOSIT BY SELF AT BRANCH", "", "35,000.00", "000915"),
    (10, "AIRTEL POSTPAID 9849012345", "1,179.00", "", "981203"),
    (11, "NEFT CR-ICIC0000456-ANAND ENTERPRISES-PYMT AGAINST INV 1190", "", "48,600.00", "N101260054321"),
    (12, "HPCL FUEL STATION KUKATPALLY", "3,500.00", "", "771204"),
    (13, "UPI/DR/410312345674/SURESH BABU/HDFC/7702012345@axl/Transport", "4,200.00", "", "410312345674"),
    (14, "ACH D- LIC OF INDIA-POLICY 556677", "8,240.00", "", "556677"),
    (15, "TDS PAYMENT CBDT CHALLAN 281", "3,600.00", "", "281115"),
    (16, "INT.PD:01-01-2026 TO 31-03-2026", "", "1,184.00", "000000"),
    (17, "BRN-TRF 8841203", "12,000.00", "", "884120"),
    (18, "UPI/CR/410812345675/LAKSHMI DEVI/SBIN/lakshmid@oksbi/Payment", "", "6,750.00", "410812345675"),
    (19, "SALARY APRIL STAFF TRANSFER", "42,000.00", "", "190426"),
    (20, "UPI/P2M/411012345676/VIJAYA MEDICALS/paytmqr2810050501011@paytm", "860.00", "", "411012345676"),
    (21, "NEFT CR-HDFC0000123-MEGHA FOODS PVT LTD-INV 1201", "", "52,300.00", "N211260012399"),
    (22, "POS 4123XXXXXX1234 RELIANCE DIGITAL HYD", "12,999.00", "", "503262"),
    (23, "ADJ ENTRY 77120 BR", "", "4,500.00", "771200"),
    (24, "UPI/DR/411412345677/KIRAN AUTO/YESB/9000012345@ybl/Repair", "2,650.00", "", "411412345677"),
    (25, "ANNUAL FEE DEBIT CARD", "590.00", "", "000000"),
    (26, "CASH DEPOSIT BY SELF CDM", "", "22,000.00", "002611"),
    (27, "GST ON CHG", "106.20", "", "000000"),
    (28, "NEFT CR-ICIC0000456-ANAND ENTERPRISES-INV 1214", "", "31,200.00", "N281260054388"),
    (29, "MISC DR 556012 RVSL", "1,850.00", "", "556012"),
]


def truths() -> list[Truth]:
    bal = OPENING
    out = []
    for day, narr, dr, cr, ref in ROWS:
        d = Decimal(dr.replace(",", "")) if dr else Decimal("0")
        c = Decimal(cr.replace(",", "")) if cr else Decimal("0")
        bal = bal + c - d
        out.append(Truth(date(2026, 4, day), narr, d, c, bal, ref))
    return out


def build() -> dict:
    hdfc = LAYOUTS["hdfc"]
    layout = Layout(**{**hdfc.__dict__, "bank_header": [
        "HDFC BANK Ltd.", "Account Branch : BALANAGAR", "RTGS/NEFT IFSC : HDFC0000521",
        "SRI LAKSHMI TRADERS", "Account No : 50200087654321"]})
    pdf = render(layout, truths(), OPENING)
    result = parse_statement(pdf)
    # A returning client: last month's choices for the two regular customers are remembered.
    rules = ClientRules()
    suggest(result.transactions)
    for t in result.transactions:
        if "Megha Foods" in t.counterparty:
            rules.learn(t, "Megha Foods Pvt Ltd", "Sundry Debtors")
        elif "Anand Enterprises" in t.counterparty:
            rules.learn(t, "Anand Enterprises", "Sundry Debtors")
    groups = suggest(result.transactions, rules)
    return {
        "id": "sample-hdfc",
        "filename": "Sample - HDFC April 2026.pdf",
        "created_at": 0,
        "sample": True,
        "summary": result.summary(),
        "groups": groups,
        "transactions": [t.to_dict() for t in result.transactions],
        "client": "Sri Lakshmi Traders",
        "client_rules": rules.to_json(),
    }


if __name__ == "__main__":
    doc = build()
    txns = doc["transactions"]
    print("rows", len(txns), "verified", doc["summary"]["balance_verified"])
    print("suspense", sum("suspense" in t["flags"] for t in txns),
          "party_guess", sum(t["ledger_source"] == "party_guess" for t in txns),
          "rules", sum(t["ledger_source"] == "default_rule" for t in txns),
          "remembered", sum(t["ledger_source"] == "client_rule" for t in txns),
          "needs_review", sum("needs_review" in t["flags"] for t in txns))
    for t in txns:
        if t["ledger_source"] != "default_rule":
            print(t["row_no"], t["ledger_source"], t["ledger"], t["group"], t["counterparty_type"], t["occurrence_count"], t["narration"][:50])
    out = Path(__file__).resolve().parents[3] / "web" / "src" / "lib" / "sample-hdfc.json"
    out.write_text(json.dumps(doc, indent=1))
    print("wrote", out)
