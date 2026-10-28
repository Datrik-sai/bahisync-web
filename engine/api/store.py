"""File-based storage for the MVP.

- Statements: parsed rows only (the PDF itself is never written to disk),
  deleted automatically after RETENTION_HOURS.
- Client rules: ledger choices per client, kept until the client deletes them.
- Waitlist: one JSON line per sign-up.

Swap this module for Postgres/Supabase later; the API only uses these functions.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from bahisync_engine.ledgers import ClientRules
from bahisync_engine.models import ParseResult, Transaction

DATA_DIR = Path(os.environ.get("BAHISYNC_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
RETENTION_HOURS = float(os.environ.get("BAHISYNC_RETENTION_HOURS", "24"))
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def _dir(name: str) -> Path:
    p = DATA_DIR / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


# ------------------------------------------------------------- statements

def _txn_to_json(t: Transaction) -> dict[str, Any]:
    return t.to_dict()


def _txn_from_json(d: dict[str, Any]) -> Transaction:
    def dec(v):
        return None if v is None else Decimal(v)

    return Transaction(
        row_no=d["row_no"],
        txn_date=date.fromisoformat(d["txn_date"]),
        narration=d["narration"],
        debit=Decimal(d["debit"]),
        credit=Decimal(d["credit"]),
        balance=dec(d.get("balance")),
        ref=d.get("ref", ""),
        value_date=date.fromisoformat(d["value_date"]) if d.get("value_date") else None,
        page=d.get("page", 1),
        balance_ok=d.get("balance_ok"),
        expected_balance=dec(d.get("expected_balance")),
        ledger=d.get("ledger", ""),
        ledger_source=d.get("ledger_source", ""),
        confidence=d.get("confidence", 0.0),
        counterparty=d.get("counterparty", ""),
        voucher_type=d.get("voucher_type", ""),
        flags=list(d.get("flags", [])),
    )


def save_statement(result: ParseResult, groups: dict[str, str], client_id: str, filename: str, statement_id: str | None = None) -> str:
    sid = statement_id or secrets.token_urlsafe(12)
    doc = {
        "id": sid,
        "client_id": client_id,
        "filename": filename,
        "created_at": time.time(),
        "summary": result.summary(),
        "opening_balance": None if result.opening_balance is None else str(result.opening_balance),
        "closing_balance": None if result.closing_balance is None else str(result.closing_balance),
        "groups": groups,
        "transactions": [_txn_to_json(t) for t in result.transactions],
    }
    (_dir("statements") / f"{sid}.json").write_text(json.dumps(doc))
    return sid


def load_statement(sid: str) -> tuple[dict[str, Any], ParseResult] | None:
    if not valid_id(sid):
        return None
    path = _dir("statements") / f"{sid}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    s = doc["summary"]
    result = ParseResult(
        bank=s["bank"],
        account_hint=s["account_hint"],
        transactions=[_txn_from_json(t) for t in doc["transactions"]],
        opening_balance=None if doc["opening_balance"] is None else Decimal(doc["opening_balance"]),
        closing_balance=None if doc["closing_balance"] is None else Decimal(doc["closing_balance"]),
        pages=s["pages"],
        used_ocr=s["used_ocr"],
        warnings=s["warnings"],
    )
    return doc, result


def update_statement(doc: dict[str, Any], result: ParseResult) -> None:
    doc["transactions"] = [_txn_to_json(t) for t in result.transactions]
    doc["summary"] = result.summary()
    (_dir("statements") / f"{doc['id']}.json").write_text(json.dumps(doc))


def delete_statement(sid: str) -> bool:
    if not valid_id(sid):
        return False
    path = _dir("statements") / f"{sid}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def purge_expired(now: float | None = None) -> int:
    now = now or time.time()
    cutoff = now - RETENTION_HOURS * 3600
    removed = 0
    for path in _dir("statements").glob("*.json"):
        try:
            created = json.loads(path.read_text()).get("created_at", 0)
        except (OSError, json.JSONDecodeError):
            created = 0
        if created < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


# ------------------------------------------------------------ client rules

def load_client_rules(client_id: str) -> ClientRules:
    path = _dir("clients") / f"{client_id}.json"
    if not valid_id(client_id) or not path.exists():
        return ClientRules()
    return ClientRules.from_json(json.loads(path.read_text()))


def save_client_rules(client_id: str, rules: ClientRules) -> None:
    if valid_id(client_id):
        (_dir("clients") / f"{client_id}.json").write_text(json.dumps(rules.to_json()))


# ---------------------------------------------------------------- waitlist

def add_waitlist(entry: dict[str, Any]) -> None:
    entry = {**entry, "at": time.time()}
    with (_dir("waitlist") / "waitlist.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")
