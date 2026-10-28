"""Parsing of Indian-format amounts and the date styles banks print."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# 1,23,456.78 / 123456.78 / 1,234.5 / .50 — optional Dr/Cr suffix, optional minus or brackets
_AMOUNT_RE = re.compile(
    r"^\(?-?(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?|\.\d{1,2})\)?\s*(dr|cr)?\.?$",
    re.IGNORECASE,
)


def parse_amount(text: str) -> tuple[Decimal, str | None] | None:
    """Return (value, 'dr'|'cr'|None) or None when the text is not an amount.

    Plain integers without separators or decimals are rejected because cheque
    numbers and reference numbers look the same; banks always print amounts
    with paise.
    """
    t = text.strip().replace(" ", "")
    if not t:
        return None
    m = _AMOUNT_RE.match(t)
    if not m:
        return None
    number = m.group(1)
    if "." not in number and "," not in number:
        return None
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    if t.startswith("-") or (t.startswith("(") and t.endswith(")")):
        value = -value
    suffix = m.group(2).lower() if m.group(2) else None
    return value, suffix


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_PATTERNS = [
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), ["%d/%m/%Y"]),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{2}$"), ["%d/%m/%y"]),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"), ["%d-%m-%Y"]),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{2}$"), ["%d-%m-%y"]),
    (re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$"), ["%d.%m.%Y"]),
    (re.compile(rf"^\d{{1,2}}-({_MONTHS})-\d{{4}}$", re.I), ["%d-%b-%Y"]),
    (re.compile(rf"^\d{{1,2}}-({_MONTHS})-\d{{2}}$", re.I), ["%d-%b-%y"]),
    (re.compile(rf"^\d{{1,2}}({_MONTHS})\d{{4}}$", re.I), ["%d%b%Y"]),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), ["%Y-%m-%d"]),
]


def parse_date(text: str) -> date | None:
    t = text.strip().rstrip(",")
    t = re.sub(r"(?i)sept", "Sep", t)
    for pattern, formats in _DATE_PATTERNS:
        if pattern.match(t):
            for fmt in formats:
                try:
                    return datetime.strptime(t, fmt).date()
                except ValueError:
                    continue
    return None


def parse_spaced_date(tokens: list[str]) -> tuple[date, int] | None:
    """Handle dates split into words, e.g. '01 Apr 2026' or '01 Apr 26'.

    Returns (date, tokens_consumed).
    """
    if len(tokens) >= 3:
        joined = f"{tokens[0]}-{tokens[1]}-{tokens[2]}"
        d = parse_date(joined)
        if d and re.match(rf"(?i)^({_MONTHS})$", tokens[1]):
            return d, 3
    if tokens:
        d = parse_date(tokens[0])
        if d:
            return d, 1
    return None
