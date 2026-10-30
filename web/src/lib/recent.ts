"use client";

/**
 * Browser storage. Statements and remembered ledger rules live only here;
 * the server keeps nothing. Statements are cleared after 24 hours.
 */

import type { ClientRules, Statement } from "./api";
import { clearPdfs, deletePdf } from "./pdfStore";
import sample from "./sample-hdfc.json";
import type { TallyLedger } from "./tallyMasters";

export type Recent = { id: string; filename: string; client: string; created_at: number };
export type StoredStatement = { statement: Statement; client: string; clientId: string };

const DAY = 24 * 3600;
const INDEX = "bahisync.recent";
const CLIENT_KEY = "bahisync.lastClient";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function remove(key: string) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/** Drop statements older than 24 hours; returns the ones still valid. */
export function recentStatements(): Recent[] {
  const now = Date.now() / 1000;
  const all = read<Recent[]>(INDEX, []);
  const keep = all.filter((r) => now - r.created_at < DAY);
  for (const r of all) {
    if (keep.includes(r)) continue;
    remove(`bahisync.stmt.${r.id}`);
    void deletePdf(r.id);
  }
  if (keep.length !== all.length) write(INDEX, keep);
  return keep;
}

export function saveStatement(s: StoredStatement): boolean {
  const ok = write(`bahisync.stmt.${s.statement.id}`, s);
  const entry: Recent = { id: s.statement.id, filename: s.statement.filename, client: s.client, created_at: s.statement.created_at };
  write(INDEX, [entry, ...recentStatements().filter((x) => x.id !== entry.id)].slice(0, 20));
  return ok;
}

export const SAMPLE_ID = "sample-hdfc";
export const SAMPLE_CLIENT_ID = "c-sample-sri-lakshmi-traders";

/** The built-in demo statement, fresh: no upload, nothing sent anywhere. */
export function freshSample(): StoredStatement {
  const st = { ...(sample as unknown as Statement), created_at: Date.now() / 1000 };
  return { statement: st, client: st.client ?? "Sri Lakshmi Traders", clientId: SAMPLE_CLIENT_ID };
}

export function loadStatement(id: string): StoredStatement | null {
  recentStatements();
  const stored = read<StoredStatement | null>(`bahisync.stmt.${id}`, null);
  if (stored || id !== SAMPLE_ID) return stored;
  // First visit to the demo: seed it, with last month's remembered rules for this client.
  const s = freshSample();
  write(`bahisync.rules.${SAMPLE_CLIENT_ID}`, s.statement.client_rules ?? {});
  rememberClient(SAMPLE_CLIENT_ID, s.client);
  saveStatement(s);
  return s;
}

export function resetSample(): StoredStatement {
  forgetStatement(SAMPLE_ID);
  remove(`bahisync.rules.${SAMPLE_CLIENT_ID}`);
  remove(`bahisync.masters.${SAMPLE_CLIENT_ID}`);
  return loadStatement(SAMPLE_ID) as StoredStatement;
}

export function forgetStatement(id: string) {
  void deletePdf(id);
  remove(`bahisync.stmt.${id}`);
  remove(`bahisync.export.${id}`);
  remove(`bahisync.ask.${id}`);
  write(INDEX, read<Recent[]>(INDEX, []).filter((x) => x.id !== id));
}

export function clientRules(clientId: string): ClientRules {
  return read<ClientRules>(`bahisync.rules.${clientId}`, {});
}

export function saveClientRules(clientId: string, rules: ClientRules) {
  write(`bahisync.rules.${clientId}`, rules);
}

export function lastClient(): string {
  return read<string>(CLIENT_KEY, "");
}

export function setLastClient(name: string) {
  write(CLIENT_KEY, name);
}

export type ExportSettings = { company: string; bankLedger: string; educationalMode?: boolean };

export function exportSettings(id: string): ExportSettings | null {
  return read<ExportSettings | null>(`bahisync.export.${id}`, null);
}

export function saveExportSettings(id: string, s: ExportSettings) {
  write(`bahisync.export.${id}`, s);
}

/** Ledgers from the client's own Tally (their masters XML), kept per client. */
export function tallyMasters(clientId: string): TallyLedger[] {
  return read<TallyLedger[]>(`bahisync.masters.${clientId}`, []);
}

export function saveTallyMasters(clientId: string, ledgers: TallyLedger[]): boolean {
  return write(`bahisync.masters.${clientId}`, ledgers);
}

export function clearTallyMasters(clientId: string) {
  remove(`bahisync.masters.${clientId}`);
}

/** Row numbers sent to the client on WhatsApp, in message order, so a reply can be matched later. */
export function askedRows(id: string): number[] {
  return read<number[]>(`bahisync.ask.${id}`, []);
}

export function saveAskedRows(id: string, rows: number[]) {
  write(`bahisync.ask.${id}`, rows);
}

// ---------------------------------------------------------------- clients

const CLIENTS = "bahisync.clients";

export type ClientInfo = { id: string; name: string; rules: number; masters: number; history: HistoryEntry[] };

export function rememberClient(id: string, name: string) {
  const all = read<Record<string, string>>(CLIENTS, {});
  if (all[id] !== name) write(CLIENTS, { ...all, [id]: name });
}

function storageKeys(prefix: string): string[] {
  const keys: string[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) keys.push(k);
    }
  } catch {
    /* storage blocked */
  }
  return keys;
}

/** Every client this browser knows: named ones, plus any with remembered rules, masters or history. */
export function listClients(): ClientInfo[] {
  const names = read<Record<string, string>>(CLIENTS, {});
  const ids = new Set(Object.keys(names));
  for (const prefix of ["bahisync.rules.", "bahisync.masters.", "bahisync.history."]) {
    for (const k of storageKeys(prefix)) ids.add(k.slice(prefix.length));
  }
  return [...ids]
    .map((id) => ({
      id,
      name: names[id] ?? id.replace(/^c-/, "").replace(/-/g, " "),
      rules: Object.keys(clientRules(id)).length,
      masters: tallyMasters(id).length,
      history: statementHistory(id),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Forget a client: remembered rules, Tally masters, upload history and its name. Today's statements stay. */
export function deleteClient(id: string) {
  remove(`bahisync.rules.${id}`);
  remove(`bahisync.masters.${id}`);
  remove(`bahisync.history.${id}`);
  const names = read<Record<string, string>>(CLIENTS, {});
  delete names[id];
  write(CLIENTS, names);
}

export type RulesFile = { format: "bahisync-rules"; version: 1; client: string; exported_at: string; rules: ClientRules };

export function rulesFile(id: string, name: string): RulesFile {
  return { format: "bahisync-rules", version: 1, client: name, exported_at: new Date().toISOString(), rules: clientRules(id) };
}

/** Validate an imported rules file and merge it into the client's rules. Returns how many were added or changed. */
export function importRules(id: string, data: unknown): number {
  const f = data as Partial<RulesFile> | null;
  if (!f || f.format !== "bahisync-rules" || typeof f.rules !== "object" || f.rules === null) {
    throw new Error("Not a BahiSync rules file.");
  }
  const current = clientRules(id);
  let changed = 0;
  for (const [k, v] of Object.entries(f.rules).slice(0, 5000)) {
    if (!/^(credit|debit):/.test(k) || !Array.isArray(v) || v.length !== 2) continue;
    const pair: [string, string] = [String(v[0]).slice(0, 120), String(v[1]).slice(0, 60)];
    if (!pair[0].trim()) continue;
    if (current[k]?.[0] !== pair[0] || current[k]?.[1] !== pair[1]) changed++;
    current[k] = pair;
  }
  saveClientRules(id, current);
  return changed;
}

// ---------------------------------------------------- overlap / duplicates

/**
 * A short record of each statement uploaded for a client (kept after the
 * statement itself expires), so a second upload of the same period is caught.
 * Rows are kept as hashes of date, amounts and balance, not their text.
 */
export type HistoryEntry = { id: string; filename: string; account: string; from: string; to: string; rows: number; at: number; keys: string[] };

function fnv(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

function rowKeys(st: Statement): string[] {
  return st.transactions.map((t) => fnv(`${t.txn_date}|${t.debit}|${t.credit}|${t.balance ?? ""}`));
}

export function statementHistory(clientId: string): HistoryEntry[] {
  return read<HistoryEntry[]>(`bahisync.history.${clientId}`, []);
}

function span(st: Statement): [string, string] {
  const dates = st.transactions.map((t) => t.txn_date).sort();
  return [dates[0] ?? "", dates[dates.length - 1] ?? ""];
}

function ddmm(iso: string) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

/** Warnings when this statement overlaps one already uploaded for the client (same account). */
export function overlapWarnings(clientId: string, st: Statement): string[] {
  const [from, to] = span(st);
  const keys = rowKeys(st);
  const out: string[] = [];
  for (const h of statementHistory(clientId)) {
    if (h.id === st.id) continue;
    const sameAccount = !h.account || !st.summary.account_hint || h.account === st.summary.account_hint;
    if (!sameAccount || h.to < from || h.from > to) continue;
    const seen = new Set(h.keys);
    const dup = keys.filter((k) => seen.has(k)).length;
    const when = new Date(h.at * 1000).toLocaleDateString("en-IN");
    out.push(
      dup > 0
        ? `${dup} of ${st.transactions.length} rows also appear in ${h.filename} (${ddmm(h.from)} to ${ddmm(h.to)}), uploaded ${when}. Importing both would post them twice in Tally: leave the repeated rows out or skip this file.`
        : `The dates overlap ${h.filename} (${ddmm(h.from)} to ${ddmm(h.to)}), uploaded ${when}, but no identical rows were found.`,
    );
  }
  return out;
}

export function recordHistory(clientId: string, st: Statement) {
  const [from, to] = span(st);
  const entry: HistoryEntry = { id: st.id, filename: st.filename, account: st.summary.account_hint, from, to, rows: st.transactions.length, at: st.created_at, keys: rowKeys(st) };
  const rest = statementHistory(clientId).filter((h) => h.id !== st.id);
  write(`bahisync.history.${clientId}`, [entry, ...rest].slice(0, 24));
}

/** Remove everything BahiSync keeps in this browser: statements, rules, masters, settings. */
export function wipeBrowserData() {
  void clearPdfs();
  try {
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("bahisync.")) keys.push(k);
    }
    for (const k of keys) localStorage.removeItem(k);
  } catch {
    /* storage blocked: nothing to wipe */
  }
}
