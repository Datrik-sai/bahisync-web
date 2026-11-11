/**
 * Browser mirror of engine/bahisync_engine/opening.py: when a statement's opening
 * balance may become the bank ledger's opening balance in Tally. The server
 * enforces the same rule; change both together.
 */

/** 1 April of the Indian financial year the statement falls in (YYYY-MM-DD). */
export function defaultBooksBegin(firstIso: string): string {
  const [y, m] = firstIso.split("-").map(Number);
  return `${m >= 4 ? y : y - 1}-04-01`;
}

/** The statement starts in the books' first month, on or after the books-beginning date. */
export function startsAtBooksBegin(firstIso: string, booksIso: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(booksIso)) return false;
  return firstIso >= booksIso && firstIso.slice(0, 7) === booksIso.slice(0, 7);
}

/** "184250.00" -> "₹1,84,250.00 Dr"; negative = overdraft (Cr); zero = nil. */
export function drCr(balance: string): string {
  const v = Number(balance);
  if (!v) return "₹0.00 (nil)";
  const s = Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `₹${s} ${v > 0 ? "Dr" : "Cr"}`;
}
