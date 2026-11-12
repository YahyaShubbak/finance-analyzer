# Changelog

All notable changes to this project are listed here. Versions follow
[semantic versioning](https://semver.org); before 1.0, a minor version may
change behaviour or the database schema (migrations run automatically on
start — back up your data before updating).

## Unreleased

### Fixed
- "Undo" on an import card could remove a different import: after its own
  import had been removed in the list (the next import got the same
  number), or after a backup was restored. A card now only offers "Undo"
  while its import is in the list, restoring a backup clears the cards, and
  an import's number is never given to a later import (schema change).
- Running the installer again removed settings added to `finance.env` by
  hand (`FINANCE_HOST`, `FINANCE_IMPORTS_DIR`, `FINANCE_BACKUPS_DIR`, ...),
  so after an update the app looked for backups and originals in another
  folder. They are kept now.
- A restore that failed while replacing files (e.g. an original document
  open in another program) could leave the restored database next to the
  previous documents. Replacing is all or nothing now: on a failure the
  previous database and documents are put back.
- A bank debit that happened to have exactly a card statement's amount was
  linked as that statement's payment — and so stopped counting as an
  expense — even when it was already sorted as a purchase (a cash
  withdrawal, groceries). Such a debit is now only suggested on the
  Reconciliation page; unsorted debits and card bills are linked as before.
- A file a reader could not cope with (e.g. a spreadsheet with a damaged
  sheet) ended in "Internal Server Error" and left the upload in the
  staging folder. It is now reported as unreadable, with the cause in the
  log. An import that failed while being stored no longer leaves the copy
  of the statement in the imports folder.
- `--open` opened the browser before the app was listening when the start
  took longer (a database upgrade): "connection refused". It now waits for
  the app. Starting the running app again with `--open` opens the browser
  instead of ending with an error.
- An amount in a spreadsheet that carries a float's rounding noise
  (59.970000000000006) was refused as "more than two decimal places".
- A remembered filter on one of your own categories was dropped on every
  reload of the Transactions page.
- The dashboard's forecast and recurring payments ignored the chosen
  account.
- "Reset everything" left the remembered filters and the dashboard's period
  and account in place.

### Changed
- The transactions search filters once the typing pauses, not on every
  keystroke.
- Long files are stored faster (a 5,000-row export in about 3.6 s instead
  of 5.2 s), and a PDF statement with many lines ending in two amounts is
  read in a fraction of the time.

### Added
- Before the database schema is upgraded on start-up, a copy of the
  database is kept in the backups folder (`pre-upgrade-….db`, the newest
  three): an upgrade that stops half-way can't be undone by SQLite itself.

## 0.8.0 — first public release

### Importing
- Bank and credit-card statements as CSV, XLSX and PDF (text PDFs; scans
  are not supported). Exports of common German banks are recognized by
  their columns; ambiguous dates or amounts are asked for, never guessed.
- Preview before every import, with a self-check against the statement's
  balances or statement amount.
- Files of a known kind are recognized and import themselves into the right
  account; any import can be undone.
- Check an import against the original document, page by page, and teach
  the reader an unknown PDF layout by example — remembered for every later
  file of that kind.
- The same period imported from two sources (PDF and export) is counted once.

### Counting
- Income, expenses, refunds (positive expenses that lower spending) and
  transfers between own accounts (not counted). Duplicates are detected
  across files and periods.
- Credit-card statements are matched with the bank debit that pays them,
  so purchases are never counted twice; money paid onto a card from someone
  else's account counts as a refund.

### Insight
- Overview with period and account filter: totals, monthly chart, spending
  per category with searchable and sortable bookings, accounts, transfers,
  recurring bookings and a cash-flow forecast.
- Transactions page with search, filters and sorting; categories learned
  from your corrections; review queue grouped by payee.
- Places (spending by country and town, read only from what statements
  state), bonus points from card statements, monthly budgets.
- Help page explaining how the app works, with troubleshooting.

### Data and safety
- Runs only on this computer; data in your personal data folder, outside
  the program folder. Backups as ZIP, restore from a file, reset everything.
- German and English interface.
