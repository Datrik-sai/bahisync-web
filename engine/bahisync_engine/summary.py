"""Printed statement figures outside the transaction table, and the checks
that compare them with what the rows add up to.

Banks print some of: an opening balance above the table, a closing balance
below it, and a summary block with total debits and credits. Two shapes are
read:

  same line   "Opening Balance : 1,84,250.00"   "Total Debits 1,68,195.90"
  two lines   "Opening Balance  Dr Count  Cr Count  Debits  Credits  Closing Bal"
              "1,84,250.00      19        11        ...     ...      2,84,688.10"

A figure that isn't printed is simply missing; nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .layout import _cells, group_lines
from .models import ParseResult
from .pdf_io import PageWords
from .values import parse_amount, parse_date

TOLERANCE = Decimal("0.01")

# label regex -> field. Order matters: "total debit" before a bare "debits".
LABELS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bopening\s+bal(ance)?\b"), "opening"),
    (re.compile(r"(?i)\bclosing\s+bal(ance)?\b"), "closing"),
    (re.compile(r"(?i)\btotal\s+(debits?|withdrawals?)(\s+amount)?\b|^\s*debits\s*$|\bdebits\s*(\(?(inr|rs\.?)\)?)?$"), "total_debit"),
    (re.compile(r"(?i)\btotal\s+(credits?|deposits?)(\s+amount)?\b|^\s*credits\s*$|\bcredits\s*(\(?(inr|rs\.?)\)?)?$"), "total_credit"),
]
COUNT_LABEL = re.compile(r"(?i)\b(dr|cr|debit|credit)\s*count\b")


@dataclass
class PrintedSummary:
    opening: Decimal | None = None
    closing: Decimal | None = None
    total_debit: Decimal | None = None
    total_credit: Decimal | None = None


def _amount(text: str, signed: bool) -> Decimal | None:
    tokens = text.replace("₹", " ").split()
    # Amount and its Dr/Cr suffix may be separate words ("2,84,688.10 Cr").
    for i, tok in enumerate(tokens):
        p = parse_amount(tok)
        if p is None:
            continue
        value, suffix = p
        if suffix is None and i + 1 < len(tokens) and tokens[i + 1].lower().strip(".()") in ("dr", "cr"):
            suffix = tokens[i + 1].lower().strip(".()")
        return -value if (signed and suffix == "dr") else value
    return None


def _field(text: str) -> str | None:
    for pattern, name in LABELS:
        if pattern.search(text):
            return name
    return None


def _starts_with_date(text: str) -> bool:
    first = text.split()[0] if text.split() else ""
    return parse_date(first) is not None


def read_printed_summary(pages: list[PageWords]) -> PrintedSummary:
    """First printed opening; last printed closing and totals (the end-of-statement block)."""
    s = PrintedSummary()
    for pw in pages:
        lines = group_lines(pw.words)
        for i, line in enumerate(lines):
            text = " ".join(w.text for w in line)
            if _starts_with_date(text):
                continue  # a transaction row, even if its narration says "closing balance"
            cells = _cells(line, gap=10.0)
            labelled = [(c, _field(c[0])) for c in cells]
            label_cells = [(c, f) for c, f in labelled if f]
            has_amount = any(parse_amount(tok) for tok in text.split())

            if len(label_cells) + sum(1 for c in cells if COUNT_LABEL.search(c[0])) >= 2 and not has_amount:
                # Two-line summary block: labels here, values on the next line.
                if i + 1 >= len(lines):
                    continue
                values = _cells(lines[i + 1], gap=10.0)
                if _starts_with_date(" ".join(w.text for w in lines[i + 1])):
                    continue
                for (label, x0, x1), f in label_cells:
                    centre = (x0 + x1) / 2
                    best = min(values, key=lambda v: abs((v[1] + v[2]) / 2 - centre), default=None)
                    if best is None or abs((best[1] + best[2]) / 2 - centre) > max(40.0, (x1 - x0)):
                        continue
                    _set(s, f, _amount(best[0], signed=f in ("opening", "closing")))
                continue

            if has_amount:
                # Same line: each label takes the first amount printed after it
                # ("Opening Balance : 1,84,250.00", "Total Debits 1,68,195.90").
                hits = sorted(
                    (m.start(), m.end(), name) for pattern, name in LABELS for m in pattern.finditer(text)
                )
                for k, (start, end, name) in enumerate(hits):
                    stop = hits[k + 1][0] if k + 1 < len(hits) else len(text)
                    # Drop a ":" or a "-" used as a separator ("Balance - 1,000.00"), never a minus sign.
                    rest = re.sub(r"^[\s:]*(?:-\s+)?", "", text[end:stop])
                    _set(s, name, _amount(rest, signed=name in ("opening", "closing")))
    return s


def _set(s: PrintedSummary, f: str, value: Decimal | None) -> None:
    if value is None:
        return
    if f == "opening":
        if s.opening is None:
            s.opening = value
    else:
        setattr(s, f, value)  # later wins: the end-of-statement figure


def reconcile(result: ParseResult, printed: PrintedSummary, derived_opening: Decimal | None) -> list[dict]:
    """Checks shown in the review screen. status: ok | mismatch | not_printed | warning."""
    def fmt(v: Decimal | None) -> str | None:
        return f"{v:.2f}" if v is not None else None

    def compare(name: str, label: str, printed_v: Decimal | None, computed: Decimal | None, note_missing: str) -> dict:
        if printed_v is None or computed is None:
            return {"check": name, "label": label, "printed": fmt(printed_v), "computed": fmt(computed),
                    "status": "not_printed", "note": note_missing}
        ok = abs(printed_v - computed) <= TOLERANCE
        return {"check": name, "label": label, "printed": fmt(printed_v), "computed": fmt(computed),
                "status": "ok" if ok else "mismatch",
                "note": "" if ok else f"Printed {printed_v:.2f} but the rows give {computed:.2f} (difference {printed_v - computed:.2f})."}

    txns = result.transactions
    checks: list[dict] = []
    checks.append(compare(
        "opening", "Opening balance", printed.opening, derived_opening,
        "Not printed: worked out from row 1 (its balance minus its amount), so row 1 can't be checked independently.",
    ))
    opening_used = result.opening_balance
    computed_closing = (opening_used + result.total_credit - result.total_debit) if opening_used is not None and txns else None
    checks.append(compare("closing", "Closing balance", printed.closing, computed_closing,
                          "No closing balance printed to compare with."))
    checks.append(compare("total_debit", "Total debits", printed.total_debit, result.total_debit if txns else None,
                          "No debit total printed to compare with."))
    checks.append(compare("total_credit", "Total credits", printed.total_credit, result.total_credit if txns else None,
                          "No credit total printed to compare with."))
    failed = [t.row_no for t in txns if t.balance_ok is False]
    checks.append({"check": "continuity", "label": "Running balance", "printed": None, "computed": None,
                   "status": "mismatch" if failed else "ok",
                   "note": f"Rows that don't tie: {', '.join(map(str, failed[:20]))}{'…' if len(failed) > 20 else ''}." if failed else "Every printed balance ties to the row before it."})
    missing = [t.row_no for t in txns if t.balance is None]
    checks.append({"check": "missing_balance", "label": "Rows with no balance", "printed": None, "computed": None,
                   "status": "warning" if missing else "ok",
                   "note": f"Rows {', '.join(map(str, missing[:20]))}{'…' if len(missing) > 20 else ''} have no printed balance; the next printed balance is checked against them." if missing else "Every row has a printed balance."})
    return checks
