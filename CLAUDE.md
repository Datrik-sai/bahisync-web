# BahiSync — project rules for Claude Code

BahiSync turns Indian bank statement PDFs into TallyPrime vouchers. Every row is
verified against the running balance; that check is the product's promise.

## Layout
- `engine/bahisync_engine/` — Python core. `parser.py` is the entry point.
  - `pdf_io.py` open/decrypt PDFs, read words (text layer or Tesseract OCR)
  - `layout.py` header-driven table parser (no per-bank code; add header synonyms to `ROLE_KEYWORDS`)
  - `balance.py` running-balance verification, newest-first detection
  - `ledgers.py` ledger suggestions: client rules > default rules > AI > party guess > Suspense
  - `export_tally.py` ledger masters + vouchers XML; `export_excel.py`
  - `ai_suggest.py` optional Claude API suggestions (only when ANTHROPIC_API_KEY is set)
- `engine/api/` — FastAPI service (`main.py`) and file storage (`store.py`)
- `engine/tests/` — pytest; `tests/fixtures/make_statements.py` generates synthetic statements
- `web/` — Next.js 15 App Router + Tailwind v4. `/` landing, `/app` upload, `/app/review/[id]` review grid.
  The browser calls `/api/*`, which `next.config.ts` rewrites to the engine.

## Non-negotiable rules
1. Any change to parsing, amounts, dates, balance or Tally export must keep `cd engine && python -m pytest -q` green, and must add a test for the new case.
2. Money is `Decimal`, never float, everywhere in the engine. Floats only at the Excel boundary.
3. Never commit real bank statements. Real samples go in `engine/samples/` (git-ignored) and must be masked.
4. Never log narrations, amounts or file contents in production logs.
5. The PDF is never written to disk. Only parsed rows are stored, and they expire after 24 hours.
6. Never auto-post to Tally without the review step. Rows that fail the balance check stay flagged.
7. Tally group names must be TallyPrime's predefined groups (see `TALLY_GROUPS` in `api/main.py`).

## Adding support for a new bank layout
1. Put a masked sample in `engine/samples/`, run `python -m bahisync_engine.cli engine/samples/x.pdf`.
2. If the header isn't found, add the bank's column titles to `ROLE_KEYWORDS` in `layout.py`.
3. Add a synthetic layout modelled on it to `tests/fixtures/make_statements.py` (`LAYOUTS`) and a test.
4. Run the full test suite.

## Commands
- Engine tests: `cd engine && pip install -r requirements-dev.txt && python -m pytest -q`
- API: `cd engine && uvicorn api.main:app --reload --port 8000`
- Web: `cd web && npm install && npm run dev` (http://localhost:3000)
- Both via Docker: `docker compose up --build`
