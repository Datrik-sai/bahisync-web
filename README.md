# BahiSync

Bank statement PDF → TallyPrime vouchers, with every row checked against the running balance.

**Live:** site https://bahisync-web.vercel.app · API https://bahisync-api.vercel.app/api/health
(Vercel, region bom1; every push to `main` redeploys both projects.)

## What works today (v0.3)

- **Any layout with a column header:** the parser finds Date / Narration / Debit / Credit / Balance
  (and ~60 synonyms) instead of using per-bank templates. Tested on synthetic statements modelled on
  SBI, HDFC, ICICI, Axis and Kotak layouts.
- **Password-protected PDFs:** the password is asked for, used once and never stored.
- **Scanned and image-only PDFs:** OCR with RapidOCR (works on Vercel, up to 12 pages a file), Tesseract as
  a fallback. Tested on a real HSBC e-statement, which has no text layer.
- **Balance check:** each row must equal previous balance + credit − debit. Newest-first statements
  are detected and reordered. Single "Amount + Dr/Cr" columns and "Cr/Dr" balance suffixes are handled.
- **Ledger suggestions:** remembered per client from your corrections, then built-in rules (ATM/cash,
  GST, TDS, bank charges, interest, electricity, rent, insurance…), optional AI, then the counterparty
  name from UPI/NEFT/IMPS/cheque narrations, else Suspense A/c.
- **Review screen:** "Statement validation" (balance check, including statements with no balance column)
  is shown separately from "Voucher preparation" (mapped / to review / Suspense / left out). A correction
  applies to its row only; similar rows are offered in a preview to confirm. Flagged rows can be approved
  (e.g. "Keep in Suspense") or left out of the vouchers, with a warning that Tally's balance will differ.
- **Exports:** one ZIP (ledger masters XML, vouchers XML, Excel and a HOW-TO-IMPORT guide) behind a
  pre-export checklist; separate files are still available.
- **Privacy:** the server is stateless. PDFs go over HTTPS to the API (Vercel, bom1), are read in memory,
  including OCR, and discarded; the extracted rows and remembered ledgers live only in the user's browser
  (statements cleared after 24 hours). The on-screen privacy note reads `ai_enabled` from `/api/health`.
- **Clients & rules** (`/app/clients`): view, remove, export and import each client's remembered rules,
  delete a client. Each upload is recorded per client (period + row hashes, no text), and a second upload
  covering the same rows of the same account is flagged as a possible duplicate.
- **Long statements:** repeated headers, Page Total, Carried / Brought Forward and dated summary rows are
  skipped; the opening balance is derived from row 1 when it isn't printed. Regional rural banks are
  detected by name, not by their sponsor bank's IFSC.
- **UPI awareness:** P2M (merchant) vs P2A (person), how often each counterparty appears, and the
  RRN / UTR / cheque number, which goes into Tally's bank allocation. One-time UPI names can be sent to
  Suspense A/c in one click; small one-time merchant spends go to Miscellaneous Expenses.
- **Review screen:** instant edits in the browser, Tally group and voucher type per row, keyboard
  shortcuts, client's existing Tally masters loaded from their XML, and a WhatsApp message listing unclear
  rows with a box to paste the client's reply.
- **TallyPrime Educational mode** export option (dates moved to the 1st / 2nd, real date kept in the narration),
  turned on only after previewing every date change.
- **Sample statement** at `/app/review/sample-hdfc`, no upload needed (its synthetic PDF is `web/public/sample-hdfc.pdf`).
- **See the row in the PDF:** every row carries `evidence` ([page, top, bottom] in PDF points, text and OCR
  alike). The uploaded PDF is kept in the browser's IndexedDB for 24 hours (`web/src/lib/pdfStore.ts`) and
  "View in PDF" renders that page with pdf.js, the row highlighted. Password-protected PDFs ask for the
  password again in the browser; it isn't stored.
- **Landing page + waitlist** for the validation phase: sample-first, an honest "banks tested" list, and
  the waitlist asks which banks clients use and their Tally version.

## Run it

```bash
# Engine + API
cd engine
pip install -r requirements-dev.txt     # also needs tesseract-ocr and poppler-utils for scans
python -m pytest -q                     # 69 tests
uvicorn service.app:app --reload --port 8000

# Web (new terminal)
cd web
npm install
npm run dev                             # http://localhost:3000
```

Or everything with Docker: `docker compose up --build`.

Generate sample PDFs to try: `cd engine && python -m tests.fixtures.make_statements`
(writes to `engine/tests/fixtures/out/`; the password-protected one uses `SAI1990`).

Concierge mode (process a customer's file by hand):
`python -m bahisync_engine.cli statement.pdf --password XXXX --company "Client Co" --bank-ledger "HDFC Bank"`

## Importing into TallyPrime

1. Make sure the company is open and the bank ledger name in BahiSync matches Tally exactly.
2. Import the **ledger masters** file first (Import → Masters). It creates missing ledgers.
3. Import the **vouchers** file (Import → Transactions).

Not yet verified against a live TallyPrime install: do that before charging anyone (see "Before launch").

## Configuration (engine environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `BAHISYNC_MAX_UPLOAD_MB` | `4` | Upload size limit (Vercel caps bodies at 4.5 MB) |
| `ANTHROPIC_API_KEY` | unset | Turns on AI ledger suggestions |
| `BAHISYNC_AI_MODEL` | `claude-haiku-5-5` | Model for AI suggestions (a current Claude model ID) |

Web: `BAHISYNC_API_URL` (build time) points the `/api` rewrite at the engine; `BLOB_READ_WRITE_TOKEN`
enables the waitlist store (without it, sign-ups go to `web/.data/waitlist.jsonl` locally).

## Before launch (not built yet, on purpose)

- [ ] Test with 30–50 **real, masked** statements across 10+ banks; target ≥95% fully balanced.
- [ ] Import the generated XML into a TallyPrime trial (Educational mode) and fix anything it rejects.
- [ ] Login (Supabase Auth or similar) so clients and rules are per account, not per browser.
- [ ] Payments (Razorpay): per-statement credits and the monthly plan.
- [ ] Accounts + a database so remembered ledgers follow the user across devices (today they live in one browser).
- [ ] Rate limiting and an abuse cap on the upload endpoint.
- [ ] Privacy policy and terms pages (DPDP-ready), and a contact email.
- [ ] Error monitoring that never captures statement contents.
