"""Public entry point: PDF bytes in, verified transactions out."""

from __future__ import annotations

from . import balance
from .banks import account_hint, detect_bank
from .layout import extract_rows
from .models import ParseResult
from .pdf_io import decrypt, read_words


def parse_statement(pdf_bytes: bytes, password: str | None = None, ocr: bool = True) -> ParseResult:
    clear = decrypt(pdf_bytes, password)
    pages, used_ocr, first_text = read_words(clear, ocr=ocr)
    txns, opening, warnings = extract_rows(pages)
    txns, opening, closing, bal_warnings = balance.verify(txns, opening)
    warnings.extend(bal_warnings)
    if used_ocr:
        warnings.append("Scanned statement: text was read with OCR. Check flagged rows carefully.")
    if not txns and not warnings:
        warnings.append("No transactions found.")
    return ParseResult(
        bank=detect_bank(first_text),
        account_hint=account_hint(first_text),
        transactions=txns,
        opening_balance=opening,
        closing_balance=closing,
        pages=len(pages),
        used_ocr=used_ocr,
        warnings=warnings,
    )
