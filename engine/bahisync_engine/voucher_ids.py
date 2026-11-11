"""Deterministic voucher identifiers (Tally REMOTEID), so that importing the same
transaction again can update the voucher instead of creating a second one.

The ID depends only on what the bank printed, never on BahiSync's choices
(ledger, group, voucher type, note), so reclassifying a row keeps its ID.

  account   bank + last four digits of the account, else the bank ledger name
  with a usable bank reference (UTR / RRN / cheque no.):
            account | REF | reference | date | direction | amount
  without one:
            account | TXT | date | direction | amount | normalised narration
  then the position among rows with the same key, in statement order (so two
  genuine, identical payments on the same day get different IDs, and the same
  two rows get the same IDs again from an overlapping statement that contains
  that whole day).

NOT YET VERIFIED in TallyPrime: whether a re-import with the same REMOTEID
alters the voucher rather than creating a duplicate. See the Tally test kit
(tests/fixtures/make_tally_kit.py). Don't describe exports as duplicate-safe
until that test passes.
"""

from __future__ import annotations

import re
import uuid

from .models import Transaction

# Fixed namespace: changing it changes every ID ever exported.
NAMESPACE = uuid.UUID("6f1d6c2e-8a8e-4b7a-9a43-3d2b1f0c5a77")


def account_identity(bank: str, account_hint: str, bank_ledger: str) -> str:
    if account_hint:
        return f"{bank.strip().upper()}|{account_hint.strip().upper()}"
    return f"LEDGER|{bank_ledger.strip().upper()}"


def usable_reference(ref: str) -> str | None:
    """A bank reference good enough to identify a transaction: at least 6
    letters/digits and not one repeated character ("000000" is a placeholder)."""
    r = re.sub(r"[^A-Za-z0-9]", "", ref or "").upper()
    if len(r) < 6 or len(set(r)) == 1:
        return None
    return r


def normalise_narration(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _base_key(account: str, t: Transaction) -> str:
    amount = f"{t.amount:.2f}"
    ref = usable_reference(t.instrument_no or t.ref)
    if ref:
        return f"{account}|REF|{ref}|{t.txn_date.isoformat()}|{t.direction}|{amount}"
    return f"{account}|TXT|{t.txn_date.isoformat()}|{t.direction}|{amount}|{normalise_narration(t.narration)}"


def voucher_ids(txns: list[Transaction], account: str) -> dict[int, str]:
    """row_no -> REMOTEID for every row (including ones that won't be exported,
    so leaving a row out never shifts another row's ID)."""
    seen: dict[str, int] = {}
    out: dict[int, str] = {}
    for t in txns:
        key = _base_key(account, t)
        seen[key] = seen.get(key, 0) + 1
        out[t.row_no] = str(uuid.uuid5(NAMESPACE, f"{key}|{seen[key]}"))
    return out
