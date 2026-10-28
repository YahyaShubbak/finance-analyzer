# Changelog

All notable changes to this project are listed here. Versions follow
[semantic versioning](https://semver.org); before 1.0, a minor version may
change behaviour or the database schema (migrations run automatically on
start — back up your data before updating).

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
