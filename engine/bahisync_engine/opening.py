"""When a statement's opening balance may become the bank ledger's opening
balance in Tally.

Tally's ledger opening balance is the balance on the books-beginning date, not
the start of every statement. So it is exported only when:
  1. the accountant has confirmed it ("this is the bank balance at the start of the books"),
  2. the statement starts in the books' first month, on or after the books-beginning date, and
  3. the opening balance is known.
Otherwise the import guide gets a reconciliation line instead: what Tally's bank
ledger should already show before these vouchers go in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .models import ParseResult


def default_books_begin(first_txn: date) -> date:
    """1 April of the Indian financial year the statement falls in."""
    return date(first_txn.year if first_txn.month >= 4 else first_txn.year - 1, 4, 1)


def starts_at_books_begin(first_txn: date, books_begin: date) -> bool:
    return first_txn >= books_begin and (first_txn.year, first_txn.month) == (books_begin.year, books_begin.month)


@dataclass
class OpeningDecision:
    export: Decimal | None  # value to write on the bank ledger, or None
    status: str  # exported | not_confirmed | not_at_books_begin | unknown | bank_in_tally | empty
    first_txn: date | None
    books_begin: date | None


def decide(result: ParseResult, confirmed: bool, books_begin: date | None, bank_in_tally: bool) -> OpeningDecision:
    txns = result.transactions
    if not txns:
        return OpeningDecision(None, "empty", None, books_begin)
    first = txns[0].txn_date
    if result.opening_balance is None:
        return OpeningDecision(None, "unknown", first, books_begin)
    if not confirmed:
        return OpeningDecision(None, "not_confirmed", first, books_begin)
    if books_begin is None or not starts_at_books_begin(first, books_begin):
        return OpeningDecision(None, "not_at_books_begin", first, books_begin)
    if bank_in_tally:
        return OpeningDecision(None, "bank_in_tally", first, books_begin)
    return OpeningDecision(result.opening_balance, "exported", first, books_begin)


def inr(v: Decimal) -> str:
    """Indian digit grouping: 1,84,250.00"""
    whole, frac = f"{abs(v):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail]) + "." + frac


def dr_cr(balance: Decimal) -> str:
    """Bank balance as printed (positive = funds in the account) in books terms."""
    if balance == 0:
        return "Rs 0.00 (nil)"
    return f"Rs {inr(balance)} {'Dr' if balance > 0 else 'Cr'}"


def day_before(d: date) -> date:
    return d - timedelta(days=1)
