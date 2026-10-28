import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BAHISYNC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import importlib

    from api import main, store

    importlib.reload(store)
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def upload(client, pdf, **form):
    return client.post("/api/statements", files={"file": ("stmt.pdf", pdf, "application/pdf")}, data=form)


def test_upload_review_export_flow(client, fixtures):
    r = upload(client, fixtures["hdfc"].pdf, client_id="client-abc")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["balance_verified"] is True
    assert len(body["transactions"]) == len(fixtures["hdfc"].truths)
    sid = body["id"]

    # Correct one party ledger; similar rows in the statement follow.
    row = next(t for t in body["transactions"] if "ANAND" in t["narration"])
    r = client.patch(f"/api/statements/{sid}/rows/{row['row_no']}", json={"ledger": "Anand Enterprises", "group": "Sundry Debtors"})
    assert r.status_code == 200
    changed = r.json()["changed_rows"]
    assert row["row_no"] in changed
    for t in r.json()["transactions"]:
        if "ANAND" in t["narration"]:
            assert t["ledger"] == "Anand Enterprises" and t["ledger_source"] == "user"

    x = client.get(f"/api/statements/{sid}/export/tally", params={"company": "Demo", "bank_ledger": "HDFC Bank"})
    assert x.status_code == 200 and b"<VOUCHER" in x.content
    m = client.get(f"/api/statements/{sid}/export/tally", params={"kind": "ledgers", "company": "Demo", "bank_ledger": "HDFC Bank"})
    assert b"Anand Enterprises" in m.content and b"Sundry Debtors" in m.content
    e = client.get(f"/api/statements/{sid}/export/excel")
    assert e.status_code == 200 and e.content[:2] == b"PK"

    # The correction is remembered for the next statement of the same client.
    r2 = upload(client, fixtures["hdfc"].pdf, client_id="client-abc").json()
    again = next(t for t in r2["transactions"] if "ANAND" in t["narration"])
    assert again["ledger"] == "Anand Enterprises" and again["ledger_source"] == "client_rule"

    assert client.delete(f"/api/statements/{sid}").json() == {"deleted": True}
    assert client.get(f"/api/statements/{sid}").status_code == 404


def test_password_flow(client, fixtures):
    r = upload(client, fixtures["hdfc_password"].pdf)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "password_required"
    r = upload(client, fixtures["hdfc_password"].pdf, password="SAI1990")
    assert r.status_code == 200


def test_rejects_non_pdf(client):
    r = client.post("/api/statements", files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert r.status_code == 415


def test_expired_statements_are_purged(client, fixtures):
    from api import store

    sid = upload(client, fixtures["kotak"].pdf).json()["id"]
    assert store.purge_expired(now=time.time() + 25 * 3600) >= 1
    assert client.get(f"/api/statements/{sid}").status_code == 404


def test_path_traversal_ids_rejected(client):
    assert client.get("/api/statements/..%2f..%2fetc").status_code == 404


def test_waitlist(client):
    assert client.post("/api/waitlist", json={"email": "ca@example.com", "role": "CA firm"}).json() == {"ok": True}
    assert client.post("/api/waitlist", json={"email": "not-an-email"}).status_code == 422
