# Frontend

React + TypeScript + Vite + TanStack Query + Tailwind. The production build
(`npm run build` → `dist/`) is served by the backend; see the main
[README](../README.md) for installation.

```bash
npm ci
npm run dev      # http://localhost:5173 — proxies /api to the backend on :8420
npm run lint     # oxlint
npm run build    # type-check + production build
npm test         # unit tests (the integration test is opt-in, see src/test/)
```

Conventions:

- All business logic lives in the backend; the frontend only displays data
  and calls the API (`src/api/`).
- Requests go through `src/api/client.ts`, which uses same-origin URLs and
  adds the `X-Finance-Client` header the backend requires for changes.
- After any change to financial data, invalidate queries with
  `invalidateTransactionDependentQueries` (`src/hooks/invalidation.ts`).
- Dates shown or sent as `YYYY-MM-DD` must be computed in local time
  (`toLocalIsoDate` in `src/lib/format.ts`), never with `toISOString()`.
- Every visible text comes from `src/i18n/` (German default, English):
  add the key to `en.ts` and `de.ts` (a missing key is a type error) and
  use `const { t, tn } = useI18n()` — `t("key", { name })` fills `{name}`,
  `tn("key", count)` picks `key.one` / `key.other`. Values stored in the
  database (categories, preset names) stay English and are translated
  when shown (`categoryLabel`). Format money and dates only with
  `src/lib/format.ts`, which follows the chosen language.
- Messages from the backend arrive in the chosen language (the client
  sends `Accept-Language`); new backend messages go through `tr()`
  (`backend/app/i18n.py`) with a German entry in `app/i18n_de.py`.
