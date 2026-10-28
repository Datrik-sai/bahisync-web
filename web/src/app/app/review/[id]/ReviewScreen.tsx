"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { SiteHeader } from "@/components/Wordmark";
import {
  ApiError,
  deleteStatement,
  exportUrl,
  formatDate,
  getLedgers,
  getStatement,
  money,
  moneyAlways,
  updateRow,
  type LedgerOption,
  type Statement,
  type Txn,
} from "@/lib/api";
import { exportSettings, forgetStatement, saveExportSettings } from "@/lib/recent";

type Filter = "all" | "review" | "suspense" | "mismatch";

const SOURCE_LABEL: Record<string, string> = {
  client_rule: "Remembered",
  default_rule: "Rule",
  ai: "AI suggestion",
  user: "You",
  party_guess: "From narration",
  suspense: "Unknown",
};

export function ReviewScreen({ id, clientName }: { id: string; clientName: string }) {
  const router = useRouter();
  const [st, setSt] = useState<Statement | null>(null);
  const [loadError, setLoadError] = useState("");
  const [options, setOptions] = useState<LedgerOption[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [applySimilar, setApplySimilar] = useState(true);
  const [notice, setNotice] = useState("");
  const [company, setCompany] = useState("");
  const [bankLedger, setBankLedger] = useState("");

  useEffect(() => {
    getStatement(id)
      .then((s) => {
        setSt(s);
        const saved = exportSettings(id);
        setCompany(saved?.company ?? clientName);
        const hint = s.summary.account_hint ? ` ${s.summary.account_hint}` : "";
        setBankLedger(saved?.bankLedger ?? `${s.summary.bank === "Unknown bank" ? "Bank" : s.summary.bank}${hint}`);
        return getLedgers(s.client_id);
      })
      .then((l) => {
        setOptions(l.ledgers);
        setGroups(l.groups);
      })
      .catch((e) => setLoadError(e instanceof ApiError && e.status === 404 ? "gone" : "error"));
  }, [id, clientName]);

  const counts = useMemo(() => {
    const t = st?.transactions ?? [];
    return {
      all: t.length,
      review: t.filter((x) => x.flags.includes("needs_review")).length,
      suspense: t.filter((x) => x.flags.includes("suspense")).length,
      mismatch: t.filter((x) => x.balance_ok === false).length,
    };
  }, [st]);

  const rows = useMemo(() => {
    const t = st?.transactions ?? [];
    if (filter === "review") return t.filter((x) => x.flags.includes("needs_review"));
    if (filter === "suspense") return t.filter((x) => x.flags.includes("suspense"));
    if (filter === "mismatch") return t.filter((x) => x.balance_ok === false);
    return t;
  }, [st, filter]);

  async function saveLedger(t: Txn, ledger: string, group: string) {
    try {
      const res = await updateRow(id, t.row_no, ledger, group, applySimilar);
      setSt(res);
      if (!options.some((o) => o.name === ledger)) setOptions((o) => [...o, { name: ledger, group }].sort((a, b) => a.name.localeCompare(b.name)));
      const others = res.changed_rows.length - 1;
      setNotice(others > 0 ? `Set ${ledger} on this row and ${others} similar row${others > 1 ? "s" : ""}.` : `Set ${ledger}.`);
    } catch {
      setNotice("Couldn't save that ledger. Try again.");
    }
  }

  async function removeNow() {
    await deleteStatement(id).catch(() => undefined);
    forgetStatement(id);
    router.push("/app");
  }

  if (loadError) {
    return (
      <>
        <SiteHeader appLink={false} wide />
        <main className="mx-auto max-w-3xl px-5 py-16 sm:px-8">
          <h1 className="text-2xl font-[720]">{loadError === "gone" ? "This statement has been deleted" : "Couldn't load this statement"}</h1>
          <p className="mt-3 text-ink-soft">
            {loadError === "gone"
              ? "Statements are removed 24 hours after upload, or when you delete them. Upload the PDF again to continue."
              : "Check your connection and reload the page."}
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
  const exportReady = company.trim() && bankLedger.trim();
  const ledgerList = options.map((o) => o.name);

  return (
    <>
      <SiteHeader appLink={false} wide />
      <main className="mx-auto max-w-[90rem] px-5 pb-24 sm:px-8">
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
          <BalanceBadge verified={s.balance_verified} failed={s.rows_failed} total={s.rows_total} />
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-rule-strong bg-rule-strong sm:grid-cols-4">
          <Stat label="Opening balance" value={moneyAlways(s.opening_balance)} />
          <Stat label="Total withdrawals" value={moneyAlways(s.total_debit)} />
          <Stat label="Total deposits" value={moneyAlways(s.total_credit)} />
          <Stat label="Closing balance" value={moneyAlways(s.closing_balance)} />
        </dl>

        {s.warnings.length > 0 && (
          <ul className="mt-4 grid gap-1 text-sm text-review">
            {s.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}

        <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_19rem]">
          <section aria-label="Transactions" className="min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div role="tablist" aria-label="Filter rows" className="flex flex-wrap gap-1 rounded-lg border border-rule-strong bg-sheet p-1">
                {([
                  ["all", "All rows"],
                  ["review", "Needs review"],
                  ["suspense", "Suspense"],
                  ["mismatch", "Balance mismatch"],
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
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" checked={applySimilar} onChange={(e) => setApplySimilar(e.target.checked)} className="h-4 w-4 accent-[#1c2a5a]" />
                Apply my choice to similar rows
              </label>
            </div>
            <p className="mt-2 min-h-5 text-sm text-ledger" aria-live="polite">{notice}</p>

            <div className="mt-2 overflow-x-auto rounded-lg border border-rule-strong bg-sheet">
              <table className="w-full min-w-[60rem] table-fixed border-collapse text-[0.84rem]">
                <thead>
                  <tr className="border-b border-rule-strong text-left text-ink-soft">
                    <th className="w-10 py-3 pl-4 pr-2 font-semibold">#</th>
                    <th className="w-[5.75rem] px-2 font-semibold">Date</th>
                    <th className="px-2 font-semibold">Narration</th>
                    <th className="w-[6.5rem] px-2 text-right font-semibold">Withdrawal</th>
                    <th className="w-[6.5rem] px-2 text-right font-semibold">Deposit</th>
                    <th className="w-[7.5rem] px-2 text-right font-semibold">Balance</th>
                    <th className="w-[15rem] px-2 font-semibold">Ledger</th>
                    <th className="w-[4.75rem] pr-4 font-semibold">Voucher</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <Row key={t.row_no} t={t} ledgerList={ledgerList} options={options} groups={groups} onSave={saveLedger} />
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
            <datalist id="ledger-options">
              {ledgerList.map((l) => (
                <option key={l} value={l} />
              ))}
            </datalist>
          </section>

          <aside className="h-fit rounded-lg border border-rule-strong bg-sheet p-5 xl:sticky xl:top-6">
            <h2 className="text-lg font-[720]">Download for Tally</h2>
            <label className="mt-4 grid gap-1 text-sm">
              <span className="font-semibold">Company name in Tally</span>
              <input value={company} onChange={(e) => setCompany(e.target.value)} onBlur={() => saveExportSettings(id, { company, bankLedger })} className="rounded-md border border-rule-strong px-3 py-2" />
            </label>
            <label className="mt-3 grid gap-1 text-sm">
              <span className="font-semibold">Bank ledger name</span>
              <input value={bankLedger} onChange={(e) => setBankLedger(e.target.value)} onBlur={() => saveExportSettings(id, { company, bankLedger })} className="rounded-md border border-rule-strong px-3 py-2" />
              <span className="text-ink-faint">Must match the bank ledger in Tally exactly.</span>
            </label>

            {counts.suspense > 0 && (
              <p className="mt-4 rounded-md bg-review-bg px-3 py-2 text-sm text-review">
                {counts.suspense} row{counts.suspense > 1 ? "s" : ""} will be posted to Suspense A/c unless you pick a ledger.
              </p>
            )}
            {counts.mismatch > 0 && (
              <p className="mt-3 rounded-md bg-mismatch-bg px-3 py-2 text-sm text-mismatch">
                {counts.mismatch} row{counts.mismatch > 1 ? "s don't" : " doesn't"} tie to the balance. Check them against the PDF before importing.
              </p>
            )}

            <ol className="mt-5 grid gap-3">
              <li>
                <DownloadLink disabled={!exportReady} href={exportUrl(id, "ledgers", company, bankLedger)} label="1. Ledger masters (XML)" />
                <p className="mt-1 text-xs text-ink-faint">In TallyPrime: Import, then Masters. Creates any ledger that doesn't exist yet.</p>
              </li>
              <li>
                <DownloadLink disabled={!exportReady} href={exportUrl(id, "vouchers", company, bankLedger)} label="2. Vouchers (XML)" primary />
                <p className="mt-1 text-xs text-ink-faint">Then Import, then Transactions. Payment, Receipt and Contra entries.</p>
              </li>
              <li>
                <DownloadLink href={exportUrl(id, "excel", company, bankLedger)} label="Excel sheet" />
              </li>
            </ol>

            <div className="mt-6 border-t border-rule pt-4 text-sm text-ink-soft">
              <p>This statement is deleted automatically 24 hours after upload.</p>
              <button onClick={removeNow} className="mt-2 font-semibold text-mismatch underline underline-offset-4">Delete it now</button>
            </div>
          </aside>
        </div>
      </main>
    </>
  );
}

function BalanceBadge({ verified, failed, total }: { verified: boolean; failed: number; total: number }) {
  if (verified) {
    return (
      <p className="rounded-md border border-ledger bg-ok-bg px-4 py-2.5 font-semibold text-ok">
        Balanced: all {total} rows tie to the running balance
      </p>
    );
  }
  return (
    <p className="rounded-md border border-mismatch bg-mismatch-bg px-4 py-2.5 font-semibold text-mismatch">
      {failed} of {total} rows don't tie. Review them before importing
    </p>
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

function DownloadLink({ href, label, disabled, primary }: { href: string; label: string; disabled?: boolean; primary?: boolean }) {
  const base = "block rounded-md px-4 py-2.5 text-center font-semibold";
  if (disabled) {
    return <span className={`${base} cursor-not-allowed border border-rule-strong text-ink-faint`} aria-disabled>{label}</span>;
  }
  return (
    <a href={href} download className={`${base} ${primary ? "bg-ink text-white hover:bg-[#121c40]" : "border border-ink/30 text-ink hover:border-ink"}`}>
      {label}
    </a>
  );
}

function Row({
  t,
  ledgerList,
  options,
  groups,
  onSave,
}: {
  t: Txn;
  ledgerList: string[];
  options: LedgerOption[];
  groups: string[];
  onSave: (t: Txn, ledger: string, group: string) => Promise<void>;
}) {
  const [value, setValue] = useState(t.ledger);
  const [group, setGroup] = useState(t.credit !== "0.00" ? "Sundry Debtors" : "Sundry Creditors");
  const [saving, setSaving] = useState(false);

  useEffect(() => setValue(t.ledger), [t.ledger]);

  const isNew = value.trim() !== "" && !ledgerList.includes(value.trim());
  const dirty = value.trim() !== t.ledger && value.trim() !== "";
  const mismatch = t.balance_ok === false;
  const review = t.flags.includes("needs_review");

  async function save() {
    if (!dirty) return;
    setSaving(true);
    const known = options.find((o) => o.name === value.trim());
    await onSave(t, value.trim(), known ? known.group : group);
    setSaving(false);
  }

  const rowTone = mismatch ? "bg-mismatch-bg/60" : review ? "bg-review-bg/40" : "";

  return (
    <tr className={`border-b border-rule align-top last:border-b-0 ${rowTone}`}>
      <td className="py-2.5 pl-4 pr-2 text-ink-faint">{t.row_no}</td>
      <td className="whitespace-nowrap px-2 py-2.5 text-ink-soft">{formatDate(t.txn_date)}</td>
      <td className="px-2 py-2.5">
        <span className="block font-medium [overflow-wrap:anywhere]">{t.narration}</span>
        {t.ref && <span className="mt-0.5 block text-xs text-ink-faint">Ref {t.ref}</span>}
      </td>
      <td className="amount px-2 py-2.5">{money(t.debit)}</td>
      <td className="amount px-2 py-2.5">{money(t.credit)}</td>
      <td className="amount px-2 py-2.5">
        <span className={mismatch ? "font-semibold text-mismatch" : ""}>{moneyAlways(t.balance)}</span>
        {mismatch && <span className="block text-xs text-mismatch">expected {moneyAlways(t.expected_balance)}</span>}
      </td>
      <td className="px-2 py-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
          className="grid gap-1.5"
        >
          <div className="flex gap-1.5">
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              list="ledger-options"
              aria-label={`Ledger for row ${t.row_no}`}
              className={`min-w-0 flex-1 rounded border px-2 py-1.5 ${t.ledger === "Suspense A/c" && !dirty ? "border-review text-review" : "border-rule-strong"}`}
            />
            {dirty && (
              <button type="submit" disabled={saving} className="rounded bg-ink px-2.5 text-xs font-semibold text-white disabled:opacity-60">
                {saving ? "Saving" : "Save"}
              </button>
            )}
          </div>
          {dirty && isNew ? (
            <label className="flex items-center gap-1.5 text-xs text-ink-soft">
              New ledger under
              <select value={group} onChange={(e) => setGroup(e.target.value)} className="rounded border border-rule-strong px-1 py-0.5 text-ink">
                {groups.map((g) => (
                  <option key={g}>{g}</option>
                ))}
              </select>
            </label>
          ) : (
            <span className="text-xs text-ink-faint">{SOURCE_LABEL[t.ledger_source] ?? ""}</span>
          )}
        </form>
      </td>
      <td className="py-2.5 pr-4 text-ink-soft">{t.voucher_type}</td>
    </tr>
  );
}
