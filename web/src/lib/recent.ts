"use client";

/** Per-browser conveniences: recent statements and the last client used. */

export type Recent = { id: string; filename: string; client: string; created_at: number };

const KEY = "bahisync.recent";
const CLIENT_KEY = "bahisync.lastClient";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: private mode etc. */
  }
}

export function recentStatements(): Recent[] {
  const day = 24 * 3600;
  const now = Date.now() / 1000;
  return read<Recent[]>(KEY, []).filter((r) => now - r.created_at < day);
}

export function rememberStatement(r: Recent) {
  write(KEY, [r, ...recentStatements().filter((x) => x.id !== r.id)].slice(0, 20));
}

export function forgetStatement(id: string) {
  write(KEY, recentStatements().filter((x) => x.id !== id));
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
