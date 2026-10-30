"""Review decisions: rows left out of Tally, honest balance status and the one-file export package."""

import io
import zipfile
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from bahisync_engine.export_tally import build_vouchers_xml
from bahisync_engine.models import ParseResult, Transaction
from bahisync_engine.serialize import txn_from_json
from service.app import app


def _txn(n, debit="0", credit="0", bal=None, ledger="Rent", state=""):
    t = Transaction(n, date(2026, 4, n), f"row {n}", Decimal(debit), Decimal(credit), Decimal(bal) if bal else None)
    t.ledger, t.review_state = ledger, state
    return t


def test_excluded_rows_are_left_out_of_vouchers():
    txns = [_txn(1, debit="100"), _txn(2, debit="50", state="excluded"), _txn(3, credit="20", state="approved")]
    root = ET.fromstring(build_vouchers_xml(txns, "Co", "HDFC Bank"))
    amounts = sorted(v.find(".//AMOUNT").text.lstrip("-") for v in root.findall(".//VOUCHER"))
    assert amounts == ["100.00", "20.00"]


def test_review_state_round_trips_and_rejects_unknown_values():
    base = {"row_no": 1, "txn_date": "2026-04-01", "narration": "x", "debit": "1.00"}
    assert txn_from_json({**base, "review_state": "excluded"}).review_state == "excluded"
    assert txn_from_json({**base, "review_state": "posted"}).review_state == ""
    assert _txn(1, state="approved").to_dict()["review_state"] == "approved"


def test_new_ledger_clears_review_state():
    from bahisync_engine.ledgers import apply_user_choice

    t = _txn(1, debit="10", ledger="Suspense A/c", state="excluded")
    apply_user_choice(t, "Rent", None, "Indirect Expenses")
    assert (t.ledger, t.review_state) == ("Rent", "")


def test_balance_status_distinguishes_missing_balances_from_mismatches():
    def result(states):
        txns = []
        for i, ok in enumerate(states, 1):
            t = _txn(i, debit="1")
            t.balance_ok = ok
            txns.append(t)
        return ParseResult("HDFC", "", txns, None, None, 1, False)

    assert result([True, True]).balance_status == "verified"
    assert result([None, None]).balance_status == "no_balance"
    assert result([True, None]).balance_status == "partial"
    assert result([True, False, None]).balance_status == "mismatch"
    s = result([None, None]).summary()
    assert (s["rows_no_balance"], s["rows_failed"], s["balance_verified"]) == (2, 0, False)


def test_export_package_zip(fixtures):
    c = TestClient(app)
    st = c.post("/api/parse", files={"file": ("hdfc.pdf", fixtures["hdfc"].pdf, "application/pdf")},
                data={"filename": "hdfc.pdf"}).json()
    assert st["summary"]["balance_status"] == "verified"
    st["transactions"][0]["review_state"] = "excluded"
    body = {"statement": st, "company": "Co", "bank_ledger": "HDFC Bank"}
    assert c.post("/api/export/package", json={**body, "company": ""}).status_code == 400
    res = c.post("/api/export/package", json=body)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = sorted(z.namelist())
    assert names == ["HOW-TO-IMPORT.txt", "hdfc.xlsx", "hdfc_tally_ledgers.xml", "hdfc_tally_vouchers.xml"]
    vouchers = ET.fromstring(z.read("hdfc_tally_vouchers.xml")).findall(".//VOUCHER")
    assert len(vouchers) == len([t for t in st["transactions"] if t["ledger"]]) - 1
    guide = z.read("HOW-TO-IMPORT.txt").decode()
    assert "LEFT OUT" in guide and "#1 " in guide and "Import > Masters" in guide
    # No narration text in the guide: it lists row numbers, dates and amounts only.
    assert st["transactions"][0]["narration"][:20] not in guide


def test_rows_carry_their_position_in_the_pdf(fixtures):
    """evidence = [page, top, bottom] covers the printed row, so the review screen can highlight it."""
    import pdfplumber

    from bahisync_engine.parser import parse_statement

    for name in ("hdfc", "sbi_net", "icici_ruled"):
        fx = fixtures[name]
        r = parse_statement(fx.pdf)
        with pdfplumber.open(io.BytesIO(fx.pdf)) as pdf:
            for t in r.transactions:
                assert t.evidence, (name, t.row_no)
                pg, y0, y1 = t.evidence[0]
                assert y0 < y1
                words = pdf.pages[int(pg) - 1].extract_words()
                inside = " ".join(w["text"] for w in words if w["top"] >= y0 - 0.5 and w["bottom"] <= y1 + 0.5)
                amount = f"{t.amount:,.2f}"
                assert amount.replace(",", "") in inside.replace(",", ""), (name, t.row_no, amount)
        assert txn_from_json(r.transactions[0].to_dict()).evidence == r.transactions[0].evidence
