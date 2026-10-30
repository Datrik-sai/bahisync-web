import Link from "next/link";

import { LedgerStrip } from "@/components/LedgerStrip";
import { WaitlistForm } from "@/components/WaitlistForm";
import { SiteHeader, Wordmark } from "@/components/Wordmark";

const STEPS = [
  {
    title: "Upload the PDF",
    body: "A statement PDF with a column header (Date, Narration, Debit, Credit, Balance), including password-protected ones. Scanned PDFs are read with OCR, so check their flagged rows.",
  },
  { title: "Every row is checked", body: "Each row is added to the previous balance. If it doesn't land on the printed balance, it's flagged." },
  {
    title: "Review only what's flagged",
    body: "Ledgers come from your past choices for that client and your existing Tally masters. Unclear rows go to the client on WhatsApp in one message.",
  },
  {
    title: "Import into Tally",
    body: "A short checklist, then one ZIP: ledger masters and vouchers XML, an Excel sheet and a step-by-step import guide.",
  },
];

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="mx-auto max-w-6xl px-5 pb-16 pt-10 sm:px-8 sm:pt-16">
          <div className="max-w-3xl">
            <h1 className="text-[2.4rem] font-[760] leading-[1.06] tracking-[-0.03em] sm:text-[3.6rem]">
              Bank statement PDF to Tally vouchers, balance-checked.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-soft">
              Upload a statement and BahiSync reads every row, proves it against the running balance, and suggests
              ledgers from the choices you made last month. You get a file Tally imports directly.
            </p>
            <p className="mt-3 text-sm text-ink-faint">The sample is a fictional client's 30-row HDFC statement: no upload, no sign-up.</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/app/review/sample-hdfc" className="rounded-md bg-ink px-5 py-3 font-semibold text-white hover:bg-[#121c40]">
                See a sample statement →
              </Link>
              <Link href="/app" className="rounded-md border border-ink/30 bg-sheet px-5 py-3 font-semibold text-ink hover:border-ink">
                Upload your own PDF
              </Link>
              <a href="#waitlist" className="px-2 py-3 font-semibold text-ink underline underline-offset-4">
                Join the waitlist
              </a>
            </div>
          </div>
          <div className="mt-12">
            <LedgerStrip />
            <p className="mt-3 text-sm text-ink-faint">Sample rows. Each tick means the row ties to the balance printed by the bank.</p>
          </div>
        </section>

        <section id="how" className="border-y border-rule-strong bg-sheet">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
            <h2 className="text-2xl font-[720] tracking-[-0.02em] sm:text-3xl">How it works</h2>
            <ol className="mt-10 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((s, i) => (
                <li key={s.title} className="border-t-2 border-ledger pt-4">
                  <span className="text-sm font-semibold text-ledger">Step {i + 1}</span>
                  <h3 className="mt-1 text-lg font-[680]">{s.title}</h3>
                  <p className="mt-2 leading-relaxed text-ink-soft">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto grid max-w-6xl gap-10 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_1.1fr] lg:items-center">
          <div>
            <h2 className="text-2xl font-[720] tracking-[-0.02em] sm:text-3xl">Why the balance check matters</h2>
            <p className="mt-4 max-w-xl leading-relaxed text-ink-soft">
              Converters that only read text can drop a row, swap a debit for a credit, or misread a digit, and you find
              out at reconciliation. BahiSync does the sum for every row. When the statement balances from opening to
              closing, every amount and every direction has been read correctly.
            </p>
          </div>
          <div className="rounded-lg border border-rule-strong bg-sheet p-6 text-[0.95rem]">
            <dl className="grid grid-cols-[1fr_auto] gap-y-2">
              <dt className="text-ink-soft">Previous balance</dt>
              <dd className="amount">48,210.00</dd>
              <dt className="text-ink-soft">Add deposit</dt>
              <dd className="amount">36,400.00</dd>
              <dt className="text-ink-soft">Less withdrawal</dt>
              <dd className="amount">0.00</dd>
              <dt className="border-t border-rule-strong pt-2 font-semibold">Expected balance</dt>
              <dd className="amount border-t border-rule-strong pt-2 font-semibold">84,610.00</dd>
              <dt className="text-ink-soft">Printed by the bank</dt>
              <dd className="amount">84,610.00</dd>
            </dl>
            <p className="mt-4 rounded-md bg-ok-bg px-3 py-2 font-semibold text-ok">Row ties</p>
            <p className="mt-3 text-sm text-ink-faint">If the two numbers differ, the row is marked in red for you to check.</p>
          </div>
        </section>

        <section id="banks" className="mx-auto max-w-6xl px-5 pb-16 sm:px-8">
          <h2 className="text-2xl font-[720] tracking-[-0.02em] sm:text-3xl">Banks tested so far</h2>
          <p className="mt-3 max-w-2xl leading-relaxed text-ink-soft">
            BahiSync reads the column header rather than using a template per bank, so other layouts often work too. This is what we have actually
            checked. If your bank isn't here, try the PDF: rows that don't tie are flagged, never hidden.
          </p>
          <div className="mt-8 grid gap-6 md:grid-cols-2 md:items-start">
            <div className="rounded-lg border border-ledger bg-sheet p-5">
              <h3 className="font-[680]">Real statements, fully balanced</h3>
              <ul className="mt-3 grid gap-2 text-ink-soft">
                <li><span className="font-semibold text-ink">State Bank of India</span>: net-banking PDF, 200+ rows</li>
                <li><span className="font-semibold text-ink">ICICI Bank</span>: net-banking transaction history</li>
                <li><span className="font-semibold text-ink">IndusInd Bank</span>: account statement PDF</li>
                <li><span className="font-semibold text-ink">HSBC India</span>: scanned e-statement, read with OCR</li>
              </ul>
            </div>
            <div className="rounded-lg border border-rule-strong bg-sheet p-5">
              <h3 className="font-[680]">Synthetic layouts in our test suite</h3>
              <ul className="mt-3 grid gap-2 text-ink-soft">
                <li><span className="font-semibold text-ink">HDFC Bank, Axis Bank, Kotak Mahindra Bank</span>: modelled on their PDF layouts</li>
                <li><span className="font-semibold text-ink">Regional rural (gramin) banks</span>: long statements with page totals and carried-forward lines</li>
                <li><span className="font-semibold text-ink">Single Amount + Dr/Cr columns</span>, newest-first order, password-protected PDFs</li>
              </ul>
              <p className="mt-3 text-sm text-ink-faint">Synthetic means generated to match the layout, not a customer's statement.</p>
            </div>
          </div>
        </section>

        <section id="data" className="border-y border-rule-strong bg-sheet">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
            <h2 className="text-2xl font-[720] tracking-[-0.02em] sm:text-3xl">Your clients' data</h2>
            <ul className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <li>
                <h3 className="font-[680]">Read in memory, then discarded</h3>
                <p className="mt-1.5 leading-relaxed text-ink-soft">
                  The PDF goes over HTTPS to our server (Vercel, Mumbai region), is read in memory, including OCR for scans, and is discarded. No
                  outside OCR or AI service sees it, and there is no database of statements.
                </p>
              </li>
              <li>
                <h3 className="font-[680]">Browser-only cache</h3>
                <p className="mt-1.5 leading-relaxed text-ink-soft">
                  Reviewed rows stay in your own browser's local storage for 24 hours so a refresh doesn't lose work. Wipe them any time with one click.
                </p>
              </li>
              <li>
                <h3 className="font-[680]">No bank logins, ever</h3>
                <p className="mt-1.5 leading-relaxed text-ink-soft">We only need the statement. We never ask for net-banking credentials.</p>
              </li>
              <li>
                <h3 className="font-[680]">Your ledger choices stay with you</h3>
                <p className="mt-1.5 leading-relaxed text-ink-soft">
                  Counterparty-to-ledger choices and loaded Tally masters are saved per client in your browser, so next month is faster. View, export,
                  import or delete them under Clients & rules.
                </p>
              </li>
            </ul>
          </div>
        </section>

        <section id="pricing" className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
          <h2 className="text-2xl font-[720] tracking-[-0.02em] sm:text-3xl">Early access pricing</h2>
          <div className="mt-8 grid gap-6 md:grid-cols-3">
            <PriceCard
              name="7-Day Catch-Up Pass"
              price="₹49"
              unit=""
              body="Up to 50 pages across multiple statements. First 3 statements free. Built for full-year client ITR and audit catch-up."
            />
            <PriceCard
              name="Prepaid Practice Pack"
              price="₹299"
              unit=""
              body="300 pages, credits never expire. Includes remembered client ledger rules and the WhatsApp Suspense helper."
            />
            <PriceCard
              name="CA Practice Monthly"
              price="₹499"
              unit=" / month"
              featured
              body="Up to 1,500 pages a month, unlimited clients, Tally masters matching and priority support for new bank layouts."
            />
          </div>
          <p className="mt-4 text-sm text-ink-faint">Early-access prices. Payments aren't live yet: join the waitlist below.</p>
        </section>

        <section id="waitlist" className="border-t border-rule-strong bg-sheet">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
            <h2 className="text-2xl font-[720] tracking-[-0.02em] sm:text-3xl">Get early access</h2>
            <p className="mt-3 max-w-2xl leading-relaxed text-ink-soft">
              We're opening to a small group of accountants first. Tell us a little about your work.
            </p>
            <div className="mt-8 max-w-4xl">
              <WaitlistForm />
            </div>
          </div>
        </section>
      </main>
      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-10 text-sm text-ink-faint sm:px-8">
        <Wordmark />
        <p>Tally and TallyPrime are trademarks of Tally Solutions. BahiSync is not affiliated with Tally Solutions.</p>
      </footer>
    </>
  );
}

function PriceCard({ name, price, unit, body, featured }: { name: string; price: string; unit: string; body: string; featured?: boolean }) {
  return (
    <div className={`rounded-lg bg-sheet p-6 ${featured ? "border-2 border-ink" : "border border-rule-strong"}`}>
      <h3 className="text-lg font-[680]">{name}</h3>
      <p className="mt-3 text-3xl font-[740]">
        {price}
        {unit && <span className="text-base font-normal text-ink-soft">{unit}</span>}
      </p>
      <p className="mt-3 leading-relaxed text-ink-soft">{body}</p>
    </div>
  );
}
