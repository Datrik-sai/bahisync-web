"""BahiSync HTTP API — stateless.

Nothing is stored on the server. The PDF is parsed in memory and the
statement JSON is returned to the browser, which sends it back for ledger
changes and exports. Client ledger rules also live in the browser and are
sent with each request.

Run locally:  uvicorn service.app:app --reload --port 8000   (from engine/)
On Vercel:    index.py exposes `app`.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import secrets
import time
import zipfile
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from bahisync_engine import ai_suggest
from bahisync_engine.export_excel import build_excel
from bahisync_engine.export_tally import build_ledger_masters_xml, build_vouchers_xml
from bahisync_engine.ledgers import DEFAULT_RULES, SUSPENSE, ClientRules, apply_user_choice, counterparty_key, suggest
from bahisync_engine.parser import parse_statement
from bahisync_engine.pdf_io import PasswordRequired, ScannedUnsupported, UnreadablePDF, ocr_available
from bahisync_engine.serialize import BadStatement, statement_from_json

# Vercel Functions accept request bodies up to 4.5 MB.
MAX_UPLOAD_MB = float(os.environ.get("BAHISYNC_MAX_UPLOAD_MB", "4"))

TALLY_GROUPS = [
    "Bank Accounts", "Cash-in-Hand", "Sundry Debtors", "Sundry Creditors", "Indirect Expenses", "Direct Expenses",
    "Indirect Incomes", "Direct Incomes", "Duties & Taxes", "Loans (Liability)", "Loans & Advances (Asset)",
    "Capital Account", "Fixed Assets", "Current Liabilities", "Bank OD A/c", "Suspense A/c",
]

app = FastAPI(title="BahiSync API", version="0.3.0", docs_url=None, redoc_url=None)


def _rules(raw: Any) -> ClientRules:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return ClientRules()
    clean = {str(k)[:120]: [str(v[0])[:120], str(v[1])[:60]] for k, v in list(raw.items())[:5000] if isinstance(v, (list, tuple)) and len(v) == 2}
    return ClientRules.from_json(clean)


def _payload(result, groups: dict[str, str], filename: str, created_at: float, sid: str) -> dict[str, Any]:
    return {
        "id": sid,
        "filename": filename,
        "created_at": created_at,
        "summary": result.summary(),
        "groups": groups,
        "transactions": [t.to_dict() for t in result.transactions],
    }


def _load(doc: dict[str, Any]):
    try:
        return statement_from_json(doc)
    except BadStatement as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ai_enabled": ai_suggest.enabled(), "ocr_enabled": ocr_available(), "max_upload_mb": MAX_UPLOAD_MB}


@app.get("/api/ledgers")
def ledgers() -> dict[str, Any]:
    names: dict[str, str] = {}
    for r in DEFAULT_RULES:
        names.setdefault(r.ledger, r.group)
    names.setdefault(SUSPENSE, "Suspense A/c")
    return {"ledgers": [{"name": k, "group": v} for k, v in sorted(names.items())], "groups": TALLY_GROUPS}


@app.post("/api/parse")
async def parse(
    file: bytes = File(...),
    filename: str = Form("statement.pdf"),
    password: str | None = Form(None),
    client_rules: str = Form(""),
) -> dict[str, Any]:
    if len(file) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, detail={"code": "too_large", "message": f"File is larger than {MAX_UPLOAD_MB:.0f} MB. Split the statement by month."})
    if not file.startswith(b"%PDF"):
        raise HTTPException(415, detail={"code": "not_pdf", "message": "Please upload a PDF bank statement."})

    try:
        result = await asyncio.to_thread(parse_statement, file, password or None)
    except PasswordRequired:
        raise HTTPException(422, detail={"code": "password_required", "message": "This PDF is password-protected. Enter its password."})
    except ScannedUnsupported as exc:
        raise HTTPException(422, detail={"code": "scanned_unsupported", "message": str(exc)})
    except UnreadablePDF as exc:
        raise HTTPException(422, detail={"code": "unreadable", "message": str(exc)})

    if not result.transactions:
        raise HTTPException(422, detail={"code": "no_transactions", "message": " ".join(result.warnings) or "No transactions found."})

    client = _rules(client_rules)
    groups = suggest(result.transactions, client)
    if ai_suggest.enabled():
        try:
            known = sorted({v[0] for v in client.mapping.values()} | {r.ledger for r in DEFAULT_RULES})
            groups.update(await asyncio.to_thread(ai_suggest.suggest_with_ai, result.transactions, known))
        except Exception as exc:  # AI is optional; never fail the upload
            result.warnings.append(f"AI suggestions unavailable: {exc.__class__.__name__}")

    safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)[:120] or "statement.pdf"
    return _payload(result, groups, safe_name, time.time(), secrets.token_urlsafe(9))


class ApplyRequest(BaseModel):
    statement: dict[str, Any]
    row_no: int
    ledger: str = Field(min_length=1, max_length=120)
    group: str = "Suspense A/c"
    voucher_type: str | None = Field(None, pattern="^(Payment|Receipt|Contra)$")
    note: str | None = Field(None, max_length=300)
    apply_to_similar: bool = True
    client_rules: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/rows/apply")
def apply_row(body: ApplyRequest) -> dict[str, Any]:
    doc = body.statement
    result = _load(doc)
    target = next((t for t in result.transactions if t.row_no == body.row_no), None)
    if target is None:
        raise HTTPException(404, "Row not found.")
    group = body.group if body.group in TALLY_GROUPS else "Suspense A/c"
    client = _rules(body.client_rules)
    if body.note is not None:
        target.note = body.note.strip()
    apply_user_choice(target, body.ledger, client, group, body.voucher_type)
    changed = [target.row_no]
    if body.apply_to_similar and target.ledger != SUSPENSE:
        key = counterparty_key(target)
        for t in result.transactions:
            if t is not target and t.direction == target.direction and t.ledger_source != "user" and counterparty_key(t) == key:
                apply_user_choice(t, target.ledger, None, group)
                changed.append(t.row_no)
    # A Tally ledger has one parent group: keep every row on this ledger in step.
    for t in result.transactions:
        if t.ledger == target.ledger and t.group != target.group:
            t.group = target.group
    groups = dict(doc.get("groups") or {})
    groups[target.ledger] = target.group
    return {
        "statement": _payload(result, groups, str(doc.get("filename", "statement.pdf")), float(doc.get("created_at", time.time())), str(doc.get("id", ""))),
        "client_rules": client.to_json(),
        "changed_rows": changed,
    }


def _stem(doc: dict[str, Any]) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", str(doc.get("filename", "statement")))
    return re.sub(r"\.pdf$", "", name, flags=re.I)[:100] or "statement"


class ExportRequest(BaseModel):
    statement: dict[str, Any]
    company: str = Field("", max_length=120)
    bank_ledger: str = Field("", max_length=120)
    educational_mode: bool = False  # vouchers: TallyPrime Educational mode dates (1st / 2nd / 31st)
    existing_ledgers: list[str] = Field(default_factory=list, max_length=20000)  # masters: skip these


@app.post("/api/export/excel")
def export_excel(body: ExportRequest) -> Response:
    result = _load(body.statement)
    return Response(
        build_excel(result),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_stem(body.statement)}.xlsx"'},
    )


def _masters_xml(body: "ExportRequest", result) -> bytes:
    used = {t.ledger for t in result.transactions if t.ledger and t.review_state != "excluded"}
    groups = {str(k): str(v) for k, v in (body.statement.get("groups") or {}).items()}
    groups.update({t.ledger: t.group for t in result.transactions if t.ledger and t.group})
    groups = {k: (v if v in TALLY_GROUPS else "Suspense A/c") for k, v in groups.items()}
    existing = {str(x)[:120] for x in body.existing_ledgers}
    return build_ledger_masters_xml(body.company.strip(), body.bank_ledger.strip(), groups, used, existing)


def _require_names(body: "ExportRequest") -> None:
    if not body.company.strip() or not body.bank_ledger.strip():
        raise HTTPException(400, "Company and bank ledger names are required.")


@app.post("/api/export/tally/{kind}")
def export_tally(kind: str, body: ExportRequest) -> Response:
    if kind not in ("vouchers", "ledgers"):
        raise HTTPException(404, "Unknown export.")
    _require_names(body)
    result = _load(body.statement)
    if kind == "ledgers":
        xml = _masters_xml(body, result)
    else:
        xml = build_vouchers_xml(result.transactions, body.company.strip(), body.bank_ledger.strip(), body.educational_mode)
    return Response(
        xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{_stem(body.statement)}_tally_{kind}.xml"'},
    )


def _n(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def import_guide(body: "ExportRequest", result, stem: str) -> str:
    excluded = [t for t in result.transactions if t.review_state == "excluded"]
    suspense = [t for t in result.transactions if t.ledger == SUSPENSE and t.review_state != "excluded"]
    status = {
        "verified": "Every row ties to the running balance.",
        "partial": f"{_n(result.rows_no_balance, 'row had', 'rows had')} no balance printed, so could not be checked.",
        "mismatch": f"{_n(result.rows_failed, 'row does', 'rows do')} NOT tie to the running balance. Check against the PDF first.",
        "no_balance": "This statement has no balance column, so rows could not be checked against a running balance.",
    }[result.balance_status]
    lines = [
        "BahiSync export: how to import into TallyPrime",
        "=" * 46,
        "",
        f"Company:       {body.company.strip()}",
        f"Bank ledger:   {body.bank_ledger.strip()}",
        f"Statement:     {result.bank or 'Bank'} {result.account_hint}".rstrip(),
        f"Rows:          {result.rows_total}",
        f"Balance check: {status}",
        "",
        "1. Open the company in TallyPrime. The bank ledger name above must match Tally exactly.",
        f"2. Gateway of Tally > Import > Masters > {stem}_tally_ledgers.xml",
        "   This creates any ledgers that don't exist yet.",
        f"3. Gateway of Tally > Import > Transactions > {stem}_tally_vouchers.xml",
        "4. Open the bank ledger and compare its closing balance with the statement.",
        f"5. {stem}.xlsx has every row, its ledger and the balance check, for your working papers.",
        "",
    ]
    if body.educational_mode:
        lines += ["Educational mode: voucher dates were moved to the 1st or 2nd of the month (the 1st, 2nd and 31st stay).",
                  "The real date is at the start of each narration.", ""]
    if suspense:
        lines += [f"{_n(len(suspense), 'row goes', 'rows go')} to Suspense A/c. Reclassify in Tally once the client confirms.", ""]
    if excluded:
        lines += [f"{_n(len(excluded), 'row was', 'rows were')} LEFT OUT of the vouchers on purpose, so Tally's bank balance",
                  "will differ from the statement by their total. They are marked in the Excel file.", ""]
        for t in excluded:
            amt = f"Dr {t.debit:.2f}" if t.debit else f"Cr {t.credit:.2f}"
            lines.append(f"   #{t.row_no}  {t.txn_date.strftime('%d-%m-%Y')}  {amt}")
        lines.append("")
    lines.append("Check a few vouchers in Tally before you rely on the import.")
    return "\r\n".join(lines) + "\r\n"


@app.post("/api/export/package")
def export_package(body: ExportRequest) -> Response:
    """One ZIP: ledger masters XML, vouchers XML, Excel and a plain-text import guide."""
    _require_names(body)
    result = _load(body.statement)
    stem = _stem(body.statement)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}_tally_ledgers.xml", _masters_xml(body, result))
        z.writestr(f"{stem}_tally_vouchers.xml",
                   build_vouchers_xml(result.transactions, body.company.strip(), body.bank_ledger.strip(), body.educational_mode))
        z.writestr(f"{stem}.xlsx", build_excel(result))
        z.writestr("HOW-TO-IMPORT.txt", import_guide(body, result, stem))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}_bahisync.zip"'},
    )
