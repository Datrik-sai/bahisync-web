"""Builds the TallyPrime test kit: XML files and step-by-step instructions for
checks that only a real TallyPrime import can settle.

    python -m tests.fixtures.make_tally_kit      -> tests/fixtures/out/tally_kit/ and tally_kit.zip

Every test runs in its OWN new, disposable TallyPrime company. Never import
these files into a company with real books, or into the existing QA company.
The build checks its own output (KIT_CHECKS.txt) and refuses to write a kit
that fails: well-formed XML, stable REMOTEIDs, C4 changing only one ledger, C5
overlapping exactly, C6 giving two IDs, company names consistent.
All data is the synthetic April 2026 sample (Sri Lakshmi Traders, HDFC XX4321).
"""

from __future__ import annotations

import copy
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

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



# One disposable TallyPrime company per test. SVCURRENTCOMPANY in every file is
# the company that file is meant for, as named in README.
CO_SIGN = "BahiSync Sign Test"
CO_RENT = "BahiSync Rent Test"
CO_DUP = "BahiSync Dup Test"
CO_ALT = "BahiSync Dup Test Alter"
CO_OFF = "BahiSync Overwrite Off"
CO_D = {"ignore": "BahiSync Masters Ignore", "modify": "BahiSync Masters Modify", "combine": "BahiSync Masters Combine"}
ORIGINAL_COMPANY = "Sri Lakshmi Traders"


def _masters(sample: dict, company: str, opening: bool = True) -> bytes:
    extra = {"opening_confirmed": True, "books_begin": "2026-04-01"} if opening else {}
    return _post("tally/ledgers", sample, company=company, **extra)


def _vouchers(statement: dict, company: str, action: str = "Create") -> bytes:
    if action == "Create":
        return _post("tally/vouchers", statement, company=company)  # exactly what production exports
    result = statement_from_json(statement)
    account = account_identity(result.bank, result.account_hint, BANK)
    return build_vouchers_xml(result.transactions, company, BANK, account=account, action=action)


def reclassified(sample: dict) -> dict:
    st = copy.deepcopy(sample)
    for t in st["transactions"]:
        if t["row_no"] == 18:  # 17-Apr BRN-TRF 8841203, Rs 12,000, Suspense A/c
            t["ledger"], t["group"], t["flags"] = "Miscellaneous Expenses", "Indirect Expenses", []
    return st


def overlap(sample: dict) -> dict:
    """A second statement covering 17-29 Apr: the same 13 bank transactions, numbered from 1."""
    st = copy.deepcopy(sample)
    st["id"], st["filename"] = "kit-overlap", "Overlap 17-29 Apr.pdf"
    st["transactions"] = [dict(t, row_no=i) for i, t in enumerate(sample["transactions"][17:], start=1)]
    return st


def build() -> Path:
    sample = json.loads(SAMPLE.read_text())
    result = statement_from_json(sample)
    assert result.rows_total == 30
    pair = identical_pair(sample)
    files: dict[str, bytes] = {}

    # A. Opening balance sign
    files["A_sign_test_masters.xml"] = sign_test_masters()

    # B. Rent date: the same voucher format the QA company imported (no REMOTEID,
    # no opening balance). Only SVCURRENTCOMPANY differs from the QA file: it names
    # the Rent test company, like every other file in the kit.
    files["B1_rent_test_masters.xml"] = _masters(sample, CO_RENT, opening=False)
    files["B2_rent_test_vouchers_original_format.xml"] = build_vouchers_xml(result.transactions, CO_RENT, BANK)

    # C. Main track: ACTION="Create" + REMOTEID, exactly what production exports.
    files["C1_masters_with_opening.xml"] = _masters(sample, CO_DUP)
    files["C2_vouchers_create.xml"] = _vouchers(sample, CO_DUP)
    files["C4_vouchers_row18_reclassified_create.xml"] = _vouchers(reclassified(sample), CO_DUP)
    files["C5_vouchers_overlap_17_to_29_apr_create.xml"] = _vouchers(overlap(sample), CO_DUP)
    files["C6_vouchers_two_identical_payments_create.xml"] = _vouchers(pair, CO_DUP)

    # C7. Fallback track, ONLY if C3 fails: the same steps with ACTION="Alter" for re-imports.
    # The first import stays "Create" (an Alter needs a voucher to exist).
    files["C7a_ALTER_TRACK_masters_with_opening.xml"] = _masters(sample, CO_ALT)
    files["C7b_ALTER_TRACK_vouchers_create.xml"] = _vouchers(sample, CO_ALT)
    files["C7c_ALTER_TRACK_vouchers_alter.xml"] = _vouchers(sample, CO_ALT, "Alter")
    files["C7d_ALTER_TRACK_row18_reclassified_alter.xml"] = _vouchers(reclassified(sample), CO_ALT, "Alter")
    files["C7e_ALTER_TRACK_overlap_17_to_29_apr_alter.xml"] = _vouchers(overlap(sample), CO_ALT, "Alter")

    # D. Repeated masters import: one company per import behaviour.
    for option, company in CO_D.items():
        files[f"D_{option}_masters_with_opening.xml"] = _masters(sample, company)

    # E. Optional control: overwrite setting off.
    files["E1_overwrite_off_masters_with_opening.xml"] = _masters(sample, CO_OFF)
    files["E2_overwrite_off_vouchers_create.xml"] = _vouchers(sample, CO_OFF)

    exp = expected(result)
    files["README.txt"] = README.format(**exp, **_names()).encode("utf-8")
    files["RESULTS.csv"] = results_csv(exp).encode("utf-8-sig")  # BOM so Excel reads the rupee sign / UTF-8
    checks = verify(files, sample)
    files["KIT_CHECKS.txt"] = ("Automated checks on this kit (code, not TallyPrime)\n\n" + "\n".join(
        f"{'PASS' if ok else 'FAIL'}  {name}" for name, ok in checks) + "\n").encode("utf-8")
    if not all(ok for _, ok in checks):
        raise SystemExit("Kit failed its own checks:\n" + files["KIT_CHECKS.txt"].decode())

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    zpath = OUT.parent / "tally_kit.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(f"bahisync_tally_kit/{name}", data)
    return zpath


def _names() -> dict[str, str]:
    return {"co_sign": CO_SIGN, "co_rent": CO_RENT, "co_dup": CO_DUP, "co_alt": CO_ALT, "co_off": CO_OFF,
            "co_ignore": CO_D["ignore"], "co_modify": CO_D["modify"], "co_combine": CO_D["combine"],
            "original": ORIGINAL_COMPANY}


# ----------------------------------------------------------------- self-checks

def _vouchers_by_id(xml: bytes) -> dict[str, ET.Element]:
    return {v.get("REMOTEID"): v for v in ET.fromstring(xml).iter("VOUCHER")}


def _shape(v: ET.Element) -> tuple:
    """Everything Tally reads from a voucher, for comparing two files."""
    entries = tuple(
        (e.findtext("LEDGERNAME"), e.findtext("ISDEEMEDPOSITIVE"), e.findtext("AMOUNT"),
         ET.tostring(e.find("BANKALLOCATIONS.LIST")) if e.find("BANKALLOCATIONS.LIST") is not None else b"")
        for e in v.findall("ALLLEDGERENTRIES.LIST")
    )
    return (v.get("VCHTYPE"), v.findtext("DATE"), v.findtext("NARRATION"), entries)


def _company(xml: bytes) -> str:
    return ET.fromstring(xml).findtext(".//SVCURRENTCOMPANY")


def verify(files: dict[str, bytes], sample: dict) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    xmls = {n: d for n, d in files.items() if n.endswith(".xml")}
    try:
        for d in xmls.values():
            ET.fromstring(d)
        out.append((f"All {len(xmls)} XML files are well-formed", True))
    except ET.ParseError:
        out.append(("All XML files are well-formed", False))
        return out

    c2 = _vouchers_by_id(xmls["C2_vouchers_create.xml"])
    ids = list(c2)
    rows = sample["transactions"]
    out.append(("C2: 30 vouchers, 30 distinct REMOTEIDs, all ACTION=Create",
                len(c2) == 30 and len(set(ids)) == 30 and all(ids)
                and {v.get("ACTION") for v in c2.values()} == {"Create"}))

    c4 = _vouchers_by_id(xmls["C4_vouchers_row18_reclassified_create.xml"])
    changed = [i for i in ids if _shape(c2[i]) != _shape(c4[i])]
    row18 = ids[17]
    led2 = [e.findtext("LEDGERNAME") for e in c2[row18].findall("ALLLEDGERENTRIES.LIST")]
    led4 = [e.findtext("LEDGERNAME") for e in c4[row18].findall("ALLLEDGERENTRIES.LIST")]
    out.append(("C4: same 30 REMOTEIDs as C2, in the same order", list(c4) == ids))
    out.append(("C4: only the 17-Apr Rs 12,000 voucher differs from C2", changed == [row18]
                and c2[row18].findtext("DATE") == "20260417" and "BRN-TRF 8841203" in c2[row18].findtext("NARRATION")))
    same_but_ledger = (
        _shape(c2[row18])[:3] == _shape(c4[row18])[:3]
        and [e[1:] for e in _shape(c2[row18])[3]] == [e[1:] for e in _shape(c4[row18])[3]]
    )
    out.append(("C4: in that voucher only the ledger changes (Suspense A/c -> Miscellaneous Expenses); "
                "date, narration, amounts and bank allocation unchanged",
                same_but_ledger and led2 == ["Suspense A/c", BANK] and led4 == ["Miscellaneous Expenses", BANK]))

    c5 = _vouchers_by_id(xmls["C5_vouchers_overlap_17_to_29_apr_create.xml"])
    out.append(("C5: 13 vouchers = C2's rows 18-30 (17-29 Apr), same REMOTEIDs, identical content",
                list(c5) == ids[17:] and all(_shape(c5[i]) == _shape(c2[i]) for i in c5)
                and [v.findtext("DATE") for v in c5.values()] == [r["txn_date"].replace("-", "") for r in rows[17:]]))

    c6 = _vouchers_by_id(xmls["C6_vouchers_two_identical_payments_create.xml"])
    shapes = [_shape(v) for v in c6.values()]
    out.append(("C6: two identical Rs 500 payments on 30-Apr with two different REMOTEIDs, neither in C2",
                len(c6) == 2 and len(set(c6)) == 2 and shapes[0] == shapes[1] and not set(c6) & set(ids)))

    alter = {n: _vouchers_by_id(xmls[n]) for n in ("C7c_ALTER_TRACK_vouchers_alter.xml",
                                                    "C7d_ALTER_TRACK_row18_reclassified_alter.xml",
                                                    "C7e_ALTER_TRACK_overlap_17_to_29_apr_alter.xml")}
    c7b = _vouchers_by_id(xmls["C7b_ALTER_TRACK_vouchers_create.xml"])
    out.append(("C7: fallback track uses the same REMOTEIDs; C7b is Create, C7c-e are Alter",
                list(c7b) == ids and {v.get("ACTION") for v in c7b.values()} == {"Create"}
                and list(alter["C7c_ALTER_TRACK_vouchers_alter.xml"]) == ids
                and list(alter["C7d_ALTER_TRACK_row18_reclassified_alter.xml"]) == ids
                and list(alter["C7e_ALTER_TRACK_overlap_17_to_29_apr_alter.xml"]) == ids[17:]
                and all({v.get("ACTION") for v in a.values()} == {"Alter"} for a in alter.values())))
    out.append(("C7d: same single change as C4",
                [i for i in ids if _shape(c2[i]) != _shape(alter["C7d_ALTER_TRACK_row18_reclassified_alter.xml"][i])] == [row18]))

    b2 = ET.fromstring(xmls["B2_rent_test_vouchers_original_format.xml"])
    rent = next(v for v in b2.iter("VOUCHER") if "RENT APRIL" in v.findtext("NARRATION"))
    out.append(("B2: original format (no REMOTEID), Rent dated 20260402",
                all(v.get("REMOTEID") is None for v in b2.iter("VOUCHER")) and rent.findtext("DATE") == "20260402"))
    out.append(("B1/C1: B has no opening balance; C1 sets -184250.00 on HDFC Bank XX4321 only",
                b"OPENINGBALANCE" not in xmls["B1_rent_test_masters.xml"]
                and [(l.get("NAME"), l.findtext("OPENINGBALANCE")) for l in ET.fromstring(xmls["C1_masters_with_opening.xml"]).iter("LEDGER")
                     if l.find("OPENINGBALANCE") is not None] == [(BANK, "-184250.00")]))

    expected_company = {
        "A_": CO_SIGN, "B1": CO_RENT, "B2": CO_RENT, "C1": CO_DUP, "C2": CO_DUP, "C4": CO_DUP,
        "C5": CO_DUP, "C6": CO_DUP, "C7": CO_ALT, "D_ignore": CO_D["ignore"], "D_modify": CO_D["modify"],
        "D_combine": CO_D["combine"], "E1": CO_OFF, "E2": CO_OFF,
    }
    wrong = [n for n, d in xmls.items() for p, c in expected_company.items() if n.startswith(p) and _company(d) != c]
    out.append(("SVCURRENTCOMPANY in every file matches the company named for it in README", not wrong))
    return out


# ----------------------------------------------------------------- results sheet

def results_csv(exp: dict[str, str]) -> str:
    import csv
    import io

    cols = ["Step", "Company", "File imported", "Import option / setting used", "Expected",
            "Tally summary: Created", "Altered", "Combined", "Ignored", "Errors",
            "Vouchers before", "Vouchers after", "HDFC Bank XX4321 closing after", "Suspense A/c after",
            "Other observed values", "Errors / exceptions shown"]
    c, s = exp["closing"], exp["susp"]
    rows = [
        ["A", CO_SIGN, "A_sign_test_masters.xml", "-", "Sign Test Dr 1,84,250.00 Dr; Sign Test Cr 1,84,250.00 Cr; Sign Test Zero nil"],
        ["B1", CO_RENT, "B1_rent_test_masters.xml", "-", "22 ledgers in file (Cash already exists)"],
        ["B2", CO_RENT, "B2_rent_test_vouchers_original_format.xml", "-",
         "Vouchers 0 -> 30. Day Book 1-3 Apr BEFORE opening anything: Megha Foods 1-Apr, Rent 2-Apr, Rajesh Kumar 3-Apr"],
        ["C1", CO_DUP, "C1_masters_with_opening.xml", "-", "HDFC opening 1,84,250.00 Dr; vouchers 0 -> 0"],
        ["C2", CO_DUP, "C2_vouchers_create.xml", "Overwrite voucher when same GUID exists = Yes",
         f"Vouchers 0 -> 30 (19 Payment, 8 Receipt, 3 Contra); HDFC {c} Dr; Suspense {s} Dr"],
        ["C3", CO_DUP, "C2_vouchers_create.xml (again)", "Overwrite = Yes", f"Vouchers 30 -> 30; HDFC {c} Dr; Suspense {s} Dr"],
        ["C4", CO_DUP, "C4_vouchers_row18_reclassified_create.xml", "Overwrite = Yes",
         f"Vouchers 30 -> 30; 17-Apr Rs 12,000 voucher now Miscellaneous Expenses; HDFC {c} Dr; Suspense {exp['susp_c4']}"],
        ["C5", CO_DUP, "C5_vouchers_overlap_17_to_29_apr_create.xml", "Overwrite = Yes",
         f"Vouchers 30 -> 30; HDFC {c} Dr; Suspense {s} Dr (row 18 back in Suspense: newer file wins)"],
        ["C6", CO_DUP, "C6_vouchers_two_identical_payments_create.xml", "Overwrite = Yes",
         f"Vouchers 30 -> 32; HDFC {exp['closing_c6']} Dr; Suspense {s} Dr"],
        ["C6b", CO_DUP, "C6_vouchers_two_identical_payments_create.xml (again)", "Overwrite = Yes",
         f"Vouchers 32 -> 32; HDFC {exp['closing_c6']} Dr"],
        ["C7a", CO_ALT, "C7a_ALTER_TRACK_masters_with_opening.xml", "ONLY IF C3 FAILED", "HDFC opening 1,84,250.00 Dr"],
        ["C7b", CO_ALT, "C7b_ALTER_TRACK_vouchers_create.xml", "ONLY IF C3 FAILED", f"Vouchers 0 -> 30; HDFC {c} Dr"],
        ["C7c", CO_ALT, "C7c_ALTER_TRACK_vouchers_alter.xml", "ONLY IF C3 FAILED", f"Vouchers 30 -> 30; HDFC {c} Dr"],
        ["C7d", CO_ALT, "C7d_ALTER_TRACK_row18_reclassified_alter.xml", "ONLY IF C3 FAILED",
         f"Vouchers 30 -> 30; Suspense {exp['susp_c4']}"],
        ["C7e", CO_ALT, "C7e_ALTER_TRACK_overlap_17_to_29_apr_alter.xml", "ONLY IF C3 FAILED", f"Vouchers 30 -> 30; Suspense {s} Dr"],
        ["D-ignore 1", CO_D["ignore"], "D_ignore_masters_with_opening.xml", "first import", "HDFC opening 1,84,250.00 Dr; Rent under Indirect Expenses"],
        ["D-ignore 2", CO_D["ignore"], "D_ignore_masters_with_opening.xml (after moving Rent to Direct Expenses)", "Ignore duplicates", "Record Rent's group and HDFC opening"],
        ["D-modify 1", CO_D["modify"], "D_modify_masters_with_opening.xml", "first import", "HDFC opening 1,84,250.00 Dr"],
        ["D-modify 2", CO_D["modify"], "D_modify_masters_with_opening.xml (after moving Rent to Direct Expenses)", "Modify with new data", "Record Rent's group and HDFC opening"],
        ["D-combine 1", CO_D["combine"], "D_combine_masters_with_opening.xml", "first import", "HDFC opening 1,84,250.00 Dr"],
        ["D-combine 2", CO_D["combine"], "D_combine_masters_with_opening.xml (after moving Rent to Direct Expenses)", "Combine opening balance", "Record Rent's group and HDFC opening (risk: 3,68,500.00 Dr)"],
        ["E1", CO_OFF, "E1_overwrite_off_masters_with_opening.xml", "-", "HDFC opening 1,84,250.00 Dr"],
        ["E2", CO_OFF, "E2_overwrite_off_vouchers_create.xml", "Overwrite = No", f"Vouchers 0 -> 30; HDFC {c} Dr"],
        ["E3", CO_OFF, "E2_overwrite_off_vouchers_create.xml (again)", "Overwrite = No", "Record: Tally's FAQ says this duplicates (60)"],
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow(r + [""] * (len(cols) - len(r)))
    return buf.getvalue()


README = """\
BahiSync - TallyPrime test kit (Phase 2, corrected)
===================================================

What this kit settles: things only a real TallyPrime import can show.
Synthetic data only (the April 2026 sample: Sri Lakshmi Traders, HDFC XX4321).
Use TallyPrime Gold, licensed, NOT Educational mode.

GROUND RULES
------------
* Every test (A, B, C, C7, each of D, E) gets its OWN new company. Create it with
  Financial year beginning from 1-Apr-2026 and Books beginning from 1-Apr-2026.
* Never use "BahiSync QA Test" or any company with real books.
* BEFORE EVERY IMPORT, make the test's company the active one: close any other
  open companies (or select the right one), and check its name at the top of
  Gateway of Tally. The XML's SVCURRENTCOMPANY field does NOT choose the company
  for a manual file import: your Phase 1 QA import landed in "BahiSync QA Test"
  although the file said "{original}", and Tally's own import help starts with
  "Select the required company". In this kit every file's SVCURRENTCOMPANY matches
  its test company anyway, so file and company always agree.
* Record every import in RESULTS.csv (opens in Excel): Tally's import summary
  (created / altered / combined / ignored / errors), voucher count before and
  after, the HDFC Bank XX4321 closing balance, the Suspense A/c balance, and any
  error or exception Tally shows. Send RESULTS.csv back.

Where to read the numbers:
  Voucher count:   Display More Reports > Statistics (counts per voucher type), or Day Book for 1-Apr to 30-Apr-2026
  HDFC closing:    Balance Sheet > Bank Accounts > HDFC Bank XX4321 (or Display > Account Books > Ledger)
  Suspense A/c:    Balance Sheet > Suspense A/c
Import paths:
  Masters:         Gateway of Tally > Import > Masters
  Transactions:    Gateway of Tally > Import > Transactions
  Import settings: in the Import screen, Alt+O / Configure

----------------------------------------------------------------------------
WHY C4 AND C5 USE ACTION="Create" (and when ACTION="Alter" is used)
----------------------------------------------------------------------------
Tally's Import FAQ says Tally recognises an existing voucher on import by its
GUID, and the import configuration "Overwrite voucher when a voucher with same
GUID exists" decides what happens: Yes = the existing voucher is overwritten;
No = a duplicate is created. For third-party XML it says to give every voucher a
unique REMOTEID. So the expectation (NOT yet proven) is: with Overwrite = Yes, a
voucher sent again with the same REMOTEID overwrites the existing one, even
with ACTION="Create".

C3, C4 and C5 keep ACTION="Create" on purpose: that is exactly what BahiSync
production exports when a user downloads again after a change, so they test the
real path. If C3 fails (vouchers double), run the C7 fallback track, which
re-imports with ACTION="Alter" instead. Its first import stays "Create" because
an Alter needs an existing voucher to change. Test E (optional) checks the other
side of Tally's setting: Overwrite = No should duplicate.

Every file uses the same REMOTEID for the same bank transaction (checked: see
KIT_CHECKS.txt).

----------------------------------------------------------------------------
TEST A - Opening balance sign                Company: "{co_sign}"
----------------------------------------------------------------------------
A. Import A_sign_test_masters.xml (Masters). Open each ledger (Alter > Ledger) and
   note the Opening Balance:
     Sign Test Dr    expected 1,84,250.00 Dr
     Sign Test Cr    expected 1,84,250.00 Cr
     Sign Test Zero  expected blank / nil
   If Dr and Cr are swapped, BahiSync's sign must be flipped before release.

----------------------------------------------------------------------------
TEST B - Rent date                           Company: "{co_rent}"
----------------------------------------------------------------------------
These two files use the same format as the Phase 1 QA files (no REMOTEID, no
opening balance), so the result is comparable. The only difference from the QA
files is SVCURRENTCOMPANY, which now says "{co_rent}". Make "{co_rent}"
the active company before importing.
B1. Import B1_rent_test_masters.xml (Masters).
B2. Import B2_rent_test_vouchers_original_format.xml (Transactions).
B3. BEFORE opening any voucher: Day Book, period 1-Apr-2026 to 3-Apr-2026.
    Expected: 1-Apr Receipt Megha Foods Pvt Ltd 64,800.00
              2-Apr Payment Rent                28,000.00
              3-Apr Payment Rajesh Kumar         1,500.00
    If Rent is NOT on 2-Apr: export this Day Book (Alt+E, XML) and send it back.
    Don't open or alter the voucher.

----------------------------------------------------------------------------
TEST C - Opening end to end + re-import      Company: "{co_dup}"
----------------------------------------------------------------------------
Before C2: in the Import screen's configuration set "Overwrite voucher when a
voucher with same GUID exists" = Yes, and note it in RESULTS.csv.
C1. C1_masters_with_opening.xml (Masters). HDFC opening expected 1,84,250.00 Dr.
C2. C2_vouchers_create.xml (Transactions). Expected 30 vouchers
    (19 Payment, 8 Receipt, 3 Contra), HDFC {closing} Dr, Suspense {susp} Dr.
C3. C2_vouchers_create.xml AGAIN.
    PASS: still 30 vouchers, HDFC {closing} Dr. FAIL: 60 vouchers -> stop C,
    go to the C7 track.
C4. C4_vouchers_row18_reclassified_create.xml. Only change: the 17-Apr
    Rs 12,000 voucher (BRN-TRF 8841203) moves from Suspense A/c to Miscellaneous
    Expenses. PASS: 30 vouchers; HDFC {closing} Dr; Suspense {susp_c4}.
C5. C5_vouchers_overlap_17_to_29_apr_create.xml: the same 13 transactions
    (17-29 Apr) as they'd come from a second, overlapping statement.
    PASS: 30 vouchers; HDFC {closing} Dr. Suspense goes back to {susp} Dr,
    because this file has the 17-Apr voucher in Suspense again (newer file wins).
C6. C6_vouchers_two_identical_payments_create.xml: two genuine Rs 500 payments on
    30-Apr with the same narration and no reference. PASS: 32 vouchers;
    HDFC {closing_c6} Dr.
C6b. The same C6 file AGAIN. PASS: still 32 vouchers; HDFC {closing_c6} Dr.

----------------------------------------------------------------------------
C7 - FALLBACK TRACK, ONLY IF C3 FAILED       Company: "{co_alt}" (new)
----------------------------------------------------------------------------
Skip C7 entirely if C3 passed. Run it only when C3 doubled the vouchers.
Same Overwrite = Yes setting.
C7a. C7a_ALTER_TRACK_masters_with_opening.xml
C7b. C7b_ALTER_TRACK_vouchers_create.xml        expected 30 vouchers, HDFC {closing} Dr
C7c. C7c_ALTER_TRACK_vouchers_alter.xml         PASS: still 30
C7d. C7d_ALTER_TRACK_row18_reclassified_alter.xml   PASS: 30; Suspense {susp_c4}
C7e. C7e_ALTER_TRACK_overlap_17_to_29_apr_alter.xml PASS: 30; Suspense {susp} Dr

----------------------------------------------------------------------------
TEST D - Importing masters again: three separate companies
----------------------------------------------------------------------------
Do the same four steps in each company, choosing a different option at step 3:
  "{co_ignore}"   file D_ignore_masters_with_opening.xml    option: Ignore duplicates
  "{co_modify}"   file D_modify_masters_with_opening.xml    option: Modify with new data
  "{co_combine}"  file D_combine_masters_with_opening.xml   option: Combine opening balance
1. Import the company's D file (Masters). Note HDFC's opening (expected 1,84,250.00 Dr)
   and Rent's group (Indirect Expenses).
2. Alter ledger Rent: change its group to Direct Expenses. Save.
3. Import the same D file again; when Tally asks what to do with masters that
   already exist, choose that company's option.
4. Note Rent's group and HDFC's opening. (Risk being checked: Combine adds the
   opening twice -> 3,68,500.00 Dr; Modify may put Rent back under Indirect Expenses.)

----------------------------------------------------------------------------
TEST E (optional) - Overwrite setting off    Company: "{co_off}"
----------------------------------------------------------------------------
Set "Overwrite voucher when a voucher with same GUID exists" = No.
E1. E1_overwrite_off_masters_with_opening.xml
E2. E2_overwrite_off_vouchers_create.xml        expected 30 vouchers
E3. E2 again. Tally's FAQ says this creates duplicates (60). Record what happens:
    it tells us what BahiSync's guide must say about that setting.
"""


if __name__ == "__main__":
    print("wrote", build())
