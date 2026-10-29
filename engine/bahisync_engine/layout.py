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
    ("ref", ["ref/cheque no", "ref / cheque no", "chq./ref.no", "chq/ref no", "chq/ref.no", "ref no./cheque no", "ref.no", "cheque number", "cheque no", "chq no", "chq.no", "ref no", "reference", "cheque", "chq", "ref"]),
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
# Browser print headers and footers on statements printed from net banking:
# "19/02/2025, 14:23  State Bank of India", "https://retail.onlinesbi.sbi/...  2/11".
PRINT_NOISE = re.compile(r"(?i)(https?://|www\.\S+\.\S+|^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\b|^\s*\d{1,3}\s*/\s*\d{1,3}\s*$)")


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

    def refine(self, words: list[Word]) -> None:
        """Move each boundary between two text columns into the empty strip the
        data actually leaves between them. Headers are often centred over
        left-aligned text (ICICI's "Transaction Remarks" sits well to the right of
        where the remarks start), so the header's left edge is a poor cut."""
        text_roles = {"date", "value_date", "narration", "ref", "ignore", "drcr"}
        cuts = [b[1] for b in self.bounds[:-1]]
        for k, (a, b) in enumerate(zip(self.columns, self.columns[1:])):
            if a.role not in text_roles or b.role not in text_roles:
                continue
            lo, hi = (a.x0 + a.x1) / 2, (b.x0 + b.x1) / 2
            spans = sorted((max(w.x0, lo), min(w.x1, hi)) for w in words if w.x1 > lo and w.x0 < hi)
            best: tuple[float, float] | None = None  # (width, midpoint)
            cursor = lo
            for x0, x1 in spans + [(hi, hi)]:
                if x0 - cursor > 4 and (best is None or x0 - cursor > best[0]):
                    best = (x0 - cursor, (cursor + x0) / 2)
                cursor = max(cursor, x1)
            if best is not None:
                cuts[k] = best[1]
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


def _match_role(t: str) -> str | None:
    for role, keys in ROLE_KEYWORDS:
        for k in keys:
            if t == k or t.startswith(k + " ") or t.endswith(" " + k) or (len(k) > 4 and k in t):
                return role
    return None


def _classify(cell_text: str) -> str | None:
    t = re.sub(r"\s+", " ", cell_text.lower().replace("(inr)", "").replace("(rs.)", "").replace("(₹)", "")).strip(" .:")
    # Bracketed text is a qualifier, not the column's name: SBI's "Date (Value Date)"
    # is the transaction date, "Withdrawal (Dr)" is the debit column.
    outside = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", t)).strip(" .:")
    return (_match_role(outside) if outside else None) or _match_role(t)


def find_header(lines: list[list[Word]]) -> tuple[int, ColumnMap, int] | None:
    """Locate the header; returns (first line index, ColumnMap, number of header lines).

    Headers can wrap over up to three lines (ICICI: "Transaction / Date",
    "Withdrawal / Amount / (INR)"); words stacked in the same column are merged.
    """
    for i, line in enumerate(lines[:80]):
        window = [line]
        for nxt in lines[i + 1 : i + 3]:
            if nxt[0].top - line[0].top >= 16 or parse_spaced_date([w.text for w in nxt][:3]):
                break
            window.append(nxt)
        joined = " ".join(w.text for ln in window for w in ln).lower()
        if "balance" not in joined or "date" not in joined:
            continue
        if not re.search(r"debit|credit|withdraw|deposit|amount|dr|cr", joined):
            continue
        # Try the longest stack first, then shorter ones (a data line can sit close below a one-line header).
        for n in range(len(window), 0, -1):
            candidate = list(window[0])
            for extra in window[1:n]:
                candidate = _merge_header_lines(candidate, extra)
            cols: list[Column] = []
            for text, x0, x1 in _cells(candidate):
                # Unknown headers (e.g. "Tran Id") become ignored columns so their
                # values don't spill into a neighbouring column.
                cols.append(Column(_classify(text) or "ignore", text, x0, x1))
            roles = [c.role for c in cols]
            has_amounts = ("debit" in roles and "credit" in roles) or "amount" in roles
            if "date" in roles and "balance" in roles and has_amounts:
                heights = sorted(w.bottom - w.top for ln in window[:n] for w in ln)
                font_size = heights[len(heights) // 2] if heights else 8.0
                return i, ColumnMap(_dedupe(cols), font_size=font_size), n
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
    mode: str | None = None  # "bands" or "amount_closes", decided on the first page with rows
    carry: list[dict[str, list[str]]] = []  # amount_closes: lines waiting for their amount line

    for pw in pages:
        lines = group_lines(pw.words)
        start = 0
        found = find_header(lines)
        if found:
            idx, colmap, header_lines = found
            start = idx + header_lines
            # Fit text-column boundaries to the data rows of this page (up to just
            # past the last dated line, so footers and legends don't count).
            body = lines[start:]
            dated = [ln[0].top for ln in body if _line_has_date(ln, colmap)]
            if dated:
                colmap.refine([w for ln in body if ln[0].top <= dated[-1] + 40 for w in ln])
        if colmap is None:
            continue

        rows: list[tuple[float, dict[str, list[str]], bool]] = []  # (top, words by role, starts a row)
        for line in lines[start:]:
            text = " ".join(w.text for w in line)
            if PRINT_NOISE.search(text):
                continue
            has_date = _line_has_date(line, colmap)
            if OPENING_PATTERNS.search(text) and (not has_date or not _has_txn_amount(line, colmap)):
                # Only the first one is the statement's opening balance; a
                # "Brought Forward" on page 2+ is the previous page's closing.
                # Dated B/F rows with only a balance ("25Aug2026 BALANCE BROUGHT
                # FORWARD 289.41") are handled here too.
                bal = _last_amount(line)
                if bal is not None and opening is None and not drafts and not any(r[2] for r in rows):
                    opening = bal
                continue
            if not has_date and _is_repeated_header(text):
                continue
            if not has_date and NOISE_PATTERNS.search(text) and not re.search(r"(?i)closing balance", text):
                continue
            if STOP_PATTERNS.search(text) and not has_date:
                if re.search(r"(?i)closing balance|end of statement|statement summary|grand total", text):
                    stopped = True
                    break
                continue

            by_role: dict[str, list[str]] = {}
            for w in line:
                by_role.setdefault(colmap.role_of(w), []).append(w.text)
            date_tokens = by_role.get("date", [])
            rows.append((line[0].top, by_role, bool(date_tokens and parse_spaced_date(date_tokens))))

        if mode is None and any(r[2] for r in rows):
            mode = _row_mode(rows)
        groups = (
            _close_on_amounts(rows, pw.page, drafts, carry)
            if mode == "amount_closes"
            else _group_rows(rows, pw.page, drafts, pw.rules)
        )
        for d, parts in groups:
            for by_role in parts:
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
        if not t.debit and not t.credit and t.balance is None and not OPENING_PATTERNS.search(t.narration):
            continue  # a date with nothing else on the row is never a transaction
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


def _group_rows(
    rows: list[tuple[float, dict[str, list[str]], bool]], page: int, drafts: list[_Draft], rules: list[float] | None = None
) -> list[tuple[_Draft, list[dict[str, list[str]]]]]:
    """Stitch a page's lines into transactions using the table's row bands.

    Lines inside one table row are a line-height apart; rows are separated by a
    larger gap. Each band of lines between two such gaps is one transaction,
    wherever its date sits: top-aligned (most banks) or vertically centred on a
    wrapped narration (SBI), so "TRANSFER TO ..." on the next line and text
    printed above the date both land on the right row.

    A band with no date continues the transaction before it (a row broken
    across pages). A band with several dates (a table with no row spacing)
    falls back to "each line belongs to the dated line above it".
    Parts are returned top to bottom so narration keeps its reading order.
    """
    out: list[tuple[_Draft, list[dict[str, list[str]]]]] = []
    if not rows:
        return out
    gaps = [b[0] - a[0] for a, b in zip(rows, rows[1:]) if b[0] - a[0] > 2]
    line_gap = min(gaps) if gaps else 0.0

    def gap_bands(idx: list[int]) -> list[list[int]]:
        bands: list[list[int]] = [[idx[0]]]
        for a, b in zip(idx, idx[1:]):
            if line_gap and rows[b][0] - rows[a][0] > line_gap * 1.3:
                bands.append([b])
            else:
                bands[-1].append(b)
        return bands

    # Ruled tables (ICICI and others draw a line under every row): the rules are
    # the row boundaries, so a bold title printed above the date stays with its
    # row. Used only when rules really separate the dated rows.
    anchor_tops = [r[0] for r in rows if r[2]]
    ruled = sorted(rules or [])
    separated = sum(1 for a, b in zip(anchor_tops, anchor_tops[1:]) if any(a < y < b for y in ruled))
    if ruled and len(anchor_tops) > 1 and separated >= (len(anchor_tops) - 1) * 0.8:
        by_rule: dict[int, list[int]] = {}
        for i, (top, _, _) in enumerate(rows):
            by_rule.setdefault(sum(1 for y in ruled if y <= top), []).append(i)
        bands = []
        last_anchor_key = max(k for k, idx in by_rule.items() if any(rows[i][2] for i in idx))
        for k in sorted(by_rule):
            if k > last_anchor_key:
                break  # below the rule closing the last row: sign-off, legends, footer
            idx = by_rule[k]
            n_anchor = sum(1 for i in idx if rows[i][2])
            bands.extend([idx] if n_anchor <= 1 else gap_bands(idx))
    else:
        bands = gap_bands(list(range(len(rows))))

    def new_draft(i: int) -> _Draft:
        d = _Draft(rows[i][1].get("date", []), page)
        drafts.append(d)
        return d

    for band in bands:
        anchors = [i for i in band if rows[i][2]]
        if len(anchors) == 1:
            out.append((new_draft(anchors[0]), [rows[i][1] for i in band]))
            continue
        current = drafts[-1] if drafts else None
        pending: list[dict[str, list[str]]] = []
        for i in band:
            if rows[i][2]:
                if current is not None and pending:
                    out.append((current, pending))
                current, pending = new_draft(i), []
            pending.append(rows[i][1])
        if current is not None and pending:
            out.append((current, pending))
    return out


_TXN_AMOUNT_ROLES = ("debit", "credit", "amount")


def _row_has_amount(by_role: dict[str, list[str]]) -> bool:
    return any(parse_amount(tok) for role in _TXN_AMOUNT_ROLES for tok in by_role.get(role, []))


def _has_txn_amount(line: list[Word], colmap: ColumnMap) -> bool:
    return any(colmap.role_of(w) in _TXN_AMOUNT_ROLES and parse_amount(w.text) for w in line)


def _row_mode(rows: list[tuple[float, dict[str, list[str]], bool]]) -> str:
    """'amount_closes' when amounts sit on undated lines more often than on dated ones.

    HSBC prints the date once per day and each transaction's amounts on its last
    line, so several transactions can share one date and the dated line has no
    amount. Everywhere else the dated line carries the amounts.
    """
    dated = sum(1 for _, by_role, is_anchor in rows if is_anchor and _row_has_amount(by_role))
    undated = sum(1 for _, by_role, is_anchor in rows if not is_anchor and _row_has_amount(by_role))
    return "amount_closes" if undated > dated else "bands"


def _close_on_amounts(
    rows: list[tuple[float, dict[str, list[str]], bool]],
    page: int,
    drafts: list[_Draft],
    carry: list[dict[str, list[str]]],
) -> list[tuple[_Draft, list[dict[str, list[str]]]]]:
    """Each line with a debit / credit amount ends a transaction; the lines since
    the previous one are its narration, and its date is the latest date above it.
    Lines after the page's last amount line wait in `carry` for the next page."""
    out: list[tuple[_Draft, list[dict[str, list[str]]]]] = []
    date_tokens = drafts[-1].date_tokens if drafts else []
    for _, by_role, is_anchor in rows:
        if is_anchor:
            date_tokens = by_role.get("date", [])
        carry.append(by_role)
        if _row_has_amount(by_role) and date_tokens:
            d = _Draft(list(date_tokens), page)
            drafts.append(d)
            out.append((d, [{k: v for k, v in r.items() if k != "date"} for r in carry]))
            carry.clear()
    return out


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
