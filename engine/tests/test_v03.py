"""v0.3: long-statement noise, single Amount + Dr/Cr columns, UPI P2M / P2A,
instrument numbers, one-off counterparties and TallyPrime Educational mode."""

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from bahisync_engine import balance
from bahisync_engine.export_tally import build_ledger_masters_xml, build_vouchers_xml, educational_date
from bahisync_engine.layout import extract_rows
from bahisync_engine.ledgers import MISC_EXPENSES, SUSPENSE, ClientRules, apply_user_choice, counterparty_type, instrument_no, suggest
from bahisync_engine.models import Transaction, Word
from bahisync_engine.parser import parse_statement
from bahisync_engine.pdf_io import PageWords
from service.app import app


def T(n, narration, debit="0", credit="0", bal=None, d=date(2026, 4, 13), ref=""):
    return Transaction(n, d, narration, Decimal(debit), Decimal(credit), Decimal(bal) if bal else None, ref=ref)


# ------------------------------------------------------------- layout noise

def test_gramin_statement_skips_page_noise_and_infers_opening(fixtures):
    fx = fixtures["gramin"]
    r = parse_statement(fx.pdf)
    assert r.rows_total == len(fx.truths) == 30
    assert r.balance_verified
    # No opening line is printed: it is derived from row 1, not taken from page 2's "Brought Forward".
    assert r.opening_balance == fx.opening
    assert r.bank == "Telangana Grameena Bank"
    for t in r.transactions:
        assert "forward" not in t.narration.lower() and "total" not in t.narration.lower()


def _words(rows, page=1, top=100.0):
    """rows: list of [(text, x0)] lines -> PageWords."""
    out = []
    y = top
    for line in rows:
        for text, x in line:
            out.append(Word(text, x, x + 5.2 * len(text), y, y + 7.5, page))
        y += 14
    return PageWords(page=page, width=600, words=out)


HEADER = [("Date", 30), ("Particulars", 90), ("Debit", 400), ("Credit", 470), ("Balance", 560)]


def test_dated_bf_cf_and_page_total_rows_are_dropped():
    p1 = _words([
        HEADER,
        [("01/04/2026", 30), ("Opening", 90), ("Balance", 130), ("10,000.00", 520)],
        [("02/04/2026", 30), ("RENT", 90), ("APRIL", 120), ("4,000.00", 370), ("6,000.00", 520)],
        [("Page", 90), ("Total", 115), ("4,000.00", 370), ("0.00", 450)],
        [("02/04/2026", 30), ("Carried", 90), ("Forward", 125), ("6,000.00", 520)],
    ])
    p2 = _words([
        HEADER,
        [("03/04/2026", 30), ("B/F", 90), ("6,000.00", 520)],
        [("Date", 30), ("Particulars", 90), ("Debit", 400), ("Credit", 470), ("Balance", 560)],
        [("04/04/2026", 30), ("INTEREST", 90), ("CREDIT", 140), ("250.00", 450), ("6,250.00", 520)],
    ], page=2)
    txns, opening, _ = extract_rows([p1, p2])
    assert [t.narration for t in txns] == ["RENT APRIL", "INTEREST CREDIT"]
    assert opening == Decimal("10000.00")
    txns, opening, closing, warnings = balance.verify(txns, opening)
    assert all(t.balance_ok for t in txns) and closing == Decimal("6250.00") and not warnings


def test_single_amount_column_with_type_column_and_suffix():
    p = _words([
        [("Date", 30), ("Particulars", 90), ("Amount", 400), ("Type", 450), ("Balance", 560)],
        [("01/04/2026", 30), ("CASH", 90), ("DEPOSIT", 120), ("5,000.00", 370), ("CR", 450), ("15,000.00", 520)],
        [("02/04/2026", 30), ("ATM", 90), ("WDL", 112), ("2,000.00", 370), ("DR", 450), ("13,000.00", 520)],
        [("03/04/2026", 30), ("SMS", 90), ("CHARGES", 112), ("17.70Dr", 370), ("12,982.30", 520)],
    ])
    txns, opening, _ = extract_rows([p])
    assert [(t.debit, t.credit) for t in txns] == [
        (Decimal("0"), Decimal("5000.00")), (Decimal("2000.00"), Decimal("0")), (Decimal("17.70"), Decimal("0"))]
    txns, opening, _, _ = balance.verify(txns, opening)
    assert opening == Decimal("10000.00")  # inferred from row 1
    assert all(t.balance_ok for t in txns)


# ------------------------------------------------------------- UPI and references

def test_p2m_vs_p2a_and_instrument_numbers():
    assert counterparty_type("UPI/P2M/503262123456/RAJU TEA STALL/q123456789@ybl", "Raju Tea Stall") == "merchant"
    assert counterparty_type("UPI/P2A/412345678901/RAMESH K/SBIN/9876543210@ybl", "Ramesh K") == "person"
    assert counterparty_type("UPI/DR/412345678901/RAMESH KUMAR/SBIN/ramesh@oksbi/Payment", "Ramesh Kumar") == "person"
    assert counterparty_type("UPI/DR/412398765432/SWIGGY/YESB/swiggy@yesbank/Food", "Swiggy") == "merchant"
    assert counterparty_type("NEFT DR-ICIC0001234-SRI LAKSHMI TRADERS-NETBANK", "Sri Lakshmi Traders") == "merchant"
    assert instrument_no("UPI/CR/412311112222/PRIYA SHARMA/ICIC/priya@okicici/Refund") == "412311112222"
    assert instrument_no("UPI-PRIYA SHARMA-priya@okicici-ICIC0000123-412311112222-REFUND") == "412311112222"
    assert instrument_no("NEFT CR-HDFCN52026102812345-ACME SOLUTIONS PVT LTD-SALARY") == "HDFCN52026102812345"
    assert instrument_no("CHQ PAID 000123 VENKATESWARA HARDWARE") == "000123"
    assert instrument_no("GST PAYMENT CBIC CPIN 26043600123456") == ""  # 14 digits is a CPIN, not an RRN


def test_one_off_people_small_merchants_and_groups():
    txns = [
        T(1, "UPI/DR/412345678901/RAMESH KUMAR/SBIN/ramesh@oksbi/Payment", debit="1250.00"),
        T(2, "UPI/P2M/503262123456/RAJU TEA STALL/q123456789@ybl", debit="180.00"),
        T(3, "UPI/P2M/503262123457/CROMA ELECTRONICS/croma.rzp@icici", debit="45999.00"),
        T(4, "IMPS/P2A/700123/CUSTOMER PAYMENT/KKBK0000958/ANAND ENTERPRISES", credit="36400.00"),
        T(5, "IMPS/P2A/700124/CUSTOMER PAYMENT/KKBK0000958/ANAND ENTERPRISES", credit="12000.00"),
        T(6, "MISC TXN 88812", debit="99.00"),
    ]
    suggest(txns)
    r, tea, croma, anand1, anand2, unknown = txns
    assert (r.ledger, r.group, r.counterparty_type, r.occurrence_count) == ("Ramesh Kumar", "Sundry Creditors", "person", 1)
    assert "one_off" in r.flags and r.instrument_no == "412345678901"
    assert (tea.ledger, tea.group) == (MISC_EXPENSES, "Indirect Expenses") and "small_merchant" in tea.flags
    assert (croma.ledger, croma.group) == ("Croma Electronics", "Sundry Creditors")  # big ticket keeps its own ledger
    assert (anand1.group, anand1.occurrence_count) == ("Sundry Debtors", 2) and "one_off" not in anand1.flags
    assert anand1.match_key == anand2.match_key
    assert (unknown.ledger, unknown.group) == (SUSPENSE, "Suspense A/c")


def test_user_voucher_type_is_kept():
    t = T(1, "NEFT DR-HDFC0000521-OWN ACCOUNT TRANSFER", debit="50000.00")
    suggest([t])
    apply_user_choice(t, "HDFC Current A/c", ClientRules(), "Bank Accounts")
    assert t.voucher_type == "Contra"  # bank-to-bank
    apply_user_choice(t, "HDFC Current A/c", None, "Bank Accounts", "Payment")
    assert t.voucher_type == "Payment" and "voucher_set" in t.flags
    apply_user_choice(t, "Rent", None, "Indirect Expenses")
    assert t.voucher_type == "Payment"


# ------------------------------------------------------------- Tally export

def test_educational_mode_dates_and_narration():
    assert educational_date(date(2026, 4, 13)) == date(2026, 4, 1)
    assert educational_date(date(2026, 4, 22)) == date(2026, 4, 2)
    assert educational_date(date(2026, 5, 31)) == date(2026, 5, 31)
    assert educational_date(date(2026, 4, 30)) == date(2026, 4, 2)
    assert educational_date(date(2026, 4, 2)) == date(2026, 4, 2)

    txns = [T(1, "UPI/CR/412311112222/PRIYA SHARMA/ICIC/priya@okicici/Refund", credit="2300.00", d=date(2026, 4, 13)),
            T(2, "POS 4123XXXXXX1234 RELIANCE DIGITAL HYD", debit="12999.00", d=date(2026, 4, 22))]
    suggest(txns)
    txns[0].note = "Customer advance"
    root = ET.fromstring(build_vouchers_xml(txns, "Sri Lakshmi Traders", "HDFC Bank", educational_mode=True))
    vouchers = root.findall(".//VOUCHER")
    assert [v.findtext("DATE") for v in vouchers] == ["20260401", "20260402"]
    n0 = vouchers[0].findtext("NARRATION")
    assert n0.startswith("[Actual Date: 13/04/2026]") and "Note: Customer advance" in n0 and "Ref 412311112222" in n0
    assert vouchers[1].findtext("NARRATION").startswith("[Actual Date: 22/04/2026]")
    # Bank allocation carries the RRN on the bank ledger's entry only.
    allocs = vouchers[0].findall(".//BANKALLOCATIONS.LIST")
    assert len(allocs) == 1 and allocs[0].findtext("INSTRUMENTNUMBER") == "412311112222"

    normal = ET.fromstring(build_vouchers_xml(txns, "Sri Lakshmi Traders", "HDFC Bank"))
    assert [v.findtext("DATE") for v in normal.findall(".//VOUCHER")] == ["20260413", "20260422"]
    assert "[Actual Date" not in normal.find(".//NARRATION").text


def test_masters_skip_existing_tally_ledgers():
    root = ET.fromstring(build_ledger_masters_xml("Co", "HDFC Bank", {"Rent": "Indirect Expenses", "Ramesh": "Sundry Creditors"},
                                                  {"Rent", "Ramesh"}, existing={"rent", "HDFC Bank"}))
    assert [l.get("NAME") for l in root.findall(".//LEDGER")] == ["Ramesh"]


def test_api_educational_mode_voucher_type_and_existing_ledgers(fixtures):
    c = TestClient(app)
    st = c.post("/api/parse", files={"file": ("hdfc.pdf", fixtures["hdfc"].pdf, "application/pdf")}).json()
    row = st["transactions"][0]
    assert {"group", "instrument_no", "counterparty_type", "occurrence_count", "match_key"} <= row.keys()
    res = c.post("/api/rows/apply", json={"statement": st, "row_no": row["row_no"], "ledger": "Own HDFC OD",
                                          "group": "Bank OD A/c", "voucher_type": "Contra", "note": "self transfer",
                                          "apply_to_similar": False}).json()
    got = res["statement"]["transactions"][0]
    assert (got["voucher_type"], got["group"], got["note"]) == ("Contra", "Bank OD A/c", "self transfer")
    body = {"statement": res["statement"], "company": "Co", "bank_ledger": "HDFC Bank", "educational_mode": True}
    xml = c.post("/api/export/tally/vouchers", json=body).text
    days = {v.findtext("DATE")[-2:] for v in ET.fromstring(xml.encode()).findall(".//VOUCHER")}
    assert days and days <= {"01", "02", "31"}
    body = {"statement": res["statement"], "company": "Co", "bank_ledger": "HDFC Bank", "existing_ledgers": ["Own HDFC OD"]}
    names = [l.get("NAME") for l in ET.fromstring(c.post("/api/export/tally/ledgers", json=body).content).findall(".//LEDGER")]
    assert "Own HDFC OD" not in names and "HDFC Bank" in names


def test_demo_statement_mix():
    """The public sample at /app/review/sample-hdfc is real engine output with a known mix."""
    from tests.fixtures.make_sample import build

    doc = build()
    txns = doc["transactions"]
    assert doc["summary"]["balance_verified"] and len(txns) == 30
    assert sum("suspense" in t["flags"] for t in txns) == 3
    assert sum(t["ledger_source"] == "party_guess" for t in txns) == 8
    assert sum(t["ledger_source"] in ("default_rule", "client_rule") for t in txns) == 19
