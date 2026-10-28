# Contributing

Thanks for helping! Bug reports, new statement layouts and fixes are welcome.

## Never share real financial data

Not in issues, pull requests, tests or screenshots: no real statements,
IBANs, account or card numbers, names, payees with amounts and dates, or
databases. To show a layout the app can't read, recreate a few lines with
invented values (same columns, same spacing, same words for headings and
signs). Tests build their PDFs and CSVs from invented data, see
`backend/tests/pdf_fixtures.py`.

## Development

See [Development](README.md#development) in the README for setup, tests and
linting. Before opening a pull request:

- `cd backend && uv run pytest && uv run ruff check app tests`
- `cd frontend && npm run lint && npm run build && npm test`
- Schema changes need an Alembic migration (`backend/DATABASE.md`); CI
  checks that migrations and models agree.
- New user-facing text goes into both `frontend/src/i18n/de.ts` and
  `en.ts` (and `backend/app/i18n_de.py` for messages from the backend).

CI runs all of this on Linux and Windows, including both installers.

## License

By contributing you agree that your contribution is licensed under the
project's license, the [GNU AGPL 3.0 or later](LICENSE).
