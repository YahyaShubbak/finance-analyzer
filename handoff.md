# Handoff: Audit-Nacharbeit finance-analyzer

Stand: 2026-11-12. Für das nächste Modell (Opus 5.5), das ohne den bisherigen
Chatverlauf weiterarbeitet. Der Nutzer spricht Deutsch; Code, Kommentare,
Tests und die Doku im Repo sind Englisch.

## Ausgangslage

Ein Architektur-Audit des Repos (Version 0.8.0) hat 15 größere Befunde
(Nr. 1–15) und eine Tabelle kleiner „Quick Wins“ ergeben. Erledigt und
getestet sind die Befunde 1–6, 12 und großteils 14 sowie ein Teil der Quick Wins (Abschnitt
„Quick Wins“). Offen sind die Befunde 7–11, 13, 15, der Rest von 14 und der Rest der Quick Wins.

Der Nutzer committet selbst. Die Befunde 1–6 stehen in Commit `68a370d`
("Harden imports, restores, and schema upgrades"); der Stand davor war
`f0a3d0f`. Die neun erledigten Quick Wins sind ebenfalls committet (bis
`7b5b058`), Befund 12 in `899e8b4`. Befund 14 lag am 2026-11-12 noch
uncommittet im Arbeitsverzeichnis (Commit-Message im Chat des Nutzers):
`frontend/src/pages/CreditCards.tsx`, `Budgets.tsx`, `Accounts.tsx`,
`loadErrors.test.tsx`, `frontend/src/components/imports/ImportHistory.tsx`,
`CHANGELOG.md`, `handoff.md`. Vor neuer Arbeit mit `git status` prüfen, ob das
inzwischen committet ist — wenn nicht, den Nutzer darauf hinweisen und diese
Dateien nicht anfassen.

## Arbeitsweise, die der Nutzer erwartet

- **Nicht selbst committen.** Jede Aufgabe endet im Chat mit einer
  kopierbaren Commit-Message (Englisch, Imperativ, ohne Präfix wie `fix:` —
  so sind die vorhandenen Commits) und der Liste der zugehörigen Dateien.
- Mehrere Aufgaben in einem Durchgang nur, wenn ihre Dateien sich nicht
  überschneiden — sonst lassen sie sich nicht getrennt committen.
- Nutzersichtbare Änderungen zusätzlich in `CHANGELOG.md` unter
  "Unreleased" eintragen.
- Jede Aufgabe hier im Dokument als erledigt vermerken (mit einem Satz, was
  getan wurde und was bewusst nicht).
- Chirurgische Eingriffe, keine Rewrites. Jeder Fix bekommt einen Test, der
  mit dem alten Code fehlschlägt (per `git stash push -- <datei>` gegenprüfen).
- Antworten an den Nutzer auf Deutsch, knapp, ohne Lob.

## Prüfen

Backend (in `backend/`, venv per `uv sync --locked`):

```
uv run --locked ruff check app tests
uv run --locked pytest -q -p no:cacheprovider          # ca. 2,5 min, zuletzt 795 bestanden
FINANCE_DATA_DIR=<leerer Temp-Ordner> uv run --locked alembic upgrade head
FINANCE_DATA_DIR=<derselbe>           uv run --locked alembic check
```

Frontend (in `frontend/`, nach `npm ci`):

```
npx tsc -b && npm run lint && npx vitest run
```

Frontend gegen ein echtes Wegwerf-Backend (wie der CI-Job `e2e`):

```
cd backend && FINANCE_DATA_DIR=<Temp-Ordner> .venv/Scripts/python.exe -m app --port 8421 --no-open
cd frontend && E2E_API_BASE=http://127.0.0.1:8421 npx vitest run
cd backend && FINANCE_DATA_DIR=<derselbe> .venv/Scripts/python.exe -m app --stop
```

Den Lauf gegen das echte Backend bei jeder Frontend-Änderung mitmachen: der
Integrationstest (`src/test/app.integration.test.tsx`) läuft ohne
`E2E_API_BASE` gar nicht und hat z. B. die Such-Verzögerung erst sichtbar
gemacht (gemerkte Filter). Der Server-Prozess endet dabei mit Exit-Code 15 —
das ist das `--stop`, kein Fehler.

## Regeln des Repos, die Tests erzwingen

- Jede Meldung an den Nutzer läuft über `tr("English text", ...)`; der
  englische Text ist der Schlüssel im deutschen Katalog
  `backend/app/i18n_de.py`. `tests/test_i18n.py` verlangt für jeden
  `tr()`-Text einen Eintrag mit denselben Platzhaltern und duldet keine
  unbenutzten Einträge.
- Schemaänderung = neue Alembic-Migration **und** ein Erkennungs-Zweig in
  `_detect_unversioned_revision` (`backend/app/db/migrate.py`), sonst
  bekommen die Test-Datenbanken (per `create_all` gebaut) eine falsche
  Revision. `alembic check` muss leer bleiben.
- `install.ps1` bleibt reines ASCII und muss unter Windows PowerShell 5.1
  laufen. Änderungen an den Installern in beiden Skripten (`install.sh`,
  `install.ps1`) gleich halten.
- Frontend-Texte stehen in `frontend/src/i18n/en.ts` und `de.ts`
  (`i18n.test.ts` vergleicht die Schlüssel), Hilfetexte in
  `frontend/src/help/`.
- Geld ist immer Integer in Minor Units; nie Float.

## Eigenheiten dieser Maschine (Windows, Git Bash)

- Bash-Heredocs mit Apostrophen im Inhalt scheitern im Tool
  („unexpected EOF“). Dateien mit dem Edit-/Write-Werkzeug ändern.
- Ein `cd` im Bash-Tool bleibt für den nächsten Aufruf bestehen; absolute
  Pfade verwenden.
- `backend/.venv`, `frontend/node_modules`, `frontend/dist` existieren lokal
  und sind per `.gitignore` ausgeschlossen.

## Erledigt: Befunde 1–6

| Nr. | Befund | Umsetzung |
|---|---|---|
| 1 | „Undo“ einer Import-Karte konnte einen fremden Import löschen (veraltete `import_id`, SQLite vergab IDs neu) | Karte prüft ihren Import gegen die Import-Liste (`isSameImport`, `ImportFileCard.tsx`), Restore leert die Queue (`useBackup.ts`), Migration `e3a91f5c7d08` setzt `AUTOINCREMENT` auf `imports` |
| 2 | Installer überschrieb `finance.env` und verlor von Hand gesetzte Schlüssel | `install.sh` / `install.ps1` ersetzen nur ihre vier eigenen Schlüssel |
| 3 | Restore tauschte DB und Originale nicht atomar | `_swap_in` in `backup_service.py`: beiseite schieben, bei Fehler zurückstellen; bei doppeltem Fehler bleibt `.restore-*/previous` erhalten |
| 4 | Schema-Migration lief in-place ohne Sicherung | `run_migrations_to_head` legt vorher `backups/pre-upgrade-<rev>-<zeit>.db` an (neueste drei bleiben); ohne Kopie kein Upgrade |
| 5 | Kartenzahlung wurde allein über den Betrag automatisch verknüpft | `find_automatic_match` verknüpft nicht, was schon als Einkauf einsortiert ist (`_known_to_be_a_purchase`); bleibt Vorschlag |
| 6 | Parser-Ausnahmen endeten als 500 und ließen Dateien liegen | `parse_file` wandelt in `ImportServiceError`, Routen antworten 422, Staging/Imports werden aufgeräumt; XLSX-`iter_rows` abgesichert |

Bewusst offen gelassen bei 5: Eine **unsortierte** Abbuchung mit zufällig
gleichem Betrag wird weiterhin automatisch verknüpft. Eine strengere Regel
(„nur was wie eine Kartenabrechnung aussieht“) würde das Verknüpfen für jeden
Herausgeber abschalten, dessen Abbuchungstext keine Regel kennt.

## Offen: Befunde 7–11 und 13–15 (12 ist erledigt, siehe dort)

Zeilennummern stammen vom Audit-Stand und können sich verschoben haben; die
Funktionsnamen sind verlässlich.

### 7. Nacharbeit pro Import skaliert mit dem Gesamtbestand
- Wo: `run_post_import_matching` (`services/import_service.py`),
  `link_pending_payments` und `derive_statements_from_exports`
  (`reconciliation/engine.py`), `retype_card_payments` und
  `sort_card_bill_payees` (`services/transfer_marking.py`), Aufruf von
  `retype_card_payments` in `commit_import` (`api/routes/imports.py`).
- Problem: Nach jedem Commit wird jede offene Abrechnung neu berechnet und
  committet (auch ohne Treffer), jeder Karten-Export einzeln abgefragt, alle
  Karten-Eingänge und `chain_index` über alle Buchungen geladen. Ein
  Sammelimport von N Dateien ist quadratisch.
- Fix: In `link_pending_payments` zuerst `find_automatic_match` aufrufen und
  nur bei Treffer `reconcile_statement`. Die globalen Schritte auf Konten und
  Datumsfenster des Imports begrenzen. Frontend: Upload-Queue mit 1–2
  gleichzeitigen Uploads (`state/importQueue.ts`, `ImportFileCard.tsx`
  startet den Upload beim Mount), und `invalidateTransactionDependentQueries`
  nicht nach jedem einzelnen Commit den ganzen Cache invalidieren lassen.
- Vorsicht: `reconcile_statement` legt für eine neue Abrechnung auch die
  `Reconciliation`-Zeile an; die darf nicht entfallen.

### 8. Review-Queue und Kategorie-Lernen: Vollscans pro Klick
- Wo: `chain_index` (`services/chains.py`), `review_groups`
  (`services/review_service.py`), `recategorize_matching`,
  `list_learned_category_rules`, `reapply_rules` (`services/rule_service.py`),
  `CategorySuggester.__init__` (`services/category_suggestion.py`),
  `CategoryMemory` (`services/category_memory.py`).
- Fix: Generationszähler per SQLAlchemy-`after_commit`-Event in
  `db/session.py`; `chain_index`, `CategorySuggester`, `CategoryMemory` darauf
  cachen. `derive_category_pattern` mit `lru_cache`. In
  `recategorize_matching` einfache (nicht-Regex-)Muster per SQL vorfiltern
  (die SQL-Funktionen `fold`/`fold_plain` gibt es schon).

### 9. Eine PDF-Vorschau liest die Datei fünf- bis siebenmal
- Wo: `file_signature` (`services/account_recognition.py`) wird in
  `_review_reasons`, `_iban_of_another_account`, `_recognized_preview` und
  `commit_import` (`api/routes/imports.py`) jeweils neu berechnet (je zwei
  `pymupdf.open` plus Volltext); dazu bis zu drei Parse-Durchläufe.
  `classify_import_rows` (`services/duplicate_preview_service.py`) lädt bei
  jeder Vorschau alle Buchungen des Kontos.
- Fix: Signatur einmal pro Request berechnen und durchreichen; vorhandene
  Buchungen auf `period_start − 3 Tage … period_end + 3 Tage` begrenzen
  (`CROSS_FILE_DATE_WINDOW_DAYS`).

### 10. Relationale Verknüpfungen stecken in JSON-Blobs
- Wo: `_duplicate_of` und `_kept_by_user` in
  `RawTransaction.extra_fields_json`, gesucht per `LIKE '%"_duplicate_of"%'`
  in `location_service.py`, `import_removal_service.py`, `engine.py`
  (`statement_transaction_ids`), `twin_merge.py`, `points_service.py`.
- Fix: Migration mit `raw_transactions.duplicate_of_transaction_id`
  (nullable, indexiert) samt Backfill; die Stellen lesen die Spalte.

### 11. Zyklische Service-Abhängigkeiten (108 funktionslokale Imports)
- Wo u. a.: `credit_card_service.py` importiert `_to_read` aus
  `api/routes/accounts.py`; `api/routes/analytics.py` importiert Privates aus
  `routes/transactions.py`; `_valid_iban` / `_IBAN_RE`
  (`account_recognition.py`), `_group_lines` (`pdf_importer.py`), `_places`
  (`normalization/location.py`) werden modulübergreifend genutzt.
- Fix: drei Blattmodule herauslösen (`app/iban.py`, Read-Builder unter
  `schemas/`, PDF-Zeilengruppierung nach `importers/pdf_layouts/`).

### 12. Restore und Reset behandeln `imports_dir` als app-exklusiv — erledigt
- Umgesetzt: `is_app_document` (`services/import_staging.py`) sagt, was im
  Imports-Ordner der App gehört: die in `ImportRecord.stored_path` genannten
  Dateien und Dateien mit dem App-Namensmuster (`<12 Hex>_<name>`, auch von
  fehlgeschlagenen Importen). Reset löscht nur diese (`reset_service.py`);
  Restore tauscht den Ordner weiterhin als Ganzes und schiebt danach alles
  Fremde zurück (`_keep_other_files` in `backup_service.py`). Beim Löschen
  der Backups gehen nur App-Dateien (`finance-backup-*`, `pre-restore-safety-*`,
  `pre-upgrade-*`) und ZIPs mit `finance.db` + `manifest.json`. Der
  Exports-Ordner wird nur geleert, wenn er im Datenordner liegt. Arbeitsordner
  heißen jetzt `.finance-tmp-*`; nur die räumt der Start weg.
- Bewusst nicht umgesetzt: `create_backup_zip` packt weiterhin **jede** Datei
  des Imports-Ordners ins Backup (`rglob`), also auch fremde. Wer das ändert,
  muss entscheiden, ob Altlasten (nicht referenzierte App-Dateien) ins Backup
  gehören. Alte `tmp*`-Reste früherer Versionen werden nicht mehr gelöscht.
- Kann ein fremdes File nach dem Restore nicht zurückgeschoben werden, bleibt
  es in `.restore-*/previous/imports`; der Ordner wird dann nicht gelöscht
  und beim Start im Log genannt. Der Restore selbst gilt als gelungen.

### 13. Import-Karte verliert ihr Ergebnis und versteckt Fehler
- Wo: `frontend/src/components/imports/ImportFileCard.tsx`,
  `ImportReview.tsx`.
- Problem: `mutate`-Callbacks gehen beim Seitenwechsel verloren (importierte
  Datei zeigt danach „Preview not found“); Commit-Fehler werden hinter dem
  Vollbild-Review gerendert; mehrere Reviews stapeln sich, ein Escape schließt
  alle. 610 Zeilen, 14 `useState`, 5 Effekte mit unterdrückten Deps.
- Fix: Ergebnisse per `mutateAsync().then(saveSnapshot)` in den Store;
  `error` als Prop an `ImportReview`; ein `openReviewKey` in der Queue;
  mittelfristig `useImportCard`-Reducer extrahieren.
- Es gibt jetzt `ImportFileCard.test.tsx` (echte Hooks, gestubbte
  API-Module) als Vorlage für weitere Tests.

### 14. Fehlgeschlagene Abfragen erscheinen als „keine Daten“ — teilweise erledigt
- Erledigt: `pages/CreditCards.tsx`, `pages/Budgets.tsx`, `pages/Accounts.tsx`
  und `components/imports/ImportHistory.tsx` zeigen `ErrorState` mit
  „Erneut versuchen“, wenn die Abfrage fehlschlägt und keine (alten) Daten da
  sind (`isError && !data`). Test: `pages/loadErrors.test.tsx`.
- Ebenfalls erledigt: `components/settings/BackupSection.tsx` und
  `LearnedRulesSection.tsx` (am 2026-11-12 noch uncommittet).
- Offen: `pages/Overview.tsx` (monatliche Reihe, Kategorien, Konten zeigen bei
  einem Fehler „nicht genug Daten“). Gleiches Muster anwenden.
- Falle beim Testen: `beforeEach(() => mock.mockReset())` ohne geschweifte
  Klammern gibt die Mock-Funktion zurück; Vitest ruft sie als Aufräum-Funktion
  auf und der Test scheitert an deren Rückgabewert.

### 15. Installer: Datenordner-Wechsel und Update bei laufender App
- Wo: Abschnitt „data folder“ in `install.ps1` / `install.sh`.
- Problem: Ein neu gewählter Datenordner wird nur eingetragen, die Daten
  bleiben im alten; die App startet auf leerer DB. Unter Windows aktualisiert
  der Installer das venv, während die laufende App dessen Dateien hält.
- Fix: abbrechen/bestätigen lassen, wenn der alte Ordner `finance.db` hat und
  der neue nicht; vor dem Paket-Schritt `python -m app --stop` anbieten.

## Quick Wins

Status wird hier fortgeschrieben.

| Quick Win | Status |
|---|---|
| Kategorie serverseitig prüfen (PATCH Buchung, `assign-category`, `category-rule`, Budget-PUT) | **zurückgestellt — braucht eine Entscheidung des Nutzers**, siehe unten |
| Upload-Limit vor dem Spooling prüfen (`LocalRequestGuard`) | **verworfen**, siehe unten |
| `--open` wartet auf `/health`; zweiter Start mit `--open` öffnet nur den Browser | **erledigt** (`_open_browser_when_ready` in `app/__main__.py`, Tests in `tests/test_instance_lock.py`). Nicht mit echtem Browser ausprobiert. |
| XLSX-Float-Artefakte (`59.970000000000006`) nicht als „zu viele Nachkommastellen“ verwerfen | **erledigt** (`amount_minor` in `importers/tabular.py` liest Floats mit 15 signifikanten Stellen; Test in `tests/test_xlsx_importer.py`) |
| Test: jede Migration ist in `_detect_unversioned_revision` registriert | **erledigt** (parametrisierter Test über alle Revisionen in `tests/test_migrations.py`) |
| Gespeicherter Filter auf eigene Kategorie wird beim Reload gelöscht (`Transactions.tsx`) | **erledigt** (als veraltet gilt der Filter erst, wenn `/api/categories` geladen ist; `pages/Transactions.test.tsx`) |
| Forecast / wiederkehrende Zahlungen ignorieren das gewählte Konto (`Overview.tsx`) | **erledigt** (`query.account_id` wird durchgereicht; `pages/Overview.test.tsx`) |
| Reset setzt gemerkte Filter nicht zurück (`ResetSection.tsx`, `filterStore.ts`) | **erledigt** (`resetFilters()` exportiert und im Reset aufgerufen, `finance.dashboard.v1` wird mit entfernt; `ResetSection.test.tsx`) |
| Suche ohne Debounce (`TransactionFilterBar.tsx`) | **erledigt** (300 ms Pause; Getipptes wird beim Verlassen der Seite noch angewendet; `TransactionFilterBar.test.tsx`). Nicht umgesetzt: `AbortSignal` für überholte Requests in `api/client.ts`. |
| Ein `session.flush()` pro Rohzeile (`commit_parsed_import`) | **erledigt** (Rohzeilen werden zusammen geschrieben; 5.000 Zeilen: 5,2 s → 3,6 s; Test zählt die Flushes in `tests/test_import_service.py`) |
| `_settle_by_balance` probiert bis zu 1023 Kombinationen mit vollem Neu-Parsen (`generic_bank.py`) | **erledigt** (`_amount_minor` merkt sich geparste Beträge; 300 Zeilen: 1,5 s → 0,03 s; drei Tests in `tests/test_statement_layouts.py`, die Funktion hatte vorher keinen direkten Test) |
| Feste zwei Nachkommastellen für alle Währungen (`decimal_to_minor_units`; KWD/BHD unlesbar, JPY ×100) | offen |
| `pre-restore-safety-*`-Backups wachsen unbegrenzt, kein Lösch-Endpunkt | offen |
| `ImportReview`: jeder Hover rendert Tabelle und Quellzeilen neu | offen |
| Backend-Konstanten und Schemas im Frontend von Hand gespiegelt (`lib/categories.ts`, `types/index.ts`) | offen |
| Release-Workflow: `contents: write` ohne Tests, kein Abgleich Tag/Version; `curl \| sh` unversioniert; CI testet nur Erstinstallation | offen |
| `--stop` ist unter Windows ein harter Kill (`os.kill(pid, SIGTERM)`) | offen |

### Weitere kleine Frontend-Befunde aus dem Audit (offen, wenn nicht anders vermerkt)

- **Erledigt:** `state/dashboardPeriod.ts` — ein unbekannter gespeicherter
  Preset-Name fällt auf "This month" zurück statt die Startseite abstürzen zu
  lassen (`state/dashboardPeriod.test.ts`). Am 2026-11-12 noch uncommittet,
  zusammen mit `CHANGELOG.md` und `handoff.md`.
- **Erledigt für `pages/Transactions.tsx`:** die Seite wird begrenzt, wenn die
  Liste schrumpft (Test in `pages/Transactions.test.tsx`; am 2026-11-12 noch
  uncommittet). Ebenso erledigt: `components/reports/MonthTransactions.tsx`
  (`MonthTransactions.test.tsx`).
- `components/charts/IncomeExpenseChart.tsx`: `Number(null) === 0` — ein
  Klick neben einen Balken wählt den ersten Monat. Fix:
  `if (state?.activeIndex == null) return;` (Verhalten von Recharts nicht
  geprüft).
- `hooks/useCategoryAssignment.ts`: `reset()` vor der nächsten Zuweisung
  verschluckt den Fehler der vorherigen.
- `components/accounts/AccountRow.tsx`: ein fehlgeschlagenes Archivieren
  zeigt nichts; `components/budgets/BudgetProgressRow.tsx`: Budget wird ohne
  Rückfrage gelöscht.
- `ImportFileCard.tsx` `remove()`: Karte während des Uploads entfernt →
  die hochgeladene Datei bleibt bis zu 24 h im Staging.
- `pages/Points.tsx`: Punktewerte sind fest als EUR formatiert
  (`PointsProgram` hat keine Währung).
- `api/client.ts`: kein `AbortSignal`; überholte Requests laufen zu Ende.
- Kleinteile: `@playwright/test` ungenutzt, `currentMonth()` und
  `CURRENCIES` mehrfach definiert, `retry: 1` wiederholt auch 4xx-Fehler
  (`main.tsx`), zwei Query-Keys für `/api/system/info` (`hooks/useSystem.ts`).

### Zurückgestellt: Kategorie serverseitig prüfen

Freie Kategorienamen sind bisher erlaubtes, getestetes Verhalten: fünf Tests
schicken Namen wie "Dates", "Cinema", "Household", "Gifts" und ein Budget
"Haus/Garten", ohne die Kategorie vorher anzulegen
(`tests/test_accounting_fixes.py`, `tests/test_rule_creation.py`). Die
Migration `d41b7c9e2a65` (eigene Kategorien) hat vorhandene freie Namen nicht
als eigene Kategorien registriert, und `CategoryCell.tsx` hält die aktuelle,
unbekannte Kategorie einer Buchung bewusst wählbar. Eine harte Prüfung ist
also kein Quick Win, sondern eine Verhaltensänderung.

Zu entscheiden: (a) hart prüfen (422 bei unbekannter Kategorie, die
unveränderte eigene Kategorie einer Buchung bleibt erlaubt, die fünf Tests
legen ihre Kategorien vorher an) — oder (b) genutzte, aber nirgends
angelegte Namen in `list_categories` mit ausgeben, damit sie in den
Einstellungen umbenannt und gelöscht werden können.

### Verworfen: Upload-Limit vor dem Spooling prüfen

Eine Ablehnung in der Middleware antwortet mit 413, bevor der Body gelesen
ist. uvicorn schließt danach die Verbindung; der Browser, der noch sendet,
zeigt dann oft einen Verbindungsabbruch statt der Meldung "Datei zu groß".
Heute kommt die Meldung zuverlässig (nach dem vollständigen Empfang). Der
einzige Gewinn wäre gesparter Temp-Plattenplatz bei einem Upload, den nur der
lokale Nutzer selbst auslösen kann (fremde Seiten scheitern am
`X-Finance-Client`-Header). Nicht umsetzen, solange sich die Bedrohungslage
nicht ändert (z. B. Betrieb im Netzwerk).
