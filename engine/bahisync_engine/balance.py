"""Running-balance verification — the accuracy guarantee.

For every row: previous balance + credit - debit must equal the printed
balance. A row that ties proves its amounts and direction were read
correctly; a row that doesn't is flagged for human review.
"""

from __future__ import annotations

from decimal import Decimal

from .models import Transaction

TOLERANCE = Decimal("0.01")


def _check(txns: list[Transaction], opening: Decimal | None) -> int:
    """Run the check in the given order; returns the number of failures."""
    prev = opening
    failures = 0
    for t in txns:
        if t.balance is None:
            t.balance_ok = None
            t.expected_balance = None
            failures += 1
            prev = None
            continue
        if prev is None:
            # First row with no opening balance: derive opening from this row.
            prev = t.balance - t.credit + t.debit
        expected = prev + t.credit - t.debit
        t.expected_balance = expected
        t.balance_ok = abs(expected - t.balance) <= TOLERANCE
        if not t.balance_ok:
            failures += 1
        prev = t.balance
    return failures


def _fix_inferred_directions(txns: list[Transaction], opening: Decimal | None) -> None:
    """Single 'Amount' column with no Dr/Cr marker: use the balance movement."""
    prev = opening
    for t in txns:
        if "direction_inferred" in t.flags and t.balance is not None and prev is not None:
            amount = t.credit or t.debit
            if abs(prev - amount - t.balance) <= TOLERANCE:
                t.debit, t.credit = amount, Decimal("0")
            elif abs(prev + amount - t.balance) <= TOLERANCE:
                t.debit, t.credit = Decimal("0"), amount
        prev = t.balance if t.balance is not None else prev


def verify(txns: list[Transaction], opening: Decimal | None) -> tuple[list[Transaction], Decimal | None, Decimal | None, list[str]]:
    """Verify balances, detecting newest-first statements.

    Returns (transactions in chronological order, opening, closing, warnings).
    """
    warnings: list[str] = []
    if not txns:
        return txns, opening, None, warnings

    _fix_inferred_directions(txns, opening)
    forward = _check(txns, opening)

    if forward > 0 and len(txns) > 1:
        reversed_txns = list(reversed(txns))
        _fix_inferred_directions(reversed_txns, None)
        backward = _check(reversed_txns, None)
        if backward < forward:
            txns = reversed_txns
            for i, t in enumerate(txns, start=1):
                t.row_no = i
            warnings.append("Statement was printed newest-first; rows were reordered by date.")
            if opening is not None:
                # A printed opening balance belongs to the oldest row, re-check with it.
                _check(txns, opening)
        else:
            _check(txns, opening)

    first = txns[0]
    derived_opening = opening
    if derived_opening is None and first.balance is not None:
        derived_opening = first.balance - first.credit + first.debit
    closing = txns[-1].balance

    for t in txns:
        if t.balance_ok is False and "balance_mismatch" not in t.flags:
            t.flags.append("balance_mismatch")

    failed = sum(1 for t in txns if t.balance_ok is False)
    if failed:
        warnings.append(f"{failed} row(s) do not tie to the running balance and need review.")
    return txns, derived_opening, closing, warnings
