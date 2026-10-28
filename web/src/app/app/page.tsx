"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SiteHeader } from "@/components/Wordmark";
import { ApiError, MAX_UPLOAD_MB as MAX_MB, clientIdFor, parseStatement } from "@/lib/api";
import { clientRules, lastClient, recentStatements, saveStatement, setLastClient, type Recent } from "@/lib/recent";

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [client, setClient] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<Recent[]>([]);

  useEffect(() => {
    setClient(lastClient());
    setRecent(recentStatements());
  }, []);

  function pick(f: File | undefined | null) {
    setError("");
    setNeedsPassword(false);
    setPassword("");
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf") && f.type !== "application/pdf") {
      setError("Choose a PDF file. Bank statements downloaded from net banking are usually PDFs.");
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`This file is over ${MAX_MB} MB. Split the statement by month and upload each part.`);
      return;
    }
    setFile(f);
  }

  async function convert(e: React.FormEvent) {
    e.preventDefault();
    if (!client.trim()) {
      setError("Enter the client's name so ledger choices are remembered for them.");
      return;
    }
    if (!file) {
      setError("Choose a statement PDF first.");
      return;
    }
    if (needsPassword && !password) {
      setError("Enter the PDF password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const clientId = clientIdFor(client);
      const st = await parseStatement(file, clientRules(clientId), password || undefined);
      setLastClient(client.trim());
      if (!saveStatement({ statement: st, client: client.trim(), clientId })) {
        setError("Your browser's storage is full or blocked, so the statement can't be kept for review. Clear old site data or leave private mode.");
        setBusy(false);
        return;
      }
      router.push(`/app/review/${st.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "password_required") {
        setNeedsPassword(true);
        setError(password ? "That password didn't open the PDF. Check it and try again." : "This PDF is password-protected. Enter its password to continue.");
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Couldn't reach BahiSync. Check your connection and try again.");
      }
      setBusy(false);
    }
  }

  return (
    <>
      <SiteHeader appLink={false} />
      <main className="mx-auto max-w-3xl px-5 pb-20 pt-6 sm:px-8">
        <h1 className="text-3xl font-[740] tracking-[-0.02em]">Convert a statement</h1>
        <p className="mt-2 text-ink-soft">Upload one bank statement PDF. You'll review the rows before downloading anything.</p>
        <Link
          href="/app/review/sample-hdfc"
          className="mt-4 inline-block rounded-md border border-ledger bg-ok-bg px-4 py-2 font-semibold text-ok hover:border-ok"
        >
          Try instant HDFC sample statement →
        </Link>
        <p className="mt-1 text-sm text-ink-faint">No upload: a fictional client's 30-row statement, ready to review.</p>

        <form onSubmit={convert} className="mt-8 grid gap-6" noValidate>
          <label className="grid gap-1.5">
            <span className="font-semibold">Client</span>
            <input
              value={client}
              onChange={(e) => setClient(e.target.value)}
              placeholder="e.g. Sri Lakshmi Traders"
              className="rounded-md border border-rule-strong bg-sheet px-3 py-2.5"
              autoComplete="organization"
            />
            <span className="text-sm text-ink-faint">Ledger choices you make are remembered for this client next month.</span>
          </label>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pick(e.dataTransfer.files?.[0]);
            }}
            className={`ruled grid place-items-center rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors ${
              dragging ? "border-ink bg-sheet" : "border-rule-strong bg-sheet/70"
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              id="statement-file"
              onChange={(e) => pick(e.target.files?.[0])}
            />
            {file ? (
              <div>
                <p className="font-semibold">{file.name}</p>
                <p className="text-sm text-ink-faint">{(file.size / 1024).toFixed(0)} KB</p>
                <button type="button" onClick={() => inputRef.current?.click()} className="mt-3 text-sm font-semibold text-ink underline underline-offset-4">
                  Choose a different file
                </button>
              </div>
            ) : (
              <div>
                <p className="text-lg font-semibold">Drop the statement PDF here</p>
                <p className="mt-1 text-sm text-ink-soft">
                  The digital PDF from net banking, up to {MAX_MB} MB. Password-protected files work too; scanned PDFs aren't supported yet.
                </p>
                <label htmlFor="statement-file" className="mt-4 inline-block cursor-pointer rounded-md border border-ink/30 bg-sheet px-4 py-2 font-semibold hover:border-ink">
                  Choose file
                </label>
              </div>
            )}
          </div>

          {needsPassword && (
            <label className="grid gap-1.5">
              <span className="font-semibold">PDF password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-md border border-rule-strong bg-sheet px-3 py-2.5"
                autoFocus
              />
              <span className="text-sm text-ink-faint">
                Banks often use part of the customer's name and date of birth. It's used once to open the file and not stored.
              </span>
            </label>
          )}

          <p className="min-h-6 text-mismatch" role="alert" aria-live="polite">{error}</p>

          <div className="flex flex-wrap items-center gap-4">
            <button type="submit" disabled={busy} className="rounded-md bg-ink px-6 py-3 font-semibold text-white hover:bg-[#121c40] disabled:opacity-60">
              {busy ? "Reading and checking rows…" : "Convert statement"}
            </button>
            <span className="text-sm text-ink-faint">The PDF is read in memory and discarded. Reviewed rows stay only in this browser, for 24 hours.</span>
          </div>
        </form>

        {recent.length > 0 && (
          <section className="mt-14">
            <h2 className="text-lg font-[700]">Today's statements</h2>
            <ul className="mt-3 divide-y divide-rule rounded-lg border border-rule-strong bg-sheet">
              {recent.map((r) => (
                <li key={r.id}>
                  <Link href={`/app/review/${r.id}`} className="flex items-center justify-between px-4 py-3 hover:bg-paper">
                    <span className="font-medium">{r.filename}</span>
                    <span className="text-sm text-ink-faint">{r.client}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
    </>
  );
}
