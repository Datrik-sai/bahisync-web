"""Optional AI ledger suggestions with the Claude API.

Off unless ANTHROPIC_API_KEY is set. Only narrations, direction and amount
are sent; never account numbers or the PDF. Suggestions are capped at 0.7
confidence so every AI pick still shows up for review.
"""

from __future__ import annotations

import json
import os
import re

import httpx

from .models import Transaction

API_URL = "https://api.anthropic.com/v1/messages"
MAX_AI_CONFIDENCE = 0.7

PROMPT = """You are helping an Indian accountant post bank transactions in TallyPrime.
For each transaction, choose the best ledger. Prefer one of the existing ledgers
when it fits; otherwise propose a short standard ledger name and its TallyPrime
group (one of: Indirect Expenses, Direct Expenses, Indirect Incomes, Direct Incomes,
Sundry Debtors, Sundry Creditors, Duties & Taxes, Loans (Liability), Capital Account,
Fixed Assets, Cash-in-Hand, Bank Accounts, Suspense A/c). If unsure, use "Suspense A/c".

Existing ledgers: {ledgers}

Transactions (id, direction, amount INR, narration):
{rows}

Reply with JSON only: [{{"id": <id>, "ledger": "...", "group": "...", "confidence": 0.0-1.0}}]"""


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def suggest_with_ai(
    txns: list[Transaction],
    existing_ledgers: list[str],
    client: httpx.Client | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Improve suspense / party-guess rows in place. Returns ledger -> group for new ledgers."""
    targets = [t for t in txns if t.ledger_source in ("suspense", "party_guess")]
    if not targets or not enabled():
        return {}
    rows = "\n".join(f"{t.row_no}, {t.direction}, {t.amount:.2f}, {t.narration}" for t in targets[:150])
    body = {
        "model": model or os.environ.get("BAHISYNC_AI_MODEL", "claude-haiku-5-5"),
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": PROMPT.format(ledgers=", ".join(existing_ledgers[:300]) or "none", rows=rows)}],
    }
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    http = client or httpx.Client(timeout=60)
    resp = http.post(API_URL, json=body, headers=headers)
    resp.raise_for_status()
    text = "".join(block.get("text", "") for block in resp.json().get("content", []))
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return {}
    try:
        picks = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}

    by_id = {t.row_no: t for t in targets}
    groups: dict[str, str] = {}
    for p in picks:
        t = by_id.get(p.get("id"))
        ledger = str(p.get("ledger", "")).strip()
        if not t or not ledger or ledger == "Suspense A/c":
            continue
        t.ledger = ledger
        t.ledger_source = "ai"
        t.confidence = min(float(p.get("confidence", 0.5)), MAX_AI_CONFIDENCE)
        groups[ledger] = str(p.get("group") or "Suspense A/c")
        t.flags = [f for f in t.flags if f != "suspense"]
        if "needs_review" not in t.flags:
            t.flags.append("needs_review")
    return groups
