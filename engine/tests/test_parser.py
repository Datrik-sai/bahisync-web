"""Every fixture statement must parse with every row's date, amounts and
balance exactly right, and the running balance must verify end to end.

Narrations are compared with whitespace removed: banks (and our fixtures)
wrap long tokens across lines, so 'swig gy@yesbank' vs 'swiggy@yesbank' is
an unavoidable ambiguity, not a parsing error.
"""

import pytest

from bahisync_engine.parser import parse_statement
from bahisync_engine.pdf_io import PasswordRequired

TEXT_FIXTURES = ["sbi", "hdfc", "icici", "axis", "kotak", "gramin", "hdfc_password"]


def squash(s: str) -> str:
    return "".join(s.split()).lower()


@pytest.mark.parametrize("name", TEXT_FIXTURES)
def test_rows_exact(fixtures, name):
    fx = fixtures[name]
    r = parse_statement(fx.pdf, fx.password)
    assert r.rows_total == len(fx.truths)
    for got, want in zip(r.transactions, fx.truths):
        assert got.txn_date == want.txn_date
        assert got.debit == want.debit, got.narration
        assert got.credit == want.credit, got.narration
        assert got.balance == want.balance
        assert squash(got.narration) == squash(want.narration)
    assert r.balance_verified
    assert r.opening_balance == fx.opening
    assert r.closing_balance == fx.truths[-1].balance
    assert r.bank == fx.expected_bank


def test_newest_first_is_reordered(fixtures):
    r = parse_statement(fixtures["axis"].pdf)
    dates = [t.txn_date for t in r.transactions]
    assert dates == sorted(dates)
    assert any("newest-first" in w for w in r.warnings)


def test_password_required(fixtures):
    with pytest.raises(PasswordRequired):
        parse_statement(fixtures["hdfc_password"].pdf)
    with pytest.raises(PasswordRequired):
        parse_statement(fixtures["hdfc_password"].pdf, "wrong")


def test_scanned_statement_ocr(fixtures):
    fx = fixtures["sbi_scanned"]
    r = parse_statement(fx.pdf)
    assert r.used_ocr
    assert r.rows_total == len(fx.truths)
    # OCR can misread, but the balance check must catch any amount error.
    for got, want in zip(r.transactions, fx.truths):
        if got.balance_ok:
            assert got.debit == want.debit and got.credit == want.credit


def test_tampered_amount_is_flagged(fixtures):
    """If a row's amount is wrong, the balance check must flag that row."""
    from decimal import Decimal

    from bahisync_engine import balance

    r = parse_statement(fixtures["hdfc"].pdf)
    txns = r.transactions
    target = next(t for t in txns if t.debit)
    target.debit += Decimal("100")
    checked, *_ = balance.verify(txns, r.opening_balance)
    bad = [t for t in checked if t.balance_ok is False]
    assert target in bad
