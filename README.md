# Local Finance Analyzer

A local-first personal finance application. Import bank and credit-card
statements (CSV, XLSX, PDF), get automatic transaction normalization,
duplicate detection, credit-card reconciliation, transfer detection,
budgets, recurring-payment detection and reports — all running entirely
on your own machine.

> **No warranty.** This is a hobby project, provided as is. It is not
> financial or tax advice — check important figures against your bank's
> statements. Questions and bug reports are answered as time allows.
> Please never post real statements, IBANs or names in issues (see
> [CONTRIBUTING.md](CONTRIBUTING.md)).

## Privacy and security

- All data stays on your computer. No cloud sync, no telemetry, no
  external API calls during normal operation.
- The app listens on `127.0.0.1` only, so other computers cannot reach it.
- It also refuses requests from other websites open in your browser:
  requests must name this machine as their host (protection against DNS
  rebinding), and every change needs a header that other sites cannot send
  (protection against cross-site request forgery). See
  `backend/app/security.py`.
- There is **no login**. Anyone who can use your user account on this
  computer can open the app. On a shared computer, use separate user
  accounts.
- Backups are ZIP files and are **not encrypted**. Store copies somewhere
  safe (e.g. an encrypted drive).
- Your data lives in your personal data folder, never inside the program
  folder (see [Where your data lives](#where-your-data-lives)). Updating,
  re-cloning or deleting the program folder cannot affect it, and nothing
  sensitive can be committed to git by accident.

## Installation

You need:

| | Linux / macOS | Windows |
|---|---|---|
| Python | 3.12 or newer — **or** [uv](https://docs.astral.sh/uv/), which downloads the right Python by itself | same; the installer can install uv, Python or Node.js for you via `winget` |
| Node.js | 20.19+ or 22.12+ **including npm** (only needed to build the web interface) | same |

On some Linux distributions npm is a separate package (e.g. Arch:
`sudo pacman -S nodejs npm`, Debian/Ubuntu: `sudo apt install nodejs npm`).
The installer tells you what is missing and offers to run the command.

Without Node.js: download a release archive from the project's GitHub
*Releases* page — it contains the prebuilt web interface, and the installer
then skips that step.

### Linux / macOS

```bash
./install.sh
./run.sh
```

### Windows

Double-click `install.bat`, then `run.bat` (or run them in a terminal).

### What the installer does

It explains each step and asks before changing anything:

1. checks Python (or uv) and Node.js/npm, and offers to install what's missing;
2. asks for the **data folder**, the **port** (default 8420), whether to
   open the browser automatically on start, and whether to add a menu /
   Start menu entry;
3. installs the backend's Python packages into `backend/.venv` —
   exactly the versions pinned in `backend/uv.lock` /
   `backend/requirements.txt` (checksum-verified), nothing system-wide;
4. builds the web interface (`npm ci` + `npm run build`);
5. saves your choices to `finance.env` in the program folder and makes the
   data folder private (only your user account can open it; an existing
   folder only after asking).

If data from an older version (≤ 0.1) is found inside the program folder,
it offers to move it to the new data folder. The app must be stopped for
that. Everything is copied and checked first (the database with SQLite's
integrity check and row counts, every other file by checksum); the
originals are deleted only once `finance.env` points to the new folder, so
an interruption at any point leaves one complete copy that the app uses.
If you answer "no", the installer remembers it and does not ask with "yes"
as the default again (`--yes` keeps the data where it is).

Run the installer again at any time — to update after `git pull`, or to
change the data folder or port. Previous choices are the defaults; data is
never deleted.

Non-interactive installation (e.g. for scripts): `./install.sh --yes`
or `install.bat -Yes`. All options: `./install.sh --help` /
`install.bat -Help` (data folder, port, `--dev` for development tools,
`--no-uv` / `-NoUv` to use plain venv + pip).

## Running

```bash
./run.sh                # Windows: run.bat
./run.sh --port 8421    # another port this time
./run.sh --open         # also open the browser
./run.sh --stop         # stop the running app — also one started without a window
./run.sh --restart      # stop it and start it again, e.g. after an update
./run.sh --help
```

Then open **http://127.0.0.1:8420** (or the port you chose). Stop the app
with Ctrl+C in its window (or close the window). Started by double-clicking
`run.sh` in a file manager, it runs without a window: stop it with
`./run.sh --stop` (Windows: `run.bat --stop`).

The **Help** page in the app explains how it works (importing, how income,
expenses, refunds and transfers are counted, card reconciliation,
categories) and lists common problems and their fixes.

The interface is in **German by default**; switch to English in the
sidebar or under **Settings → Language** (remembered per browser). Dates,
amounts and the app's messages — import warnings, errors — follow the
chosen language.

## Updating

Your data lives outside the program folder, so an update never touches it.
Make a backup first anyway (**Settings → Backup**): updates may change the
database schema, and that can't be undone by going back to an older
version. (Before it changes the schema, the app also puts a copy of the
database into the backups folder by itself — `pre-upgrade-….db`, the newest
three are kept. A backup holds your original documents as well.)

- **From a git checkout:** `git pull`, then run the installer again
  (`./install.sh` / `install.bat` — it installs the new package versions and
  rebuilds the interface; your previous answers are the defaults), then
  `./run.sh --restart`.
- **From a release archive:** unpack the new archive in place of the old
  program folder (or next to it) and run the installer in it, choosing the
  same data folder.

Database migrations run automatically on the next start. What changed is
listed in [CHANGELOG.md](CHANGELOG.md). The running app notices when its
files were updated and asks for a restart.

## Where your data lives

| System | Default data folder |
|---|---|
| Linux | `~/.local/share/finance-analyzer` (or `$XDG_DATA_HOME/finance-analyzer`) |
| macOS | `~/Library/Application Support/finance-analyzer` |
| Windows | `%LOCALAPPDATA%\finance-analyzer` |

Inside it: `finance.db` (a single SQLite database), `imports/` (the
original documents you imported), `backups/` and `exports/`. The app's
Settings page shows the exact paths.

Back up by using **Settings → Backup** (one ZIP with the database and all
original documents), or by copying the whole folder while the app is not
running.

## Settings (`finance.env`)

Written by the installer; you can also edit it and restart the app.
Settings you add yourself are kept when the installer runs again.
Environment variables with the same names take precedence.

| Setting | Meaning |
|---|---|
| `FINANCE_DATA_DIR` | data folder (see above) |
| `FINANCE_PORT` | port, default `8420` |
| `FINANCE_OPEN_BROWSER` | `true` to open the browser on start |
| `FINANCE_HOST` | interface to bind; default `127.0.0.1`. **Changing this exposes your data to the network — there is no login.** |
| `FINANCE_ALLOWED_HOSTS` | extra host names to accept (comma-separated), only needed together with `FINANCE_HOST` |
| `FINANCE_IMPORTS_DIR`, `FINANCE_BACKUPS_DIR`, `FINANCE_EXPORTS_DIR` | override single sub-folders. If such a folder also holds files of your own, a restore or "Reset everything" leaves them alone: only what the app put there is replaced or deleted. (A backup still packs every file of the imports folder.) |

## Importing statements

- **CSV / XLSX**: delimiter, encoding, a header row below account details,
  decimal comma/point and the date format are detected per file.
  Exports from **Sparkasse (CSV-CAMT), DKB, ING, comdirect, Commerzbank,
  N26 and Revolut** are recognized by their column layout, as are separate
  Soll/Haben (S/H) marker columns (e.g. Volksbank). Opening/closing balance
  rows and pending or cancelled rows are skipped (and reported). If a file
  is not recognized, or its dates/amounts are ambiguous (e.g. `02/03/2026`,
  `1.500`), the import dialog asks you to choose instead of guessing.
  Card exports that list purchases as positive numbers (e.g. the American
  Express CSV) are recognized on a credit-card account and inverted
  automatically — the preview says so, and **Invert all amounts** in that
  dialog undoes it. Card exports with the card
  network's **merchant category** ("GROCERY STORES/SUPERMARKETS") use it
  to categorize purchases no rule names.
- **PDF**: statements printed as a table (e.g. comdirect) are read by
  column — the amount only from the amount column, the payee and the
  counterparty's IBAN from their own columns, SEPA references apart from
  the purpose text. Otherwise: text-based statements with one transaction per line
  (`date  description  amount  [balance]`, including `S`/`H` and `CR`/`DR`
  markers), bank statements where a booking continues on the following
  lines (value date, payee, reference), and card statements with
  year-less `dd.mm dd.mm` dates and credits marked on the next line (e.g.
  American Express). Statements that print money in and out in two unsigned
  columns are read by column when the columns are headed (e.g.
  "Zahlungseingang"/"Zahlungsausgang", "Soll"/"Haben"); without such
  headings they are refused, because the direction can't be read reliably.
  Scanned PDFs (images) are not supported — use the bank's CSV export
  instead.
- Every file gets a **preview** first: new rows, exact duplicates
  (skipped by default), possible duplicates (kept by default) and rows
  that could not be read. The preview is made as soon as the file is
  dropped.
- **Known kinds of files import themselves.** The first file of a kind
  (e.g. a comdirect statement) asks for its account and waits for
  **Import**. The next file of that kind is recognized — by the format
  and the account/card number it prints, or by an IBAN you entered for an
  account — goes to the same account, is read with the same settings
  (column mapping, inverted signs, ...) and is imported without a click
  if its preview shows nothing to check: no warning, no possible
  duplicate, no unreadable row, balances that add up. Otherwise it waits
  for you as before. **Undo** right after an import removes it again
  (e.g. to choose another account); the option *Import recognized files
  right away* on the Imports page turns the automatic import off.
- **Self-check**: a bank statement with opening and closing balance is
  checked (opening balance + bookings = closing balance), a card statement
  against its statement amount. The preview shows ✓ — or warns that a
  booking may be missing. A line that can be read two ways (a number in
  the booking text right before the amount, "Rechnung 12 345,67 -345,67")
  is read the way the statement's own balances add up.
- The same month from **two sources** (e.g. the PDF statement and the
  spreadsheet export) is recognized as the same bookings; the bookings
  already imported are completed with what only the other file has
  (merchant category, booking type).
- **Credit cards**: a card statement is matched with the bank payment
  that settles it, so a purchase is never counted twice. A card export
  covering one billing period (e.g. the American Express CSV) whose
  purchases add up exactly to a later bank debit for a card bill is
  treated as that bill's statement. A bill whose purchases aren't imported
  is an expense of its own ("Card bills"). The payment is
  linked automatically only if exactly one bank debit has exactly the
  statement amount and isn't already sorted as a purchase (a cash
  withdrawal of the same amount stays an expense); otherwise the app
  suggests candidates for you to confirm on the Reconciliation page. Cards without statements (e.g. a
  card account with its own IBAN): money paid onto the card is recognized
  as a transfer and paired with the bank account's debit, refunds are not.
- **Transfers** between your own accounts are excluded from income and
  expenses. They are detected when amounts match exactly within a few
  days. Entering the **IBAN** of your accounts (Accounts page) makes
  detection more reliable.
- **Categories** come from rules (built in: groceries, food, housing,
  utilities, transport, travel, shopping, subscriptions, entertainment,
  health, education, insurance, taxes, cash, fees, donations, salary,
  transfers — e.g. paying off a credit card — and other income/expense).
  Click a transaction's category on the **Transactions** page to change
  it: the app learns the payee (e.g. "REWE Markt GmbH" from "Lastschrift
  / Belastung REWE Markt GmbH Einkauf 12,34 EUR vom 01.09.") and sorts
  similar existing transactions and future imports the same way. Lines
  that name no payee (e.g. a bare PayPal line) only change themselves.
  Own categories (e.g. "Loan", "Debts") are added under **Settings →
  Categories**; renaming one carries its transactions, learned rules and
  budget along. Deleting one moves its transactions to a category you
  choose (or back to the review queue) and removes its learned rules and
  budget.
  **Settings → Learned categories** lists what was learned; forgetting a
  rule undoes it. Categories set by hand are never changed by a rule.
  Your other corrections can become rules for future imports; **Settings → Re-apply categorization rules** applies
  rules to transactions you already imported (manual corrections are
  kept). On the **Overview** page, clicking a category lists the
  transactions behind its amount (searchable and sortable); their
  categories can be changed there too.
- **Places**: the **Places** page shows spending by country and town,
  plus online purchases. The place is read from what a statement prints,
  never guessed: the SEPA card-payment format (`MERCHANT//TOWN/DE`), the
  town column of a card export ("Merchant Area"), the town at the end of
  a card statement's merchant text (only for statements whose format puts
  it there, e.g. American Express), a web address (online purchase) or a
  currency used by only one country. Bank transfers and direct debits
  carry no place and are shown as "No place stated". Towns are recognized
  with the [GeoNames](https://www.geonames.org) town index (towns with
  15,000+ inhabitants, CC BY 4.0), bundled in
  `backend/app/normalization/places.tsv.gz` — no network access.

## Architecture

```
IMPORT (CSV/XLSX/PDF) → preview → RAW DATA (kept unchanged)
    → NORMALIZATION (merchant/category rules, deterministic — no AI/LLM)
    → DATABASE (SQLite, Alembic-migrated)
    → RECONCILIATION / TRANSFERS → ANALYSIS → GUI
```

- **Backend:** Python, FastAPI, SQLModel, Alembic (`backend/`). All
  business logic lives here. See `backend/DATABASE.md` for migrations.
- **Frontend:** React + TypeScript + Vite (`frontend/`), built to static
  files and served by the backend — one process, one port.

## Development

```bash
cd backend
uv sync                            # or: ./install.sh --dev
uv run pytest                      # backend tests
uv run ruff check app tests        # lint
uv run python -m app --reload      # backend with auto-reload

cd frontend
npm ci
npm run dev                        # Vite dev server on :5173, proxies /api to :8420
npm run lint && npm run build
npm test                           # unit tests
```

The frontend integration test uses a real backend and writes data, so it
only runs against a throwaway one:

```bash
cd backend && FINANCE_DATA_DIR=$(mktemp -d) .venv/bin/python -m app --port 8421 --no-open
cd frontend && E2E_API_BASE=http://127.0.0.1:8421 npm test
```

`backend/requirements*.txt` are generated from `uv.lock` (for installs
without uv) — regenerate them after changing dependencies:

```bash
uv export --locked --no-dev --no-emit-project --format requirements-txt -o requirements.txt
uv export --locked --all-groups --no-emit-project --format requirements-txt -o requirements-dev.txt
```

CI (`.github/workflows/ci.yml`) runs all of this on Linux and Windows,
including both installers.

## Troubleshooting

- **"The app is not installed yet"** when starting — run the installer first.
- **"port … is already in use"** — the app is probably already running;
  open it in the browser, or start it with `--port 8421`.
- **"the app is already running with the data in …"** — another instance
  uses the same data folder (on any port). Use that one, or stop it first.
  The installer refuses to move data for the same reason.
- **"Invalid Host header"** — open the app as `http://127.0.0.1:PORT` or
  `http://localhost:PORT`, not via another host name.
- **The page loads but stays empty / "Loading…"** — rebuild the web
  interface by running the installer again.
- **Node.js too old / npm missing** — see [Installation](#installation).
- **Windows: SmartScreen warns about install.bat** — the files come from
  the internet (e.g. a downloaded ZIP). Right-click → Properties →
  "Unblock", or run it from a terminal.
- **Existing database after an update** — schema migrations run
  automatically on start; see `backend/DATABASE.md`.
- **Updating from 0.1 with existing data** — the importer now reads some
  bank formats more precisely (e.g. the Sparkasse description comes from
  "Verwendungszweck" instead of "Buchungstext"). When you import a file
  that overlaps with data imported by 0.1, review the duplicate section
  of the preview before confirming.

## License

Copyright © the contributors. This program is free software under the
[GNU Affero General Public License 3.0 or later](LICENSE) (AGPL-3.0-or-later):
you may use, change and share it; changed versions you distribute or offer
over a network must be published under the same license. It comes with
**no warranty**.

The AGPL follows from [PyMuPDF](https://pymupdf.readthedocs.io), which reads
the PDFs and is itself licensed under the AGPL (or commercially by Artifex).
The other libraries are under permissive licenses (MIT, BSD, ISC, Apache 2.0, PSF):
FastAPI, SQLModel, pandas, Alembic, React, Recharts, TanStack Query,
Tailwind CSS and others — see `backend/uv.lock` and
`frontend/package-lock.json`.

## Credits

Town names: [GeoNames](https://www.geonames.org), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (converted by
`backend/scripts/build_places.py`).
