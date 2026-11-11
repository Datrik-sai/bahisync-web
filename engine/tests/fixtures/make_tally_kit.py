"""Builds the TallyPrime test kit: XML files and step-by-step instructions for
checks that only a real TallyPrime import can settle.

    python -m tests.fixtures.make_tally_kit      -> tests/fixtures/out/tally_kit/ and tally_kit.zip

Every test runs in its OWN new, disposable TallyPrime company. Never import
these files into a company with real books, or into the existing QA company.
All data is the synthetic April 2026 sample (Sri Lakshmi Traders, HDFC XX4321).
"""

from __future__ import annotations

import copy
import json
import zipfile
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from bahisync_engine.export_tally import _envelope, _serialise, _sub, build_vouchers_xml
from bahisync_engine.opening import inr
from bahisync_engine.serialize import statement_from_json
from bahisync_engine.voucher_ids import account_identity
from service.app import app

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "web" / "src" / "lib" / "sample-hdfc.json"
OUT = Path(__file__).resolve().parent / "out" / "tally_kit"
BANK = "HDFC Bank XX4321"
UDF = {"xmlns:UDF": "TallyUDF"}


def _post(kind: str, statement: dict, **extra) -> bytes:
    body = {"statement": statement, "company": "BahiSync Test", "bank_ledger": BANK, **extra}
    r = TestClient(app).post(f"/api/export/{kind}", json=body)
    r.raise_for_status()
    return r.content


def sign_test_masters() -> bytes:
    """Three bank ledgers whose opening balances use BahiSync's sign convention."""
    env, data = _envelope("BahiSync Sign Test", "All Masters")
    for name, value in (("Sign Test Dr", "-184250.00"), ("Sign Test Cr", "184250.00"), ("Sign Test Zero", "0.00")):
        msg = _sub(data, "TALLYMESSAGE", **UDF)
        led = _sub(msg, "LEDGER", NAME=name, ACTION="Create")
        _sub(_sub(led, "NAME.LIST"), "NAME", name)
        _sub(led, "PARENT", "Bank Accounts")
        _sub(led, "OPENINGBALANCE", value)
    return _serialise(env)


def identical_pair(sample: dict) -> dict:
    """Two genuine, identical payments on one day with no bank reference."""
    st = copy.deepcopy(sample)
    st["id"], st["filename"] = "kit-identical-pair", "Identical pair.pdf"
    base = sample["transactions"][-1]
    rows = []
    bal = Decimal(base["balance"])
    for i in (1, 2):
        bal -= Decimal("500.00")
        row = copy.deepcopy(base)
        row.update(row_no=i, txn_date="2026-04-30", narration="CASH PAID PETTY EXPENSES", debit="500.00", credit="0",
                   balance=f"{bal:.2f}", ref="", instrument_no="", ledger="Miscellaneous Expenses",
                   group="Indirect Expenses", voucher_type="Payment", flags=[], review_state="", evidence=[])
        rows.append(row)
    st["transactions"] = rows
    return st


def _dr_cr(v: Decimal) -> str:
    return f"{inr(v)} {'Dr' if v > 0 else 'Cr'}" if v else "nil"


def expected(result) -> dict[str, str]:
    """Figures quoted in README, computed from the sample so they can't drift."""
    susp = sum((t.debit - t.credit for t in result.transactions if t.ledger == "Suspense A/c"), Decimal("0"))
    row18 = next(t for t in result.transactions if t.row_no == 18)
    closing = result.opening_balance + result.total_credit - result.total_debit
    return {
        "closing": inr(closing),
        "closing_c6": inr(closing - Decimal("1000.00")),
        "susp": inr(susp),
        "susp_c4": _dr_cr(susp - row18.debit),
    }


def build() -> Path:
    sample = json.loads(SAMPLE.read_text())
    result = statement_from_json(sample)
    assert result.rows_total == 30
    files: dict[str, bytes] = {}

    # A. Opening balance sign
    files["A_sign_test_masters.xml"] = sign_test_masters()

    # B. Rent date: the same format the QA company imported (no REMOTEID, company as in the original)
    files["B1_rent_test_masters.xml"] = TestClient(app).post(
        "/api/export/tally/ledgers", json={"statement": sample, "company": "Sri Lakshmi Traders", "bank_ledger": BANK}
    ).content
    files["B2_rent_test_vouchers_original_format.xml"] = build_vouchers_xml(result.transactions, "Sri Lakshmi Traders", BANK)

    # C. Opening balance end to end + duplicate protection (REMOTEID)
    files["C1_masters_with_opening.xml"] = _post("tally/ledgers", sample, opening_confirmed=True, books_begin="2026-04-01")
    files["C2_vouchers.xml"] = _post("tally/vouchers", sample)
    reclassified = copy.deepcopy(sample)
    for t in reclassified["transactions"]:
        if t["row_no"] == 18:  # BRN-TRF 8841203, Rs 12,000, Suspense A/c
            t["ledger"], t["group"], t["flags"] = "Miscellaneous Expenses", "Indirect Expenses", []
    files["C4_vouchers_row18_reclassified.xml"] = _post("tally/vouchers", reclassified)
    overlap = copy.deepcopy(sample)
    overlap["id"], overlap["filename"] = "kit-overlap", "Overlap from 17 Apr.pdf"
    overlap["transactions"] = [dict(t, row_no=i) for i, t in enumerate(sample["transactions"][17:], start=1)]
    files["C5_vouchers_overlap_17_to_29_apr.xml"] = _post("tally/vouchers", overlap)
    pair = identical_pair(sample)
    files["C6_vouchers_two_identical_payments.xml"] = _post("tally/vouchers", pair)
    account = account_identity(result.bank, result.account_hint, BANK)
    files["C7_vouchers_action_alter_ONLY_IF_C3_FAILS.xml"] = build_vouchers_xml(
        result.transactions, "BahiSync Test", BANK, account=account, action="Alter")

    # D. Repeated masters import behaviour
    files["D_masters_with_opening.xml"] = files["C1_masters_with_opening.xml"]

    files["README.txt"] = README.format(**expected(result)).encode("utf-8")
    files["RESULTS.txt"] = RESULTS.encode("utf-8")

    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    zpath = OUT.parent / "tally_kit.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(f"bahisync_tally_kit/{name}", data)
    return zpath


README = """\
BahiSync - TallyPrime test kit (Phase 2)
=======================================

These tests settle what only a real TallyPrime import can show. Use TallyPrime
Gold (licensed, not Educational mode). Create a NEW company for each test, with
"Financial year beginning from" 1-Apr-2026 and "Books beginning from" 1-Apr-2026.
Never use the existing "BahiSync QA Test" company or any company with real books.

Import paths used below:
  Masters:      Gateway of Tally > Import > Masters       (choose the file)
  Transactions: Gateway of Tally > Import > Transactions  (choose the file)
Tally shows an import summary after each import (created / altered / errors).
Write it down: it's the most useful evidence.

Record every result in RESULTS.txt and send it back.

----------------------------------------------------------------------------
TEST A - Opening balance sign            Company: "BahiSync Sign Test"
----------------------------------------------------------------------------
1. Import A_sign_test_masters.xml as Masters.
2. Open each ledger (Alter > Ledger) and note its Opening Balance field:
     Sign Test Dr    expected  1,84,250.00 Dr
     Sign Test Cr    expected  1,84,250.00 Cr
     Sign Test Zero  expected  blank / nil
3. Also open Balance Sheet > Bank Accounts and note the three closing balances.
If Dr and Cr come out swapped, BahiSync's sign must be flipped before release.

----------------------------------------------------------------------------
TEST B - Rent date                       Company: "BahiSync Rent Test"
----------------------------------------------------------------------------
These files use exactly the format the QA company received (no REMOTEID).
1. Import B1_rent_test_masters.xml as Masters.
2. Import B2_rent_test_vouchers_original_format.xml as Transactions.
3. BEFORE opening any voucher: Day Book, change period to 1-Apr-2026 to 3-Apr-2026.
   Expected, without opening anything:
     1-Apr-2026  Receipt  Megha Foods Pvt Ltd     64,800.00
     2-Apr-2026  Payment  Rent                    28,000.00
     3-Apr-2026  Payment  Rajesh Kumar             1,500.00
4. Note the date Tally lists for Rent.
5. Only if Rent is NOT on 2-Apr: export that Day Book (Alt+E > Export, XML format)
   and send the file back with RESULTS.txt. Don't alter the voucher.

----------------------------------------------------------------------------
TEST C - Opening balance end to end + duplicate protection
                                         Company: "BahiSync Dup Test"
----------------------------------------------------------------------------
C1. Import C1_masters_with_opening.xml as Masters.
    HDFC Bank XX4321 opening balance expected: 1,84,250.00 Dr.
C2. Import C2_vouchers.xml as Transactions.
    Expected: 30 vouchers (19 Payment, 8 Receipt, 3 Contra);
    HDFC Bank XX4321 closing balance {closing} Dr; Suspense A/c {susp} Dr
    (12,000 + 1,850 paid out, 4,500 received).
C3. Import C2_vouchers.xml AGAIN, unchanged.
    PASS: still 30 vouchers and {closing} Dr (Tally altered, not created).
    FAIL: 60 vouchers / doubled movement. If it fails, delete this company,
    repeat C1 + C2 in a fresh one, then import C7 instead of C2 at this step.
C4. Import C4_vouchers_row18_reclassified.xml.
    PASS: still 30 vouchers; the 17-Apr Rs 12,000 voucher (BRN-TRF 8841203)
    now debits Miscellaneous Expenses; Suspense A/c becomes {susp_c4};
    HDFC closing unchanged at {closing} Dr.
C5. Import C5_vouchers_overlap_17_to_29_apr.xml (13 vouchers from a second,
    overlapping statement).
    PASS: still 30 vouchers; closing balance unchanged at {closing} Dr.
    Note: this file has row 18 back in Suspense A/c, so after C5 Suspense is
    back to {susp} Dr. That's expected: the newer file wins.
C6. Import C6_vouchers_two_identical_payments.xml (two genuine Rs 500 payments
    on 30-Apr with the same narration).
    PASS: 32 vouchers; closing balance {closing_c6} Dr.
C6b. Import C6 AGAIN.
    PASS: still 32 vouchers; {closing_c6} Dr.

----------------------------------------------------------------------------
TEST D - Importing masters again         Company: "BahiSync Masters Test"
----------------------------------------------------------------------------
1. Import D_masters_with_opening.xml. Note HDFC Bank XX4321's opening (1,84,250 Dr).
2. Alter ledger "Rent": change its group to Direct Expenses. Save.
3. Import D_masters_with_opening.xml again. When Tally asks how to treat
   masters that already exist, choose "Ignore duplicates". Note Rent's group and
   HDFC's opening.
4. Repeat with "Modify with new data". Note both again.
5. Repeat with "Combine opening balance". Note both again.
   (Expected risk: Combine adds the opening a second time.)
"""

RESULTS = """\
BahiSync TallyPrime test results
TallyPrime version / release:
Date tested:

TEST A  Opening balance as shown by Tally
  Sign Test Dr   :
  Sign Test Cr   :
  Sign Test Zero :

TEST B  Rent date
  Day Book 1-3 Apr, Rent listed on :
  Megha Foods on                   :
  Rajesh Kumar on                  :
  (if Rent not on 2-Apr) exported Day Book attached? :

TEST C
  C1 HDFC opening                      :
  C2 vouchers / types / HDFC closing   :
  C2 Suspense A/c balance              :
  C3 after re-import: vouchers / HDFC  :   Tally import summary (created / altered):
  C4 vouchers / row 18 ledger / Suspense :
  C5 vouchers / HDFC closing           :
  C6 vouchers / HDFC closing           :
  C6b vouchers / HDFC closing          :
  (only if C3 failed) C7 result        :

TEST D  (Rent group / HDFC opening after each)
  After first import          :
  Ignore duplicates           :
  Modify with new data        :
  Combine opening balance     :

Anything else Tally reported (errors, exceptions):
"""


if __name__ == "__main__":
    print("wrote", build())
