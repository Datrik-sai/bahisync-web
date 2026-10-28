"use client";

/**
 * Browser storage. Statements and remembered ledger rules live only here;
 * the server keeps nothing. Statements are cleared after 24 hours.
 */

import type { ClientRules, Statement } from "./api";

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

export function loadStatement(id: string): StoredStatement | null {
  recentStatements();
  return read<StoredStatement | null>(`bahisync.stmt.${id}`, null);
}

export function forgetStatement(id: string) {
  remove(`bahisync.stmt.${id}`);
  remove(`bahisync.export.${id}`);
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

export function exportSettings(id: string): { company: string; bankLedger: string } | null {
  return read<{ company: string; bankLedger: string } | null>(`bahisync.export.${id}`, null);
}

export function saveExportSettings(id: string, s: { company: string; bankLedger: string }) {
  write(`bahisync.export.${id}`, s);
}
