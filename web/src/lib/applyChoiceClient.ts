/**
 * Ledger edits on the review screen, applied in the browser with no network
 * call. This mirrors `apply_user_choice` and `/api/rows/apply` in the engine
 * (engine/bahisync_engine/ledgers.py, engine/service/app.py); keep the two in
 * step. The server endpoint stays for tests and other clients.
 */

import type { ClientRules, Statement, Txn } from "./api";

export const SUSPENSE = "Suspense A/c";
export const CASH = "Cash";
export const CASH_BANK_GROUPS = new Set(["Bank Accounts", "Cash-in-Hand", "Bank OD A/c"]);
export const VOUCHER_TYPES = ["Payment", "Receipt", "Contra"] as const;
export type VoucherType = (typeof VOUCHER_TYPES)[number];

/** TallyPrime's predefined groups most used for bank-statement ledgers. Must match TALLY_GROUPS in the API. */
export const TALLY_GROUPS = [
  "Sundry Creditors",
  "Sundry Debtors",
  "Indirect Expenses",
  "Direct Expenses",
  "Indirect Incomes",
  "Direct Incomes",
  "Duties & Taxes",
  "Suspense A/c",
  "Bank Accounts",
  "Bank OD A/c",
  "Cash-in-Hand",
  "Capital Account",
  "Loans (Liability)",
  "Loans & Advances (Asset)",
  "Current Liabilities",
  "Fixed Assets",
];

const REVIEW_THRESHOLD = 0.75;

export function direction(t: Txn): "credit" | "debit" {
  return Number(t.credit) > 0 ? "credit" : "debit";
}

/** Same key the engine uses for client rules and "apply to similar". */
export function matchKey(t: Txn): string {
  if (t.match_key) return t.match_key;
  const base = t.counterparty ? t.counterparty : t.narration.replace(/\d+/g, "");
  return base.toLowerCase().replace(/[^a-z]/g, "").slice(0, 60);
}

export function ruleKey(t: Txn): string {
  return `${direction(t)}:${matchKey(t)}`;
}

function voucherFor(t: Txn): VoucherType {
  if (t.flags.includes("voucher_set") && (VOUCHER_TYPES as readonly string[]).includes(t.voucher_type)) {
    return t.voucher_type as VoucherType;
  }
  if (t.ledger === CASH || CASH_BANK_GROUPS.has(t.group ?? "")) return "Contra";
  return direction(t) === "credit" ? "Receipt" : "Payment";
}

function refreshFlags(t: Txn): string[] {
  const flags = t.flags.filter((f) => f !== "needs_review" && f !== "suspense");
  if (t.ledger === SUSPENSE) flags.push("suspense");
  if (t.confidence < REVIEW_THRESHOLD || t.balance_ok === false) flags.push("needs_review");
  return flags;
}

/** One row set by the accountant: ledger, group, optional voucher type and note. */
function choose(t: Txn, ledger: string, group: string, voucher?: VoucherType, note?: string): Txn {
  const name = ledger.trim();
  let next: Txn = {
    ...t,
    ledger: name,
    group: name === SUSPENSE ? SUSPENSE : group,
    ledger_source: "user",
    confidence: 1,
    flags: t.flags.filter((f) => f !== "one_off" && f !== "small_merchant"),
  };
  if (note !== undefined) next.note = note.trim();
  if (voucher) {
    next.voucher_type = voucher;
    if (!next.flags.includes("voucher_set")) next.flags = [...next.flags, "voucher_set"];
  }
  next = { ...next, voucher_type: voucherFor(next) };
  next.flags = refreshFlags(next);
  return next;
}

export type ChoiceResult = { statement: Statement; rules: ClientRules; changed: number[] };

export function applyChoice(
  st: Statement,
  rowNo: number,
  choice: { ledger: string; group: string; voucher?: VoucherType; note?: string },
  applyToSimilar: boolean,
  rules: ClientRules,
): ChoiceResult {
  const target = st.transactions.find((t) => t.row_no === rowNo);
  if (!target) return { statement: st, rules, changed: [] };
  const group = TALLY_GROUPS.includes(choice.group) ? choice.group : SUSPENSE;
  const updated = choose(target, choice.ledger, group, choice.voucher, choice.note);
  const changed = [rowNo];
  const key = ruleKey(target);
  const nextRules = { ...rules };
  if (updated.ledger !== SUSPENSE) nextRules[key] = [updated.ledger, updated.group ?? group];

  let txns = st.transactions.map((t) => {
    if (t.row_no === rowNo) return updated;
    if (
      applyToSimilar &&
      updated.ledger !== SUSPENSE &&
      t.ledger_source !== "user" &&
      direction(t) === direction(target) &&
      matchKey(t) === matchKey(target)
    ) {
      changed.push(t.row_no);
      return choose(t, updated.ledger, updated.group ?? group);
    }
    return t;
  });
  // A Tally ledger has one parent group: keep every row on this ledger in step.
  txns = txns.map((t) => (t.ledger === updated.ledger && t.group !== updated.group ? { ...t, group: updated.group, voucher_type: voucherFor({ ...t, group: updated.group }) } : t));
  const groups = { ...st.groups, [updated.ledger]: updated.group ?? group };
  return { statement: { ...st, transactions: txns, groups }, rules: nextRules, changed };
}

/** Change the parent group of a ledger everywhere in the statement. */
export function setLedgerGroup(st: Statement, ledger: string, group: string, rules: ClientRules): ChoiceResult {
  const changed: number[] = [];
  const txns = st.transactions.map((t) => {
    if (t.ledger !== ledger) return t;
    changed.push(t.row_no);
    const next = { ...t, group };
    return { ...next, voucher_type: voucherFor(next) };
  });
  const nextRules: ClientRules = {};
  for (const [k, [l, g]] of Object.entries(rules)) nextRules[k] = l === ledger ? [l, group] : [l, g];
  return { statement: { ...st, transactions: txns, groups: { ...st.groups, [ledger]: group } }, rules: nextRules, changed };
}

/** Switch a row's voucher type without touching its ledger. */
export function setVoucherType(st: Statement, rowNo: number, voucher: VoucherType): Statement {
  return {
    ...st,
    transactions: st.transactions.map((t) =>
      t.row_no === rowNo ? { ...t, voucher_type: voucher, flags: t.flags.includes("voucher_set") ? t.flags : [...t.flags, "voucher_set"] } : t,
    ),
  };
}

/** Rows whose ledger is a one-time UPI name guessed from the narration. */
export function oneOffUpiRows(st: Statement): Txn[] {
  return st.transactions.filter(
    (t) =>
      t.ledger_source === "party_guess" &&
      t.flags.includes("one_off") &&
      !t.flags.includes("small_merchant") &&
      /^UPI/i.test(t.narration.trim()),
  );
}

/** Send every one-time UPI name to Suspense A/c so Tally doesn't get a new ledger for each. */
export function routeOneOffUpiToSuspense(st: Statement): { statement: Statement; changed: number[] } {
  const ids = new Set(oneOffUpiRows(st).map((t) => t.row_no));
  const txns = st.transactions.map((t) => (ids.has(t.row_no) ? choose(t, SUSPENSE, SUSPENSE) : t));
  return { statement: { ...st, transactions: txns, groups: { ...st.groups, [SUSPENSE]: SUSPENSE } }, changed: [...ids] };
}

/**
 * Rows to ask the client about: Suspense or still needing review. Balance
 * mismatches are left out: those are checked against the PDF, not the client.
 */
export function unclearRows(st: Statement): Txn[] {
  return st.transactions.filter(
    (t) => t.balance_ok !== false && (t.flags.includes("suspense") || t.flags.includes("needs_review")),
  );
}
