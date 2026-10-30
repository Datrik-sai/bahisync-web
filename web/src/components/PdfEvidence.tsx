"use client";

import { useEffect, useRef, useState } from "react";

import type { Txn } from "@/lib/api";

type PdfDoc = import("pdfjs-dist").PDFDocumentProxy;

let pdfjsPromise: Promise<typeof import("pdfjs-dist")> | null = null;

/** pdf.js is loaded only when someone opens a row in the PDF. */
function pdfjs() {
  pdfjsPromise ??= import("pdfjs-dist").then((lib) => {
    lib.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
    return lib;
  });
  return pdfjsPromise;
}

/**
 * Shows the page a row is printed on, with the row highlighted. The PDF comes
 * from this browser (or the public sample); nothing is fetched from our server.
 */
export function PdfEvidence({ row, getPdf, onClose }: { row: Txn; getPdf: () => Promise<ArrayBuffer | null>; onClose: () => void }) {
  const [doc, setDoc] = useState<PdfDoc | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "password" | "error">("loading");
  const [password, setPassword] = useState("");
  const [badPassword, setBadPassword] = useState(false);
  const [spanIdx, setSpanIdx] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [mark, setMark] = useState<{ top: number; height: number } | null>(null);
  const evidence = row.evidence ?? [];
  const span = evidence[spanIdx];

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function openDoc(pw?: string) {
    setState("loading");
    const data = await getPdf();
    if (!data) {
      setState("missing");
      return;
    }
    try {
      const lib = await pdfjs();
      const d = await lib.getDocument({ data: new Uint8Array(data), password: pw, isEvalSupported: false }).promise;
      setDoc(d);
      setState("ready");
    } catch (err) {
      if ((err as { name?: string })?.name === "PasswordException") {
        setBadPassword(Boolean(pw));
        setState("password");
      } else {
        setState("error");
      }
    }
  }

  useEffect(() => {
    void openDoc();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => void doc?.destroy(), [doc]);

  useEffect(() => {
    if (!doc || !span || !canvasRef.current || !wrapRef.current) return;
    let cancelled = false;
    let task: { cancel: () => void; promise: Promise<void> } | null = null;
    (async () => {
      const [pageNo, y0, y1] = span;
      if (pageNo < 1 || pageNo > doc.numPages) return;
      const page = await doc.getPage(pageNo);
      const base = page.getViewport({ scale: 1 });
      const width = wrapRef.current?.clientWidth ?? 600;
      const scale = width / base.width;
      const viewport = page.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      const canvas = canvasRef.current;
      if (!canvas || cancelled) return;
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      task = page.render({ canvas, viewport, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] });
      await task.promise.catch(() => undefined);
      if (cancelled) return;
      const pad = 3;
      setMark({ top: (y0 - pad) * scale, height: (y1 - y0 + pad * 2) * scale });
      requestAnimationFrame(() => markRef.current?.scrollIntoView({ block: "center" }));
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, span]);

  const amount = Number(row.credit) > 0 ? `Deposit ${row.credit}` : `Withdrawal ${row.debit}`;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Row ${row.row_no} in the PDF`}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-3xl flex-col border-l border-rule-strong bg-sheet shadow-xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-[720]">Row {row.row_no} in the PDF</h2>
            <p className="truncate text-sm text-ink-soft">
              {amount} · {row.narration}
            </p>
            {evidence.length > 1 && (
              <p className="mt-1 text-sm">
                This row continues across pages:{" "}
                {evidence.map((e, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setSpanIdx(i)}
                    className={`mr-2 underline underline-offset-2 ${i === spanIdx ? "font-semibold text-ink" : "text-ink-soft"}`}
                  >
                    page {e[0]}
                  </button>
                ))}
              </p>
            )}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="rounded px-2 py-1 text-sm font-semibold text-ink-soft hover:text-ink">
            Close
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-paper p-4">
          {state === "loading" && <p className="text-ink-soft">Opening the PDF…</p>}
          {state === "missing" && (
            <p className="text-ink-soft">
              The PDF isn't in this browser any more (it's kept for 24 hours, in the browser it was uploaded from). Upload it again to see rows in place.
            </p>
          )}
          {state === "error" && <p className="text-mismatch">Couldn't open the PDF in the browser.</p>}
          {state === "password" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void openDoc(password);
              }}
              className="grid max-w-sm gap-2"
            >
              <label className="grid gap-1 text-sm">
                <span className="font-semibold">PDF password</span>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus className="rounded-md border border-rule-strong px-3 py-2" />
                <span className="text-ink-faint">{badPassword ? "That password didn't open it." : "Used in this browser to open the file. Not stored."}</span>
              </label>
              <button type="submit" className="justify-self-start rounded-md bg-ink px-4 py-2 font-semibold text-white">
                Open
              </button>
            </form>
          )}
          {state === "ready" && !span && <p className="text-ink-soft">This row has no position recorded. It was parsed before this feature existed.</p>}
          <div ref={wrapRef} className={`relative mx-auto ${state === "ready" && span ? "" : "hidden"}`}>
            <canvas ref={canvasRef} className="block bg-white shadow" />
            {mark && (
              <div
                ref={markRef}
                aria-hidden
                className="pointer-events-none absolute inset-x-0 rounded-sm border-2 border-[#d97706] bg-[#f59e0b]/20"
                style={{ top: mark.top, height: mark.height }}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
