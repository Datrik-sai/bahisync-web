"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { PdfEvidence } from "@/components/PdfEvidence";
import { PrivacyNote } from "@/components/PrivacyNote";
import { hasPdf, loadPdf } from "@/lib/pdfStore";
import { SiteHeader } from "@/components/Wordmark";
import { downloadExport, formatDate, getLedgers, money, moneyAlways, type ClientRules, type LedgerOption, type Statement, type Txn } from "@/lib/api";
import {
  CASH_BANK_GROUPS,
  SUSPENSE,
  TALLY_GROUPS,
  VOUCHER_TYPES,
  applyChoice,
  applyToRows,
  balanceStatus,
  direction,
  educationalDate,
  isPending,
  oneOffUpiRows,
  prepSummary,
  routeOneOffUpiToSuspense,
  setLedgerGroup,
  setReviewState,
  setVoucherType,
  similarRows,
  unclearRows,
  type ReviewState,
  type VoucherType,
} from "@/lib/applyChoiceClient";
import {
  askedRows,
  clearTallyMasters,
  clientRules,
  exportSettings,
  forgetStatement,
  loadStatement,
  resetSample,
  saveAskedRows,
  saveClientRules,
  saveExportSettings,
  saveStatement,
  saveTallyMasters,
  tallyMasters,
  wipeBrowserData,
} from "@/lib/recent";
import { decodeTallyFile, parseTallyMasters, type TallyLedger } from "@/lib/tallyMasters";
import { WHATSAPP_LINK_LIMIT, buildAskMessage, parseReply, whatsappLink } from "@/lib/whatsapp";

type Filter = "all" | "review" | "suspense" | "mismatch" | "excluded";
type ExportKind = "ledgers" | "vouchers" | "excel" | "package";
type SimilarOffer = { ledger: string; group: string; from: number; rows: Txn[] };

const SOURCE_LABEL: Record<string, string> = {
  client_rule: "Remembered",
  default_rule: "Rule",
  ai: "AI suggestion",
  user: "You",
  party_guess: "From narration",
  suspense: "Unknown",
};

function defaultGroup(t: Txn): string {
  return direction(t) === "credit" ? "Sundry Debtors" : "Sundry Creditors";
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

export function ReviewScreen({ id }: { id: string }) {
  const router = useRouter();
  const [st, setSt] = useState<Statement | null>(null);
  const [clientName, setClientName] = useState("");
  const [clientId, setClientId] = useState("");
  const [rules, setRules] = useState<ClientRules>({});
  const [loadError, setLoadError] = useState("");
  const [defaults, setDefaults] = useState<LedgerOption[]>([]);
  const [masters, setMasters] = useState<TallyLedger[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [similar, setSimilar] = useState<SimilarOffer | null>(null);
  const [similarOpen, setSimilarOpen] = useState(false);
  const [eduPreview, setEduPreview] = useState(false);
  const [pendingExport, setPendingExport] = useState<ExportKind | null>(null);
  const [pdfAvailable, setPdfAvailable] = useState(false);
  const [viewRow, setViewRow] = useState<Txn | null>(null);
  const [notice, setNotice] = useState("");
  const [company, setCompany] = useState("");
  const [bankLedger, setBankLedger] = useState("");
  const [educational, setEducational] = useState(false);
  const [exporting, setExporting] = useState<ExportKind | null>(null);
  const [exportError, setExportError] = useState("");
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    const stored = loadStatement(id);
    if (!stored) {
      setLoadError("gone");
      return;
    }
    const s = stored.statement;
    setSt(s);
    if (s.sample) setPdfAvailable(true);
    else void hasPdf(id).then(setPdfAvailable);
    setClientName(stored.client);
    setClientId(stored.clientId);
    setRules(clientRules(stored.clientId));
    setMasters(tallyMasters(stored.clientId));
    const saved = exportSettings(id);
    setCompany(saved?.company ?? stored.client);
    setEducational(Boolean(saved?.educationalMode));
    const hint = s.summary.account_hint ? ` ${s.summary.account_hint}` : "";
    setBankLedger(saved?.bankLedger ?? `${s.summary.bank === "Unknown bank" ? "Bank" : s.summary.bank}${hint}`);
    getLedgers()
      .then((l) => setDefaults(l.ledgers))
      .catch(() => setNotice("Couldn't load the standard ledger list. You can still type ledger names."));
  }, [id]);

  /** Ledger name -> group, from Tally masters (highest), remembered choices, then defaults. */
  const known = useMemo(() => {
    const m = new Map<string, LedgerOption>();
    for (const o of defaults) m.set(o.name.toLowerCase(), o);
    for (const [name, group] of Object.values(rules)) m.set(name.toLowerCase(), { name, group });
    for (const o of masters) m.set(o.name.toLowerCase(), { name: o.name, group: TALLY_GROUPS.includes(o.group) ? o.group : o.group || SUSPENSE });
    return m;
  }, [defaults, rules, masters]);
  const ledgerList = useMemo(() => [...known.values()].map((o) => o.name).sort((a, b) => a.localeCompare(b)), [known]);
  const masterNames = useMemo(() => new Set(masters.map((m) => m.name.toLowerCase())), [masters]);

  const counts = useMemo(() => {
    const t = st?.transactions ?? [];
    return {
      all: t.length,
      review: t.filter((x) => x.flags.includes("needs_review") && !x.review_state).length,
      suspense: t.filter((x) => x.flags.includes("suspense") && x.review_state !== "excluded").length,
      mismatch: t.filter((x) => x.balance_ok === false).length,
      excluded: t.filter((x) => x.review_state === "excluded").length,
    };
  }, [st]);
  const oneOff = useMemo(() => (st ? oneOffUpiRows(st) : []), [st]);
  const unclear = useMemo(() => (st ? unclearRows(st) : []), [st]);

  const rows = useMemo(() => {
    const t = st?.transactions ?? [];
    if (filter === "review") return t.filter((x) => x.flags.includes("needs_review") && !x.review_state);
    if (filter === "suspense") return t.filter((x) => x.flags.includes("suspense") && x.review_state !== "excluded");
    if (filter === "mismatch") return t.filter((x) => x.balance_ok === false);
    if (filter === "excluded") return t.filter((x) => x.review_state === "excluded");
    return t;
  }, [st, filter]);

  function commit(next: Statement, nextRules?: ClientRules) {
    setSt(next);
    if (!saveStatement({ statement: next, client: clientName, clientId })) {
      setNotice("Your browser's storage is full, so this change won't survive a reload. Download the files now.");
    }
    if (nextRules) {
      setRules(nextRules);
      saveClientRules(clientId, nextRules);
    }
  }

  function groupFor(ledger: string, t: Txn): string {
    const k = known.get(ledger.trim().toLowerCase());
    if (k && TALLY_GROUPS.includes(k.group)) return k.group;
    if (ledger.trim() === t.ledger && t.group) return t.group;
    return defaultGroup(t);
  }

  function setLedger(t: Txn, ledger: string, note?: string) {
    if (!st) return;
    const name = ledger.trim();
    if (!name) return;
    const canonical = known.get(name.toLowerCase())?.name ?? name;
    const group = groupFor(canonical, t);
    const res = applyChoice(st, t.row_no, { ledger: canonical, group, note }, false, rules);
    commit(res.statement, res.rules);
    setNotice(`Set ${canonical} on row ${t.row_no}.`);
    // Similar rows are never changed silently: offer them, and apply only after the accountant has seen the list.
    const more = similarRows(res.statement, t.row_no, canonical);
    setSimilar(more.length ? { ledger: canonical, group: res.statement.transactions.find((x) => x.row_no === t.row_no)?.group ?? group, from: t.row_no, rows: more } : null);
  }

  function applySimilar(rowNos: number[]) {
    if (!st || !similar) return;
    commit(applyToRows(st, rowNos, similar.ledger, similar.group));
    setNotice(`Set ${similar.ledger} on ${plural(rowNos.length, "more row")}.`);
    setSimilar(null);
    setSimilarOpen(false);
  }

  function decide(t: Txn, state: ReviewState) {
    if (!st) return;
    commit(setReviewState(st, [t.row_no], state));
    setNotice(
      state === "excluded"
        ? `Row ${t.row_no} will be left out of the Tally vouchers. Tally's bank balance won't match the statement by ₹${money(Number(t.debit) ? t.debit : t.credit)}.`
        : state === "approved"
          ? `Row ${t.row_no} approved as it is.`
          : `Row ${t.row_no} is back in review.`,
    );
  }

  function setGroup(t: Txn, group: string) {
    if (!st) return;
    const res = setLedgerGroup(st, t.ledger, group, rules);
    commit(res.statement, res.rules);
    setNotice(`${t.ledger} is now under ${group}${res.changed.length > 1 ? ` on all ${res.changed.length} rows that use it` : ""}.`);
  }

  function setVoucher(t: Txn, v: VoucherType) {
    if (!st) return;
    commit(setVoucherType(st, t.row_no, v));
    setNotice(`Row ${t.row_no} is now a ${v} voucher.`);
  }

  function toSuspense(t: Txn) {
    if (!st) return;
    const res = applyChoice(st, t.row_no, { ledger: SUSPENSE, group: SUSPENSE }, false, rules);
    commit(res.statement);
    setNotice(`Row ${t.row_no} sent to Suspense A/c.`);
  }

  function sendOneOffsToSuspense() {
    if (!st) return;
    const res = routeOneOffUpiToSuspense(st);
    commit(res.statement);
    setNotice(`Moved ${plural(res.changed.length, "one-time UPI row")} to Suspense A/c. Ask the client about them on WhatsApp.`);
  }

  async function exportFile(kind: ExportKind) {
    if (!st) return;
    setExporting(kind);
    setExportError("");
    try {
      setPendingExport(null);
      await downloadExport(st, kind, company.trim(), bankLedger.trim(), {
        educationalMode: educational,
        existingLedgers: masters.map((m) => m.name),
      });
    } catch {
      setExportError("Couldn't create the file. Check your connection and try again.");
    } finally {
      setExporting(null);
    }
  }

  function persistExport(next: Partial<{ company: string; bankLedger: string; educationalMode: boolean }>) {
    saveExportSettings(id, { company, bankLedger, educationalMode: educational, ...next });
  }

  async function loadMasters(file: File | undefined) {
    if (!file) return;
    try {
      const list = parseTallyMasters(decodeTallyFile(await file.arrayBuffer()));
      if (list.length === 0) {
        setNotice("No ledgers found in that file. In TallyPrime, export the List of Accounts (masters) as XML.");
        return;
      }
      setMasters(list);
      saveTallyMasters(clientId, list);
      setNotice(`Loaded ${plural(list.length, "ledger")} from Tally for ${clientName || "this client"}. They're suggested first and left out of the masters file.`);
    } catch {
      setNotice("Couldn't read that file. Choose the XML exported from TallyPrime.");
    }
  }

  function removeNow() {
    forgetStatement(id);
    router.push("/app");
  }

  function wipeAll() {
    wipeBrowserData();
    router.push("/app");
  }

  if (loadError) {
    return (
      <>
        <SiteHeader appLink={false} wide />
        <main className="mx-auto max-w-3xl px-5 py-16 sm:px-8">
          <h1 className="text-2xl font-[720]">This statement is no longer in this browser</h1>
          <p className="mt-3 text-ink-soft">
            Reviewed rows are kept only in your browser, for 24 hours or until you delete them. Upload the PDF again to continue.
          </p>
          <Link href="/app" className="mt-6 inline-block rounded-md bg-ink px-5 py-2.5 font-semibold text-white">Upload a statement</Link>
        </main>
      </>
    );
  }

  if (!st) {
    return (
      <>
        <SiteHeader appLink={false} wide />
        <main className="mx-auto max-w-6xl px-5 py-16 text-ink-soft sm:px-8">Loading statement…</main>
      </>
    );
  }

  const s = st.summary;
  const exportReady = Boolean(company.trim() && bankLedger.trim());
  const status = balanceStatus(st);
  const prep = prepSummary(st);
  const mismatchOpen = st.transactions.filter((t) => t.balance_ok === false && !t.review_state).length;
  const suspenseOpen = st.transactions.filter((t) => t.ledger === SUSPENSE && !t.review_state).length;
  const reviewOpen = st.transactions.filter((t) => t.flags.includes("needs_review") && t.ledger !== SUSPENSE && t.balance_ok !== false && !t.review_state).length;
  const excludedRows = st.transactions.filter((t) => t.review_state === "excluded");
  const excludedTotal = excludedRows.reduce((sum, t) => sum + Number(t.credit) - Number(t.debit), 0);
  const checks: Check[] = [
    { ok: Boolean(company.trim()), label: "Company name entered", hard: true },
    { ok: Boolean(bankLedger.trim()), label: "Bank ledger name entered", hard: true },
    status === "mismatch"
      ? { ok: mismatchOpen === 0, label: mismatchOpen ? `${plural(mismatchOpen, "balance mismatch", "balance mismatches")} not checked against the PDF` : "Balance mismatches checked against the PDF" }
      : status === "no_balance"
        ? { ok: false, label: "No balance column: compare totals with the PDF yourself", info: true }
        : status === "partial"
          ? { ok: true, label: `Balance check passed (${plural(s.rows_no_balance ?? 0, "row")} had no balance)` }
          : { ok: true, label: "Every row ties to the running balance" },
    { ok: reviewOpen === 0, label: reviewOpen ? `${plural(reviewOpen, "suggested ledger")} not reviewed yet` : "Suggested ledgers reviewed" },
    { ok: suspenseOpen === 0, label: suspenseOpen ? `${plural(suspenseOpen, "Suspense row")} not approved` : "Suspense rows approved or resolved" },
    { ok: prep.contraProblems === 0, label: prep.contraProblems ? `${plural(prep.contraProblems, "Contra voucher")} without a Bank or Cash ledger` : "Voucher types set" },
  ];
  if (excludedRows.length) {
    checks.push({ ok: false, info: true, label: `${plural(excludedRows.length, "row")} left out: Tally's bank balance will be off by ₹${moneyAlways(String(Math.abs(excludedTotal)))}` });
  }
  const openChecks = checks.filter((c) => !c.ok && !c.hard && !c.info).length;

  function requestExport(kind: ExportKind) {
    if ((kind === "vouchers" || kind === "package") && openChecks > 0) {
      setPendingExport(kind);
      return;
    }
    void exportFile(kind);
  }

  return (
    <>
      <SiteHeader appLink={false} wide />
      <main className="mx-auto max-w-[90rem] px-5 pb-24 sm:px-8">
        {st.sample && (
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ledger bg-ok-bg px-4 py-3 text-sm">
            <p className="text-ok">
              <strong className="font-semibold">Sample statement.</strong> A fictional client, Sri Lakshmi Traders, on HDFC Bank. Correct a ledger,
              try the WhatsApp helper and download the Tally files. Nothing here is real.
            </p>
            <button
              type="button"
              onClick={() => {
                const fresh = resetSample();
                setSt(fresh.statement);
                setRules(clientRules(fresh.clientId));
                setMasters([]);
                setNotice("Sample reset.");
              }}
              className="font-semibold text-ink underline underline-offset-4"
            >
              Reset sample
            </button>
          </div>
        )}

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <Link href="/app" className="text-sm text-ink-soft hover:text-ink">Back to upload</Link>
            <h1 className="mt-1 text-2xl font-[740] tracking-[-0.02em] sm:text-3xl">{st.filename}</h1>
            <p className="mt-1 text-ink-soft">
              {s.bank}
              {s.account_hint && `, account ${s.account_hint}`}
              {clientName && `, for ${clientName}`}
            </p>
          </div>
        </div>

        <StatusPanels status={status} summary={s} prep={prep} />

        <dl className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-rule-strong bg-rule-strong sm:grid-cols-4">
          <Stat label="Opening balance" value={moneyAlways(s.opening_balance)} />
          <Stat label="Total withdrawals" value={moneyAlways(s.total_debit)} />
          <Stat label="Total deposits" value={moneyAlways(s.total_credit)} />
          <Stat label="Closing balance" value={moneyAlways(s.closing_balance)} />
        </dl>

        {(st.upload_warnings ?? []).length > 0 && (
          <div role="alert" className="mt-4 rounded-lg border border-mismatch bg-mismatch-bg px-4 py-3 text-sm text-mismatch">
            <p className="font-semibold">Possible duplicate upload</p>
            <ul className="mt-1 grid gap-1">
              {(st.upload_warnings ?? []).map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}
        {s.warnings.length > 0 && (
          <ul className="mt-4 grid gap-1 text-sm text-review">
            {s.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}

        <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_19rem]">
          <section aria-label="Transactions" className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <div role="tablist" aria-label="Filter rows" className="flex flex-wrap gap-1 rounded-lg border border-rule-strong bg-sheet p-1">
                {([
                  ["all", "All rows"],
                  ["review", "Needs review"],
                  ["suspense", "Suspense"],
                  ["mismatch", "Balance mismatch"],
                  ...(counts.excluded > 0 || filter === "excluded" ? [["excluded", "Left out"]] : []),
                ] as [Filter, string][]).map(([key, label]) => (
                  <button
                    key={key}
                    role="tab"
                    aria-selected={filter === key}
                    onClick={() => setFilter(key)}
                    className={`rounded-md px-3 py-1.5 text-sm font-semibold ${filter === key ? "bg-ink text-white" : "text-ink-soft hover:text-ink"}`}
                  >
                    {label} <span className="tabular-nums opacity-75">{counts[key]}</span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setAsking(true)}
                disabled={unclear.length === 0}
                className="rounded-md bg-ledger px-3.5 py-2 text-sm font-semibold text-white hover:bg-[#25573a] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Request clarification from client <span className="tabular-nums opacity-80">({unclear.length})</span>
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-soft">A ledger you set applies to that row only. Similar rows are offered for you to check first.</p>
              <button
                type="button"
                onClick={sendOneOffsToSuspense}
                disabled={oneOff.length === 0}
                title="One-time UPI payees would each become a new ledger in Tally. Park them in Suspense A/c instead."
                className="rounded-md border border-ink/30 px-3 py-1.5 text-sm font-semibold text-ink hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                Send {oneOff.length} one-time UPI {oneOff.length === 1 ? "name" : "names"} to Suspense A/c
              </button>
            </div>
            <div className="mt-2 flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 text-sm" aria-live="polite">
              <span className="text-ledger">{notice}</span>
              {similar && (
                <span className="text-ink">
                  {plural(similar.rows.length, "similar row")} could also go to {similar.ledger}.{" "}
                  <button type="button" onClick={() => setSimilarOpen(true)} className="font-semibold underline underline-offset-4">
                    Review and apply
                  </button>{" "}
                  <button type="button" onClick={() => setSimilar(null)} className="text-ink-soft underline underline-offset-4">
                    Dismiss
                  </button>
                </span>
              )}
            </div>

            <div className="relative mt-2 overflow-x-auto rounded-lg border border-rule-strong bg-sheet">
              <table className="w-full min-w-[62rem] table-fixed border-collapse text-[0.84rem]">
                <thead>
                  <tr className="border-b border-rule-strong text-left text-ink-soft">
                    <th className="w-10 py-3 pl-4 pr-2 font-semibold">#</th>
                    <th className="w-[5.75rem] px-2 font-semibold">Date</th>
                    <th className="px-2 font-semibold">Narration</th>
                    <th className="w-[6.25rem] px-2 text-right font-semibold">Withdrawal</th>
                    <th className="w-[6.25rem] px-2 text-right font-semibold">Deposit</th>
                    <th className="w-[7.25rem] px-2 text-right font-semibold">Balance</th>
                    <th className="w-[14.5rem] px-2 font-semibold">Ledger and Tally group</th>
                    <th className="w-[7.5rem] px-2 pr-4 font-semibold">Voucher</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <Row
                      key={t.row_no}
                      t={t}
                      inTally={masterNames.has(t.ledger.toLowerCase())}
                      onLedger={setLedger}
                      onGroup={setGroup}
                      onVoucher={setVoucher}
                      onSuspense={toSuspense}
                      onDecide={decide}
                      onView={pdfAvailable && t.evidence?.length ? setViewRow : undefined}
                    />
                  ))}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-10 text-center text-ink-soft">
                        {filter === "all" ? "No rows." : "Nothing here. Every row in this view is sorted."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-ink-faint">
              <Kbd>Tab</Kbd> / <Kbd>↑</Kbd> <Kbd>↓</Kbd> move between ledgers · <Kbd>Enter</Kbd> apply and move down · <Kbd>Alt</Kbd>+<Kbd>S</Kbd> send row to
              Suspense · <Kbd>Alt</Kbd>+<Kbd>C</Kbd> toggle Contra
            </p>
            <datalist id="ledger-options">
              {ledgerList.map((l) => (
                <option key={l} value={l} />
              ))}
            </datalist>
          </section>

          <aside className="h-fit rounded-lg border border-rule-strong bg-sheet p-5 xl:sticky xl:top-6">
            <h2 className="text-lg font-[720]">Download for Tally</h2>

            <div className="mt-4 rounded-md border border-dashed border-rule-strong px-3 py-3 text-sm">
              {masters.length > 0 ? (
                <div className="flex items-start justify-between gap-2">
                  <p className="text-ink-soft">
                    <span className="font-semibold text-ink">{plural(masters.length, "ledger")}</span> loaded from this client's Tally.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      clearTallyMasters(clientId);
                      setMasters([]);
                    }}
                    className="shrink-0 text-xs font-semibold text-ink-soft underline underline-offset-4"
                  >
                    Clear
                  </button>
                </div>
              ) : (
                <label className="block cursor-pointer">
                  <span className="font-semibold text-ink">+ Load existing Tally masters (.xml)</span>
                  <input type="file" accept=".xml,text/xml,application/xml" className="sr-only" onChange={(e) => void loadMasters(e.target.files?.[0])} />
                  <span className="mt-1 block text-xs text-ink-faint">Read in your browser only. Matching ledgers are suggested and not created again.</span>
                </label>
              )}
            </div>

            <label className="mt-4 grid gap-1 text-sm">
              <span className="font-semibold">Company name in Tally</span>
              <input value={company} onChange={(e) => setCompany(e.target.value)} onBlur={() => persistExport({ company })} className="rounded-md border border-rule-strong px-3 py-2" />
            </label>
            <label className="mt-3 grid gap-1 text-sm">
              <span className="font-semibold">Bank ledger name</span>
              <input value={bankLedger} onChange={(e) => setBankLedger(e.target.value)} onBlur={() => persistExport({ bankLedger })} className="rounded-md border border-rule-strong px-3 py-2" />
              <span className="text-ink-faint">Must match the bank ledger in Tally exactly.</span>
            </label>
            <label className="mt-3 flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={educational}
                onChange={(e) => {
                  if (e.target.checked) {
                    setEduPreview(true); // turned on only after the date changes are confirmed
                    return;
                  }
                  setEducational(false);
                  persistExport({ educationalMode: false });
                }}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[#1c2a5a]"
              />
              <span>
                <span className="font-semibold">Tally Educational mode</span>
                <span className="block text-xs text-ink-faint">
                  Free TallyPrime Educational mode only accepts vouchers dated the 1st, 2nd or 31st. Dates move to the 1st or 2nd of the month; the real
                  date is kept in the narration.
                </span>
              </span>
            </label>

            <h3 className="mt-5 text-sm font-semibold">Before you import</h3>
            <ul className="mt-2 grid gap-1.5 text-sm" aria-label="Pre-export checklist">
              {checks.map((c) => (
                <li key={c.label} className={`flex gap-2 ${c.ok ? "text-ink-soft" : c.info ? "text-review" : c.hard ? "text-mismatch" : "text-review"}`}>
                  <span aria-hidden className="w-4 shrink-0 text-center font-bold">{c.ok ? "✓" : "!"}</span>
                  <span>
                    <span className="sr-only">{c.ok ? "Done: " : "Open: "}</span>
                    {c.label}
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-5">
              <DownloadButton
                disabled={!exportReady}
                busy={exporting === "package"}
                onClick={() => requestExport("package")}
                label="Download for Tally (ZIP)"
                primary
              />
              <p className="mt-1 text-xs text-ink-faint">Ledger masters XML, vouchers XML, the Excel sheet and a step-by-step import guide.</p>
            </div>

            {pendingExport && (
              <div role="alertdialog" aria-labelledby="open-checks" className="mt-3 rounded-md border border-review bg-review-bg px-3 py-3 text-sm">
                <p id="open-checks" className="text-review">
                  {plural(openChecks, "check is", "checks are")} still open. Unreviewed rows will import with their suggested ledger, and Suspense rows go to
                  Suspense A/c.
                </p>
                <div className="mt-2 flex gap-3">
                  <button type="button" onClick={() => void exportFile(pendingExport)} className="rounded bg-ink px-3 py-1.5 font-semibold text-white">
                    Download anyway
                  </button>
                  <button type="button" onClick={() => setPendingExport(null)} className="font-semibold text-ink-soft underline underline-offset-4">
                    Keep reviewing
                  </button>
                </div>
              </div>
            )}

            <details className="mt-4 text-sm">
              <summary className="cursor-pointer font-semibold text-ink-soft">Separate files</summary>
              <ol className="mt-3 grid gap-3">
                <li>
                  <DownloadButton disabled={!exportReady} busy={exporting === "ledgers"} onClick={() => requestExport("ledgers")} label="1. Ledger masters (XML)" />
                  <p className="mt-1 text-xs text-ink-faint">
                    In TallyPrime: Import, then Masters. Creates ledgers that don't exist yet{masters.length > 0 ? "; ledgers already in Tally are left out" : ""}.
                  </p>
                </li>
                <li>
                  <DownloadButton disabled={!exportReady} busy={exporting === "vouchers"} onClick={() => requestExport("vouchers")} label="2. Vouchers (XML)" />
                  <p className="mt-1 text-xs text-ink-faint">Then Import, then Transactions. Payment, Receipt and Contra entries; left-out rows are skipped.</p>
                </li>
                <li>
                  <DownloadButton busy={exporting === "excel"} onClick={() => requestExport("excel")} label="Excel sheet" />
                </li>
              </ol>
            </details>
            <p className="mt-2 min-h-5 text-sm text-mismatch" aria-live="polite">{exportError}</p>

            <div className="mt-6 grid gap-2 border-t border-rule pt-4 text-sm text-ink-soft">
              <PrivacyNote compact />
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <button onClick={removeNow} className="font-semibold text-mismatch underline underline-offset-4">Delete this statement</button>
                <button onClick={wipeAll} className="font-semibold text-mismatch underline underline-offset-4">Wipe browser data now</button>
              </div>
            </div>
          </aside>
        </div>
      </main>

      {asking && (
        <AskModal
          statementId={id}
          client={clientName}
          rows={unclear}
          all={st.transactions}
          onApply={(t, ledger, note) => setLedger(t, ledger, note)}
          onClose={() => setAsking(false)}
        />
      )}

      {viewRow && (
        <PdfEvidence
          row={viewRow}
          getPdf={async () => {
            if (!st.sample) return loadPdf(id);
            const res = await fetch("/sample-hdfc.pdf");
            return res.ok ? res.arrayBuffer() : null;
          }}
          onClose={() => setViewRow(null)}
        />
      )}

      {similarOpen && similar && (
        <SimilarModal offer={similar} onApply={applySimilar} onClose={() => setSimilarOpen(false)} />
      )}

      {eduPreview && (
        <EducationalModal
          rows={st.transactions.filter((t) => t.review_state !== "excluded")}
          onConfirm={() => {
            setEducational(true);
            persistExport({ educationalMode: true });
            setEduPreview(false);
            setNotice("Educational mode is on: voucher dates will move as shown, with the real date in each narration.");
          }}
          onClose={() => setEduPreview(false)}
        />
      )}
    </>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-rule-strong bg-paper px-1 py-px font-sans text-[0.7rem] text-ink-soft">{children}</kbd>;
}

type Check = { ok: boolean; label: string; hard?: boolean; info?: boolean };

const STATUS_COPY: Record<string, { title: string; tone: string }> = {
  verified: { title: "Balanced", tone: "border-ledger bg-ok-bg text-ok" },
  partial: { title: "Balanced where printed", tone: "border-ledger bg-ok-bg text-ok" },
  mismatch: { title: "Doesn't tie", tone: "border-mismatch bg-mismatch-bg text-mismatch" },
  no_balance: { title: "Not checkable", tone: "border-review bg-review-bg text-review" },
};

function StatusPanels({ status, summary, prep }: { status: string; summary: Statement["summary"]; prep: ReturnType<typeof prepSummary> }) {
  const copy = STATUS_COPY[status] ?? STATUS_COPY.mismatch;
  const total = summary.rows_total;
  const detail =
    status === "verified"
      ? `All ${total} rows tie to the running balance.`
      : status === "partial"
        ? `${total - (summary.rows_no_balance ?? 0)} rows tie; ${plural(summary.rows_no_balance ?? 0, "row")} had no balance printed to check.`
        : status === "mismatch"
          ? `${summary.rows_failed} of ${total} rows don't tie to the running balance. Check them against the PDF.`
          : "This statement has no balance column, so rows can't be checked. Compare the totals with the PDF.";
  return (
    <div className="mt-6 grid gap-3 md:grid-cols-2">
      <section aria-label="Statement validation" className={`rounded-lg border px-4 py-3 ${copy.tone}`}>
        <h2 className="text-xs font-semibold uppercase tracking-wide opacity-80">Statement validation</h2>
        <p className="mt-0.5 text-lg font-[720]">{copy.title}</p>
        <p className="text-sm">{detail}</p>
      </section>
      <section aria-label="Voucher preparation" className="rounded-lg border border-rule-strong bg-sheet px-4 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Voucher preparation</h2>
        <dl className="mt-1 grid grid-cols-4 gap-2 text-sm">
          <PrepStat label="Mapped" value={prep.mapped} />
          <PrepStat label="To review" value={prep.pending} tone={prep.pending ? "text-review" : ""} />
          <PrepStat label="In Suspense" value={prep.suspense} />
          <PrepStat label="Left out" value={prep.excluded} tone={prep.excluded ? "text-mismatch" : ""} />
        </dl>
      </section>
    </div>
  );
}

function PrepStat({ label, value, tone = "" }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <dt className="text-ink-soft">{label}</dt>
      <dd className={`text-lg font-[720] tabular-nums ${tone}`}>{value}</dd>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-sheet px-4 py-3">
      <dt className="text-sm text-ink-soft">{label}</dt>
      <dd className="amount mt-0.5 text-left text-lg font-[680]">{value}</dd>
    </div>
  );
}

function DownloadButton({
  label,
  onClick,
  disabled,
  busy,
  primary,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  primary?: boolean;
}) {
  const tone = disabled
    ? "cursor-not-allowed border border-rule-strong text-ink-faint"
    : primary
      ? "bg-ink text-white hover:bg-[#121c40]"
      : "border border-ink/30 text-ink hover:border-ink";
  return (
    <button type="button" onClick={onClick} disabled={disabled || busy} className={`block w-full rounded-md px-4 py-2.5 text-center font-semibold ${tone} disabled:opacity-70`}>
      {busy ? "Preparing…" : label}
    </button>
  );
}

function ledgerInputs(): HTMLInputElement[] {
  return [...document.querySelectorAll<HTMLInputElement>("input[data-ledger-input]")];
}

function neighbour(el: HTMLInputElement, step: 1 | -1): HTMLInputElement | undefined {
  const all = ledgerInputs();
  return all[all.indexOf(el) + step];
}

function Row({
  t,
  inTally,
  onLedger,
  onGroup,
  onVoucher,
  onSuspense,
  onDecide,
  onView,
}: {
  t: Txn;
  inTally: boolean;
  onLedger: (t: Txn, ledger: string) => void;
  onGroup: (t: Txn, group: string) => void;
  onVoucher: (t: Txn, v: VoucherType) => void;
  onSuspense: (t: Txn) => void;
  onDecide: (t: Txn, state: ReviewState) => void;
  onView?: (t: Txn) => void;
}) {
  const [value, setValue] = useState(t.ledger);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setValue(t.ledger), [t.ledger]);

  const dirty = value.trim() !== t.ledger && value.trim() !== "";
  const mismatch = t.balance_ok === false;
  const review = t.flags.includes("needs_review");
  const group = t.group || (t.ledger === SUSPENSE ? SUSPENSE : "");
  const contraProblem = t.voucher_type === "Contra" && !CASH_BANK_GROUPS.has(group);
  const ref = [t.instrument_no, t.ref].find((r) => r && !/^0+$/.test(r)) ?? "";

  function commitAndMove(next?: HTMLInputElement) {
    if (dirty) onLedger(t, value);
    // Rows can leave a filtered view once they're sorted; the next input still exists.
    requestAnimationFrame(() => next?.focus());
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    const el = e.currentTarget;
    if (e.altKey && e.code === "KeyS") {
      e.preventDefault();
      onSuspense(t);
      return;
    }
    if (e.altKey && e.code === "KeyC") {
      e.preventDefault();
      onVoucher(t, t.voucher_type === "Contra" ? (direction(t) === "credit" ? "Receipt" : "Payment") : "Contra");
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      commitAndMove(neighbour(el, 1));
      return;
    }
    if (!dirty && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      const next = neighbour(el, e.key === "ArrowDown" ? 1 : -1);
      if (next) {
        e.preventDefault();
        next.focus();
      }
    }
  }

  const excluded = t.review_state === "excluded";
  const pending = isPending(t);
  const approveLabel = mismatch ? "Checked against PDF" : t.ledger === SUSPENSE ? "Keep in Suspense" : "Looks right";
  const rowTone = excluded ? "opacity-60" : mismatch ? "bg-mismatch-bg/60" : review && pending ? "bg-review-bg/40" : "";
  let badge = SOURCE_LABEL[t.ledger_source] ?? "";
  let badgeTitle = badge;
  if (inTally) {
    badge = "In Tally";
    badgeTitle = "Existing Tally ledger";
  } else if (t.flags.includes("small_merchant")) {
    badge = "Small spend";
    badgeTitle = "Small one-time merchant spend, posted to Miscellaneous Expenses";
  } else if (t.flags.includes("one_off") && t.ledger_source === "party_guess") {
    badge = "One-time";
    badgeTitle = "Seen once in this statement: would become a new ledger in Tally";
  }

  return (
    <tr className={`border-b border-rule align-top last:border-b-0 ${rowTone}`}>
      <td className="py-2.5 pl-4 pr-2 text-ink-faint">{t.row_no}</td>
      <td className="whitespace-nowrap px-2 py-2.5 text-ink-soft">{formatDate(t.txn_date)}</td>
      <td className="px-2 py-2.5">
        <span className="block font-medium [overflow-wrap:anywhere]">{t.narration}</span>
        {ref && <span className="mt-0.5 block text-xs text-ink-faint">Ref {ref}</span>}
        {t.note && <span className="mt-0.5 block text-xs text-ledger">Note: {t.note}</span>}
        {onView && (
          <button type="button" onClick={() => onView(t)} className="mt-0.5 text-xs font-semibold text-ink-soft underline underline-offset-2 hover:text-ink">
            View in PDF
          </button>
        )}
      </td>
      <td className={`amount px-2 py-2.5 ${excluded ? "line-through" : ""}`}>{money(t.debit)}</td>
      <td className={`amount px-2 py-2.5 ${excluded ? "line-through" : ""}`}>{money(t.credit)}</td>
      <td className="amount px-2 py-2.5">
        <span className={mismatch ? "font-semibold text-mismatch" : ""}>{moneyAlways(t.balance)}</span>
        {mismatch && <span className="block text-xs text-mismatch">expected {moneyAlways(t.expected_balance)}</span>}
      </td>
      <td className="min-w-0 px-2 py-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            commitAndMove(inputRef.current ? neighbour(inputRef.current, 1) : undefined);
          }}
          className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5"
        >
          <div className="flex min-w-0 gap-1.5">
            <input
              ref={inputRef}
              data-ledger-input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={onKeyDown}
              list="ledger-options"
              aria-label={`Ledger for row ${t.row_no}`}
              className={`w-full min-w-0 flex-1 rounded border bg-sheet px-2 py-1.5 ${t.ledger === SUSPENSE && !dirty ? "border-review text-review" : "border-rule-strong"}`}
            />
            {dirty && (
              <button type="submit" className="rounded bg-ink px-2.5 text-xs font-semibold text-white">
                Apply
              </button>
            )}
          </div>
          <div className="flex min-w-0 items-center gap-1.5">
            <select
              value={TALLY_GROUPS.includes(group) ? group : ""}
              onChange={(e) => onGroup(t, e.target.value)}
              disabled={dirty || t.ledger === SUSPENSE}
              aria-label={`Tally group for ${t.ledger}`}
              className="w-[8.4rem] flex-none rounded-full border border-rule-strong bg-paper px-2 py-0.5 text-xs text-ink disabled:opacity-60"
            >
              {!TALLY_GROUPS.includes(group) && <option value="">Pick group</option>}
              {TALLY_GROUPS.map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
            <span className={`min-w-0 truncate text-xs ${inTally ? "font-semibold text-ledger" : "text-ink-faint"}`} title={badgeTitle}>
              {badge}
            </span>
          </div>
        </form>
        {t.review_state ? (
          <p className={`mt-1.5 text-xs ${excluded ? "font-semibold text-mismatch" : "text-ok"}`}>
            {excluded ? "Left out of Tally" : t.ledger === SUSPENSE ? "Suspense approved" : "Approved"} ·{" "}
            <button type="button" onClick={() => onDecide(t, "")} className="font-normal text-ink-soft underline underline-offset-2">
              Undo
            </button>
          </p>
        ) : (
          (pending || t.ledger === SUSPENSE) && (
            <div className="mt-1.5 flex flex-wrap gap-x-3 text-xs">
              <button type="button" onClick={() => onDecide(t, "approved")} className="font-semibold text-ink underline underline-offset-2">
                {approveLabel}
              </button>
              <button
                type="button"
                onClick={() => onDecide(t, "excluded")}
                title="Skip this row in the vouchers file. Tally's bank balance will then differ from the statement."
                className="text-ink-soft underline underline-offset-2"
              >
                Leave out
              </button>
            </div>
          )
        )}
      </td>
      <td className="px-2 py-2 pr-4">
        <select
          value={VOUCHER_TYPES.includes(t.voucher_type as VoucherType) ? t.voucher_type : direction(t) === "credit" ? "Receipt" : "Payment"}
          onChange={(e) => onVoucher(t, e.target.value as VoucherType)}
          aria-label={`Voucher type for row ${t.row_no}`}
          className="w-full rounded border border-rule-strong bg-sheet py-1.5 pl-1.5 pr-0.5 text-ink"
        >
          {VOUCHER_TYPES.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        {contraProblem && <span className="mt-1 block text-xs text-review">Contra needs a Bank or Cash ledger</span>}
      </td>
    </tr>
  );
}

function AskModal({
  statementId,
  client,
  rows,
  all,
  onApply,
  onClose,
}: {
  statementId: string;
  client: string;
  rows: Txn[];
  all: Txn[];
  onApply: (t: Txn, ledger: string, note: string) => void;
  onClose: () => void;
}) {
  // The numbered list is kept, so a reply still matches its numbers after rows are cleared or the page reloads.
  const [items, setItems] = useState<number[]>(() => {
    const saved = askedRows(statementId);
    if (saved.length) return saved;
    const nums = rows.map((r) => r.row_no);
    saveAskedRows(statementId, nums);
    return nums;
  });
  const current = rows.map((r) => r.row_no).join(",");
  const stale = items.join(",") !== current && rows.length > 0;
  const [reply, setReply] = useState("");
  const [copied, setCopied] = useState(false);
  const [ledgers, setLedgers] = useState<Record<number, string>>({});
  const [done, setDone] = useState<Record<number, boolean>>({});
  const closeRef = useRef<HTMLButtonElement>(null);

  const byNo = useMemo(() => new Map(all.map((t) => [t.row_no, t])), [all]);
  const listed = useMemo(() => items.map((n) => byNo.get(n)).filter((t): t is Txn => Boolean(t)), [items, byNo]);
  const built = useMemo(() => buildAskMessage(client, listed), [client, listed]);
  const [edited, setEdited] = useState<string | null>(null);
  const message = edited ?? built;
  const answers = useMemo(() => parseReply(reply, listed.length), [reply, listed.length]);
  const tooLong = message.length > WHATSAPP_LINK_LIMIT;

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(message);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="ask-title"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-rule-strong bg-sheet p-5 shadow-xl sm:p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="ask-title" className="text-xl font-[720]">Request clarification from {client || "the client"}</h2>
            <p className="mt-1 text-sm text-ink-soft">{plural(listed.length, "unclear row")}: Suspense or needing review. Balance mismatches are left out.</p>
            {stale && (
              <p className="mt-1 text-sm text-review">
                This is the list you sent earlier, so reply numbers still match.{" "}
                <button
                  type="button"
                  className="font-semibold underline underline-offset-4"
                  onClick={() => {
                    const nums = rows.map((r) => r.row_no);
                    saveAskedRows(statementId, nums);
                    setItems(nums);
                    setReply("");
                    setDone({});
                    setEdited(null);
                  }}
                >
                  Start a new list ({rows.length})
                </button>
              </p>
            )}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="rounded px-2 py-1 text-sm font-semibold text-ink-soft hover:text-ink">
            Close
          </button>
        </div>

        <textarea
          value={message}
          onChange={(e) => setEdited(e.target.value)}
          rows={Math.min(14, listed.length + 5)}
          className="mt-4 w-full rounded-md border border-rule-strong bg-paper p-3 font-sans text-sm leading-relaxed"
          aria-label="Message to send"
        />
        <p className="mt-1 text-xs text-ink-faint">
          Edit freely before sending. Keep the item numbers so the client's reply matches the rows.
          {edited !== null && (
            <>
              {" "}
              <button type="button" onClick={() => setEdited(null)} className="font-semibold text-ink-soft underline underline-offset-2">
                Reset message
              </button>
            </>
          )}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => void copy()} className="rounded-md border border-ink/30 px-4 py-2 font-semibold text-ink hover:border-ink">
            {copied ? "Copied" : "Copy message"}
          </button>
          {tooLong ? (
            <span className="text-sm text-review">Too long for a WhatsApp link. Copy it and paste into the chat.</span>
          ) : (
            <a href={whatsappLink(message)} target="_blank" rel="noopener noreferrer" className="rounded-md bg-ledger px-4 py-2 font-semibold text-white hover:bg-[#25573a]">
              Open in WhatsApp
            </a>
          )}
        </div>

        <div className="mt-6 border-t border-rule pt-5">
          <label className="grid gap-1.5 text-sm">
            <span className="font-semibold">Paste the client's reply</span>
            <textarea
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={3}
              placeholder="1 - Customer advance, 2 - Office laptop"
              className="rounded-md border border-rule-strong p-3"
            />
          </label>
          {answers.length > 0 && (
            <ul className="mt-4 grid gap-3">
              {answers.map(({ item, purpose }) => {
                const t = listed[item - 1];
                if (!t) return null;
                const amount = Number(t.credit) > 0 ? t.credit : t.debit;
                return (
                  <li key={item} className="rounded-md border border-rule p-3 text-sm">
                    <p>
                      <span className="font-semibold">{item}.</span> {formatDate(t.txn_date)}, ₹{money(amount)}, {t.counterparty || t.narration.slice(0, 40)}
                    </p>
                    <p className="mt-0.5 text-ledger">Client says: {purpose}</p>
                    {done[item] ? (
                      <p className="mt-2 font-semibold text-ok">Applied to row {t.row_no}, with the client's words as the note.</p>
                    ) : (
                      <form
                        className="mt-2 flex gap-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          const ledger = (ledgers[item] ?? "").trim();
                          if (!ledger) return;
                          onApply(t, ledger, purpose);
                          setDone((d) => ({ ...d, [item]: true }));
                        }}
                      >
                        <input
                          value={ledgers[item] ?? ""}
                          onChange={(e) => setLedgers((l) => ({ ...l, [item]: e.target.value }))}
                          list="ledger-options"
                          placeholder="Ledger, e.g. Customer Advances"
                          aria-label={`Ledger for item ${item}`}
                          className="min-w-0 flex-1 rounded border border-rule-strong px-2 py-1.5"
                        />
                        <button type="submit" className="rounded bg-ink px-3 text-sm font-semibold text-white">Apply</button>
                      </form>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-rule-strong bg-sheet p-5 shadow-xl sm:p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-xl font-[720]">{title}</h2>
          <button ref={closeRef} type="button" onClick={onClose} className="rounded px-2 py-1 text-sm font-semibold text-ink-soft hover:text-ink">
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function SimilarModal({ offer, onApply, onClose }: { offer: SimilarOffer; onApply: (rowNos: number[]) => void; onClose: () => void }) {
  const [picked, setPicked] = useState<Set<number>>(() => new Set(offer.rows.map((t) => t.row_no)));
  function toggle(n: number) {
    setPicked((p) => {
      const next = new Set(p);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  }
  return (
    <Modal title={`Apply ${offer.ledger} to similar rows?`} onClose={onClose}>
      <p className="mt-1 text-sm text-ink-soft">
        Same counterparty and direction as row {offer.from}. Untick any that are different. Rows you've already set yourself aren't listed.
      </p>
      <ul className="mt-4 grid gap-1.5 text-sm">
        {offer.rows.map((t) => (
          <li key={t.row_no}>
            <label className="flex gap-2 rounded border border-rule px-3 py-2">
              <input type="checkbox" checked={picked.has(t.row_no)} onChange={() => toggle(t.row_no)} className="mt-0.5 h-4 w-4 shrink-0 accent-[#1c2a5a]" />
              <span className="min-w-0">
                <span className="tabular-nums text-ink-soft">
                  #{t.row_no} · {formatDate(t.txn_date)} · ₹{money(Number(t.debit) ? t.debit : t.credit)}
                </span>
                <span className="block [overflow-wrap:anywhere]">{t.narration}</span>
                <span className="block text-xs text-ink-faint">Now: {t.ledger || "no ledger"}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex gap-3">
        <button
          type="button"
          disabled={picked.size === 0}
          onClick={() => onApply([...picked])}
          className="rounded-md bg-ink px-4 py-2 font-semibold text-white disabled:opacity-50"
        >
          Apply to {plural(picked.size, "row")}
        </button>
        <button type="button" onClick={onClose} className="font-semibold text-ink-soft underline underline-offset-4">
          Cancel
        </button>
      </div>
    </Modal>
  );
}

function EducationalModal({ rows, onConfirm, onClose }: { rows: Txn[]; onConfirm: () => void; onClose: () => void }) {
  const moved = rows.filter((t) => educationalDate(t.txn_date) !== t.txn_date);
  return (
    <Modal title="Turn on Educational mode?" onClose={onClose}>
      <p className="mt-1 text-sm text-ink-soft">
        TallyPrime Educational mode only accepts vouchers dated the 1st, 2nd or 31st. {plural(moved.length, "voucher")} of {rows.length} will get a
        different date in Tally; the real date goes at the start of the narration. Use this only for practice companies, never for real books.
      </p>
      <div className="mt-4 max-h-80 overflow-y-auto rounded border border-rule">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-ink-soft">
              <th className="px-3 py-2 font-semibold">#</th>
              <th className="px-3 py-2 font-semibold">Statement date</th>
              <th className="px-3 py-2 font-semibold">Date in Tally</th>
            </tr>
          </thead>
          <tbody>
            {moved.map((t) => (
              <tr key={t.row_no} className="border-b border-rule last:border-b-0">
                <td className="px-3 py-1.5 text-ink-faint">{t.row_no}</td>
                <td className="px-3 py-1.5 tabular-nums">{formatDate(t.txn_date)}</td>
                <td className="px-3 py-1.5 tabular-nums font-semibold">{formatDate(educationalDate(t.txn_date))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex gap-3">
        <button type="button" onClick={onConfirm} className="rounded-md bg-ink px-4 py-2 font-semibold text-white">
          Use these dates
        </button>
        <button type="button" onClick={onClose} className="font-semibold text-ink-soft underline underline-offset-4">
          Keep real dates
        </button>
      </div>
    </Modal>
  );
}
