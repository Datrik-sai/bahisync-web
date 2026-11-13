"""Builds the X experiment kit: six minimal voucher files (plus one masters file)
that separate how TallyPrime matches an imported voucher to an existing one.

    python -m tests.fixtures.make_x_kit     -> tests/fixtures/out/x_kit/ and x_kit.zip

Question it answers (Phase 2 Test E): why re-importing BahiSync vouchers never
created duplicates, even with "Overwrite voucher when a voucher with same GUID
exists" = No. Each file changes exactly ONE thing against X1:

    X1  REMOTEID A, base content                      baseline
    X2  identical to X1, byte for byte                same REMOTEID, same content
    X3  REMOTEID A, amount and ledger changed         same REMOTEID, changed content
    X4  REMOTEID B, base content                      different REMOTEID, same content
    X5  no REMOTEID, base content                     content only, no identifier
    X6  no REMOTEID, <GUID> element G, base content   GUID only

Test-kit code only: it uses the production voucher builder unchanged (no
REMOTEID from it) and then sets the identifier under test, so the voucher shape
is exactly what BahiSync exports. Nothing in bahisync_engine is modified.
"""

from __future__ import annotations

import csv
import io
import shutil
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from bahisync_engine.export_tally import build_ledger_masters_xml, build_vouchers_xml
from bahisync_engine.models import Transaction

OUT = Path(__file__).resolve().parent / "out" / "x_kit"
BANK = "ID Test Bank"
COMPANIES = {"no": "BahiSync ID Test No", "yes": "BahiSync ID Test Yes"}
NS = uuid.UUID("0d3c5c55-2f3e-4f7e-9a51-6b8a1c4e7d21")  # kit-only namespace, unrelated to production IDs
ID_A, ID_B, GUID_G = (str(uuid.uuid5(NS, k)) for k in ("X-A", "X-B", "X-G"))

BASE = {"amount": Decimal("1000.00"), "ledger": "Rent"}
CHANGED = {"amount": Decimal("1200.00"), "ledger": "Miscellaneous Expenses"}


def _voucher_xml(company: str, amount: Decimal, ledger: str) -> bytes:
    # A constant UTR so the voucher carries a bank allocation, like the Phase 2 C files.
    t = Transaction(1, date(2026, 4, 5), "X TEST PAYMENT", amount, Decimal("0"), None,
                    ref="409300000001", instrument_no="409300000001")
    t.ledger, t.group, t.voucher_type = ledger, "Indirect Expenses", "Payment"
    return build_vouchers_xml([t], company, BANK)  # production builder, no REMOTEID


def _with_ids(xml: bytes, remote_id: str | None = None, guid: str | None = None) -> bytes:
    """Edits the production bytes in place (no re-serialising), so the only
    difference from the base file is the identifier added. Re-parsing would drop
    the xmlns:UDF declaration and add an unrelated variable."""
    start = b'<VOUCHER VCHTYPE="Payment" ACTION="Create" OBJVIEW="Accounting Voucher View">'
    assert xml.count(start) == 1, "unexpected voucher shape"
    if remote_id:
        xml = xml.replace(start, start.replace(b"<VOUCHER ", f'<VOUCHER REMOTEID="{remote_id}" '.encode()))
    if guid:
        line_start = xml.rfind(b"\n", 0, xml.find(b"<VOUCHER ")) + 1
        indent = xml[line_start:xml.find(b"<VOUCHER ")]
        end = xml.find(b">", xml.find(b"<VOUCHER ")) + 1
        xml = xml[:end] + b"\n" + indent + b"  <GUID>" + guid.encode() + b"</GUID>" + xml[end:]
    return xml


def build_files(company: str) -> dict[str, bytes]:
    masters = build_ledger_masters_xml(
        company, BANK, {"Rent": "Indirect Expenses", "Miscellaneous Expenses": "Indirect Expenses"},
        {"Rent", "Miscellaneous Expenses"},
    )
    base = _voucher_xml(company, **BASE)
    x1 = _with_ids(base, remote_id=ID_A)
    return {
        "X0_masters.xml": masters,
        "X1_remoteid_A_base.xml": x1,
        "X2_remoteid_A_base_SAME_AS_X1.xml": x1,
        "X3_remoteid_A_changed_1200_misc.xml": _with_ids(_voucher_xml(company, **CHANGED), remote_id=ID_A),
        "X4_remoteid_B_base.xml": _with_ids(base, remote_id=ID_B),
        "X5_no_identifier_base.xml": base,
        "X6_guid_G_only_base.xml": _with_ids(base, guid=GUID_G),
    }


# ----------------------------------------------------------------- self-checks

def _v(xml: bytes) -> ET.Element:
    return ET.fromstring(xml).find(".//VOUCHER")


def _body(v: ET.Element) -> bytes:
    """The voucher without its identifiers, for comparing content."""
    c = ET.fromstring(ET.tostring(v))
    c.attrib.pop("REMOTEID", None)
    for g in c.findall("GUID"):
        c.remove(g)
    return ET.tostring(c)


def verify(files: dict[str, bytes], company: str) -> list[tuple[str, bool]]:
    out = []
    try:
        for d in files.values():
            ET.fromstring(d)
        out.append(("All 7 XML files are well-formed", True))
    except ET.ParseError:
        return [("All 7 XML files are well-formed", False)]
    x = {k.split("_")[0]: _v(d) for k, d in files.items() if k != "X0_masters.xml"}
    out.append(("Every file names this company in SVCURRENTCOMPANY",
                all(ET.fromstring(d).findtext(".//SVCURRENTCOMPANY") == company for d in files.values())))
    out.append(("Each voucher file holds exactly one voucher, ACTION=Create, dated 20260405",
                all(len(ET.fromstring(files[k]).findall(".//VOUCHER")) == 1 for k in files if k != "X0_masters.xml")
                and all(v.get("ACTION") == "Create" and v.findtext("DATE") == "20260405" for v in x.values())))
    out.append(("X2 is byte-identical to X1", files["X2_remoteid_A_base_SAME_AS_X1.xml"] == files["X1_remoteid_A_base.xml"]))
    amounts = lambda v: [(e.findtext("LEDGERNAME"), e.findtext("AMOUNT"), e.findtext("BANKALLOCATIONS.LIST/AMOUNT"))  # noqa: E731
                         for e in v.findall("ALLLEDGERENTRIES.LIST")]
    out.append(("X3 keeps REMOTEID A; only amount (1,000 -> 1,200) and expense ledger (Rent -> Misc) change",
                x["X3"].get("REMOTEID") == ID_A
                and amounts(x["X1"]) == [("Rent", "-1000.00", None), (BANK, "1000.00", "1000.00")]
                and amounts(x["X3"]) == [("Miscellaneous Expenses", "-1200.00", None), (BANK, "1200.00", "1200.00")]
                and x["X3"].findtext("NARRATION") == x["X1"].findtext("NARRATION")))
    out.append(("X4 differs from X1 only in REMOTEID (B instead of A)",
                x["X4"].get("REMOTEID") == ID_B != ID_A and _body(x["X4"]) == _body(x["X1"])))
    out.append(("X5 is X1 without any identifier",
                x["X5"].get("REMOTEID") is None and x["X5"].find("GUID") is None and _body(x["X5"]) == _body(x["X1"])))
    base_lines = files["X5_no_identifier_base.xml"].splitlines()
    for name in ("X1_remoteid_A_base.xml", "X4_remoteid_B_base.xml", "X6_guid_G_only_base.xml"):
        lines = files[name].splitlines()
        extra = [l for l in lines if l not in base_lines]
        out.append((f"{name.split('_')[0]}: text differs from X5 only in the identifier "
                    f"(same namespace declarations, same bytes otherwise)",
                    len(extra) in (1, 2) and all(b"REMOTEID=" in l or b"<GUID>" in l for l in extra)
                    and [l for l in base_lines if l not in lines] == ([l for l in base_lines if b"<VOUCHER " in l] if any(b"REMOTEID=" in l for l in extra) else [])))
    out.append(("X6 is X1 with a GUID element G instead of a REMOTEID",
                x["X6"].get("REMOTEID") is None and x["X6"].findtext("GUID") == GUID_G
                and GUID_G not in (ID_A, ID_B) and _body(x["X6"]) == _body(x["X1"])))
    return out


# ----------------------------------------------------------------- build

STEPS = [
    # step, file, what changes, expected count after, voucher on 5-Apr afterwards, bank closing
    ("X0", "X0_masters.xml", "Masters", "0", "-", "nil"),
    ("X1", "X1_remoteid_A_base.xml", "Baseline", "1", "A: 1,000 Rent", "1,000.00 Cr"),
    ("X2", "X2_remoteid_A_base_SAME_AS_X1.xml", "Same REMOTEID, same content", "1", "A: 1,000 Rent (unchanged)", "1,000.00 Cr"),
    ("X3", "X3_remoteid_A_changed_1200_misc.xml", "Same REMOTEID, changed content", "1", "A: 1,200 Misc. Exp. if altered; 1,000 Rent if skipped", "1,200.00 Cr if altered; 1,000.00 Cr if skipped"),
    ("X4", "X4_remoteid_B_base.xml", "Different REMOTEID, same content as X1", "2", "A as after X3, plus B: 1,000 Rent", "+1,000.00 Cr"),
    ("X5a", "X5_no_identifier_base.xml", "No identifier", "3", "+1 voucher 1,000 Rent", "+1,000.00 Cr"),
    ("X5b", "X5_no_identifier_base.xml (again)", "No identifier, imported again", "4", "+1 voucher 1,000 Rent", "+1,000.00 Cr"),
    ("X6a", "X6_guid_G_only_base.xml", "GUID only", "5", "+1 voucher 1,000 Rent", "+1,000.00 Cr"),
    ("X6b", "X6_guid_G_only_base.xml (again)", "GUID only, imported again", "5 or 6 (see README)", "Record", "Record"),
]


def results_csv() -> str:
    cols = ["Company", "Overwrite setting shown", "Step", "File imported", "What changes vs X1",
            "Expected voucher count after", "Expected 5-Apr voucher(s)", "Expected ID Test Bank closing",
            "Tally summary: Created", "Altered", "Combined", "Ignored", "Errors",
            "Vouchers before", "Vouchers after", "ID Test Bank closing after",
            "5-Apr voucher(s) actually shown (amount, ledger)", "Screenshot file name", "Errors / exceptions / notes"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for key, company in COMPANIES.items():
        for step, f, change, n, vch, bank in STEPS:
            w.writerow([company, "No" if key == "no" else "Yes", step, f, change, n, vch, bank] + [""] * (len(cols) - 8))
    return buf.getvalue()


README = """\
BahiSync - X experiment kit (Test E follow-up)
==============================================

WHY
---
In Phase 2, re-importing BahiSync vouchers never created duplicates, even with
"Overwrite voucher when a voucher with same GUID exists" = No (Test E). This kit
finds out which identifier TallyPrime uses to match an incoming voucher:
BahiSync's REMOTEID, a GUID element, or the voucher's content.

Each voucher file holds ONE payment and differs from X1 in exactly one thing:

  File                                   REMOTEID   GUID   Content (5-Apr-2026, "X TEST PAYMENT | Ref 409300000001")
  X1_remoteid_A_base.xml                 A          -      1,000.00 to Rent
  X2_remoteid_A_base_SAME_AS_X1.xml      A          -      1,000.00 to Rent      (byte-identical to X1)
  X3_remoteid_A_changed_1200_misc.xml    A          -      1,200.00 to Miscellaneous Expenses
  X4_remoteid_B_base.xml                 B          -      1,000.00 to Rent
  X5_no_identifier_base.xml              -          -      1,000.00 to Rent
  X6_guid_G_only_base.xml                -          G      1,000.00 to Rent

  A = {id_a}
  B = {id_b}
  G = {guid_g}
These IDs are made up for this kit; none is a BahiSync production ID.
All vouchers are ACTION="Create", built with BahiSync's own voucher code, with
the bank ledger "ID Test Bank" (no opening balance, so its balance shows Cr).
KIT_CHECKS.txt lists the automated checks that each file differs only as stated.

SETUP: TWO NEW COMPANIES (TallyPrime Gold, licensed)
---------------------------------------------------
  Company 1: "{co_no}"    files in folder no/
  Company 2: "{co_yes}"   files in folder yes/
Both: Financial year beginning 1-Apr-2026, Books beginning 1-Apr-2026.
Never use BahiSync QA Test, the Phase 2 companies, or real books.

Before ANY import into a company:
 1. Make that company the active one (check its name at the top of Gateway of Tally).
 2. Gateway of Tally > Import > Transactions, then open the configuration (Alt+O / Configure):
      "{co_no}":  Overwrite voucher when a voucher with same GUID exists = No
      "{co_yes}": Overwrite voucher when a voucher with same GUID exists = Yes
    Screenshot this screen once per company. When you switch companies, open it
    again and note whether the value changed by itself (this tells us whether the
    setting is per company or per installation).

AFTER EVERY IMPORT
------------------
 a. Screenshot Tally's import summary (created / altered / combined / ignored /
    errors) before closing it, and copy the numbers into RESULTS.csv.
 b. Voucher count: Display More Reports > Statistics (Payment), or Day Book for 5-Apr-2026.
 c. ID Test Bank closing balance: Balance Sheet > Bank Accounts.
 d. Day Book for 5-Apr-2026: note each voucher's amount and debit ledger.
    Don't alter any voucher.

THE SEQUENCE (same in both companies; use that company's folder)
----------------------------------------------------------------
Expected values below are the predictions under the leading explanation (H1:
Tally matches by REMOTEID, whatever the overwrite setting). Any difference is the
result we're looking for, so record exactly what you see.

 X0  X0_masters.xml (Import > Masters).
     ID Test Bank, Rent, Miscellaneous Expenses created.
 X1  X1 (Transactions).                          Expected: 1 voucher, 1,000 Rent; bank 1,000.00 Cr.
 X2  X2 = X1 again.                              Expected: still 1 voucher, unchanged.
     -> 2 vouchers: Tally does NOT match on REMOTEID.
 X3  X3: same REMOTEID A, 1,200 to Misc. Exp.   Expected: still 1 voucher.
     -> 1 voucher, now 1,200 Misc. Exp.: Tally ALTERS by REMOTEID (H1).
     -> 1 voucher, still 1,000 Rent: Tally SKIPS a matched voucher (H2).
     -> 2 vouchers: REMOTEID is not used for matching.
     Compare the two companies here: a difference means the overwrite setting
     controls REMOTEID matches.
 X4  X4: REMOTEID B, same content as X1.         Expected: 2 vouchers (A as after X3, plus a new 1,000 Rent).
     -> still 1: Tally matches on content (would contradict Phase 2 C6).
 X5a X5: no identifier.                          Expected: 3 vouchers.
 X5b X5 again.                                   Expected: 4 vouchers.
     -> 3 after X5b: Tally matches identical content when there is no identifier.
 X6a X6: GUID G only.                            Expected: 5 vouchers.
 X6b X6 again.
     "{co_yes}" expected 5 (GUID matched, overwritten).
     "{co_no}"  expected 6 if the No setting makes a duplicate for GUID matches,
                as Tally's FAQ describes.
     -> 5 in both companies: GUID matched and the setting made no difference.
     -> 6 in both companies: the GUID element is not used for matching on import.

WHAT THE ANSWERS MEAN FOR BAHISYNC
----------------------------------
 * X3 altered in both companies: re-imports update vouchers whatever the user's
   setting (most predictable). Keep REMOTEID and ACTION="Create".
 * X3 skipped under No (or both): a changed classification is NOT applied unless
   the user sets Overwrite = Yes, so the import guide must say so.
 * X6 only matters for understanding the setting; BahiSync sends no GUID.

FINALLY: EXPORT EACH COMPANY'S DAY BOOK AS XML
---------------------------------------------
After X6b in each company:
 1. Day Book, period 1-Apr-2026 to 30-Apr-2026.
 2. Export (Alt+E > Export, or the Export button), Format: XML (Data Interchange).
 3. Save as DayBook_ID_Test_No.xml / DayBook_ID_Test_Yes.xml and send them back
    with RESULTS.csv and the screenshots.
 The exported XML shows which REMOTEID / GUID Tally stored for each voucher.
"""


def build() -> Path:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    out: dict[str, bytes] = {}
    checks_txt = ["Automated checks on this kit (code, not TallyPrime)", ""]
    ok_all = True
    for key, company in COMPANIES.items():
        files = build_files(company)
        checks = verify(files, company)
        ok_all &= all(ok for _, ok in checks)
        checks_txt.append(f"[{key}/  {company}]")
        checks_txt += [f"{'PASS' if ok else 'FAIL'}  {name}" for name, ok in checks]
        checks_txt.append("")
        out.update({f"{key}/{n}": d for n, d in files.items()})
    out["README.txt"] = README.format(id_a=ID_A, id_b=ID_B, guid_g=GUID_G,
                                      co_no=COMPANIES["no"], co_yes=COMPANIES["yes"]).encode("utf-8")
    out["RESULTS_X.csv"] = results_csv().encode("utf-8-sig")
    out["KIT_CHECKS.txt"] = "\n".join(checks_txt).encode("utf-8")
    if not ok_all:
        raise SystemExit(out["KIT_CHECKS.txt"].decode())
    for name, data in out.items():
        p = OUT / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    zpath = OUT.parent / "x_kit.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in out.items():
            z.writestr(f"bahisync_x_kit/{name}", data)
    return zpath


if __name__ == "__main__":
    print("wrote", build())
