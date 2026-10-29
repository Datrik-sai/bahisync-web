"""Every fixture statement must parse with every row's date, amounts and
balance exactly right, and the running balance must verify end to end.

Narrations are compared with whitespace removed: banks (and our fixtures)
wrap long tokens across lines, so 'swig gy@yesbank' vs 'swiggy@yesbank' is
an unavoidable ambiguity, not a parsing error.
"""

import pytest

from bahisync_engine.parser import parse_statement
from bahisync_engine.pdf_io import PasswordRequired

TEXT_FIXTURES = ["sbi", "sbi_net", "sbi_net2", "hdfc", "icici", "axis", "kotak", "gramin", "hdfc_password"]


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


def test_bracketed_header_qualifiers():
    """SBI's 'Date (Value Date)' is the transaction date column, not the value date."""
    from bahisync_engine.layout import _classify

    assert _classify("Date (Value Date)") == "date"
    assert _classify("Value Date") == "value_date"
    assert _classify("Ref/Cheque No.") == "ref"
    assert _classify("Withdrawal (Dr)") == "debit"
    assert _classify("Deposit (Cr)") == "credit"
    assert _classify("Balance (INR)") == "balance"


def test_sbi_centred_rows_keep_wrapped_narration(fixtures):
    """Date and amounts centred on a 3-line narration: every line stays on its own row."""
    r = parse_statement(fixtures["sbi_net"].pdf)
    upi = [t for t in r.transactions if t.narration.startswith("UPI")]
    assert upi and all(t.narration.replace(" ", "").endswith("TRANSFERTO4897696162090") for t in upi)
    assert not any("(" in t.narration for t in r.transactions)  # bracketed value dates never leak into narration
    # Browser print header ("19/02/2025, 14:23 ...") and footer URL / page number are not rows or narration.
    assert not any("http" in t.narration or "14:23" in t.narration for t in r.transactions)
    assert r.balance_verified


def test_hsbc_one_date_per_day_amounts_on_last_line(fixtures):
    """HSBC prints the date once per day and the amounts on each transaction's last line."""
    fx = fixtures["hsbc"]
    r = parse_statement(fx.pdf)
    assert r.balance_verified and r.rows_total == len(fx.truths)
    for got, want in zip(r.transactions, fx.truths):
        assert (got.txn_date, got.debit, got.credit, got.balance) == (want.txn_date, want.debit, want.credit, want.balance)
        assert squash(got.narration).startswith(squash(want.narration))  # + HSBC's own reference line
    assert len({t.txn_date for t in fx.truths}) < len(fx.truths)  # some days really have several rows
    assert r.opening_balance == fx.opening  # dated "BALANCE BROUGHT FORWARD" row, not a transaction


def test_image_only_statement_is_read_with_ocr(fixtures):
    """HSBC e-statement exports have no text layer at all: every amount must come back exact."""
    fx = fixtures["hsbc_scanned"]
    r = parse_statement(fx.pdf)
    assert r.used_ocr and r.bank == "HSBC"
    assert r.rows_total == len(fx.truths)
    for got, want in zip(r.transactions, fx.truths):
        assert (got.txn_date, got.debit, got.credit, got.balance) == (want.txn_date, want.debit, want.credit, want.balance)
    assert r.balance_verified


def test_icici_ruled_rows_three_line_header(fixtures):
    """ICICI: header over three lines, a rule under every row, a bold title above
    the date, remarks left of their centred header, legends after the table."""
    fx = fixtures["icici_ruled"]
    r = parse_statement(fx.pdf)
    assert r.balance_verified and r.rows_total == len(fx.truths) and r.bank == "ICICI Bank"
    for got, want in zip(r.transactions, fx.truths):
        assert (got.txn_date, got.debit, got.credit, got.balance) == (want.txn_date, want.debit, want.credit, want.balance)
        title = "DATRIKSAI" if want.credit else "debittrxn"
        assert squash(got.narration) == (title + squash(want.narration)).lower()
        assert got.ref == ""  # the empty Cheque Number column takes none of the remarks
    assert not any("legends" in t.narration.lower() or "sincerly" in t.narration.lower() for t in r.transactions)
