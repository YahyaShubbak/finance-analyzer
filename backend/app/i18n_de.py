"""German translations of the user-facing messages (see app.i18n).

Key: the English message exactly as written in the code, placeholders
included; value: the German text with the same placeholders.
tests/test_i18n.py checks that every ``tr("...")`` in the code has an
entry here and that the placeholders match.
"""
from __future__ import annotations

DE: dict[str, str] = {
    # --- general / API -----------------------------------------------------
    "account_id must be a comma-separated list of numbers.":
        "account_id muss eine durch Kommas getrennte Liste von Zahlen sein.",
    "Account not found": "Konto nicht gefunden",
    "An account named '{name}' already exists.": "Ein Konto namens „{name}“ gibt es bereits.",
    "Budget not found": "Budget nicht gefunden",
    "Invalid 'month' — expected format YYYY-MM.": "Ungültiger Monat — erwartet wird das Format JJJJ-MM.",
    "Invalid month '{month}' — expected format YYYY-MM.":
        "Ungültiger Monat „{month}“ — erwartet wird das Format JJJJ-MM.",
    "A budget for category '{category}' already exists.": "Für die Kategorie „{category}“ gibt es bereits ein Budget.",
    "Credit-card account not found": "Kreditkartenkonto nicht gefunden",
    "Statement not found": "Abrechnung nicht gefunden",
    "Transaction not found": "Buchung nicht gefunden",
    "File is too large (limit: {limit} MB).": "Die Datei ist zu groß (Grenze: {limit} MB).",
    "not a valid IBAN": "keine gültige IBAN",
    "IBAN check digits are wrong — please check for typos": "Die IBAN-Prüfziffern stimmen nicht — bitte auf Tippfehler prüfen",
    "must be a 3-letter ISO 4217 currency code, e.g. EUR": "muss ein dreistelliger ISO-4217-Währungscode sein, z. B. EUR",
    "must not be empty": "darf nicht leer sein",

    # --- imports -------------------------------------------------------------
    "Purchases are listed as positive numbers in this credit-card file, so all amounts were inverted (purchases "
    "negative, refunds and payments positive). If that is wrong, open \"Adjust columns / formats\" and untick "
    "\"Invert all amounts\".":
        "In dieser Kreditkartendatei stehen Käufe als positive Zahlen, deshalb wurden alle Beträge umgekehrt "
        "(Käufe negativ, Erstattungen und Zahlungen positiv). Falls das nicht stimmt, öffnen Sie „Spalten / "
        "Formate anpassen“ und entfernen Sie den Haken bei „Alle Beträge umkehren“.",
    "Unsupported file type '{suffix}'. Allowed: {allowed}": "Nicht unterstützter Dateityp „{suffix}“. Erlaubt: {allowed}",
    "Invalid import options: {error}": "Ungültige Import-Optionen: {error}",
    "No importer available for file type: {suffix}": "Für diesen Dateityp gibt es keinen Import: {suffix}",
    "Importer cannot handle file: {path}": "Diese Datei kann nicht importiert werden: {path}",
    "This file looks like a credit-card statement, but '{account}' is not a credit-card account. Choose the "
    "credit-card account (or create one) for this file.":
        "Diese Datei sieht nach einer Kreditkartenabrechnung aus, aber „{account}“ ist kein Kreditkartenkonto. "
        "Wählen Sie für diese Datei das Kreditkartenkonto (oder legen Sie eines an).",
    "This PDF looks like an account statement, but '{account}' is a credit-card account. That is fine for a card "
    "account with its own IBAN — otherwise choose the bank account.":
        "Dieses PDF sieht nach einem Kontoauszug aus, aber „{account}“ ist ein Kreditkartenkonto. Das passt bei "
        "einem Kartenkonto mit eigener IBAN — andernfalls wählen Sie das Bankkonto.",
    "Unknown account_id={account_id}": "Unbekanntes Konto (account_id={account_id})",
    "This file appears to have already been imported ({count} transactions, on {date}).":
        "Diese Datei wurde offenbar bereits importiert ({count} Buchungen, am {date}).",
    "This file could not be reliably parsed and was not imported.":
        "Diese Datei konnte nicht zuverlässig gelesen werden und wurde nicht importiert.",
    "Preview not found or has expired. Please re-upload the file.":
        "Die Vorschau wurde nicht gefunden oder ist abgelaufen. Bitte laden Sie die Datei erneut hoch.",
    "Invalid staging id.": "Ungültige Vorschau-ID.",
    "Unknown import_id={import_id}": "Unbekannter Import (import_id={import_id})",

    # tabular files (CSV / XLSX)
    "Card export with merchant category": "Kartenexport mit Händlerkategorie",
    # categories
    "Please enter a name.": "Bitte geben Sie einen Namen ein.",
    "A category name can have at most {count} characters.": "Ein Kategoriename darf höchstens {count} Zeichen haben.",
    "“{name}” is a built-in category.": "„{name}“ ist eine eingebaute Kategorie.",
    "The category “{name}” already exists.": "Die Kategorie „{name}“ gibt es bereits.",
    "Category not found.": "Kategorie nicht gefunden.",
    "Unknown replacement category “{name}”.": "Unbekannte Ersatzkategorie „{name}“.",
    "File is empty.": "Die Datei ist leer.",
    "Header row {number} does not exist in this file.": "Kopfzeile {number} gibt es in dieser Datei nicht.",
    "Unsupported date format {format!r}.": "Nicht unterstütztes Datumsformat „{format}“.",
    "Column {column!r} does not exist in this file.": "Die Spalte „{column}“ gibt es in dieser Datei nicht.",
    "Could not identify the date, amount and description columns. Please map them manually.":
        "Die Spalten für Datum, Betrag und Beschreibung konnten nicht erkannt werden. Bitte ordnen Sie sie von Hand zu.",
    "The date format is ambiguous (e.g. 02/03 could be 2 March or 3 February). Please choose the date format.":
        "Das Datumsformat ist nicht eindeutig (z. B. kann 02/03 der 2. März oder der 3. Februar sein). "
        "Bitte wählen Sie das Datumsformat.",
    "Amounts like \"1.500\" or \"1,234\" could use either decimal separator. Please choose the decimal separator.":
        "Beträge wie „1.500“ oder „1,234“ können mit beiden Dezimaltrennzeichen gemeint sein. "
        "Bitte wählen Sie das Dezimaltrennzeichen.",
    "Row {row}: missing date.": "Zeile {row}: Datum fehlt.",
    "Row {row}: could not parse date {date!r}.": "Zeile {row}: Datum „{date}“ konnte nicht gelesen werden.",
    "Row {row}: {problem}.": "Zeile {row}: {problem}.",
    "Row {row}: missing amount.": "Zeile {row}: Betrag fehlt.",
    "Row {row}: both debit ({debit}) and credit ({credit}) are filled; using credit minus debit.":
        "Zeile {row}: Soll ({debit}) und Haben ({credit}) sind beide ausgefüllt; verwendet wird Haben minus Soll.",
    "{count} row(s) without date and amount were ignored (e.g. balance or summary lines).":
        "{count} Zeile(n) ohne Datum und Betrag wurden ignoriert (z. B. Salden- oder Summenzeilen).",
    "{count} balance row(s) (e.g. opening/closing balance) were skipped.":
        "{count} Saldenzeile(n) (z. B. Anfangs-/Endsaldo) wurden übersprungen.",
    "{count} pending or cancelled row(s) were skipped — booked transactions appear in a later export.":
        "{count} vorgemerkte oder stornierte Zeile(n) wurden übersprungen — gebuchte Umsätze erscheinen in einem "
        "späteren Export.",
    "Unknown currency {currency!r} — the account's currency will be used for these rows.":
        "Unbekannte Währung „{currency}“ — für diese Zeilen wird die Währung des Kontos verwendet.",
    "No transaction rows detected.": "Keine Buchungszeilen gefunden.",

    # amount / date parsing
    "empty amount": "leerer Betrag",
    "could not parse amount: {amount!r}": "Betrag „{amount}“ konnte nicht gelesen werden",
    "could not parse amount: {amount!r} (unexpected digit grouping)":
        "Betrag „{amount}“ konnte nicht gelesen werden (unerwartete Zifferngruppierung)",
    "amount {amount!r} has more than two decimal places": "Betrag „{amount}“ hat mehr als zwei Nachkommastellen",
    "amount {amount!r} is ambiguous: '{separator}' could be a decimal or a thousands separator":
        "Betrag „{amount}“ ist nicht eindeutig: „{separator}“ kann Dezimal- oder Tausendertrennzeichen sein",
    "empty date": "leeres Datum",
    "could not parse date: {date!r}": "Datum „{date}“ konnte nicht gelesen werden",
    "could not parse date {date!r} as {format}": "Datum „{date}“ passt nicht zum Format {format}",
    "date {date!r} is ambiguous (could be {formats})": "Datum „{date}“ ist nicht eindeutig (möglich: {formats})",
    " or ": " oder ",

    # PDF
    "No extractable text found in this PDF. It may be a scanned image — OCR is not enabled in V1. Please provide "
    "a text-based PDF, or a CSV export instead.":
        "In diesem PDF wurde kein auslesbarer Text gefunden. Vermutlich ist es ein eingescanntes Bild — "
        "Texterkennung (OCR) gibt es in dieser Version nicht. Bitte verwenden Sie ein textbasiertes PDF oder "
        "stattdessen einen CSV-Export.",
    "Could not confidently identify this document's layout (bank statement vs. credit-card statement vs. "
    "unknown). No transactions were imported. The original file is preserved so you can inspect it, or a "
    "bank-specific parser can be added.":
        "Der Aufbau dieses Dokuments konnte nicht sicher erkannt werden (Kontoauszug, Kreditkartenabrechnung "
        "oder unbekannt). Es wurden keine Buchungen importiert. Die Originaldatei bleibt erhalten, damit Sie sie "
        "prüfen können oder ein bankspezifischer Leser ergänzt werden kann.",
    "The dates in this PDF could be read as day/month or month/day. Please import a CSV export of this "
    "statement instead.":
        "Die Datumsangaben in diesem PDF können als Tag/Monat oder Monat/Tag gelesen werden. Bitte importieren "
        "Sie stattdessen einen CSV-Export dieses Auszugs.",
    "Line {line}: could not parse date {date!r}.": "Zeile {line}: Datum „{date}“ konnte nicht gelesen werden.",
    "Line {line}: could not parse amount {amount!r}.": "Zeile {line}: Betrag „{amount}“ konnte nicht gelesen werden.",
    "No transaction lines matched the generic bank-statement layout.":
        "Keine Zeile entsprach dem allgemeinen Aufbau eines Kontoauszugs.",
    "No transaction lines matched the generic credit-card layout.":
        "Keine Zeile entsprach dem allgemeinen Aufbau einer Kreditkartenabrechnung.",
    "{count} balance line(s) (e.g. opening/closing balance) were skipped.":
        "{count} Saldenzeile(n) (z. B. alter/neuer Kontostand) wurden übersprungen.",
    "{count} line(s) starting with a date could not be read as a transaction, e.g. {example!r}. Check them "
    "against the statement.":
        "{count} Zeile(n) mit einem Datum am Anfang konnten nicht als Buchung gelesen werden, z. B. „{example}“. "
        "Bitte gleichen Sie sie mit dem Auszug ab.",
    "The statement shows dates without a year and no statement period was found, so those dates cannot be read.":
        "Der Auszug zeigt Datumsangaben ohne Jahr, und es wurde kein Abrechnungszeitraum gefunden — diese Daten "
        "können daher nicht gelesen werden.",
    "This statement prints money in and money out in separate columns without a sign, so the direction of each "
    "amount can't be read reliably from the PDF. Please import the bank's CSV export of this statement instead.":
        "Dieser Auszug führt Eingänge und Ausgänge in getrennten Spalten ohne Vorzeichen, deshalb lässt sich die "
        "Richtung der Beträge aus dem PDF nicht zuverlässig lesen. Bitte importieren Sie stattdessen den "
        "CSV-Export der Bank für diesen Auszug.",
    "The bookings don't add up: opening balance + bookings differs from the closing balance by {difference}. "
    "A booking may have been missed or misread — please compare with the statement.":
        "Die Buchungen gehen nicht auf: Alter Saldo + Buchungen weicht um {difference} vom neuen Saldo ab. "
        "Möglicherweise wurde eine Buchung nicht erkannt oder falsch gelesen — bitte mit dem Auszug abgleichen.",
    "This statement covers several sub-accounts with their own balances, and more than one has bookings. "
    "All of them are imported into the chosen account.":
        "Dieser Auszug umfasst mehrere Unterkonten mit eigenem Saldo, und mehr als eines hat Buchungen. "
        "Alle werden in das gewählte Konto importiert.",
    "{count} row(s) with a date but no amount in the amount column could not be read as a booking. "
    "Check them against the statement.":
        "{count} Zeile(n) mit Datum, aber ohne Betrag in der Betragsspalte konnten nicht als Buchung gelesen "
        "werden. Bitte mit dem Auszug abgleichen.",
    "No statement total line detected — reconciliation will be limited.":
        "Keine Zeile mit dem Abrechnungsbetrag gefunden — der Abgleich ist nur eingeschränkt möglich.",

    # duplicates and review
    "Same account, date, amount, and description as an existing transaction.":
        "Gleiches Konto, Datum, Betrag und gleiche Beschreibung wie eine vorhandene Buchung.",
    "{similarity} + same amount + {date_gap}.": "{similarity} + gleicher Betrag + {date_gap}.",
    "Same merchant": "Gleicher Händler",
    "Similar description": "Ähnliche Beschreibung",
    "same date": "gleiches Datum",
    "date difference of 1 day": "1 Tag Abstand",
    "date difference of {days} days": "{days} Tage Abstand",
    "Merchant could not be confidently normalized.": "Der Händler konnte nicht sicher bestimmt werden.",
    "Category could not be confidently determined.": "Die Kategorie konnte nicht sicher bestimmt werden.",
    "Paid onto the card from someone else's account, so counted as a refund."
    " Give it the category of the expense it repays.":
        "Von einem fremden Konto auf die Karte gezahlt und daher als Erstattung gezählt."
        " Geben Sie ihr die Kategorie der Ausgabe, die sie erstattet.",

    # rules
    "Unknown transaction_id={transaction_id}": "Unbekannte Buchung (transaction_id={transaction_id})",
    "Transaction has no original description to derive a rule from.":
        "Die Buchung hat keine ursprüngliche Beschreibung, aus der sich eine Regel ableiten ließe.",
    "Learned rule not found.": "Gelernte Regel nicht gefunden.",

    # reconciliation
    "Unknown statement_id={statement_id}": "Unbekannte Abrechnung (statement_id={statement_id})",
    "Unknown reconciliation_id={reconciliation_id}": "Unbekannter Abgleich (reconciliation_id={reconciliation_id})",
    "Unknown bank_debit_transaction_id={bank_debit_transaction_id}":
        "Unbekannte Bankbuchung (bank_debit_transaction_id={bank_debit_transaction_id})",
    "The payment must be a transaction on a bank account.": "Die Zahlung muss eine Buchung auf einem Bankkonto sein.",
    "The payment must be money leaving the bank account.": "Die Zahlung muss ein Abgang vom Bankkonto sein.",
    "This transaction is already the payment of another statement.":
        "Diese Buchung ist bereits die Zahlung einer anderen Abrechnung.",

    # backup / restore
    "Backup was created but could not be read back.": "Die Sicherung wurde erstellt, konnte aber nicht wieder gelesen werden.",
    "Backup not found.": "Sicherung nicht gefunden.",
    "Restore requires explicit confirmation.": "Die Wiederherstellung muss ausdrücklich bestätigt werden.",
    "No database found to back up yet.": "Es gibt noch keine Datenbank, die gesichert werden könnte.",
    "This backup contains an unsafe file name: {name!r}": "Diese Sicherung enthält einen unsicheren Dateinamen: „{name}“",
    "This file is not a valid backup archive (not a ZIP file).":
        "Diese Datei ist kein gültiges Sicherungsarchiv (keine ZIP-Datei).",
    "This backup archive is damaged: {error}": "Dieses Sicherungsarchiv ist beschädigt: {error}",
    "This backup is missing its database file (finance.db).": "In dieser Sicherung fehlt die Datenbankdatei (finance.db).",
    "This backup is missing its manifest (manifest.json).": "In dieser Sicherung fehlt das Manifest (manifest.json).",
    "This backup would unpack to {size} MB, which exceeds the limit of {limit} MB.":
        "Diese Sicherung wäre entpackt {size} MB groß und überschreitet damit die Grenze von {limit} MB.",
    "This backup's manifest is corrupt: {error}": "Das Manifest dieser Sicherung ist beschädigt: {error}",
    "This backup's manifest is corrupt: not a JSON object.": "Das Manifest dieser Sicherung ist beschädigt: kein JSON-Objekt.",
    "This backup's database failed an integrity check: {integrity}":
        "Die Datenbank dieser Sicherung hat die Integritätsprüfung nicht bestanden: {integrity}",
    "This backup's database is missing expected tables: {tables}":
        "In der Datenbank dieser Sicherung fehlen erwartete Tabellen: {tables}",
    "This backup was created by a newer version of the app. Update the app, then restore it again.":
        "Diese Sicherung stammt von einer neueren Version des Programms. Aktualisieren Sie das Programm und "
        "stellen Sie sie dann erneut wieder her.",
    "This backup's database file is corrupt or not a valid SQLite database: {error}":
        "Die Datenbankdatei dieser Sicherung ist beschädigt oder keine gültige SQLite-Datenbank: {error}",
    "This backup's database could not be upgraded to the current version: {error}":
        "Die Datenbank dieser Sicherung konnte nicht auf die aktuelle Version gebracht werden: {error}",
    "Restore failed while replacing files: {error}.": "Die Wiederherstellung ist beim Ersetzen der Dateien fehlgeschlagen: {error}.",
    "Your previous data is saved in {file}.": "Ihre bisherigen Daten sind in {file} gesichert.",
    "Some rows of this file now look like transactions that are already imported. "
    "Please check the preview and import it yourself.":
        "Einige Zeilen dieser Datei sehen inzwischen wie bereits importierte Buchungen aus. "
        "Bitte prüfen Sie die Vorschau und importieren Sie die Datei selbst.",
    "This file names the IBAN of your account '{other}', not of '{account}'. "
    "Check that you chose the right account.":
        "Diese Datei nennt die IBAN Ihres Kontos „{other}“, nicht die von „{account}“. "
        "Prüfen Sie, ob Sie das richtige Konto gewählt haben.",
    "The account '{name}' already has this IBAN.": "Das Konto „{name}“ hat bereits diese IBAN.",
    "This backup's files can't be unpacked here: {error}":
        "Die Dateien dieser Sicherung lassen sich hier nicht entpacken: {error}",
    "This statement is already imported (from {file}).": "Diese Abrechnung ist bereits importiert (aus {file}).",
    "A number in the request is too large.": "Eine Zahl in der Anfrage ist zu groß.",
    "There is already a budget for “{name}”. Remove it first.":
        "Für „{name}“ gibt es bereits ein Budget. Entfernen Sie es zuerst.",
    "amount {amount!r} is implausibly large": "Betrag {amount!r} ist unplausibel groß",
    "Could not open the spreadsheet — it may be damaged or not an XLSX file ({error}).":
        "Die Tabelle lässt sich nicht öffnen — sie ist vielleicht beschädigt oder keine XLSX-Datei ({error}).",
    "The spreadsheet is empty.": "Die Tabelle ist leer.",
    "Could not open the PDF — it may be damaged or not a PDF file.":
        "Die PDF lässt sich nicht öffnen — sie ist vielleicht beschädigt oder keine PDF-Datei.",
    "Only PDF files have pages.": "Nur PDF-Dateien haben Seiten.",
    "This page doesn't exist.": "Diese Seite gibt es nicht.",
    "The original file is no longer there.": "Die Originaldatei ist nicht mehr vorhanden.",
    "The template needs at least the date and the amount of a booking.":
        "Die Vorlage braucht mindestens das Datum und den Betrag einer Buchung.",
    "{count} dated line(s) did not fit the template — check them in the review.":
        "{count} Datumszeile(n) passten nicht zur Vorlage — bitte in der Prüfansicht ansehen.",
    "No booking matched the template.": "Keine Buchung passte zur Vorlage.",
    "This bonus program doesn't exist.": "Dieses Bonusprogramm gibt es nicht.",
    "The same booking from the other kind of file (statement and export): same amount and merchant, {date_gap}.":
        "Dieselbe Buchung aus der anderen Dateiart (Abrechnung und Export): gleicher Betrag und Händler, {date_gap}.",
    "This backup's database contains code the app never creates (triggers or views); it was changed outside the app and is not restored.":
        "Die Datenbank dieser Sicherung enthält Code, den die App nie anlegt (Trigger oder Views); "
        "sie wurde außerhalb der App verändert und wird nicht wiederhergestellt.",
    "The file is too large to be a statement (more than {rows} rows or {cells} cells). Please export a shorter period.":
        "Die Datei ist zu groß für einen Kontoauszug (mehr als {rows} Zeilen oder {cells} Zellen). "
        "Bitte exportieren Sie einen kürzeren Zeitraum.",
    "This PDF is password-protected. Please save it without a password (e.g. print it to a new PDF) and import that file.":
        "Dieses PDF ist passwortgeschützt. Bitte speichern Sie es ohne Passwort (z. B. als neues PDF drucken) "
        "und importieren Sie diese Datei.",
    "must be at most {count} characters": "darf höchstens {count} Zeichen lang sein",
}
