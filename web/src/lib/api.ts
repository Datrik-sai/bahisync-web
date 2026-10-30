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
  counterparty_type?: "merchant" | "person" | "unknown" | "";
  occurrence_count?: number;
  match_key?: string;
  group?: string;
  instrument_no?: string;
  voucher_type: string;
  note?: string;
  /** Accountant's decision: "approved" keeps the row as is; "excluded" leaves it out of the Tally vouchers. */
  review_state?: "" | "approved" | "excluded";
  flags: string[];
};

export type Summary = {
  bank: string;
  account_hint: string;
  pages: number;
  used_ocr: boolean;
  rows_total: number;
  rows_failed: number;
  /** Missing on statements parsed before v0.4. */
  rows_no_balance?: number;
  balance_status?: "verified" | "mismatch" | "partial" | "no_balance";
  balance_verified: boolean;
  opening_balance: string | null;
  closing_balance: string | null;
  total_debit: string;
  total_credit: string;
  warnings: string[];
};

export type Statement = {
  id: string;
  filename: string;
  created_at: number;
  summary: Summary;
  groups: Record<string, string>;
  transactions: Txn[];
  /** Only on the built-in demo statement. */
  sample?: boolean;
  client?: string;
  client_rules?: ClientRules;
  /** Added in the browser at upload: overlaps with this client's earlier statements. */
  upload_warnings?: string[];
};

/** direction:counterparty-key -> [ledger, group], remembered per client in the browser. */
export type ClientRules = Record<string, [string, string]>;

export type LedgerOption = { name: string; group: string };

export const MAX_UPLOAD_MB = 4;

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let code = "error";
  let message = `Request failed (${res.status}).`;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object" && !Array.isArray(d)) {
      code = d.code ?? code;
      message = d.message ?? message;
    }
  } catch {
    if (res.status === 413) {
      code = "too_large";
      message = `This file is over ${MAX_UPLOAD_MB} MB. Split the statement by month and upload each part.`;
    }
  }
  return new ApiError(res.status, code, message);
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

export async function parseStatement(file: File, rules: ClientRules, password?: string): Promise<Statement> {
  const form = new FormData();
  form.append("file", file);
  form.append("filename", file.name);
  form.append("client_rules", JSON.stringify(rules));
  if (password) form.append("password", password);
  return json(await fetch("/api/parse", { method: "POST", body: form }));
}

export async function applyLedger(
  statement: Statement,
  rowNo: number,
  ledger: string,
  group: string,
  applyToSimilar: boolean,
  rules: ClientRules,
): Promise<{ statement: Statement; client_rules: ClientRules; changed_rows: number[] }> {
  return json(
    await fetch("/api/rows/apply", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ statement, row_no: rowNo, ledger, group, apply_to_similar: applyToSimilar, client_rules: rules }),
    }),
  );
}

export async function getHealth(): Promise<{ ok: boolean; ai_enabled: boolean; ocr_enabled: boolean }> {
  return json(await fetch("/api/health"));
}

export async function getLedgers(): Promise<{ ledgers: LedgerOption[]; groups: string[] }> {
  return json(await fetch("/api/ledgers"));
}

export async function joinWaitlist(
  email: string,
  role: string,
  statements: string,
  extra: { banks?: string; tally_version?: string } = {},
): Promise<void> {
  await json(
    await fetch("/api/waitlist", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, role, statements_per_month: statements, ...extra }),
    }),
  );
}

/** Build an export on the server from the browser's copy and save it as a file. */
export async function downloadExport(
  statement: Statement,
  kind: "excel" | "ledgers" | "vouchers" | "package",
  company: string,
  bankLedger: string,
  opts: { educationalMode?: boolean; existingLedgers?: string[] } = {},
): Promise<void> {
  const url = kind === "excel" ? "/api/export/excel" : kind === "package" ? "/api/export/package" : `/api/export/tally/${kind}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      statement,
      company,
      bank_ledger: bankLedger,
      educational_mode: Boolean(opts.educationalMode),
      existing_ledgers: opts.existingLedgers ?? [],
    }),
  });
  if (!res.ok) throw await errorFrom(res);
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  const fallback = { excel: "statement.xlsx", package: "statement_bahisync.zip", ledgers: "statement_tally_ledgers.xml", vouchers: "statement_tally_vouchers.xml" };
  const name = match?.[1] ?? fallback[kind];
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** Client names become stable ids so ledger choices are remembered per client. */
export function clientIdFor(name: string): string {
  const slug = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50);
  return `c-${slug || "default"}`;
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
