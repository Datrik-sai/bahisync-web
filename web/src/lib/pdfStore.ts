"use client";

/**
 * The uploaded PDF, kept in this browser (IndexedDB) next to its statement so a
 * row can be shown where it is printed. Never sent anywhere again; cleared with
 * the statement after 24 hours, on "Delete this statement" and on "Wipe browser data".
 */

const DB = "bahisync";
const STORE = "pdfs";
const DAY_MS = 24 * 3600 * 1000;

type Entry = { id: string; at: number; data: Blob };

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("no IndexedDB"));
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

export async function savePdf(id: string, data: Blob): Promise<boolean> {
  try {
    await purgeOldPdfs();
    await run("readwrite", (s) => s.put({ id, at: Date.now(), data } satisfies Entry));
    return true;
  } catch {
    return false;
  }
}

export async function loadPdf(id: string): Promise<ArrayBuffer | null> {
  try {
    const e = (await run("readonly", (s) => s.get(id))) as Entry | undefined;
    if (!e || Date.now() - e.at > DAY_MS) return null;
    return await e.data.arrayBuffer();
  } catch {
    return null;
  }
}

export async function hasPdf(id: string): Promise<boolean> {
  try {
    const key = await run("readonly", (s) => s.getKey(id));
    return key !== undefined;
  } catch {
    return false;
  }
}

export async function deletePdf(id: string): Promise<void> {
  try {
    await run("readwrite", (s) => s.delete(id));
  } catch {
    /* nothing stored */
  }
}

export async function purgeOldPdfs(): Promise<void> {
  try {
    const all = (await run("readonly", (s) => s.getAll())) as Entry[];
    for (const e of all) if (Date.now() - e.at > DAY_MS) await deletePdf(e.id);
  } catch {
    /* ignore */
  }
}

export async function clearPdfs(): Promise<void> {
  try {
    await run("readwrite", (s) => s.clear());
  } catch {
    /* ignore */
  }
}
