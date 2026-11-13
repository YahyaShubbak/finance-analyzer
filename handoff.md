# Handoff: Audit-Nacharbeit finance-analyzer

Stand: 2026-11-13. Für das nächste Modell (Opus 5.5), das ohne den bisherigen
Chatverlauf weiterarbeitet. Der Nutzer spricht Deutsch; Code, Kommentare,
Tests und die Doku im Repo sind Englisch.

## Ausgangslage

Ein Architektur-Audit des Repos (Version 0.8.0) hat 15 größere Befunde
(Nr. 1–15) und eine Tabelle kleiner „Quick Wins“ ergeben. Stand 2026-11-13:
**alle 15 Befunde und alle Quick Wins sind bearbeitet.** Was bewusst nicht
umgesetzt wurde, steht jeweils dabei und gesammelt im Abschnitt „Bewusst
offen gelassen“ am Ende.

Der Nutzer committet selbst. Bis `e23b96d` ist alles committet (Befunde
1–13). Der letzte Durchgang vom 2026-11-13 (Befund 15, Rest von 14, alle
restlichen Quick Wins und kleinen Frontend-Befunde) lag danach uncommittet
im Arbeitsverzeichnis; die Commit-Gruppen dazu stehen im nächsten Abschnitt.
Vor neuer Arbeit mit `git status` prüfen, ob das inzwischen committet ist —
wenn nicht, den Nutzer darauf hinweisen und diese Dateien nicht anfassen.

## Durchgang vom 2026-11-13: Commit-Gruppen

Der Nutzer hat verlangt, alle restlichen Punkte ohne Rückfrage abzuarbeiten.
Die Commit-Messages stehen im Chat; die Gruppen haben getrennte Dateien und
sind in dieser Reihenfolge zu committen (jeder Stand baut und testet):

1. **Installer, Start/Stopp der App, Sicherungen (Backend):** `install.sh`,
   `install.ps1`, `README.md`, `backend/app/__main__.py`,
   `backend/app/api/routes/system.py`, `backend/app/api/routes/backup.py`,
   `backend/app/services/backup_service.py`, `reset_service.py`,
   `backend/app/i18n_de.py`, `backend/tests/test_instance_lock.py`,
   `test_run_stop.py`, `test_backup_restore.py`. (Ein Commit, weil
   `i18n_de.py` Texte für Stopp und Sicherungen enthält.)
2. **Punkte in der Währung der Karte (Backend):** `schemas/points.py`,
   `services/points_service.py`, `tests/test_points.py`.
3. **Genutzte, nie angelegte Kategorien:** `services/category_service.py`,
   `tests/test_custom_categories.py`.
4. **Trefferzahlen gelernter Regeln einmal pro Datenstand:**
   `services/rule_service.py`, `tests/test_category_learning.py`.
5. **Frontend, kleine Befunde + Punkte-Währung + Sicherung löschen:** alle
   geänderten Dateien unter `frontend/` außer denen der Gruppen 6–8 (ein
   Commit, weil `i18n/en.ts`, `de.ts`, `lib/format.ts`, `types/index.ts`
   Teile von allen dreien enthalten).
6. **Übersichtsseite zeigt Ladefehler:** `pages/Overview.tsx`,
   `pages/Overview.test.tsx`, `components/reports/CurrencySection.tsx`.
7. **Review zeichnet beim Hover nur betroffene Zeilen:**
   `components/imports/ImportReview.tsx`, `ImportReview.test.tsx`.
8. **Tests und CI:** `backend/tests/test_frontend_mirrors.py`,
   `.github/workflows/ci.yml`, `release.yml`,
   `frontend/src/test/app.integration.test.tsx`.
9. **Doku:** `CHANGELOG.md`, `handoff.md`.

Stand der CI nach dem ersten Push (Lauf zu `035cfe5`, 2026-11-13): Backend-,
Frontend- und beide `install.sh`-Jobs grün — die neuen Linux-Schritte (Update
bei laufender App, Ablehnung eines leeren Datenordners) laufen also. Zwei
Dinge schlugen fehl und sind danach behoben worden (Commit-Message im Chat,
Dateien `.github/workflows/ci.yml`, `frontend/src/test/app.integration.test.tsx`):

- `install.bat`-Jobs: Der Installer tat, was er sollte (Update, dann
  Ablehnung), aber ein `pwsh`-Schritt endet mit dem Exit-Code des letzten
  Programms — hier der gewollten Ablehnung (1). Der Schritt endet jetzt mit
  `exit 0`.
- Integrationstest „Dashboard totals and charts render“: `getByText("Income")`
  / `("Expenses")` fand zwei Elemente, sobald die Konten-Tabelle (mit
  gleichnamigen Spalten) vor der zweiten Zeile ankam. Der Test bestand nur,
  solange die Summen zuerst kamen; jetzt `getAllByText`.

Noch ungeprüft: `release.yml` (läuft erst bei einem Tag; ruft `ci.yml` als
`workflow_call` auf und vergleicht Tag und Version — die Versions-Extraktion
per `sed` ist lokal ausprobiert).

Die Fehlermeldungen eines CI-Laufs stehen ohne Anmeldung unter
`https://api.github.com/repos/<owner>/<repo>/check-runs/<job-id>/annotations`
(Job-IDs aus `/actions/runs/<run-id>/jobs`); `gh` ist auf dieser Maschine
nicht installiert.

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
uv run --locked pytest -q -p no:cacheprovider          # ca. 3 min, zuletzt 887 bestanden
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
- `tests/test_architecture.py` liest die Imports aus dem Quelltext und
  verlangt: kein Modul braucht ein Modul, das es selbst braucht (auch nicht
  über einen Import in einer Funktion); Imports eigener Module stehen am
  Modulanfang (einzige Ausnahme, im Test aufgelistet: `reset_service` liest
  `engine` erst beim Aufruf); kein `_privater` Name wird aus einem anderen
  Modul importiert; `db`, `importers`, `normalization` importieren nichts
  aus `services`, `reconciliation`, `schemas`, `api`; nur `api` und `main`
  importieren `api`, und keine Route importiert eine andere Route. Schlägt
  einer dieser Tests fehl, gehört die Hilfsfunktion in ein Modul, das beide
  Seiten benutzen dürfen — nicht der Import in die Funktion.
- `tests/test_frontend_mirrors.py` liest `frontend/src/lib/categories.ts` und
  `frontend/src/types/index.ts` und vergleicht sie mit dem Backend: die
  eingebauten Kategorien (samt Übersetzungen), die festen Wertelisten
  (`AccountType`, `TransactionType`, …) und für 33 Typen, dass das Frontend
  kein Feld erwartet, das das Backend-Schema nicht hat (weglassen darf es
  welche). Neues Feld in einer API-Antwort = beide Seiten ändern.
- Die Test-Engines erzwingen Fremdschlüssel wie die echte App
  (`enforce_foreign_keys` in `tests/conftest.py`). Vorher liefen die Tests
  ohne `PRAGMA foreign_keys=ON`, die App mit. Wer in einem Test eine eigene
  Engine baut und Löschpfade prüft, sollte sie ebenfalls damit versehen.
- Wer Buchungen löscht, muss vorher die Verweise übersprungener Rohzeilen
  auf sie lösen (`RawTransaction.duplicate_of_transaction_id`, siehe
  Befund 10) — sonst lehnt SQLite das Löschen ab.
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
- Vitest scheitert in **jeder** Testdatei mit „Vitest failed to find the
  runner“, wenn das Arbeitsverzeichnis mit kleinem Laufwerksbuchstaben
  betreten wurde (`cd /c/Users/...` in Git Bash ergibt `c:\...`). Mit
  `cd "C:/Users/..."` wechseln; `node -e "console.log(process.cwd())"` zeigt,
  was Node sieht.
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

## Befunde 7–15: alle erledigt

Zeilennummern stammen vom Audit-Stand und können sich verschoben haben; die
Funktionsnamen sind verlässlich.

### Messung zu 7–9

Künstlicher Bestand mit 30.000 Buchungen, 36 Kartenabrechnungen, 72 Importen
(Skript nicht im Repo; es baut die Daten per ORM und ruft die Service-Funktionen
direkt auf). Vorher → nachher:

| Pfad | vorher | nachher |
|---|---|---|
| Kategorie zuweisen mit Lernen (`learn_category`) | 1,2 s | 0,11–0,14 s |
| Review-Queue, eine Seite (`review_groups`) | 0,6 s | 0,12 s (0,4 s beim ersten Aufruf nach einer Datenänderung) |
| Vorschau: Zeilen klassifizieren (`classify_import_rows`, 100 Zeilen) | 0,54 s | 0,23 s |
| Zahlungen verknüpfen nach jedem Import (`link_pending_payments`) | 0,86 s | 0,03–0,06 s |
| Kartenrechnungs-Zahler sortieren (`sort_card_bill_payees`) | 0,30 s | 0,006 s, wenn sich keine Zahlertexte geändert haben |
| `derive_statements_from_exports`, `retype_card_payments` | 2 ms, 7 ms | unverändert |

### 7. Nacharbeit pro Import skaliert mit dem Gesamtbestand — erledigt
- Umgesetzt: `link_pending_payments` (`reconciliation/engine.py`) holt
  „bearbeitet“, „hat Zahlung“ und die Beträge der freien Bankabbuchungen in je
  einer Abfrage; eine Abrechnung, deren Betrag keine freie Abbuchung hat, wird
  gar nicht mehr geprüft, und eine ohne Treffer nicht mehr neu berechnet und
  committet. Eine Abrechnung ohne gespeicherte `Reconciliation` bekommt
  weiterhin eine. Im Frontend laufen höchstens zwei Uploads gleichzeitig
  (`uploadSlot` in `state/importQueue.ts`, Karte zeigt „Wartet, bis sie dran
  ist…“), der Commit wartet nicht mehr auf das Neuladen aller Listen
  (`hooks/useImports.ts`), und das doppelte `history.refetch()` ist weg
  (die Prop `onDone` der Karte gibt es nicht mehr).
- Bewusst nicht umgesetzt, weil gemessen unerheblich:
  `derive_statements_from_exports` und `retype_card_payments` auf das
  Datumsfenster des Imports begrenzen. Beide skalieren mit der Zahl der
  Karten-Exporte bzw. der Karten-Eingänge, nicht mit dem Bestand. Wer es doch
  macht: `derive…` sortiert erst **nach** sich neue „Card bills“ ein
  (`sort_card_bill_payees`), ein Fenster dürfte die also nicht verpassen.
- Bewusst offen gelassen: Commits in Dateireihenfolge; nach jedem Commit wird weiterhin der
  ganze Query-Cache invalidiert (nur nicht mehr abgewartet).

### 8. Review-Queue und Kategorie-Lernen: Vollscans pro Klick — erledigt
- Umgesetzt: `remembered(session, name, build)` in `db/session.py` merkt sich
  Werte, die aus dem ganzen Bestand errechnet werden, bis etwas committet wird
  (Zähler über SQLAlchemy-Events). Eine Session mit eigenen, noch nicht
  committeten Änderungen bekommt immer einen frischen Wert, der nicht behalten
  wird. Darüber laufen `chain_index` (mit `payees_only=True`: überlebt
  Commits, die weder Buchungen anlegen/löschen noch `merchant` /
  `normalized_description` ändern), `category_memory()` und der
  `CategorySuggester`. `derive_category_pattern` hat einen `lru_cache`.
  `recategorize_matching` und `_rename_matching` (`rule_service.py`) laden per
  `_could_contain` nur noch Buchungen, in denen das Muster vorkommen kann
  (SQL-Funktion `fold`, Obermenge; die exakte Prüfung bleibt in Python).
- Regeln für jede weitere Nutzung von `remembered`: den zurückgegebenen Wert
  nie verändern; nach rohen SQL-Schreibzugriffen an der Session vorbei
  `note_data_changed()` aufrufen (macht der Restore).
- `rule_service.py` importiert `app.db.session` auf Modulebene, damit `fold`
  für jede danach geöffnete Verbindung registriert ist — eine Engine, deren
  Verbindung **vor** diesem Import geöffnet wurde, kennt `fold` nicht
  (Fehler „no such function: fold“).
- Nachgezogen am 2026-11-13: `list_learned_category_rules` zählt die
  Treffer jeder Regel einmal pro Datenstand (`remembered`,
  `_learned_rule_matches` liefert `{regel_id: anzahl}` — keine ORM-Objekte
  im Cache). `reapply_rules` lädt bewusst alles.

### 9. Eine PDF-Vorschau liest die Datei fünf- bis siebenmal — erledigt
- Umgesetzt: `_signature` (`api/routes/imports.py`) berechnet die
  Datei-Signatur einmal pro Parse-Ergebnis statt bis zu dreimal;
  `classify_import_rows` vergleicht nur noch mit Buchungen im Datumsbereich der
  Datei ± 3 Tage; ein automatischer Import klassifiziert seine Zeilen einmal
  statt zweimal (`classified`-Parameter von `commit_parsed_import`).
- Bleibt so: bis zu drei Parse-Durchläufe pro Vorschau (erster Versuch, mit
  den Optionen des erkannten Dateityps, mit umgekehrten Vorzeichen) und der
  erneute Parse beim Commit — jeder liest mit anderen Optionen bzw. ist
  Absicht („Commit liest dieselben Bytes noch einmal“).

### 10. Relationale Verknüpfungen stecken in JSON-Blobs — erledigt
- Umgesetzt: `raw_transactions` hat zwei neue Spalten (Migration
  `a6f4c2d81e93`, Erkennungs-Zweig in `_detect_unversioned_revision`):
  `duplicate_of_transaction_id` (Fremdschlüssel auf `transactions.id`,
  indexiert) ersetzt `"_duplicate_of"`, `kept_by_user` ersetzt
  `"_kept_by_user"` im JSON. Die Migration zieht die Werte aus dem JSON in
  die Spalten und entfernt sie dort; ein Verweis auf eine nicht mehr
  vorhandene Buchung wird verworfen; Schlüssel gleichen Namens mit anderem
  Werttyp (Spalte einer Datei, kein Eintrag der App) bleiben unangetastet.
  Der Downgrade schreibt die Werte zurück ins JSON.
- Alle Stellen lesen und schreiben die Spalten: `commit_parsed_import`,
  `statement_transaction_ids` (`engine.py`), `_row_transactions`
  (`points_service.py`), `refresh_locations` (lädt nur noch die
  übersprungenen Zeilen der betroffenen Buchungen statt aller),
  `_rehome_shared_bookings` / `remove_import`, `find_twins`. Die Konstante
  `KEPT_BY_USER` gibt es nicht mehr.
- Folgen des Fremdschlüssels: `raw_transactions` und `transactions`
  verweisen jetzt gegenseitig aufeinander. Der neue Schlüssel ist deshalb
  mit `use_alter=True` deklariert (sonst warnt `metadata.sorted_tables`, das
  der Reset benutzt), und die Beziehungen `RawTransaction.transaction` /
  `Transaction.raw_transaction` nennen ihren Schlüssel ausdrücklich.
  `remove_import` löst vor dem Löschen der Buchungen die Verweise der
  eigenen Zeilen (zwei Zeilen einer Datei standen für dieselbe Buchung),
  `reset_everything` setzt die Spalte vor dem Leeren der Tabellen auf NULL.
- Nebenbei: `tests/conftest.py` erzwingt jetzt Fremdschlüssel (siehe
  „Regeln des Repos“); alle 814 vorher vorhandenen Tests liefen damit ohne
  Änderung durch.
- Geprüft außer mit Tests: echte App auf einer Wegwerf-Datenbank im alten
  Format gestartet (Kopie vor dem Upgrade wurde angelegt, die Buchung zog
  beim Entfernen der ersten Datei zur zweiten um, danach ließ sich auch die
  zweite entfernen).
- Bewusst nicht umgesetzt: `twin_merge` markiert Zwillinge weiter über
  `Transaction.duplicate_of_id` (war nie im JSON). Die übrigen `_…`-Schlüssel
  im JSON (`_details`, `_booking_text`, `_merchant_category`,
  `_counterparty_iban`, `_value_date`) sind Daten der Zeile, keine
  Verknüpfungen, und bleiben dort.

### 11. Zyklische Service-Abhängigkeiten (108 funktionslokale Imports) — erledigt
- Ausgangslage, gemessen: 117 funktionslokale Imports eigener Module und
  zwei Gruppen von Modulen, die sich im Kreis brauchten —
  `pdf_importer` ↔ `pdf_layouts/template` und neun Module um
  `reconciliation/engine`, `import_service`, `rule_service`,
  `transfer_marking`, `transfer_detection_service`,
  `duplicate_preview_service`, `account_recognition`, `chains`,
  `points_service`.
- Umgesetzt — Hilfsfunktionen dorthin verschoben, wo beide Seiten sie holen
  dürfen (Verhalten unverändert, nur der Ort):
  - `app/iban.py`: `IBAN_RE`, `valid_iban` (aus `account_recognition`).
  - `app/services/import_reading.py`: `ImportServiceError`,
    `build_importer_for`, `parse_file`, `document_account_mismatch`,
    `document_account_warning`, `purchases_listed_as_positive` (aus
    `import_service`; Lesen einer Datei ohne Datenbank).
  - `app/services/rule_patterns.py`: `derive_merchant_pattern`,
    `derive_category_pattern`, `category_rule_source`, `raw_extra`,
    `raw_counterparty` samt Wortlisten (aus `rule_service`; reine
    Textfunktionen).
  - `transfer_marking.py` hat jetzt auch `natural_type`,
    `manually_corrected_type_ids`, `unpair_transfer` (aus
    `transfer_detection_service`); der Start-Job `link_card_bills` ist nach
    `app/services/card_bill_linking.py` gezogen (er ruft Abgleich und
    Transfer-Erkennung nacheinander auf und steht deshalb über beiden).
  - `account_read` in `services/account_service.py` (vorher `_to_read` in
    `api/routes/accounts.py`, von `credit_card_service` aus der Route
    geholt); `app/api/transaction_listing.py` mit `transaction_read`,
    `search_filter`, `sorted_by`, `TransactionSort`, `SortOrder` (vorher in
    `routes/transactions.py`, von `routes/analytics.py` importiert).
  - `app/importers/pdf_layouts/lines.py`: `group_lines`.
  - Umbenannt, weil von einem zweiten Modul benutzt: `places`, `NOT_A_TOWN`
    (`normalization/location.py`), `error_result` (`importers/tabular.py`),
    `validate_currency` (`schemas/account.py`), `descriptions_overlap`,
    `is_same_merchant` (`duplicate_preview_service.py`).
- Danach ist der Importgraph zyklenfrei, und 114 der 115 verbliebenen
  funktionslokalen Imports stehen jetzt am Modulanfang. Reihenfolge der
  Dienste von unten nach oben: `iban`, `import_reading`, `rule_patterns` →
  `account_recognition`, `chains`, `category_memory` →
  `duplicate_preview_service` → `transfer_marking` →
  `transfer_detection_service`, `reconciliation/engine` →
  `card_bill_linking`, `rule_service`, `points_service` → `import_service`.
- Abgesichert durch `tests/test_architecture.py` (siehe „Regeln des
  Repos“); vier der sechs Tests schlagen auf dem Stand davor fehl, die
  anderen zwei schreiben fest, was schon galt.
- Geprüft außer mit Tests: echte App auf einem leeren Datenordner gestartet
  und die Frontend-Tests dagegen laufen lassen (elf Läufe: zehnmal 58
  bestanden; im allerersten Lauf schlug ein Test fehl, dessen Name nicht
  festgehalten wurde und der sich nicht wiederholen ließ — bei einem
  erneuten Auftreten nachgehen).
- Bewusst nicht angefasst: funktionslokale Imports fremder Pakete
  (`sqlalchemy`, `fastapi.responses`) und die in Tests. Kein Eintrag im
  Changelog (für Nutzer ändert sich nichts).

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

### 13. Import-Karte verliert ihr Ergebnis und versteckt Fehler — erledigt
- Umgesetzt: Was eine Anfrage der Karte ändert, steht jetzt in der
  Warteschlange (`CardSnapshot` in `state/importQueue.ts`), nicht mehr in
  `useState` der Karte: Vorschau, Import-Ergebnis, die laufende Anfrage
  (`busy`: `waiting` / `reading` / `importing` / `undoing`), Fehler
  (`error`, `commitError`, `autoRefused`) und die Merker (`manual`,
  `accountChosen`, …). Die Karte liest alles aus ihrer `snapshot`-Prop und
  schickt jede Anfrage über `request()` (`mutateAsync`, Ergebnis per
  `onSnapshot` in die Warteschlange). Folgen:
  - Die Antwort auf einen Import kommt auch an, wenn die Seite inzwischen
    verlassen wurde; vorher zeigte die Karte danach wieder die Vorschau und
    ein zweiter Import-Versuch endete in „Preview not found“.
  - Wird die Seite geöffnet, während der Import noch läuft, wird nicht ein
    zweites Mal importiert (`busy` ist bekannt).
  - Dateien werden weitergelesen, während eine andere Seite offen ist
    (vorher gab eine wartende Karte ihren Platz zurück und begann beim
    Zurückkommen neu).
  - Ein Fehler, der kam, während die Seite nicht offen war, steht beim
    Zurückkommen auf der Karte.
- Fehler stehen im Review: `ImportReview` hat die Prop `error` und zeigt sie
  als `role="alert"` über der Fußzeile (Import-Fehler und Fehler beim
  erneuten Lesen). Der Import-Knopf im Review ist gesperrt, solange ein
  angelernter Reader angewendet wird.
- Ein Review zur Zeit: `reviewKey` in der Warteschlange (`useReviewKey`,
  `showReview`). Wollen mehrere Dateien ihr Review zeigen, öffnet sich das
  nächste, wenn das offene geschlossen wird; Escape schließt nur das offene.
- Wird eine Karte entfernt, während ihre Datei hochgeladen wird, wird die
  hochgeladene Datei verworfen (`saveSnapshot` meldet `false`, wenn die
  Datei nicht mehr in der Warteschlange ist) — das war einer der kleinen
  Frontend-Befunde unten.
- `components/imports/ImportFileCards.tsx` verdrahtet Karten und
  Warteschlange (vorher in `pages/Imports.tsx`); die Tests in
  `ImportFileCard.test.tsx` laufen darüber mit der echten Warteschlange
  (zwölf Tests, sieben neu). Gegenprobe: zwei Szenarien gegen den alten
  Stand gefahren (Import bei Seitenwechsel, Weiterlesen), die übrigen per
  herausgenommener Schutzstelle.
- Die Karte hat jetzt vier `useState` (vorher 17) und fünf Effekte. Vier
  davon haben weiterhin unterdrückte Abhängigkeiten, weil sie Funktionen
  aus dem Render aufrufen; das geht erst mit einem ausgelagerten Reducer
  ganz weg (bewusst nicht gemacht: die Zustandshoheit liegt jetzt richtig,
  ein Reducer wäre ein Umschreiben der Karte ohne weiteren Fehler, den er
  behebt).
- Geändertes Verhalten, das auffallen kann: Nach einem fehlgeschlagenen
  Upload wird beim erneuten Öffnen der Seite weiterhin neu hochgeladen; das
  Auswahlfeld für das Konto bleibt nach „Rückgängig“ sichtbar, bis der neue
  Upload geklappt hat (vorher verschwand es sofort, und nach einem Fehler
  gab es keinen Weg mehr, ein Konto zu wählen).
- Nicht mit echtem Browser ausprobiert; StrictMode (doppelte Effekte im
  Entwicklungsmodus) ist nur durchdacht, nicht getestet — dafür gibt es
  `started` und `sending` als Refs in der Karte.

### 14. Fehlgeschlagene Abfragen erscheinen als „keine Daten“ — erledigt
- Erledigt: `pages/CreditCards.tsx`, `pages/Budgets.tsx`, `pages/Accounts.tsx`
  und `components/imports/ImportHistory.tsx` zeigen `ErrorState` mit
  „Erneut versuchen“, wenn die Abfrage fehlschlägt und keine (alten) Daten da
  sind (`isError && !data`). Test: `pages/loadErrors.test.tsx`.
- Ebenfalls erledigt: `components/settings/BackupSection.tsx` und
  `LearnedRulesSection.tsx` (am 2026-11-12 noch uncommittet).
- Am 2026-11-13 nachgezogen: `pages/Overview.tsx` zeigt je Abschnitt
  (Monate, Kategorien, Konten, Prognose) `ErrorState` mit „Erneut
  versuchen“ über die Hilfsfunktion `failed(query)`; im
  Mehrwährungs-Fall über die Prop `monthlyFailed` von `CurrencySection`.
  Test: vier Fälle in `pages/Overview.test.tsx`.
- Falle beim Testen: `beforeEach(() => mock.mockReset())` ohne geschweifte
  Klammern gibt die Mock-Funktion zurück; Vitest ruft sie als Aufräum-Funktion
  auf und der Test scheitert an deren Rückgabewert.

### 15. Installer: Datenordner-Wechsel und Update bei laufender App — erledigt
- Datenordner: Hat der bisher benutzte Ordner (aus `finance.env`, sonst der
  Standardordner) eine `finance.db` und der neu gewählte keine, warnen beide
  Installer und fragen, ob wirklich leer begonnen werden soll (Vorgabe:
  nein, dann bleibt der bisherige Ordner). Ohne Rückfrage-Möglichkeit
  (`--yes` / `-Yes`, kein Terminal) brechen sie mit einer Anleitung ab,
  bevor etwas geändert ist. Ein Ordner mit eigener `finance.db` wird ohne
  Frage übernommen (Wahl zwischen zwei Datenbeständen). Nicht betroffen:
  der Umzug aus dem Programmordner (`MOVE_LEGACY`).
- Laufende App: `python -m app --status` (neu; Exit 0 = läuft, 3 = läuft
  nicht, alles andere = nicht feststellbar) wird vor dem Paket-Schritt mit
  dem vorhandenen venv aufgerufen. Läuft die App, bieten die Installer
  `--stop` an. Windows: ohne Stopp wird abgebrochen (gesperrte Dateien);
  Linux/macOS: es geht mit einem Hinweis weiter. Lässt sich der Zustand
  nicht feststellen und ist der Port belegt, wird nachgefragt.
- Bewusst nicht umgesetzt: die Daten in den neuen Ordner **umziehen**. Das
  bräuchte eine verallgemeinerte `app.legacy_migration` (kopieren, prüfen,
  umschalten, erst dann löschen); der Installer sagt stattdessen, wie man es
  von Hand macht.
- Geprüft: Test für `--status` in `tests/test_instance_lock.py`; `--status`
  an der echten App (vorher 3, laufend 0, nach `--stop` 3); die beiden neuen
  Blöcke jedes Installers einzeln mit ersetzten Rückfragen durchgespielt
  (Datenordner: fünf Fälle; laufende App: sechs bzw. sieben Fälle),
  `install.ps1` unter Windows PowerShell 5.1, `install.sh` unter Git Bash
  mit `set -euo pipefail`. **Nicht** geprüft: ein vollständiger
  Installer-Lauf mit diesen Fällen (er würde auf dieser Maschine
  Voraussetzungen prüfen und ggf. installieren) und die echten Rückfragen
  am Terminal. Die CI testet weiterhin nur die Erstinstallation.

## Quick Wins

Status wird hier fortgeschrieben.

| Quick Win | Status |
|---|---|
| Kategorie serverseitig prüfen (PATCH Buchung, `assign-category`, `category-rule`, Budget-PUT) | **erledigt in Variante (b), ohne Rückfrage entschieden** — siehe unten |
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
| Feste zwei Nachkommastellen für alle Währungen (`decimal_to_minor_units`; KWD/BHD unlesbar, JPY ×100) | **bewusst nicht umgesetzt** — siehe „Bewusst offen gelassen“ |
| `pre-restore-safety-*`-Backups wachsen unbegrenzt, kein Lösch-Endpunkt | **erledigt**: die neuesten drei bleiben (`_prune_safety_backups`, `SAFETY_BACKUPS_KEPT`); `DELETE /api/backup/{filename}` und „Löschen“ mit Rückfrage in den Einstellungen — nur für echte Backups (`is_backup_zip`: ZIP mit `finance.db` und `manifest.json`), fremde ZIPs im Ordner bleiben unberührt (404) |
| `ImportReview`: jeder Hover rendert Tabelle und Quellzeilen neu | **erledigt**: `BookingRow` und `SourceRow` als `memo` mit stabilen Callbacks; im Test (80 Zeilen) 241 → unter 20 gezeichnete Zeilen pro Hover (`ImportReview.test.tsx` zählt `clsx`-Aufrufe) |
| Backend-Konstanten und Schemas im Frontend von Hand gespiegelt (`lib/categories.ts`, `types/index.ts`) | **abgesichert statt generiert**: `backend/tests/test_frontend_mirrors.py` (siehe „Regeln des Repos“). Nicht umgesetzt: Typen aus dem OpenAPI-Schema generieren |
| Release-Workflow: `contents: write` ohne Tests, kein Abgleich Tag/Version; `curl \| sh` unversioniert; CI testet nur Erstinstallation | **erledigt, in CI ungeprüft**: `release.yml` ruft erst `ci.yml` auf (`workflow_call`), Schreibrecht nur im Release-Job, Tag muss der Version in `pyproject.toml`, `config.py`, `package.json` entsprechen; `install.sh` lädt uv in fester Version (`UV_VERSION`); die Installer-Jobs der CI installieren ein zweites Mal bei laufender App und prüfen die Ablehnung eines leeren Datenordners |
| `--stop` ist unter Windows ein harter Kill (`os.kill(pid, SIGTERM)`) | **erledigt**: unter Windows wird die App zuerst gebeten, sich selbst zu beenden (`POST /api/system/stop` mit der gemeinten PID, sonst 409; intern `signal.raise_signal(SIGINT)` wie Strg+C); antwortet sie nicht, bleibt der Kill. An der echten App geprüft („Application shutdown complete“). `tests/test_run_stop.py` hat eine autouse-Fixture, damit Tests nie eine echte App auf Port 8420 ansprechen |

### Weitere kleine Frontend-Befunde aus dem Audit — alle erledigt

- `state/dashboardPeriod.ts`: unbekannter Preset-Name fällt auf "This month"
  zurück (`dashboardPeriod.test.ts`).
- `pages/Transactions.tsx`, `components/reports/MonthTransactions.tsx`: die
  Seite wird begrenzt, wenn die Liste schrumpft.
- `components/charts/IncomeExpenseChart.tsx`: ein Klick neben die Balken
  wählt keinen Monat mehr (`clickedIndex` in `lib/chartClick.ts`; das
  Verhalten von Recharts selbst ist nicht im Browser nachgestellt).
- `hooks/useCategoryAssignment.ts`: Fehler stehen im eigenen State
  (`mutateAsync`), der Fehler einer überholten Zuweisung geht nicht mehr
  verloren.
- `components/accounts/AccountRow.tsx`: ein fehlgeschlagenes Archivieren
  zeigt die Meldung; `components/budgets/BudgetProgressRow.tsx`: Löschen
  erst nach Rückfrage.
- `ImportFileCard.tsx` `remove()` während des Uploads: mit Befund 13.
- `pages/Points.tsx`: Werte in der Währung der Karte
  (`PointsProgramSummary.currency`, aus den Konten der Importe des
  Programms; Spaltenüberschrift `points.perUnit`). Sind mehrere Programme
  in verschiedenen Währungen da, entfällt die Gesamtsumme.
- `api/client.ts`: `apiGet` nimmt ein `AbortSignal`; die Buchungsliste und
  die Listen hinter Kategorien und Orten reichen das Signal des Query-Caches
  durch. Ein abgebrochener Request wird nicht als „App läuft nicht“ gemeldet.
- Kleinteile: `@playwright/test` entfernt; `currentMonth()` in
  `lib/format.ts`, `CURRENCIES` in `lib/currencies.ts`; 4xx-Antworten werden
  nicht wiederholt (`retryQuery`); ein Query-Key für `/api/system/info`.
- Tests dazu: `components/smallFixes.test.tsx`, `api/client.test.ts`,
  `pages/Points.test.tsx`.
- Der Integrationstest „Dashboard opens successfully“ schlug etwa in einem
  von zehn Läufen fehl (Seiten werden per `lazy` geladen, die Standard-
  Wartezeit von 1 s reichte beim ersten Aufruf nicht immer):
  `configure({ asyncUtilTimeout: 10_000 })` in
  `src/test/app.integration.test.tsx`; danach sechs Läufe grün.

### Kategorie serverseitig prüfen — Variante (b), ohne Rückfrage entschieden

Zur Wahl standen (a) hart prüfen (422 bei unbekannter Kategorie) und (b)
genutzte, aber nie angelegte Namen verwaltbar machen. Der Nutzer war beim
Durchgang vom 2026-11-13 nicht erreichbar und hatte „ohne Rückfrage
fertigmachen“ verlangt; gewählt wurde (b), weil es nichts bricht: freie
Namen bleiben erlaubt (fünf Tests nutzen sie), aber `list_categories`
übernimmt jeden genutzten, nirgends angelegten Namen als eigene Kategorie
(`_adopt_used_names` in `services/category_service.py`: aus Buchungen,
gelernten Regeln und Budgets; von zwei Schreibweisen, die sich nur in
Groß-/Kleinschreibung unterscheiden, die häufigere; eine andere Schreibweise
einer eingebauten Kategorie wird nicht übernommen). Danach lässt sie sich in
den Einstellungen umbenennen und löschen. Die Übernahme passiert beim
Auflisten (ein GET, das schreibt) — bewusst, weil so auch Daten aus alten
Sicherungen ohne weiteren Start-Job erfasst werden.

Will der Nutzer doch (a): in `PATCH /api/transactions/{id}`,
`assign-category`, `category-rule` und Budget-PUT gegen
`BUILT_IN_CATEGORIES` + `CustomCategory` prüfen und die fünf Tests ihre
Kategorien vorher anlegen lassen.

### Verworfen: Upload-Limit vor dem Spooling prüfen

Eine Ablehnung in der Middleware antwortet mit 413, bevor der Body gelesen
ist. uvicorn schließt danach die Verbindung; der Browser, der noch sendet,
zeigt dann oft einen Verbindungsabbruch statt der Meldung "Datei zu groß".
Heute kommt die Meldung zuverlässig (nach dem vollständigen Empfang). Der
einzige Gewinn wäre gesparter Temp-Plattenplatz bei einem Upload, den nur der
lokale Nutzer selbst auslösen kann (fremde Seiten scheitern am
`X-Finance-Client`-Header). Nicht umsetzen, solange sich die Bedrohungslage
nicht ändert (z. B. Betrieb im Netzwerk).

## Bewusst offen gelassen

- **Währungen mit drei oder null Nachkommastellen.** `amount_minor` ist
  überall „Hundertstel“, nicht die kleinste Einheit der Währung. Für JPY
  ist das nur eine Benennungsfrage: 1000 ¥ werden als 100000 gespeichert
  und im Frontend (÷ 100, `Intl` mit JPY) wieder als 1.000 ¥ gezeigt. KWD,
  BHD und andere Währungen mit drei Nachkommastellen lassen sich nicht
  importieren („more than two decimal places“). Das zu ändern hieße, die
  Einheit je Währung zu speichern: Migration aller Beträge, alle Summen,
  Salden, Budgets und jede Formatierung im Frontend. Kein Hinweis, dass der
  Nutzer solche Konten hat.
- **Daten in einen neuen Datenordner umziehen** (Befund 15): die Installer
  fragen nach und erklären den Weg von Hand; ein geprüfter Umzug bräuchte
  eine verallgemeinerte `app.legacy_migration`.
- **`useImportCard`-Reducer** (Befund 13): die Zustandshoheit liegt in der
  Warteschlange; vier Effekte der Karte haben weiter unterdrückte
  Abhängigkeiten.
- **Befund 7:** Commits vieler Dateien laufen in der Reihenfolge, in der
  ihre Vorschauen eintreffen, nicht in Dateireihenfolge (Duplikat- und
  Zwillingserkennung sind reihenfolgeunabhängig ausgelegt); nach jedem
  Import wird der ganze Query-Cache für ungültig erklärt (nicht mehr
  abgewartet).
- **Typen aus dem OpenAPI-Schema generieren:** stattdessen Vergleichstests.
- **Verworfen:** Upload-Limit vor dem Spooling (siehe oben).
- **Nie im echten Browser ausprobiert:** die Änderungen an der Import-Karte
  (Befund 13), der Klick neben die Balken, `--open`. Vollständige
  Installer-Läufe mit den neuen Fällen laufen erst in der CI.
