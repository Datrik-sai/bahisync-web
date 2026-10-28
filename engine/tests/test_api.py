import json

import pytest
from fastapi.testclient import TestClient

from service.app import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


def parse(client, pdf, **form):
    return client.post("/api/parse", files={"file": ("stmt.pdf", pdf, "application/pdf")}, data={"filename": "stmt.pdf", **form})


def test_parse_apply_export_flow(client, fixtures):
    r = parse(client, fixtures["hdfc"].pdf)
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["summary"]["balance_verified"] is True
    assert len(st["transactions"]) == len(fixtures["hdfc"].truths)

    row = next(t for t in st["transactions"] if "ANAND" in t["narration"])
    r = client.post("/api/rows/apply", json={"statement": st, "row_no": row["row_no"], "ledger": "Anand Enterprises", "group": "Sundry Debtors"})
    assert r.status_code == 200, r.text
    body = r.json()
    st, rules = body["statement"], body["client_rules"]
    assert len(body["changed_rows"]) >= 2
    for t in st["transactions"]:
        if "ANAND" in t["narration"]:
            assert t["ledger"] == "Anand Enterprises" and t["ledger_source"] == "user"
    assert st["groups"]["Anand Enterprises"] == "Sundry Debtors"

    v = client.post("/api/export/tally/vouchers", json={"statement": st, "company": "Demo", "bank_ledger": "HDFC Bank"})
    assert v.status_code == 200 and b"<VOUCHER" in v.content
    m = client.post("/api/export/tally/ledgers", json={"statement": st, "company": "Demo", "bank_ledger": "HDFC Bank"})
    assert b"Anand Enterprises" in m.content and b"Sundry Debtors" in m.content
    e = client.post("/api/export/excel", json={"statement": st})
    assert e.status_code == 200 and e.content[:2] == b"PK"

    # Remembered rules sent with the next upload are applied.
    r2 = parse(client, fixtures["hdfc"].pdf, client_rules=json.dumps(rules)).json()
    again = next(t for t in r2["transactions"] if "ANAND" in t["narration"])
    assert again["ledger"] == "Anand Enterprises" and again["ledger_source"] == "client_rule"


def test_password_flow(client, fixtures):
    r = parse(client, fixtures["hdfc_password"].pdf)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "password_required"
    assert parse(client, fixtures["hdfc_password"].pdf, password="SAI1990").status_code == 200


def test_scanned_without_ocr_gives_clear_error(client, fixtures, monkeypatch):
    from bahisync_engine import pdf_io

    monkeypatch.setattr(pdf_io, "ocr_available", lambda: False)
    r = parse(client, fixtures["sbi_scanned"].pdf)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "scanned_unsupported"


def test_rejects_non_pdf_and_large(client, monkeypatch):
    r = client.post("/api/parse", files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert r.status_code == 415
    from service import app as app_module

    monkeypatch.setattr(app_module, "MAX_UPLOAD_MB", 0.0001)
    r = client.post("/api/parse", files={"file": ("x.pdf", b"%PDF" + b"0" * 500, "application/pdf")})
    assert r.status_code == 413


def test_bad_statement_json_rejected(client):
    r = client.post("/api/export/excel", json={"statement": {"summary": {}, "transactions": [{"row_no": "x"}]}})
    assert r.status_code == 400


def test_tally_export_requires_names(client, fixtures):
    st = parse(client, fixtures["kotak"].pdf).json()
    r = client.post("/api/export/tally/vouchers", json={"statement": st, "company": "", "bank_ledger": "Bank"})
    assert r.status_code == 400


def test_ledgers_and_health(client):
    assert "Suspense A/c" in [x["name"] for x in client.get("/api/ledgers").json()["ledgers"]]
    assert client.get("/api/health").json()["ok"] is True
