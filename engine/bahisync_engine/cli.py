"""Command line: python -m bahisync_engine.cli statement.pdf [--password X] [--out DIR]

Parses a statement, suggests ledgers and writes Excel + Tally XML next to it.
Handy for the concierge phase: run it on customer files by hand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .export_excel import build_excel
from .export_tally import build_ledger_masters_xml, build_vouchers_xml
from .ledgers import suggest
from .parser import parse_statement


def main() -> None:
    ap = argparse.ArgumentParser(description="BahiSync: bank statement PDF to Tally")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--password")
    ap.add_argument("--company", default="My Company")
    ap.add_argument("--bank-ledger", default="")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    result = parse_statement(args.pdf.read_bytes(), args.password)
    groups = suggest(result.transactions)
    out = args.out or args.pdf.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = args.pdf.stem
    bank_ledger = args.bank_ledger or result.bank
    (out / f"{stem}.xlsx").write_bytes(build_excel(result))
    used = {t.ledger for t in result.transactions if t.ledger}
    (out / f"{stem}_ledgers.xml").write_bytes(build_ledger_masters_xml(args.company, bank_ledger, groups, used))
    (out / f"{stem}_vouchers.xml").write_bytes(build_vouchers_xml(result.transactions, args.company, bank_ledger))
    print(json.dumps(result.summary(), indent=2))


if __name__ == "__main__":
    main()
