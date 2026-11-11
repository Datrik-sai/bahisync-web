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


# ------------------------------------------------- step 2: printed vs calculated

from decimal import Decimal

from bahisync_engine.models import ParseResult, Word
from bahisync_engine.parser import parse_statement
from bahisync_engine.pdf_io import PageWords
from bahisync_engine.summary import PrintedSummary, read_printed_summary, reconcile
from tests.fixtures.make_statements import LAYOUTS, render


def _line(y, *cells):
    """cells = (text, x0); each word ~6pt per character."""
    words = []
    for text, x in cells:
        for part in text.split(" "):
            words.append(Word(part, x, x + 6 * len(part), y, y + 8, 1))
            x += 6 * len(part) + 3
    return words


def test_same_line_labels_are_read_with_dr_cr_and_minus():
    words = (_line(10, ("Opening Balance : 1,84,250.00", 30))
             + _line(400, ("Total Debits 1,68,195.90", 30))
             + _line(415, ("Total Credits : 2,68,634.00", 30))
             + _line(430, ("Closing Balance 2,84,688.10 Dr", 30)))
    s = read_printed_summary([PageWords(1, 600, words)])
    assert (s.opening, s.total_debit, s.total_credit, s.closing) == (
        Decimal("184250.00"), Decimal("168195.90"), Decimal("268634.00"), Decimal("-284688.10"))
    neg = read_printed_summary([PageWords(1, 600, _line(10, ("CLOSING BALANCE", 30), ("-20,334.69", 300)))])
    assert neg.closing == Decimal("-20334.69")


def test_two_line_summary_block_maps_values_by_column():
    words = (_line(500, ("Opening Balance", 30), ("Dr Count", 140), ("Cr Count", 210), ("Debits", 290), ("Credits", 370), ("Closing Bal", 450))
             + _line(512, ("1,84,250.00", 30), ("19", 150), ("11", 220), ("1,68,195.90", 280), ("2,68,634.00", 360), ("2,84,688.10", 450)))
    s = read_printed_summary([PageWords(1, 600, words)])
    assert (s.opening, s.total_debit, s.total_credit, s.closing) == (
        Decimal("184250.00"), Decimal("168195.90"), Decimal("268634.00"), Decimal("284688.10"))


def test_transaction_rows_mentioning_closing_balance_are_ignored():
    words = _line(100, ("01/04/26", 30), ("CLOSING BALANCE TRF", 90), ("5,000.00", 400))
    assert read_printed_summary([PageWords(1, 600, words)]).closing is None


def test_sample_reads_printed_opening_and_closing(fixtures):
    r = parse_statement(fixtures["hdfc"].pdf)
    checks = {c["check"]: c for c in r.reconciliation}
    assert r.opening_source == "printed"
    assert checks["opening"]["status"] == "ok" and checks["closing"]["status"] == "ok"
    assert checks["total_debit"]["status"] == "not_printed"
    assert r.balance_status == "verified"


def test_printed_opening_that_disagrees_with_row_1_is_flagged(fixtures):
    fx = fixtures["hdfc"]
    wrong = fx.truths[0].balance - fx.truths[0].credit + fx.truths[0].debit + Decimal("100")
    r = parse_statement(render(LAYOUTS["hdfc"], fx.truths, wrong))
    checks = {c["check"]: c for c in r.reconciliation}
    assert checks["opening"]["status"] == "mismatch"
    assert r.transactions[0].balance_ok is False and "balance_mismatch" in r.transactions[0].flags
    assert r.balance_status == "mismatch" and not r.balance_verified
    assert any("Opening balance" in w for w in r.warnings)


def test_opening_not_printed_is_reported_as_derived(fixtures):
    r = parse_statement(fixtures["axis"].pdf)
    checks = {c["check"]: c for c in r.reconciliation}
    assert r.opening_source == "derived"
    assert checks["opening"]["status"] == "not_printed" and "row 1" in checks["opening"]["note"]


def test_totals_mismatch_makes_status_mismatch():
    txns = [_t(1, 1, debit="100", bal="900"), _t(2, 2, credit="50", bal="950")]
    out, opening, closing, _ = balance.verify(txns, D("1000"))
    r = ParseResult("X", "", out, opening, closing, 1, False)
    r.reconciliation = reconcile(r, PrintedSummary(D("1000"), D("950"), D("100"), D("60")), D("1000"))
    st = {c["check"]: c["status"] for c in r.reconciliation}
    assert st == {"opening": "ok", "closing": "ok", "total_debit": "ok", "total_credit": "mismatch",
                  "continuity": "ok", "missing_balance": "ok"}
    assert r.balance_status == "mismatch" and r.reconciliation_mismatches == ["total_credit"]


def test_missing_balance_rows_are_listed():
    txns = [_t(1, 1, debit="100", bal="900"), _t(2, 2, debit="50"), _t(3, 3, credit="10", bal="860")]
    out, opening, closing, _ = balance.verify(txns, D("1000"))
    r = ParseResult("X", "", out, opening, closing, 1, False)
    checks = {c["check"]: c for c in reconcile(r, PrintedSummary(), D("1000"))}
    assert checks["missing_balance"]["status"] == "warning" and "Rows 2 " in checks["missing_balance"]["note"]


def test_reconciliation_round_trips_through_json(fixtures):
    from bahisync_engine.serialize import statement_from_json, statement_to_json

    r = parse_statement(fixtures["hdfc"].pdf)
    back = statement_from_json(statement_to_json(r, {}, "x.pdf", 0, "id"))
    assert back.reconciliation == r.reconciliation and back.opening_source == "printed"
