"""BahiSync HTTP API.

Run locally:  uvicorn api.main:app --reload --port 8000   (from engine/)
"""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from bahisync_engine import ai_suggest
from bahisync_engine.export_excel import build_excel
from bahisync_engine.export_tally import build_ledger_masters_xml, build_vouchers_xml
from bahisync_engine.ledgers import DEFAULT_RULES, SUSPENSE, apply_user_choice, counterparty_key, suggest
from bahisync_engine.parser import parse_statement
from bahisync_engine.pdf_io import PasswordRequired, UnreadablePDF

from . import store

MAX_UPLOAD_MB = float(os.environ.get("BAHISYNC_MAX_UPLOAD_MB", "15"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("BAHISYNC_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

TALLY_GROUPS = [
    "Bank Accounts", "Cash-in-Hand", "Sundry Debtors", "Sundry Creditors", "Indirect Expenses", "Direct Expenses",
    "Indirect Incomes", "Direct Incomes", "Duties & Taxes", "Loans (Liability)", "Loans & Advances (Asset)",
    "Capital Account", "Fixed Assets", "Current Liabilities", "Suspense A/c",
]


async def _purge_loop() -> None:
    while True:
        store.purge_expired()
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_purge_loop())
    yield
    task.cancel()


app = FastAPI(title="BahiSync API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


def _payload(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"],
        "client_id": doc["client_id"],
        "filename": doc["filename"],
        "created_at": doc["created_at"],
        "expires_in_hours": store.RETENTION_HOURS,
        "summary": doc["summary"],
        "groups": doc["groups"],
        "transactions": doc["transactions"],
    }


def _get(sid: str):
    loaded = store.load_statement(sid)
    if not loaded:
        raise HTTPException(404, "Statement not found or already deleted.")
    return loaded


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ai_enabled": ai_suggest.enabled()}


@app.post("/api/statements")
async def upload_statement(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    client_id: str = Form("default-client"),
) -> dict[str, Any]:
    if not store.valid_id(client_id):
        raise HTTPException(400, "Invalid client id.")
    data = await file.read(int(MAX_UPLOAD_MB * 1024 * 1024) + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB:.0f} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Please upload a PDF bank statement.")

    try:
        result = await asyncio.to_thread(parse_statement, data, password or None)
    except PasswordRequired:
        raise HTTPException(422, detail={"code": "password_required", "message": "This PDF is password-protected. Enter its password."})
    except UnreadablePDF as exc:
        raise HTTPException(422, detail={"code": "unreadable", "message": str(exc)})

    if not result.transactions:
        raise HTTPException(422, detail={"code": "no_transactions", "message": " ".join(result.warnings) or "No transactions found."})

    client = store.load_client_rules(client_id)
    groups = suggest(result.transactions, client)
    if ai_suggest.enabled():
        try:
            known = sorted({v[0] for v in client.mapping.values()} | {r.ledger for r in DEFAULT_RULES})
            groups.update(await asyncio.to_thread(ai_suggest.suggest_with_ai, result.transactions, known))
        except Exception as exc:  # AI is a nice-to-have; never fail the upload
            result.warnings.append(f"AI suggestions unavailable: {exc.__class__.__name__}")

    safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", file.filename or "statement.pdf")[:120]
    sid = store.save_statement(result, groups, client_id, safe_name)
    doc, _ = _get(sid)
    return _payload(doc)


@app.get("/api/statements/{sid}")
def get_statement(sid: str) -> dict[str, Any]:
    doc, _ = _get(sid)
    return _payload(doc)


class RowUpdate(BaseModel):
    ledger: str = Field(min_length=1, max_length=120)
    group: str = "Suspense A/c"
    apply_to_similar: bool = True


@app.patch("/api/statements/{sid}/rows/{row_no}")
def update_row(sid: str, row_no: int, body: RowUpdate) -> dict[str, Any]:
    doc, result = _get(sid)
    target = next((t for t in result.transactions if t.row_no == row_no), None)
    if target is None:
        raise HTTPException(404, "Row not found.")
    group = body.group if body.group in TALLY_GROUPS else "Suspense A/c"
    client = store.load_client_rules(doc["client_id"])
    apply_user_choice(target, body.ledger, client, group)
    changed = [row_no]
    if body.apply_to_similar and body.ledger.strip() != SUSPENSE:
        key = counterparty_key(target)
        for t in result.transactions:
            if t is not target and t.direction == target.direction and t.ledger_source != "user" and counterparty_key(t) == key:
                apply_user_choice(t, body.ledger, None, group)
                changed.append(t.row_no)
    doc["groups"][target.ledger] = group
    store.save_client_rules(doc["client_id"], client)
    store.update_statement(doc, result)
    return {"changed_rows": changed, **_payload(doc)}


def _filename(doc: dict[str, Any], suffix: str) -> str:
    stem = re.sub(r"\.pdf$", "", doc["filename"], flags=re.I)
    return f"{stem}{suffix}"


@app.get("/api/statements/{sid}/export/excel")
def export_excel(sid: str) -> Response:
    doc, result = _get(sid)
    return Response(
        build_excel(result),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_filename(doc, ".xlsx")}"'},
    )


@app.get("/api/statements/{sid}/export/tally")
def export_tally(
    sid: str,
    kind: str = Query("vouchers", pattern="^(vouchers|ledgers)$"),
    company: str = Query(..., min_length=1, max_length=120),
    bank_ledger: str = Query(..., min_length=1, max_length=120),
) -> Response:
    doc, result = _get(sid)
    if kind == "ledgers":
        used = {t.ledger for t in result.transactions if t.ledger}
        xml = build_ledger_masters_xml(company, bank_ledger, doc["groups"], used)
        name = _filename(doc, "_tally_ledgers.xml")
    else:
        xml = build_vouchers_xml(result.transactions, company, bank_ledger)
        name = _filename(doc, "_tally_vouchers.xml")
    return Response(xml, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.delete("/api/statements/{sid}")
def delete_statement(sid: str) -> dict[str, bool]:
    return {"deleted": store.delete_statement(sid)}


@app.get("/api/ledgers")
def ledgers(client_id: str = "default-client") -> dict[str, Any]:
    client = store.load_client_rules(client_id)
    names = {v[0]: v[1] for v in client.mapping.values()}
    for r in DEFAULT_RULES:
        names.setdefault(r.ledger, r.group)
    names.setdefault(SUSPENSE, "Suspense A/c")
    return {"ledgers": [{"name": k, "group": v} for k, v in sorted(names.items())], "groups": TALLY_GROUPS}


class WaitlistEntry(BaseModel):
    email: EmailStr
    role: str = Field("", max_length=60)
    statements_per_month: str = Field("", max_length=30)


@app.post("/api/waitlist")
def waitlist(entry: WaitlistEntry) -> dict[str, bool]:
    store.add_waitlist(entry.model_dump())
    return {"ok": True}
