/** "Ask the client" message for unclear rows, and parsing of their reply. */

import { formatDate, type Txn } from "./api";

const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function who(t: Txn): string {
  if (t.counterparty) return t.counterparty.toUpperCase();
  const n = t.narration.replace(/\s+/g, " ").trim();
  return n.length > 48 ? `${n.slice(0, 47)}…` : n;
}

export function buildAskMessage(client: string, rows: Txn[]): string {
  const name = client.trim() || "there";
  const lines = rows.map((t, i) => {
    const received = Number(t.credit) > 0;
    const amount = inr.format(Number(received ? t.credit : t.debit));
    const ref = t.instrument_no || t.ref;
    return `${i + 1}. *${formatDate(t.txn_date)}* — ₹${amount} (${received ? "Received" : "Paid"}) — ${who(t)}${ref ? ` (Ref: ${ref})` : ""} -> ?`;
  });
  return [
    `Hi *${name}*, please confirm what these bank entries are for your Tally accounting:`,
    "",
    ...lines,
    "",
    'Reply with the item number and purpose (e.g. "1 - Customer advance, 2 - Office laptop").',
  ].join("\n");
}

/** wa.me links over ~4,000 characters are unreliable on phones; copy instead. */
export const WHATSAPP_LINK_LIMIT = 4000;

export function whatsappLink(message: string): string {
  return `https://wa.me/?text=${encodeURIComponent(message)}`;
}

export type ReplyItem = { item: number; purpose: string };

/** "1 - Customer advance, 2 - Office laptop" or one item per line. */
export function parseReply(text: string, maxItem: number): ReplyItem[] {
  const out = new Map<number, string>();
  const chunks = text
    .replace(/\r/g, "")
    .split(/\n|[,;](?=\s*\d{1,3}\s*[-–—:.)=])/);
  for (const raw of chunks) {
    const m = /^\s*(?:item\s*)?(\d{1,3})\s*[-–—:.)=]+\s*(.+?)\s*$/i.exec(raw);
    if (!m) continue;
    const item = Number(m[1]);
    if (item >= 1 && item <= maxItem && m[2]) out.set(item, m[2].replace(/^[*_]+|[*_]+$/g, "").trim());
  }
  return [...out.entries()].sort((a, b) => a[0] - b[0]).map(([item, purpose]) => ({ item, purpose }));
}
