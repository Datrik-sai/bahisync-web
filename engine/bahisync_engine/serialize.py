"""Statement <-> JSON. The browser holds the statement between requests, so
every endpoint receives and returns this shape."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import ParseResult, Transaction


class BadStatement(ValueError):
    pass


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation as exc:
        raise BadStatement(f"Bad amount: {v!r}") from exc


def txn_from_json(d: dict[str, Any]) -> Transaction:
    try:
        return Transaction(
            row_no=int(d["row_no"]),
            txn_date=date.fromisoformat(d["txn_date"]),
            narration=str(d.get("narration", ""))[:2000],
            debit=_dec(d.get("debit")) or Decimal("0"),
            credit=_dec(d.get("credit")) or Decimal("0"),
            balance=_dec(d.get("balance")),
            ref=str(d.get("ref", ""))[:200],
            value_date=date.fromisoformat(d["value_date"]) if d.get("value_date") else None,
            page=int(d.get("page", 1)),
            balance_ok=d.get("balance_ok"),
            expected_balance=_dec(d.get("expected_balance")),
            ledger=str(d.get("ledger", ""))[:120],
            ledger_source=str(d.get("ledger_source", "")),
            confidence=float(d.get("confidence", 0.0)),
            counterparty=str(d.get("counterparty", ""))[:200],
            voucher_type=str(d.get("voucher_type", "")),
            flags=[str(f) for f in d.get("flags", [])][:20],
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise BadStatement(f"Bad transaction row: {exc}") from exc


def statement_to_json(result: ParseResult, groups: dict[str, str], filename: str, created_at: float, sid: str) -> dict[str, Any]:
    return {
        "id": sid,
        "filename": filename,
        "created_at": created_at,
        "summary": result.summary(),
        "groups": groups,
        "transactions": [t.to_dict() for t in result.transactions],
    }


def statement_from_json(doc: dict[str, Any]) -> ParseResult:
    try:
        s = doc["summary"]
        txns = [txn_from_json(t) for t in doc["transactions"]]
    except (KeyError, TypeError) as exc:
        raise BadStatement("Statement data is incomplete.") from exc
    if len(txns) > 20000:
        raise BadStatement("Too many rows.")
    return ParseResult(
        bank=str(s.get("bank", "")),
        account_hint=str(s.get("account_hint", "")),
        transactions=txns,
        opening_balance=_dec(s.get("opening_balance")),
        closing_balance=_dec(s.get("closing_balance")),
        pages=int(s.get("pages", 0)),
        used_ocr=bool(s.get("used_ocr", False)),
        warnings=[str(w) for w in s.get("warnings", [])],
    )
