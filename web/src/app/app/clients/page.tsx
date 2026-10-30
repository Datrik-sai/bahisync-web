"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SiteHeader } from "@/components/Wordmark";
import { clientRules, deleteClient, importRules, listClients, rulesFile, saveClientRules, type ClientInfo } from "@/lib/recent";

function formatIso(iso: string) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function download(name: string, data: unknown) {
  const href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientInfo[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const refresh = () => setClients(listClients());
  useEffect(refresh, []);

  async function onImport(c: ClientInfo, file: File | undefined) {
    if (!file) return;
    try {
      const n = importRules(c.id, JSON.parse(await file.text()));
      setNotice(`Imported into ${c.name}: ${n} rule${n === 1 ? "" : "s"} added or changed.`);
      refresh();
    } catch {
      setNotice("That file isn't a BahiSync rules export. Use a file downloaded from this page.");
    }
  }

  function removeRule(c: ClientInfo, key: string) {
    const rules = clientRules(c.id);
    delete rules[key];
    saveClientRules(c.id, rules);
    refresh();
  }

  return (
    <>
      <SiteHeader appLink={false} />
      <main className="mx-auto max-w-4xl px-5 pb-20 pt-6 sm:px-8">
        <Link href="/app" className="text-sm text-ink-soft hover:text-ink">Back to upload</Link>
        <h1 className="mt-1 text-3xl font-[740] tracking-[-0.02em]">Clients & rules</h1>
        <p className="mt-2 max-w-2xl text-ink-soft">
          What this browser remembers for each client: the ledger rules learned from your corrections, Tally masters you loaded, and the periods
          you've uploaded (used to warn about duplicates). It's kept only here. Export a client's rules to move them to another computer.
        </p>
        <p className="mt-3 min-h-6 text-sm text-ledger" aria-live="polite">{notice}</p>

        {clients.length === 0 ? (
          <p className="mt-6 rounded-lg border border-rule-strong bg-sheet px-4 py-8 text-center text-ink-soft">
            No clients yet. They appear here after you convert a statement.
          </p>
        ) : (
          <ul className="mt-4 grid gap-4">
            {clients.map((c) => {
              const rules = Object.entries(clientRules(c.id)).sort((a, b) => a[1][0].localeCompare(b[1][0]));
              return (
                <li key={c.id} className="rounded-lg border border-rule-strong bg-sheet p-4 sm:p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-lg font-[720] [overflow-wrap:anywhere]">{c.name}</h2>
                      <p className="text-sm text-ink-soft">
                        {c.rules} remembered rule{c.rules === 1 ? "" : "s"} · {c.masters} Tally ledger{c.masters === 1 ? "" : "s"} loaded ·{" "}
                        {c.history.length} upload{c.history.length === 1 ? "" : "s"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-sm">
                      <button
                        type="button"
                        onClick={() => setOpen(open === c.id ? null : c.id)}
                        aria-expanded={open === c.id}
                        className="rounded-md border border-ink/30 px-3 py-1.5 font-semibold hover:border-ink"
                      >
                        {open === c.id ? "Hide" : "View rules"}
                      </button>
                      <button
                        type="button"
                        onClick={() => download(`bahisync-rules-${c.id.replace(/^c-/, "")}.json`, rulesFile(c.id, c.name))}
                        disabled={c.rules === 0}
                        className="rounded-md border border-ink/30 px-3 py-1.5 font-semibold hover:border-ink disabled:opacity-50"
                      >
                        Export rules
                      </button>
                      <label className="cursor-pointer rounded-md border border-ink/30 px-3 py-1.5 font-semibold hover:border-ink">
                        Import rules
                        <input
                          type="file"
                          accept="application/json,.json"
                          className="sr-only"
                          onChange={(e) => {
                            void onImport(c, e.target.files?.[0]);
                            e.target.value = "";
                          }}
                        />
                      </label>
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(c.id)}
                        className="rounded-md px-3 py-1.5 font-semibold text-mismatch underline underline-offset-4"
                      >
                        Delete client
                      </button>
                    </div>
                  </div>

                  {confirmDelete === c.id && (
                    <div role="alertdialog" aria-label={`Delete ${c.name}`} className="mt-3 rounded-md border border-mismatch bg-mismatch-bg px-3 py-3 text-sm text-mismatch">
                      <p>
                        Forget {c.name}'s rules, Tally masters and upload history in this browser? Export the rules first if you'll need them. This can't be
                        undone.
                      </p>
                      <div className="mt-2 flex gap-3">
                        <button
                          type="button"
                          onClick={() => {
                            deleteClient(c.id);
                            setConfirmDelete(null);
                            setNotice(`Deleted ${c.name} from this browser.`);
                            refresh();
                          }}
                          className="rounded bg-mismatch px-3 py-1.5 font-semibold text-white"
                        >
                          Delete
                        </button>
                        <button type="button" onClick={() => setConfirmDelete(null)} className="font-semibold text-ink-soft underline underline-offset-4">
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {open === c.id && (
                    <div className="mt-4 grid gap-4">
                      {rules.length === 0 ? (
                        <p className="text-sm text-ink-soft">No remembered rules yet. They're learned when you set a ledger on the review screen.</p>
                      ) : (
                        <div className="overflow-x-auto rounded border border-rule">
                          <table className="w-full min-w-[34rem] text-sm">
                            <thead>
                              <tr className="border-b border-rule text-left text-ink-soft">
                                <th className="px-3 py-2 font-semibold">When the narration matches</th>
                                <th className="px-3 py-2 font-semibold">Ledger</th>
                                <th className="px-3 py-2 font-semibold">Tally group</th>
                                <th className="px-3 py-2" />
                              </tr>
                            </thead>
                            <tbody>
                              {rules.map(([key, [ledger, group]]) => {
                                const [dir, match] = key.split(":");
                                return (
                                  <tr key={key} className="border-b border-rule last:border-b-0">
                                    <td className="px-3 py-1.5">
                                      <span className="text-ink-faint">{dir === "credit" ? "Money in" : "Money out"} · </span>
                                      <span className="font-mono text-xs [overflow-wrap:anywhere]">{match}</span>
                                    </td>
                                    <td className="px-3 py-1.5 font-medium">{ledger}</td>
                                    <td className="px-3 py-1.5 text-ink-soft">{group}</td>
                                    <td className="px-3 py-1.5 text-right">
                                      <button type="button" onClick={() => removeRule(c, key)} className="text-xs font-semibold text-mismatch underline underline-offset-2">
                                        Remove
                                      </button>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {c.history.length > 0 && (
                        <div>
                          <h3 className="text-sm font-semibold">Uploaded periods</h3>
                          <ul className="mt-1 grid gap-0.5 text-sm text-ink-soft">
                            {c.history.map((h) => (
                              <li key={h.id}>
                                {formatIso(h.from)} to {formatIso(h.to)} · {h.rows} rows · {h.filename}
                                {h.account && ` · ${h.account}`}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </main>
    </>
  );
}
