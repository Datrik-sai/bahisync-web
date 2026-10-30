"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";

/**
 * What actually happens to a statement. Keep this accurate: it is a promise.
 * The AI line comes from the API's health check, so it can't drift from the deployment.
 */
export function PrivacyNote({ compact = false }: { compact?: boolean }) {
  const [ai, setAi] = useState<boolean | null>(null);
  useEffect(() => {
    getHealth()
      .then((h) => setAi(h.ai_enabled))
      .catch(() => setAi(null));
  }, []);
  const aiLine =
    ai === true
      ? "AI ledger suggestions are on: narrations and amounts of unmatched rows (not the PDF) are sent to Anthropic's API."
      : ai === false
        ? "AI ledger suggestions are off, so no third-party AI sees your data."
        : "";
  return (
    <div className={`grid gap-1.5 text-sm text-ink-soft ${compact ? "" : "rounded-lg border border-rule bg-sheet px-4 py-3"}`}>
      {!compact && <p className="font-semibold text-ink">What happens to the PDF</p>}
      <p>
        It is sent over HTTPS to the BahiSync server (Vercel, Mumbai region) and read in memory there, including OCR for scanned pages, which runs on
        that server with no outside OCR service. Nothing is written to disk or a database, and the file is discarded once the rows are returned.
      </p>
      <p>The rows, your ledger choices and each client's remembered rules are kept only in this browser. Statements are cleared after 24 hours.</p>
      {aiLine && <p>{aiLine}</p>}
    </div>
  );
}
