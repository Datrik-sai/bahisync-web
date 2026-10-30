"""Core data structures shared by the parser, ledger engine and exporters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass
class Word:
    """A word on a page with its position, from the PDF text layer or OCR."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Transaction:
    row_no: int
    txn_date: date
    narration: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    balance: Decimal | None = None
    ref: str = ""
    value_date: date | None = None
    page: int = 1
    # Filled by the balance check
    balance_ok: bool | None = None
    expected_balance: Decimal | None = None
    # Filled by the ledger engine
    ledger: str = ""
    ledger_source: str = ""  # "client_rule" | "default_rule" | "ai" | "user" | "suspense"
    confidence: float = 0.0
    counterparty: str = ""
    counterparty_type: str = ""  # "merchant" | "person" | "unknown"
    occurrence_count: int = 0  # rows in this statement with the same counterparty key
    match_key: str = ""  # stable key used for client rules and "apply to similar"
    group: str = ""  # TallyPrime parent group of `ledger`
    instrument_no: str = ""  # UPI RRN / NEFT-IMPS UTR / cheque number
    voucher_type: str = ""  # Payment | Receipt | Contra
    note: str = ""  # accountant's or client's note, added to the Tally narration
    # Accountant's decision on a row: "" (none), "approved" (keep as is, e.g. Suspense on purpose)
    # or "excluded" (leave out of the Tally vouchers; the bank balance will no longer tie in Tally).
    review_state: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def amount(self) -> Decimal:
        return self.credit if self.credit else self.debit

    @property
    def direction(self) -> str:
        return "credit" if self.credit > 0 else "debit"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = f"{v:.2f}"
            elif isinstance(v, date):
                d[k] = v.isoformat()
        return d


@dataclass
class ParseResult:
    bank: str
    account_hint: str
    transactions: list[Transaction]
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    pages: int
    used_ocr: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_total(self) -> int:
        return len(self.transactions)

    @property
    def rows_failed(self) -> int:
        return sum(1 for t in self.transactions if t.balance_ok is False)

    @property
    def rows_no_balance(self) -> int:
        return sum(1 for t in self.transactions if t.balance_ok is None)

    @property
    def balance_status(self) -> str:
        """verified | mismatch | partial (some rows had no balance to check) | no_balance."""
        if not self.transactions or self.rows_no_balance == self.rows_total:
            return "no_balance"
        if self.rows_failed:
            return "mismatch"
        return "partial" if self.rows_no_balance else "verified"

    @property
    def balance_verified(self) -> bool:
        """True only when every row has a balance and every running balance ties."""
        return bool(self.transactions) and all(t.balance_ok for t in self.transactions)

    @property
    def total_debit(self) -> Decimal:
        return sum((t.debit for t in self.transactions), Decimal("0"))

    @property
    def total_credit(self) -> Decimal:
        return sum((t.credit for t in self.transactions), Decimal("0"))

    def summary(self) -> dict[str, Any]:
        def fmt(v: Decimal | None) -> str | None:
            return None if v is None else f"{v:.2f}"

        return {
            "bank": self.bank,
            "account_hint": self.account_hint,
            "pages": self.pages,
            "used_ocr": self.used_ocr,
            "rows_total": self.rows_total,
            "rows_failed": self.rows_failed,
            "rows_no_balance": self.rows_no_balance,
            "balance_status": self.balance_status,
            "balance_verified": self.balance_verified,
            "opening_balance": fmt(self.opening_balance),
            "closing_balance": fmt(self.closing_balance),
            "total_debit": fmt(self.total_debit),
            "total_credit": fmt(self.total_credit),
            "warnings": self.warnings,
        }
