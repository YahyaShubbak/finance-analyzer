import type { HelpSection } from "./types";

export const HELP_DE: HelpSection[] = [
  {
    id: "basics",
    title: "So funktioniert die App",
    topics: [
      {
        id: "idea",
        title: "Das Prinzip",
        body: [
          "Sie laden Kontoauszüge und Kreditkartenabrechnungen hoch (PDF, CSV oder Excel). Die App liest daraus die Buchungen, ordnet sie Kategorien zu, erkennt doppelte Buchungen und Umbuchungen zwischen Ihren eigenen Konten und gleicht Kreditkartenabrechnungen mit ihrer Abbuchung vom Girokonto ab. Daraus entstehen die Auswertungen der Übersicht.",
          "Alles läuft auf Ihrem Computer: keine Cloud, kein Konto, keine Verbindung ins Internet. Die Kategorien kommen aus festen Regeln und aus dem, was Sie der App beibringen — es ist keine KI im Spiel.",
          "Die Originaldateien werden unverändert aufbewahrt. So lässt sich jede Buchung auf ihr Original zurückführen, und ein Import kann jederzeit entfernt werden.",
        ],
      },
      {
        id: "first-steps",
        title: "Erste Schritte",
        body: [
          [
            "Unter „Konten“ Ihre Konten anlegen: Girokonto, Sparkonto, Kreditkarten. Tragen Sie die IBAN ein, wo es eine gibt — damit erkennt die App Umbuchungen zwischen Ihren Konten sicherer.",
            "Unter „Importe“ Dateien hineinziehen. Die erste Datei einer Art fragt nach ihrem Konto; spätere Dateien derselben Art erkennt die App selbst.",
            "„Zu prüfen“ durchgehen: Dort stehen Buchungen, deren Kategorie die App nicht sicher bestimmen konnte, nach Empfänger gruppiert.",
            "Die „Übersicht“ zeigt dann Einnahmen, Ausgaben und alles Weitere für den gewählten Zeitraum.",
          ],
        ],
        link: { to: "/accounts", label: "Zu den Konten" },
      },
    ],
  },
  {
    id: "imports",
    title: "Importieren",
    topics: [
      {
        id: "formats",
        title: "Welche Dateien gehen?",
        body: [
          [
            "CSV und Excel: Trennzeichen, Kodierung, Datumsformat und Dezimalkomma werden erkannt; die Exporte der gängigen Banken (u. a. Sparkasse, DKB, ING, comdirect, Commerzbank, N26, Revolut) an ihren Spalten. Ist etwas mehrdeutig (z. B. 02/03/2026), fragt die App, statt zu raten.",
            "PDF: Kontoauszüge und Kartenabrechnungen mit Text. Tabellen werden spaltenweise gelesen, sonst zeilenweise.",
            "Eingescannte PDFs (nur Bilder) gehen nicht — nehmen Sie dafür den CSV-Export Ihrer Bank.",
          ],
        ],
      },
      {
        id: "preview",
        title: "Die Vorschau",
        body: [
          "Jede Datei wird zuerst nur gelesen und als Vorschau gezeigt: neue Buchungen, sichere Duplikate (werden übersprungen), mögliche Duplikate (werden behalten, bis Sie anders entscheiden) und Zeilen, die nicht gelesen werden konnten. Erst „Importieren“ übernimmt die Buchungen.",
          "Selbstprüfung: Nennt ein Kontoauszug alten und neuen Saldo, prüft die App „alter Saldo + Buchungen = neuer Saldo“; eine Kartenabrechnung prüft sie gegen den Abrechnungsbetrag. Ein ✓ heißt, es fehlt nichts; sonst warnt sie, dass eine Buchung fehlen könnte.",
        ],
        link: { to: "/imports", label: "Zu den Importen" },
      },
      {
        id: "auto",
        title: "Automatischer Import bekannter Dateien",
        body: [
          "Die erste Datei einer Art (z. B. ein Auszug einer bestimmten Bank) fragt nach dem Konto und wartet auf „Importieren“. Die nächste Datei dieser Art wird erkannt — am Format und an der Konto- oder Kartennummer, die sie nennt, oder an der IBAN eines Ihrer Konten — und landet im selben Konto, mit denselben Einstellungen.",
          "Zeigt ihre Vorschau nichts zu prüfen (keine Warnung, kein mögliches Duplikat, keine unlesbare Zeile, Salden stimmen), importiert sie sich ohne Klick. Mit „Rückgängig“ direkt danach entfernen Sie sie wieder, etwa um ein anderes Konto zu wählen. Abschalten lässt sich das mit „Erkannte Dateien sofort importieren“ auf der Seite „Importe“.",
        ],
      },
      {
        id: "check-original",
        title: "Mit dem Original prüfen",
        body: [
          "„Mit dem Original prüfen“ zeigt links die Seiten der Datei und rechts, was daraus gelesen wurde. Zeigen Sie rechts auf eine Buchung, um zu sehen, wo sie im Original steht, oder klicken Sie links auf einen Kasten. Grün ist eine gelesene Buchung, orange eine Zeile, die wie eine Buchung aussieht, aber nicht gelesen wurde.",
          "Die Ansicht öffnet sich von selbst beim ersten Import einer Dateiart und wenn etwas nicht stimmt. Mit „Stimmt — Dateien dieser Art künftig ohne Nachfrage in … importieren“ fragt sie für diese Art und dieses Konto nicht mehr (bei Problemen öffnet sie sich trotzdem).",
        ],
      },
      {
        id: "teach",
        title: "Den Leser anlernen",
        body: [
          "Liest die App eine Datei falsch oder gar nicht, können Sie ihr zeigen, wie sie aussieht: In „Mit dem Original anlernen“ klicken Sie eine Buchungszeile als Beispiel an und sagen, welches Wort Datum, Text und Betrag ist. Dann markieren Sie Zeilen, die übersprungen werden sollen, und – wenn vorhanden – die Zeile mit dem Abrechnungsbetrag oder den Salden, damit die Selbstprüfung greift.",
          "Wählen Sie außerdem, ob Beträge ohne Vorzeichen Ausgaben oder Einnahmen sind. Nach jedem Schritt wird die Datei neu gelesen. Beim Import merkt sich die App das Gelernte für alle künftigen Dateien dieser Art.",
        ],
      },
      {
        id: "two-sources",
        title: "Derselbe Monat aus zwei Quellen",
        body: [
          "Importieren Sie für denselben Zeitraum z. B. den PDF-Auszug und den CSV-Export, erkennt die App die gleichen Buchungen und zählt sie nur einmal. Was nur eine der beiden Dateien enthält (etwa die Händlerkategorie), ergänzt sie bei der bereits vorhandenen Buchung.",
        ],
      },
    ],
  },
  {
    id: "counting",
    title: "Wie gezählt wird",
    topics: [
      {
        id: "types",
        title: "Einnahme, Ausgabe, Erstattung, Umbuchung",
        body: [
          [
            "Einnahme: Geld, das Sie bekommen (Gehalt, Zinsen, Geschenke …).",
            "Ausgabe: Geld, das Sie ausgeben.",
            "Erstattung: eine Ausgabe mit positivem Betrag — Geld, das für eine Ausgabe zurückkommt (Rückgabe, Gutschrift, ein Freund zahlt seinen Anteil). Sie verringert die Ausgaben ihrer Kategorie und zählt nicht als Einnahme.",
            "Umbuchung: Geld zwischen Ihren eigenen Konten, auch das Begleichen einer Kreditkartenabrechnung vom Girokonto. Umbuchungen zählen weder als Einnahme noch als Ausgabe — sonst würde ein Kauf mit der Karte doppelt gezählt.",
          ],
          "Duplikate und Buchungen archivierter Konten zählen nirgends mit.",
        ],
      },
      {
        id: "net-vs-balance",
        title: "Warum ist der Netto-Cashflow nicht mein Kontostand?",
        body: [
          "Der Netto-Cashflow ist Einnahmen minus Ausgaben im gewählten Zeitraum über alle gewählten Konten — kein Kontostand. Er weicht vom Stand des Girokontos ab, zum Beispiel weil:",
          [
            "Kreditkartenkäufe schon als Ausgabe zählen, die Abrechnung aber noch nicht vom Girokonto abgebucht ist;",
            "Geld von außerhalb auf eine Karte gezahlt wurde (z. B. vor dem ersten importierten Auszug oder von einem Konto, das nicht in der App ist);",
            "der Zeitraum nicht alle Buchungen umfasst oder ein Konto archiviert ist;",
            "der Anfangsstand des Kontos vor dem ersten Auszug nicht mitzählt.",
          ],
          "Den Stand eines Kontos sehen Sie unter „Konten“.",
        ],
        link: { to: "/accounts", label: "Zu den Konten" },
      },
      {
        id: "transfers",
        title: "Wie werden Umbuchungen erkannt?",
        body: [
          "Zwei Buchungen auf zwei Ihrer Konten mit genau demselben Betrag (einmal ab, einmal zu) innerhalb weniger Tage gelten als Umbuchung. Eingetragene IBANs machen das sicherer: Nennt eine Buchung die IBAN Ihres anderen Kontos, wird dieses Paar bevorzugt; nennt sie eine fremde IBAN (Vermieter, Freund), gilt sie nicht als Umbuchung, auch wenn der Betrag passt.",
          "Zahlungen auf eine Kreditkarte sind Umbuchungen, wenn sie von Ihnen kommen. Kommt das Geld von einer fremden IBAN — etwa wenn jemand Ihnen einen Flug, den Sie für ihn gebucht haben, direkt auf die Karte zurückzahlt —, ist es eine Erstattung und verringert Ihre Ausgaben. Dafür muss die App Ihre eigenen IBANs kennen (bei den Konten eintragen oder aus Ihren Auszügen).",
        ],
      },
    ],
  },
  {
    id: "cards",
    title: "Kreditkarten und Abgleich",
    topics: [
      {
        id: "card-bills",
        title: "Abrechnung und Abbuchung",
        body: [
          "Die Käufe auf der Kartenabrechnung sind die eigentlichen Ausgaben. Die Abbuchung der Abrechnung vom Girokonto ist eine Umbuchung — die App verknüpft beide, damit nichts doppelt zählt.",
          "Automatisch verknüpft wird nur, wenn genau eine Abbuchung genau den Abrechnungsbetrag hat. Sonst schlägt die Seite „Abgleich“ passende Abbuchungen vor, die Sie bestätigen.",
          "Haben Sie für eine Karte keine Abrechnungen importiert, zählt ihre Abbuchung vom Girokonto als Ausgabe der Kategorie „Kreditkartenabrechnungen“ — so geht die Ausgabe nicht verloren.",
        ],
        link: { to: "/reconciliation", label: "Zum Abgleich" },
      },
    ],
  },
  {
    id: "categories",
    title: "Kategorien",
    topics: [
      {
        id: "assign",
        title: "Kategorien zuweisen und lernen",
        body: [
          "Klicken Sie in „Buchungen“ (oder in einer Liste der Übersicht) auf die Kategorie einer Buchung, um sie zu ändern. Die App lernt daraus den Empfänger und sortiert ähnliche vorhandene und künftige Buchungen genauso ein. Zeilen ohne erkennbaren Empfänger (z. B. eine bloße PayPal-Zeile) ändern nur sich selbst.",
          "In „Zu prüfen“ sind unsichere Buchungen nach Empfänger gruppiert: Eine Kategorie für die ganze Gruppe genügt. Dort lässt sich auch der Typ einer Buchung ändern (Einnahme, Ausgabe, Umbuchung).",
          "Von Hand gesetzte Kategorien ändert keine Regel mehr.",
        ],
        link: { to: "/needs-review", label: "Zu „Zu prüfen“" },
      },
      {
        id: "manage",
        title: "Eigene Kategorien und gelernte Regeln",
        body: [
          "Unter „Einstellungen → Kategorien“ legen Sie eigene Kategorien an, benennen sie um (Buchungen, Regeln und Budget ziehen mit) oder löschen sie. „Gelernte Kategorien“ zeigt, was die App gelernt hat; dort können Sie Gelerntes vergessen. „Kategorisierungsregeln“ wendet die Regeln erneut auf alle vorhandenen Buchungen an — Ihre Korrekturen bleiben.",
        ],
        link: { to: "/settings", label: "Zu den Einstellungen" },
      },
    ],
  },
  {
    id: "pages",
    title: "Die Seiten",
    topics: [
      {
        id: "overview",
        title: "Übersicht",
        body: [
          "Zeitraum und Konto wählen Sie oben; die Wahl bleibt gespeichert. Ein Klick auf einen Monat im Diagramm listet seine Buchungen, ein Klick auf eine Kategorie die Buchungen hinter ihrem Betrag — durchsuchbar und sortierbar nach Datum, Konto, Typ und Betrag. Darunter: Ihre Budgets, die Aufteilung nach Konten, Umbuchungen, wiederkehrende Buchungen (Abos, Miete, Gehalt) und eine Prognose für die nächsten Monate.",
        ],
        link: { to: "/", label: "Zur Übersicht" },
      },
      {
        id: "transactions",
        title: "Buchungen",
        body: [
          "Alle Buchungen, durchsuchbar (Groß-/Kleinschreibung und Umlaute egal: „muller“ findet „Müller“), filterbar nach Konto, Typ, Kategorie und Zeitraum, sortierbar durch Klick auf die Spaltenköpfe.",
        ],
        link: { to: "/transactions", label: "Zu den Buchungen" },
      },
      {
        id: "places",
        title: "Orte",
        body: [
          "Ausgaben nach Land und Stadt sowie Online-Käufe. Der Ort wird nur aus dem gelesen, was die Abrechnung angibt — nie geraten. Überweisungen und Lastschriften nennen keinen Ort und stehen unter „Ohne Ortsangabe“.",
        ],
        link: { to: "/places", label: "Zu den Orten" },
      },
      {
        id: "points",
        title: "Bonuspunkte",
        body: [
          "Punkte und Meilen, die in Ihren Kartenabrechnungen (PDF) stehen: Punkte je Buchung, Einlösungen, Punktestand und Wert in Euro. Den Wert je Punkt können Sie je Programm ändern. CSV- und Excel-Exporte enthalten keine Punkte.",
        ],
        link: { to: "/points", label: "Zu den Bonuspunkten" },
      },
      {
        id: "budgets",
        title: "Budgets",
        body: [
          "Ein monatliches Ausgabenziel je Kategorie. Die Übersicht zeigt, wie weit Sie in diesem Monat sind.",
        ],
        link: { to: "/budgets", label: "Zu den Budgets" },
      },
    ],
  },
  {
    id: "data",
    title: "Ihre Daten",
    topics: [
      {
        id: "where",
        title: "Wo liegen die Daten?",
        body: [
          "In Ihrem persönlichen Datenordner, nicht im Programmordner — unter Linux ~/.local/share/finance-analyzer, unter macOS ~/Library/Application Support/finance-analyzer, unter Windows %LOCALAPPDATA%\\finance-analyzer. Den genauen Ort zeigt „Einstellungen → Wo Ihre Daten liegen“. Ein Update des Programms lässt Ihre Daten unberührt.",
        ],
      },
      {
        id: "backup",
        title: "Sichern und wiederherstellen",
        body: [
          "„Einstellungen → Sicherung“ erstellt eine ZIP-Datei mit der Datenbank und allen Originaldateien. Die Sicherung ist nicht verschlüsselt — bewahren Sie Kopien an einem sicheren Ort auf (z. B. einem verschlüsselten Laufwerk). Mit „Aus einer Sicherungsdatei wiederherstellen“ holen Sie einen gesicherten Stand zurück; den aktuellen Stand sichert die App vorher selbst.",
          "„Alles zurücksetzen“ löscht alle Daten unwiderruflich — nur eine Sicherung bringt sie zurück.",
        ],
        link: { to: "/settings", label: "Zu den Einstellungen" },
      },
      {
        id: "privacy",
        title: "Sicherheit",
        body: [
          "Die App ist nur auf diesem Computer erreichbar (127.0.0.1) und lehnt Anfragen anderer Webseiten ab. Es gibt keine Anmeldung: Wer Ihr Benutzerkonto auf diesem Computer benutzt, kann die App öffnen. Auf einem gemeinsam genutzten Computer verwenden Sie daher getrennte Benutzerkonten.",
        ],
      },
    ],
  },
  {
    id: "troubleshooting",
    title: "Fehlerbehebung",
    intro: "Häufige Probleme und was dagegen hilft.",
    topics: [
      {
        id: "nothing-read",
        title: "Aus einer Datei wurden keine oder falsche Buchungen gelesen",
        body: [
          [
            "Öffnen Sie „Mit dem Original prüfen“: Orange markierte Zeilen sehen wie Buchungen aus, wurden aber nicht gelesen.",
            "Lernen Sie den Leser mit „Mit dem Original anlernen“ an (siehe „Den Leser anlernen“). Das Gelernte gilt dann für alle Dateien dieser Art.",
            "Ist das PDF eingescannt (Text lässt sich nicht markieren), kann die App es nicht lesen — nehmen Sie den CSV-Export der Bank.",
          ],
        ],
      },
      {
        id: "selfcheck",
        title: "Die Selbstprüfung meldet, dass eine Buchung fehlen könnte",
        body: [
          "Die gelesenen Buchungen ergeben nicht den Saldo oder Abrechnungsbetrag der Datei. Vergleichen Sie in „Mit dem Original prüfen“ die Liste mit dem Original — oft ist es eine Buchung über einen Seitenumbruch oder eine Zeile mit ungewöhnlichem Aufbau. Lernen Sie den Leser an oder importieren Sie trotzdem und ergänzen Sie den Rest über eine CSV-Datei.",
        ],
      },
      {
        id: "wrong-account",
        title: "Eine Datei ist im falschen Konto gelandet",
        body: [
          "Direkt nach dem Import: „Rückgängig“ und das richtige Konto wählen. Später: auf der Seite „Importe“ den Import entfernen und die Datei erneut importieren. Abgleiche und Umbuchungen werden dabei neu berechnet.",
        ],
        link: { to: "/imports", label: "Zu den Importen" },
      },
      {
        id: "double",
        title: "Eine Buchung erscheint doppelt",
        body: [
          "Mögliche Duplikate (gleicher Betrag, ähnliches Datum, aber nicht eindeutig gleich) behält die App vorsichtshalber. Prüfen Sie sie in der Vorschau unter „Duplikate prüfen“. Haben Sie dieselbe Datei zweimal importiert, entfernen Sie einen der Importe unter „Importe“.",
        ],
      },
      {
        id: "card-twice",
        title: "Kartenausgaben zählen doppelt — oder die Abbuchung zählt als Ausgabe",
        body: [
          "Dann ist die Kartenabrechnung noch nicht mit ihrer Abbuchung vom Girokonto verknüpft. Auf der Seite „Abgleich“ steht sie als offen; bestätigen Sie dort die passende Abbuchung. Fehlt die Abrechnung, importieren Sie sie — sonst zählt die Abbuchung bewusst als Ausgabe „Kreditkartenabrechnungen“.",
        ],
        link: { to: "/reconciliation", label: "Zum Abgleich" },
      },
      {
        id: "transfer-counted",
        title: "Geld zwischen meinen Konten zählt als Einnahme oder Ausgabe",
        body: [
          "Tragen Sie unter „Konten“ die IBANs Ihrer Konten ein und importieren Sie die Auszüge beider Konten für den Zeitraum — eine Umbuchung wird erkannt, wenn beide Seiten in der App sind. Steht die Buchung unter „Zu prüfen“, können Sie dort ihren Typ auf „Umbuchung“ setzen.",
          "Umgekehrt: Zählt eine Zahlung von Ihrem eigenen Konto auf die Karte als Erstattung, kennt die App die IBAN dieses Kontos nicht. Tragen Sie sie bei dem Konto ein.",
        ],
        link: { to: "/accounts", label: "Zu den Konten" },
      },
      {
        id: "wrong-category",
        title: "Viele Buchungen haben die falsche Kategorie",
        body: [
          "Ändern Sie die Kategorie einer davon — die App lernt den Empfänger und sortiert die übrigen mit. Unter „Einstellungen → Gelernte Kategorien“ nehmen Sie eine falsch gelernte Regel zurück.",
        ],
      },
      {
        id: "points-missing",
        title: "Bonuspunkte fehlen",
        body: [
          "Punkte stehen nur in den PDF-Abrechnungen. Importieren Sie auch die PDFs dieser Karte; Buchungen, die schon aus einer CSV-Datei da sind, werden dabei nicht doppelt gezählt.",
        ],
      },
      {
        id: "outdated",
        title: "Nach einem Update fehlt etwas oder eine Fehlermeldung erscheint",
        body: [
          "Starten Sie das Programm neu: ./run.sh --restart (Windows: run.bat --restart) und laden Sie die Seite danach neu (Strg+Umschalt+R). Bleibt die Seite leer oder bei „Lädt …“, führen Sie das Installationsprogramm erneut aus — es baut die Oberfläche neu, Ihre Daten bleiben erhalten.",
        ],
      },
      {
        id: "start",
        title: "Die App startet nicht",
        body: [
          [
            "„The app is already running“: Sie läuft schon, vielleicht ohne Fenster — öffnen Sie http://127.0.0.1:8420 (bzw. Ihren Port). Beenden mit ./run.sh --stop, neu starten mit ./run.sh --restart (Windows: run.bat …).",
            "„port … is used by another program“: Ein anderes Programm belegt den Port. Starten Sie die App auf einem anderen: ./run.sh --port 8421.",
            "„the app is already running with the data in …“: Eine andere Instanz nutzt denselben Datenordner. Verwenden Sie diese oder beenden Sie sie mit ./run.sh --stop.",
            "„Invalid Host header“: Öffnen Sie die App über http://127.0.0.1:PORT oder http://localhost:PORT.",
            "„The app is not installed yet“: Führen Sie zuerst das Installationsprogramm aus (install.sh bzw. install.bat).",
          ],
        ],
      },
    ],
  },
];
