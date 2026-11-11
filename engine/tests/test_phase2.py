"""Phase 2 (TallyPrime QA): balance continuity, printed-vs-calculated checks,
opening balance export, voucher identifiers and the import guide."""

from datetime import date
from decimal import Decimal as D

from bahisync_engine import balance
from bahisync_engine.models import Transaction


def _t(n, day, debit="0", credit="0", bal=None, narration="row", ref=""):
    return Transaction(n, date(2026, 4, day), narration, D(debit), D(credit), D(bal) if bal is not None else None, ref=ref)


# ------------------------------------------------------------- step 1: continuity


def test_row_after_missing_balance_is_checked_against_carried_balance():
    # opening 1000; row 2 has no printed balance; row 3's printed balance is wrong by 1.
    txns = [_t(1, 1, debit="100", bal="900"), _t(2, 2, debit="50"), _t(3, 3, credit="10", bal="861")]
    out, *_ = balance.verify(txns, D("1000"))
    assert [t.balance_ok for t in out] == [True, None, False]
    assert out[1].expected_balance == D("850") and out[2].expected_balance == D("860")


def test_row_after_missing_balance_passes_when_it_ties():
    txns = [_t(1, 1, debit="100", bal="900"), _t(2, 2, debit="50"), _t(3, 3, credit="10", bal="860")]
    out, *_ = balance.verify(txns, D("1000"))
    assert [t.balance_ok for t in out] == [True, None, True]
