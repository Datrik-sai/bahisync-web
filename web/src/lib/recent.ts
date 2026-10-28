"use client";

/**
 * Browser storage. Statements and remembered ledger rules live only here;
 * the server keeps nothing. Statements are cleared after 24 hours.
 */

import type { ClientRules, Statement } from "./api";
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
  for (const r of all) if (!keep.includes(r)) remove(`bahisync.stmt.${r.id}`);
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

/** Remove everything BahiSync keeps in this browser: statements, rules, masters, settings. */
export function wipeBrowserData() {
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
