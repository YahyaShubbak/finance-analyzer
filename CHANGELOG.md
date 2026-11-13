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
- An import that finished while another page was shown was lost on its
  card: back on the imports page the card offered the file again, and
  importing it a second time failed with "Preview not found". A card now
  shows what became of its file whenever the page is opened — also why an
  import failed — and never imports a file twice.
- Why an import failed was written on the card behind the full-window
  review, where nobody saw it. It is said in the review now.
- Several files that wanted their review looked at opened them on top of
  each other, and one Escape closed them all. One review is open at a time;
  the next opens when it is closed.
- A file removed from the page while it was still being uploaded stayed in
  the app's staging folder for up to a day. It is discarded right away.
- Choosing another data folder in the installer only changed the setting:
  the data stayed in the old folder and the app started empty, as if
  everything was gone. The installer now says so and asks before it
  switches to a folder without data (and stops when it can't ask).
- Updating while the app was running: on Windows the installer replaced
  packages the running app held open and could leave a broken environment.
  The installer now notices the running app and offers to stop it first.
- `./run.sh --stop` on Windows cut the app off in the middle of whatever it
  was doing. The app is now asked to end itself, as on Ctrl+C; only one
  that does not answer is ended from outside.
- Parts of the overview that could not be loaded (the months, the
  categories, the accounts, the forecast) said "not enough data" or "no
  expenses". They now say that loading failed, with "Try again".
- A category that was in use but had never been created (typed in with an
  older version) appeared in no list and could not be renamed or removed.
  It is now one of your own categories in Settings.
- The value of bonus points was always shown in euros. It is shown in the
  currency of the card the points belong to.
- One click on "Remove" deleted a budget. It asks first now.
- Archiving an account that failed said nothing. The reason is shown.
- A click beside the bars of the income/expense chart chose the first month.
- Assigning categories quickly one after the other: when the first one
  failed, nothing said so.
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
- With the imports or backups folder set to a folder that also holds other
  files (`FINANCE_IMPORTS_DIR`, `FINANCE_BACKUPS_DIR`), a restore and "Reset
  everything" deleted those too. Only the app's own files are replaced or
  deleted now: the imports' stored originals, and backups. On start-up,
  only working folders with the app's own name are cleaned away — no longer
  any folder starting with "tmp" that holds a `finance.db`.
- When the credit cards, budgets, accounts or imports could not be loaded
  (the app stopped, an error), the page said there were none. It now says
  that loading failed, and offers to try again.
- A remembered dashboard period this version doesn't know made the start
  page fail on every load. It falls back to "This month".
- The backups and learned rules in Settings showed nothing when they could
  not be loaded; they now say so.
- The transactions list, and a month's list in the reports, stayed on a page
  that no longer existed when the list got shorter ("Page 3 of 2" over an
  empty table).

### Changed
- The transactions search filters once the typing pauses, not on every
  keystroke.
- Long files are stored faster (a 5,000-row export in about 3.6 s instead
  of 5.2 s), and a PDF statement with many lines ending in two amounts is
  read in a fraction of the time.
- Faster with many bookings (measured with 30,000): assigning a category
  that is learned takes about 0.1 s instead of 1.2 s, a page of the review
  queue 0.1 s instead of 0.6 s, and the work after each import no longer
  grows with the number of card statements waiting for their payment.
- Of many files dropped at once, two are uploaded and read at a time; the
  others wait for their turn.
- Dropped files go on being read while another page is shown.
- Of the backups the app makes right before a restore, the newest three are
  kept (each holds every original document; they used to pile up).
- In the import review of a long file, moving the mouse over the bookings
  no longer redraws every row.
- A search that was replaced by a newer one is given up instead of answered
  for nothing, and a request the server refused is not sent a second time.
- `install.sh` downloads a named version of uv when it installs it.
- A release is only published after all checks passed, and only when its
  tag is the version the app reports.
- Which booking a row stands for that was skipped as a duplicate (the same
  purchase in a card's statement and in its export) is now a checked
  reference in the database instead of a note inside the row's extra
  columns: it can no longer point at a booking that is gone. The database is
  upgraded on the first start (a copy is kept, see below).

### Added
- `./run.sh --status` (Windows: `run.bat --status`) says whether the app is
  running.
- Backups can be deleted in Settings (after a confirmation).
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
