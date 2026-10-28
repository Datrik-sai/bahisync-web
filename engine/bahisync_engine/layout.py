"""Turns positioned words into transaction rows.

The parser is header-driven rather than bank-specific: it finds the column
header row (Date / Narration / Debit / Credit / Balance and their many
synonyms), works out each column's horizontal span, and assigns every word
below it to a column. A line whose date column holds a date starts a new
transaction; lines without a date continue the previous narration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Transaction, Word
from .pdf_io import PageWords
from .values import parse_amount, parse_spaced_date

LINE_TOLERANCE = 3.0  # points; words whose tops differ by less are on one line

# Order matters: more specific phrases first.
ROLE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("value_date", ["value date", "value dt", "val dt", "value"]),
    ("date", ["txn date", "transaction date", "tran date", "trans date", "post date", "posting date", "date"]),
    ("narration", ["narration", "description", "particulars", "transaction remarks", "remarks", "details", "transaction details"]),
    ("ref", ["chq./ref.no", "chq/ref no", "chq/ref.no", "ref no./cheque no", "ref.no", "cheque number", "cheque no", "chq no", "chq.no", "ref no", "reference", "cheque", "chq", "ref"]),
    ("debit", ["withdrawal amt", "withdrawal amount", "withdrawals", "withdrawal", "debit amount", "debits", "debit", "dr amount"]),
    ("credit", ["deposit amt", "deposit amount", "deposits", "deposit", "credit amount", "credits", "credit", "cr amount"]),
    ("drcr", ["dr/cr", "cr/dr", "dr / cr", "type"]),
    ("balance", ["closing balance", "available balance", "running balance", "balance"]),
    ("amount", ["transaction amount", "amount"]),
    ("ignore", ["s no", "sl no", "s.no", "sr no", "sno", "init br", "branch", "init.", "br"]),
]

STOP_PATTERNS = re.compile(
    r"(?i)(closing balance|statement summary|total\b|grand total|page \d+ of \d+|\*\*\s*end of statement|this is a (system|computer) generated)"
)
OPENING_PATTERNS = re.compile(r"(?i)(opening balance|balance b/?f|brought forward|b/f)")
# Lines that repeat on every page of long statements and are never transactions.
NOISE_PATTERNS = re.compile(
    r"(?i)(carried\s*forward|balance\s*c/?f|\bc/f\b|page\s*total|transaction\s*total|"
    r"total\s*(debits?|credits?|withdrawals?|deposits?)|closing balance)"
)


@dataclass
class Column:
    role: str
    text: str
    x0: float
    x1: float


AMOUNT_ROLES = {"debit", "credit", "amount", "balance"}


@dataclass
class ColumnMap:
    columns: list[Column]
    font_size: float = 8.0
    bounds: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        cols = sorted(self.columns, key=lambda c: c.x0)
        self.columns = cols
        # Text columns are left-aligned: their values start at the header's left
        # edge. Amount columns are right-aligned: values end at the header's right
        # edge and can extend left past a short header ("Debit" vs "1,23,456.78").
        max_amount_width = 8.5 * self.font_size  # ~15 characters
        cuts: list[float] = []
        for a, b in zip(cols, cols[1:]):
            if b.role in AMOUNT_ROLES:
                cut = min(b.x0, b.x1 - max_amount_width)
                floor = a.x1 + 2 if a.role in AMOUNT_ROLES else a.x0 + 10
                cut = max(cut, floor)
            else:
                cut = b.x0 - 3
            cuts.append(cut)
        edges = [-1e9, *cuts, 1e9]
        self.bounds = list(zip(edges[:-1], edges[1:]))

    def role_of(self, word: Word) -> str:
        roles = {c.role for c in self.columns}
        for (left, right), col in zip(self.bounds, self.columns):
            if left <= word.xc < right:
                # Right-aligned amounts can sit under a neighbouring header's edge;
                # if a numeric word lands in a text column but overlaps an amount
                # column's span, prefer the amount column.
                if col.role in ("narration", "ref", "ignore") and parse_amount(word.text):
                    for other in self.columns:
                        if other.role in ("debit", "credit", "amount", "balance") and word.x1 >= other.x0 - 2 and word.x0 <= other.x1 + 25:
                            return other.role
                return col.role
        return "ignore" if "ignore" in roles else "narration"

    def has(self, role: str) -> bool:
        return any(c.role == role for c in self.columns)


def group_lines(words: list[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (round(w.top, 1), w.x0)):
        if lines and abs(lines[-1][0].top - w.top) <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def _cells(line: list[Word], gap: float = 7.0) -> list[tuple[str, float, float]]:
    """Merge adjacent header words into cells ('Txn' + 'Date' -> 'Txn Date')."""
    cells: list[list[Word]] = []
    for w in line:
        if cells and w.x0 - cells[-1][-1].x1 <= gap:
            cells[-1].append(w)
        else:
            cells.append([w])
    return [(" ".join(w.text for w in c), c[0].x0, c[-1].x1) for c in cells]


def _classify(cell_text: str) -> str | None:
    t = re.sub(r"\s+", " ", cell_text.lower().replace("(inr)", "").replace("(rs.)", "").replace("(₹)", "")).strip(" .:")
    for role, keys in ROLE_KEYWORDS:
        for k in keys:
            if t == k or t.startswith(k + " ") or t.endswith(" " + k) or (len(k) > 4 and k in t):
                return role
    return None


def find_header(lines: list[list[Word]]) -> tuple[int, ColumnMap] | None:
    """Locate the header line; returns (line_index, ColumnMap)."""
    for i, line in enumerate(lines[:80]):
        joined = " ".join(w.text for w in line).lower()
        if "balance" not in joined or "date" not in joined:
            continue
        if not re.search(r"debit|credit|withdraw|deposit|amount|dr|cr", joined):
            continue
        candidate = list(line)
        # Two-line headers: pull in the next line if it is close and has no date.
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if abs(nxt[0].top - line[0].top) < 14 and not parse_spaced_date([w.text for w in nxt][:3]):
                candidate = _merge_header_lines(line, nxt)
        cols: list[Column] = []
        for text, x0, x1 in _cells(candidate):
            # Unknown headers (e.g. "Tran Id") become ignored columns so their
            # values don't spill into a neighbouring column.
            cols.append(Column(_classify(text) or "ignore", text, x0, x1))
        roles = [c.role for c in cols]
        has_amounts = ("debit" in roles and "credit" in roles) or "amount" in roles
        if "date" in roles and "balance" in roles and has_amounts:
            heights = sorted(w.bottom - w.top for w in line)
            font_size = heights[len(heights) // 2] if heights else 8.0
            return i, ColumnMap(_dedupe(cols), font_size=font_size)
    return None


def _merge_header_lines(a: list[Word], b: list[Word]) -> list[Word]:
    """Stack words from two header lines that sit in the same column."""
    merged: list[Word] = []
    used = set()
    for w in a:
        parts = [w]
        for j, v in enumerate(b):
            if j not in used and v.x0 < w.x1 + 4 and v.x1 > w.x0 - 4:
                parts.append(v)
                used.add(j)
        merged.append(
            Word(" ".join(p.text for p in parts), min(p.x0 for p in parts), max(p.x1 for p in parts), w.top, w.bottom, w.page)
        )
    merged.extend(v for j, v in enumerate(b) if j not in used)
    return sorted(merged, key=lambda w: w.x0)


def _dedupe(cols: list[Column]) -> list[Column]:
    """Keep the first 'date' column as the transaction date; later ones become value_date."""
    seen_date = False
    out = []
    for c in sorted(cols, key=lambda c: c.x0):
        if c.role == "date":
            if seen_date:
                c = Column("value_date", c.text, c.x0, c.x1)
            seen_date = True
        out.append(c)
    return out


@dataclass
class _Draft:
    date_tokens: list[str]
    page: int
    narration: list[str] = field(default_factory=list)
    ref: list[str] = field(default_factory=list)
    value_date: list[str] = field(default_factory=list)
    debit: list[str] = field(default_factory=list)
    credit: list[str] = field(default_factory=list)
    amount: list[str] = field(default_factory=list)
    drcr: list[str] = field(default_factory=list)
    balance: list[str] = field(default_factory=list)


def extract_rows(pages: list[PageWords]) -> tuple[list[Transaction], Decimal | None, list[str]]:
    """Return (transactions, opening_balance_if_printed, warnings)."""
    warnings: list[str] = []
    colmap: ColumnMap | None = None
    drafts: list[_Draft] = []
    opening: Decimal | None = None
    stopped = False

    for pw in pages:
        lines = group_lines(pw.words)
        start = 0
        found = find_header(lines)
        if found:
            idx, colmap = found
            start = idx + 1
            # Skip the second header line if it was merged in.
            if start < len(lines) and abs(lines[start][0].top - lines[idx][0].top) < 14 and not _line_has_date(lines[start], colmap):
                start += 1
        if colmap is None:
            continue

        for line in lines[start:]:
            text = " ".join(w.text for w in line)
            has_date = _line_has_date(line, colmap)
            if OPENING_PATTERNS.search(text) and not has_date:
                # Only the first one is the statement's opening balance; a
                # "Brought Forward" on page 2+ is the previous page's closing.
                bal = _last_amount(line)
                if bal is not None and opening is None and not drafts:
                    opening = bal
                continue
            if not has_date and _is_repeated_header(text):
                continue
            if not has_date and NOISE_PATTERNS.search(text) and not re.search(r"(?i)closing balance", text):
                continue
            if STOP_PATTERNS.search(text) and not _line_has_date(line, colmap):
                if re.search(r"(?i)closing balance|end of statement|statement summary|grand total", text):
                    stopped = True
                    break
                continue

            by_role: dict[str, list[str]] = {}
            for w in line:
                by_role.setdefault(colmap.role_of(w), []).append(w.text)

            date_tokens = by_role.get("date", [])
            parsed = parse_spaced_date(date_tokens) if date_tokens else None
            if parsed:
                d = _Draft(date_tokens, pw.page)
                # Tokens after the date in the date column (e.g. a time) are ignored.
                drafts.append(d)
            elif drafts:
                d = drafts[-1]
            else:
                continue  # text between header and first row (e.g. account details)

            for role in ("narration", "ref", "value_date", "debit", "credit", "amount", "drcr", "balance"):
                getattr(d, role).extend(by_role.get(role, []))
        if stopped:
            break

    if colmap is None:
        warnings.append("Could not find the transaction table header (Date / Narration / Debit / Credit / Balance).")
        return [], None, warnings

    txns: list[Transaction] = []
    for n, d in enumerate(drafts, start=1):
        t = _finalise(n, d, colmap, warnings)
        if t is None:
            continue
        if not t.debit and not t.credit:
            # Dated summary rows: "01/04/2026 Opening Balance", "B/F", "C/F", "Page Total".
            if OPENING_PATTERNS.search(t.narration):
                if opening is None and not txns:
                    opening = t.balance
                continue
            if NOISE_PATTERNS.search(t.narration):
                continue
        txns.append(t)
    for i, t in enumerate(txns, start=1):
        t.row_no = i
    return txns, opening, warnings


def _is_repeated_header(text: str) -> bool:
    """A column-header line printed again mid-page (some banks repeat it)."""
    t = text.lower()
    if "balance" not in t or "date" not in t:
        return False
    hits = sum(1 for _, keys in ROLE_KEYWORDS for k in keys if len(k) > 3 and k in t)
    return hits >= 3 and not re.search(r"\d[\d,]*\.\d{2}", t)


def _line_has_date(line: list[Word], colmap: ColumnMap) -> bool:
    toks = [w.text for w in line if colmap.role_of(w) == "date"]
    return bool(toks and parse_spaced_date(toks))


def _last_amount(line: list[Word]) -> Decimal | None:
    for w in reversed(line):
        p = parse_amount(w.text)
        if p:
            value, suffix = p
            return -value if suffix == "dr" else value
    return None


def _first_amount(tokens: list[str]) -> tuple[Decimal, str | None] | None:
    joined = " ".join(tokens)
    # Amount and its Dr/Cr suffix are sometimes separate words.
    for i, tok in enumerate(tokens):
        p = parse_amount(tok)
        if p:
            value, suffix = p
            if suffix is None and i + 1 < len(tokens) and tokens[i + 1].lower().strip(".()") in ("dr", "cr"):
                suffix = tokens[i + 1].lower().strip(".()")
            return value, suffix
    p = parse_amount(joined)
    return p


def _finalise(n: int, d: _Draft, colmap: ColumnMap, warnings: list[str]) -> Transaction | None:
    parsed = parse_spaced_date(d.date_tokens)
    if not parsed:
        return None
    txn_date, _ = parsed
    vd = parse_spaced_date(d.value_date) if d.value_date else None

    debit = credit = Decimal("0")
    flags: list[str] = []

    deb = _first_amount(d.debit)
    cre = _first_amount(d.credit)
    if deb:
        debit = abs(deb[0])
    if cre:
        credit = abs(cre[0])
    if not deb and not cre and d.amount:
        amt = _first_amount(d.amount)
        if amt:
            value, suffix = amt
            kind = suffix or (d.drcr[0].lower().strip(".") if d.drcr else None)
            if kind in ("dr", "debit", "d"):
                debit = abs(value)
            elif kind in ("cr", "credit", "c"):
                credit = abs(value)
            elif value < 0:
                debit = abs(value)
            else:
                credit = value
                flags.append("direction_inferred")

    balance = None
    bal = _first_amount(d.balance)
    if bal:
        value, suffix = bal
        balance = -abs(value) if suffix == "dr" else value
    else:
        flags.append("missing_balance")

    if debit and credit:
        flags.append("both_debit_and_credit")
    if not debit and not credit:
        flags.append("missing_amount")

    narration = re.sub(r"\s+", " ", " ".join(d.narration)).strip()
    return Transaction(
        row_no=n,
        txn_date=txn_date,
        narration=narration,
        debit=debit,
        credit=credit,
        balance=balance,
        ref=" ".join(d.ref).strip(),
        value_date=vd[0] if vd else None,
        page=d.page,
        flags=flags,
    )
