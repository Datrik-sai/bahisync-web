"""Generates synthetic bank statement PDFs in layouts modelled on common
Indian banks. No real customer data is used. Each statement comes with the
ground-truth transactions so tests can check every row.

Run directly to write PDFs to tests/fixtures/out/:
    python -m tests.fixtures.make_statements
"""

from __future__ import annotations

import io
import random
import textwrap
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pikepdf
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


@dataclass
class Truth:
    txn_date: date
    narration: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    ref: str = ""


NARRATIONS_DR = [
    ("UPI/DR/412345678901/RAMESH KUMAR/SBIN/ramesh@oksbi/Payment", "1,250.00"),
    ("UPI/DR/412398765432/SWIGGY/YESB/swiggy@yesbank/Food", "486.00"),
    ("ATM WDL/HYDERABAD AMEERPET/ATM ID S1AW0123", "10,000.00"),
    ("NEFT DR-ICIC0001234-SRI LAKSHMI TRADERS-NETBANK-INV 2231", "48,560.00"),
    ("BIL/ONL/TSSPDCL ELECTRICITY/1102938", "3,214.00"),
    ("GST PAYMENT CBIC CPIN 26043600123456", "18,000.00"),
    ("SMS CHARGES QTR ENDED MAR", "17.70"),
    ("IMPS/P2A/612345/RENT OCTOBER/HDFC0000001/SURESH REDDY", "25,000.00"),
    ("ACH D- LIC OF INDIA-POLICY 556677", "6,240.00"),
    ("POS 4123XXXXXX1234 RELIANCE DIGITAL HYD", "12,999.00"),
    ("CHQ PAID 000123 VENKATESWARA HARDWARE", "7,800.00"),
    ("TDS PAYMENT CBDT CHALLAN 280", "2,500.00"),
]
NARRATIONS_CR = [
    ("NEFT CR-HDFC0000123-ACME SOLUTIONS PVT LTD-SALARY OCT 2026", "85,000.00"),
    ("UPI/CR/412311112222/PRIYA SHARMA/ICIC/priya@okicici/Refund", "2,300.00"),
    ("INT.PD:01-07-2026 TO 30-09-2026", "1,184.00"),
    ("CASH DEPOSIT BY SELF AT BRANCH", "20,000.00"),
    ("IMPS/P2A/700123/CUSTOMER PAYMENT/KKBK0000958/ANAND ENTERPRISES", "36,400.00"),
    ("CHQ DEP 445566 MEGHA FOODS", "15,750.00"),
]


def make_truths(seed: int, n: int, opening: Decimal) -> list[Truth]:
    rnd = random.Random(seed)
    d = date(2026, 4, 1)
    bal = opening
    out: list[Truth] = []
    for i in range(n):
        d += timedelta(days=rnd.choice([0, 1, 1, 2, 3]))
        if rnd.random() < 0.38:
            narr, amt = rnd.choice(NARRATIONS_CR)
            v = Decimal(amt.replace(",", ""))
            bal += v
            out.append(Truth(d, narr, Decimal("0"), v, bal, f"{rnd.randint(100000, 999999)}"))
        else:
            narr, amt = rnd.choice(NARRATIONS_DR)
            v = Decimal(amt.replace(",", ""))
            bal -= v
            out.append(Truth(d, narr, v, Decimal("0"), bal, f"{rnd.randint(100000, 999999)}"))
    return out


def inr(v: Decimal) -> str:
    """Indian digit grouping: 1,23,456.78"""
    neg = v < 0
    s = f"{abs(v):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + "." + frac


# ---------------------------------------------------------------- layouts

@dataclass
class Layout:
    name: str
    bank_header: list[str]
    columns: list[tuple[str, float, str]]  # (header, x, align: l/r)
    date_fmt: str
    wrap: int
    mode: str = "split"  # split = debit/credit columns, single = amount + dr/cr
    newest_first: bool = False
    balance_suffix: bool = False
    page_size: tuple[float, float] = A4
    two_line_header: bool = False
    rows_per_page: int = 22
    amount_suffix: bool = False  # single Amount column printed as "1,250.00 Dr"
    page_noise: bool = False  # Page Total / Carried Forward / Brought Forward rows, repeated header
    print_opening: bool = True


LAYOUTS = {
    "sbi": Layout(
        "sbi",
        ["State Bank of India", "Branch: AMEERPET HYDERABAD   IFSC: SBIN0001234", "Account No: 00000031234567890", "Statement from 01 Apr 2026 to 30 Sep 2026"],
        [("Txn Date", 30, "l"), ("Value Date", 90, "l"), ("Description", 150, "l"), ("Ref No./Cheque No.", 330, "l"),
         ("Debit", 470, "r"), ("Credit", 540, "r"), ("Balance", 610, "r")],
        "%d %b %Y", 34, page_size=landscape(A4)[::-1] if False else (640, 842),
    ),
    "hdfc": Layout(
        "hdfc",
        ["HDFC BANK Ltd.", "Account Branch : BALANAGAR", "RTGS/NEFT IFSC : HDFC0000521", "Account No : 50100123456789"],
        [("Date", 30, "l"), ("Narration", 80, "l"), ("Chq./Ref.No.", 300, "l"), ("Value Dt", 380, "l"),
         ("Withdrawal Amt.", 500, "r"), ("Deposit Amt.", 580, "r"), ("Closing Balance", 670, "r")],
        "%d/%m/%y", 38, page_size=(700, 842),
    ),
    "icici": Layout(
        "icici",
        ["ICICI Bank Limited", "IFSC Code: ICIC0000456", "Account Number XXXXXXXX4521"],
        [("S No.", 30, "l"), ("Value Date", 60, "l"), ("Transaction Date", 125, "l"), ("Cheque Number", 200, "l"),
         ("Transaction Remarks", 270, "l"), ("Withdrawal Amount (INR)", 560, "r"), ("Deposit Amount (INR)", 640, "r"),
         ("Balance (INR)", 730, "r")],
        "%d/%m/%Y", 36, page_size=(760, 842), two_line_header=True,
    ),
    "axis": Layout(
        "axis",
        ["AXIS BANK", "IFSC: UTIB0000789", "Customer ID 987654  Account No 912010012345678"],
        [("Tran Date", 30, "l"), ("Particulars", 95, "l"), ("Amount", 430, "r"), ("Dr/Cr", 460, "l"), ("Balance", 570, "r")],
        "%d-%m-%Y", 44, mode="single", newest_first=True, balance_suffix=True, page_size=(600, 842),
    ),
    # Regional / Gramin style: one Amount column with Dr/Cr suffix, page totals,
    # carried/brought forward rows, a repeated header mid-page and no opening line.
    "gramin": Layout(
        "gramin",
        ["Telangana Grameena Bank", "Branch: BHONGIR   IFSC: SBIN0RRDCGB", "Account No: 62012345678"],
        [("Date", 30, "l"), ("Particulars", 90, "l"), ("Chq No", 320, "l"), ("Amount", 450, "r"), ("Balance", 560, "r")],
        "%d.%m.%Y", 40, mode="single", amount_suffix=True, balance_suffix=True, page_size=(600, 842),
        rows_per_page=10, page_noise=True, print_opening=False,
    ),
    "kotak": Layout(
        "kotak",
        ["Kotak Mahindra Bank", "IFSC KKBK0000958", "Account No. 1234567890"],
        [("Date", 30, "l"), ("Description", 95, "l"), ("Chq/Ref No", 330, "l"), ("Withdrawal (Dr)", 470, "r"),
         ("Deposit (Cr)", 545, "r"), ("Balance", 620, "r")],
        "%d-%m-%Y", 36, page_size=(640, 842),
    ),
}


def _header_cells(c: canvas.Canvas, layout: Layout, y: float) -> float:
    c.setFont("Helvetica-Bold", 7.5)
    for title, x, align in layout.columns:
        if layout.two_line_header and " " in title and len(title) > 12:
            first, second = title.split(" ", 1)
            draw = c.drawRightString if align == "r" else c.drawString
            draw(x, y, first)
            draw(x, y - 9, second)
        else:
            (c.drawRightString if align == "r" else c.drawString)(x, y, title)
    return y - (22 if layout.two_line_header else 14)


def render(layout: Layout, truths: list[Truth], opening: Decimal) -> bytes:
    buf = io.BytesIO()
    w, h = layout.page_size
    c = canvas.Canvas(buf, pagesize=(w, h))
    rows = list(reversed(truths)) if layout.newest_first else truths
    pages = [rows[i : i + layout.rows_per_page] for i in range(0, len(rows), layout.rows_per_page)]

    for p_no, page_rows in enumerate(pages, start=1):
        y = h - 40
        if p_no == 1:
            c.setFont("Helvetica-Bold", 11)
            c.drawString(30, y, layout.bank_header[0])
            c.setFont("Helvetica", 8)
            for line in layout.bank_header[1:]:
                y -= 12
                c.drawString(30, y, line)
            y -= 22
            if not layout.newest_first and layout.print_opening:
                c.setFont("Helvetica", 8)
                c.drawString(30, y, f"Opening Balance : {inr(opening)}")
                y -= 18
        y = _header_cells(c, layout, y)
        c.setFont("Helvetica", 7.5)
        bal_x = next(x for title, x, _ in layout.columns if "balance" in title.lower())
        if layout.page_noise and p_no > 1:
            c.drawString(90, y, "Brought Forward")
            c.drawRightString(bal_x, y, inr(pages[p_no - 2][-1].balance) + (" Cr" if layout.balance_suffix else ""))
            y -= 14
        for s_no, t in enumerate(page_rows, start=1 + (p_no - 1) * layout.rows_per_page):
            if layout.page_noise and s_no % layout.rows_per_page == 6:
                y = _header_cells(c, layout, y)  # header printed again mid-page
                c.setFont("Helvetica", 7.5)
            lines = textwrap.wrap(t.narration, layout.wrap) or [""]
            for col_title, x, align in layout.columns:
                key = col_title.lower()
                draw = c.drawRightString if align == "r" else c.drawString
                if key in ("txn date", "date", "transaction date", "tran date"):
                    draw(x, y, t.txn_date.strftime(layout.date_fmt))
                elif key in ("value date", "value dt"):
                    draw(x, y, t.txn_date.strftime(layout.date_fmt))
                elif key == "s no.":
                    draw(x, y, str(s_no))
                elif key in ("description", "narration", "particulars", "transaction remarks"):
                    for k, line in enumerate(lines):
                        c.drawString(x, y - k * 9, line)
                elif key in ("ref no./cheque no.", "chq./ref.no.", "cheque number", "chq/ref no"):
                    draw(x, y, t.ref)
                elif layout.mode == "split" and key.startswith(("debit", "withdrawal")):
                    if t.debit:
                        draw(x, y, inr(t.debit))
                elif layout.mode == "split" and key.startswith(("credit", "deposit")):
                    if t.credit:
                        draw(x, y, inr(t.credit))
                elif key == "amount":
                    suffix = (" Dr" if t.debit else " Cr") if layout.amount_suffix else ""
                    draw(x, y, inr(t.debit or t.credit) + suffix)
                elif key == "dr/cr":
                    draw(x, y, "DR" if t.debit else "CR")
                elif "balance" in key:
                    text = inr(t.balance) + (" Cr" if layout.balance_suffix else "")
                    draw(x, y, text)
            y -= 9 * len(lines) + 5
        if layout.page_noise:
            dr = sum((t.debit for t in page_rows), Decimal("0"))
            cr = sum((t.credit for t in page_rows), Decimal("0"))
            c.drawString(90, y, "Page Total")
            c.drawRightString(330, y, f"Dr {inr(dr)}")
            c.drawRightString(450, y, f"{inr(cr)} Cr")
            y -= 12
            c.drawString(90, y, "Carried Forward" if p_no < len(pages) else "Transaction Total")
            c.drawRightString(bal_x, y, inr(page_rows[-1].balance) + (" Cr" if layout.balance_suffix else ""))
        c.setFont("Helvetica", 7)
        c.drawString(30, 30, f"Page {p_no} of {len(pages)}")
        if p_no == len(pages):
            c.drawString(30, 45, "**** END OF STATEMENT ****" if layout.name != "hdfc" else f"Closing Balance {inr(truths[-1].balance)}")
        c.showPage()
    c.save()
    return buf.getvalue()


def encrypt(pdf_bytes: bytes, password: str) -> bytes:
    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        pdf.save(out, encryption=pikepdf.Encryption(user=password, owner=password + "-owner", R=4))
    return out.getvalue()


def rasterise(pdf_bytes: bytes) -> bytes:
    """Turn a text PDF into an image-only PDF, like a scan."""
    from pdf2image import convert_from_bytes
    from reportlab.lib.utils import ImageReader

    images = convert_from_bytes(pdf_bytes, dpi=200)
    buf = io.BytesIO()
    first = images[0]
    w, h = first.width * 72 / 200, first.height * 72 / 200
    c = canvas.Canvas(buf, pagesize=(w, h))
    for img in images:
        c.drawImage(ImageReader(img.convert("L")), 0, 0, width=w, height=h)
        c.showPage()
    c.save()
    return buf.getvalue()


@dataclass
class Fixture:
    name: str
    pdf: bytes
    truths: list[Truth]
    opening: Decimal
    password: str | None = None
    expected_bank: str = ""


def build_all() -> dict[str, Fixture]:
    specs = [
        ("sbi", 11, 40, Decimal("152340.55"), "State Bank of India"),
        ("hdfc", 12, 30, Decimal("48210.00"), "HDFC Bank"),
        ("icici", 13, 26, Decimal("905.10"), "ICICI Bank"),
        ("axis", 14, 28, Decimal("310500.00"), "Axis Bank"),
        ("kotak", 15, 24, Decimal("75000.00"), "Kotak Mahindra Bank"),
        ("gramin", 16, 30, Decimal("64500.00"), "Telangana Grameena Bank"),
    ]
    out: dict[str, Fixture] = {}
    for name, seed, n, opening, bank in specs:
        truths = make_truths(seed, n, opening)
        pdf = render(LAYOUTS[name], truths, opening)
        out[name] = Fixture(name, pdf, truths, opening, expected_bank=bank)

    hd = out["hdfc"]
    out["hdfc_password"] = Fixture("hdfc_password", encrypt(hd.pdf, "SAI1990"), hd.truths, hd.opening, "SAI1990", hd.expected_bank)
    short = make_truths(21, 12, Decimal("20000.00"))
    sbi_short = render(LAYOUTS["sbi"], short, Decimal("20000.00"))
    out["sbi_scanned"] = Fixture("sbi_scanned", rasterise(sbi_short), short, Decimal("20000.00"), expected_bank="State Bank of India")
    return out


if __name__ == "__main__":
    target = Path(__file__).parent / "out"
    target.mkdir(exist_ok=True)
    for name, fx in build_all().items():
        (target / f"{name}.pdf").write_bytes(fx.pdf)
        print(f"wrote {name}.pdf ({len(fx.truths)} rows)")
