"""Public entry point: PDF bytes in, verified transactions out."""

from __future__ import annotations

from . import balance
from .banks import account_hint, detect_bank
from .layout import extract_rows
from .models import ParseResult
from .pdf_io import decrypt, read_words
from .summary import read_printed_summary, reconcile


def _header_text(first_text: str) -> str:
    """Page-1 text above the transaction table. Narrations below it carry other
    banks' IFSCs and names (a payee's KKBK... IFSC is not the account's bank)."""
    lines = first_text.splitlines()
    for i, line in enumerate(lines):
        low = line.lower()
        if "balance" in low and ("date" in low or "debit" in low or "withdraw" in low):
            return "\n".join(lines[:i]) or first_text
    return first_text


def parse_statement(pdf_bytes: bytes, password: str | None = None, ocr: bool = True) -> ParseResult:
    clear = decrypt(pdf_bytes, password)
    pages, used_ocr, first_text = read_words(clear, ocr=ocr)
    txns, opening, warnings = extract_rows(pages)
    printed = read_printed_summary(pages)
    if opening is None:
        # An opening balance printed above the table ("Opening Balance : 1,84,250.00")
        # is used for the check instead of one worked out from row 1.
        opening = printed.opening
    elif printed.opening is None:
        printed.opening = opening  # printed inside the table (B/F line)
    opening_source = "printed" if opening is not None else "derived"
    txns, opening, closing, bal_warnings = balance.verify(txns, opening)
    warnings.extend(bal_warnings)
    first = txns[0] if txns else None
    derived_opening = first.balance - first.credit + first.debit if first is not None and first.balance is not None else None
    if used_ocr:
        warnings.append("Scanned statement: text was read with OCR. Check flagged rows carefully.")
    if not txns and not warnings:
        warnings.append("No transactions found.")
    result = ParseResult(
        bank=detect_bank(_header_text(first_text)),
        account_hint=account_hint(first_text),
        transactions=txns,
        opening_balance=opening,
        closing_balance=closing,
        pages=len(pages),
        used_ocr=used_ocr,
        warnings=warnings,
        opening_source=opening_source if txns else "",
    )
    result.reconciliation = reconcile(result, printed, derived_opening) if txns else []
    for c in result.reconciliation:
        if c["status"] == "mismatch" and c["check"] != "continuity":
            warnings.append(f"{c['label']}: {c['note']} Review before exporting.")
    return result
