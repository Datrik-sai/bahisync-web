export type Txn = {
  row_no: number;
  txn_date: string;
  narration: string;
  debit: string;
  credit: string;
  balance: string | null;
  ref: string;
  page: number;
  balance_ok: boolean | null;
  expected_balance: string | null;
  ledger: string;
  ledger_source: "client_rule" | "default_rule" | "ai" | "user" | "party_guess" | "suspense" | "";
  confidence: number;
  counterparty: string;
  voucher_type: string;
  flags: string[];
};

export type Summary = {
  bank: string;
  account_hint: string;
  pages: number;
  used_ocr: boolean;
  rows_total: number;
  rows_failed: number;
  balance_verified: boolean;
  opening_balance: string | null;
  closing_balance: string | null;
  total_debit: string;
  total_credit: string;
  warnings: string[];
};

export type Statement = {
  id: string;
  client_id: string;
  filename: string;
  created_at: number;
  expires_in_hours: number;
  summary: Summary;
  groups: Record<string, string>;
  transactions: Txn[];
};

export type LedgerOption = { name: string; group: string };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>;
  let code = "error";
  let message = `Request failed (${res.status}).`;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object") {
      code = d.code ?? code;
      message = d.message ?? message;
    }
  } catch {
    /* non-JSON error */
  }
  throw new ApiError(res.status, code, message);
}

export async function uploadStatement(file: File, clientId: string, password?: string): Promise<Statement> {
  const form = new FormData();
  form.append("file", file);
  form.append("client_id", clientId);
  if (password) form.append("password", password);
  return handle(await fetch("/api/statements", { method: "POST", body: form }));
}

export async function getStatement(id: string): Promise<Statement> {
  return handle(await fetch(`/api/statements/${encodeURIComponent(id)}`, { cache: "no-store" }));
}

export async function updateRow(
  id: string,
  rowNo: number,
  ledger: string,
  group: string,
  applyToSimilar: boolean,
): Promise<Statement & { changed_rows: number[] }> {
  return handle(
    await fetch(`/api/statements/${encodeURIComponent(id)}/rows/${rowNo}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ledger, group, apply_to_similar: applyToSimilar }),
    }),
  );
}

export async function deleteStatement(id: string): Promise<void> {
  await handle(await fetch(`/api/statements/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

export async function getLedgers(clientId: string): Promise<{ ledgers: LedgerOption[]; groups: string[] }> {
  return handle(await fetch(`/api/ledgers?client_id=${encodeURIComponent(clientId)}`, { cache: "no-store" }));
}

export async function joinWaitlist(email: string, role: string, statements: string): Promise<void> {
  await handle(
    await fetch("/api/waitlist", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, role, statements_per_month: statements }),
    }),
  );
}

export function exportUrl(id: string, kind: "excel" | "ledgers" | "vouchers", company: string, bankLedger: string): string {
  const base = `/api/statements/${encodeURIComponent(id)}/export`;
  if (kind === "excel") return `${base}/excel`;
  const q = new URLSearchParams({ kind, company, bank_ledger: bankLedger });
  return `${base}/tally?${q}`;
}

/** Client names become stable ids so ledger choices are remembered per client. */
export function clientIdFor(name: string): string {
  const slug = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50);
  return `c-${slug || "default"}`.padEnd(6, "x");
}

const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function money(v: string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return n === 0 ? "" : inr.format(n);
}
export function moneyAlways(v: string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return inr.format(Number(v));
}

export function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}
