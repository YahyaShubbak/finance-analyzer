import type { HelpSection } from "./types";

export const HELP_EN: HelpSection[] = [
  {
    id: "basics",
    title: "How the app works",
    topics: [
      {
        id: "idea",
        title: "The idea",
        body: [
          "You upload bank statements and credit-card statements (PDF, CSV or Excel). The app reads their bookings, sorts them into categories, spots duplicates and transfers between your own accounts, and matches card statements with the bank debit that pays them. The Overview is built from that.",
          "Everything runs on your computer: no cloud, no sign-up, no internet connection. Categories come from fixed rules and from what you teach the app — there is no AI involved.",
          "The original files are kept unchanged, so every booking can be traced back to its source and any import can be removed again.",
        ],
      },
      {
        id: "first-steps",
        title: "First steps",
        body: [
          [
            "Create your accounts under “Accounts”: checking, savings, credit cards. Enter the IBAN where there is one — it helps the app recognize transfers between your accounts.",
            "Drop files on the “Imports” page. The first file of a kind asks for its account; later files of the same kind are recognized by themselves.",
            "Go through “Needs Review”: bookings whose category the app could not tell for sure, grouped by payee.",
            "The “Overview” then shows income, expenses and everything else for the chosen period.",
          ],
        ],
        link: { to: "/accounts", label: "Go to Accounts" },
      },
    ],
  },
  {
    id: "imports",
    title: "Importing",
    topics: [
      {
        id: "formats",
        title: "Which files work?",
        body: [
          [
            "CSV and Excel: delimiter, encoding, date format and decimal comma are detected; exports of common banks (Sparkasse, DKB, ING, comdirect, Commerzbank, N26, Revolut and others) by their columns. If something is ambiguous (e.g. 02/03/2026), the app asks instead of guessing.",
            "PDF: bank and card statements containing text. Tables are read by column, everything else line by line.",
            "Scanned PDFs (images only) don't work — use your bank's CSV export instead.",
          ],
        ],
      },
      {
        id: "preview",
        title: "The preview",
        body: [
          "Every file is read into a preview first: new bookings, certain duplicates (skipped), possible duplicates (kept until you decide otherwise) and rows that could not be read. Only “Import” takes the bookings over.",
          "Self-check: when a bank statement states opening and closing balance, the app checks “opening balance + bookings = closing balance”; a card statement is checked against its statement amount. A ✓ means nothing is missing; otherwise it warns that a booking may be missing.",
        ],
        link: { to: "/imports", label: "Go to Imports" },
      },
      {
        id: "auto",
        title: "Known files import themselves",
        body: [
          "The first file of a kind (say, one bank's statement) asks for its account and waits for “Import”. The next file of that kind is recognized — by its format and the account or card number it prints, or by the IBAN of one of your accounts — and goes to the same account with the same settings.",
          "If its preview shows nothing to check (no warning, no possible duplicate, no unreadable row, balances add up), it is imported without a click. “Undo” right afterwards removes it again, e.g. to choose another account. Turn this off with “Import recognized files right away” on the Imports page.",
        ],
      },
      {
        id: "check-original",
        title: "Check against the original",
        body: [
          "“Check against the original” shows the file's pages on the left and what was read on the right. Point at a booking on the right to see where it is in the original, or click a box on the left. Green is a booking that was read, orange a line that looks like a booking but was not read.",
          "It opens by itself on the first import of a kind of file and whenever something is off. Confirming with “Correct — files of this kind go to … without asking from now on” stops it asking for this kind and account (problems still open it).",
        ],
      },
      {
        id: "teach",
        title: "Teach the reader",
        body: [
          "If the app reads a file wrongly or not at all, show it what the file looks like: in “Teach the reader with the original”, click a booking line as an example and say which word is the date, the text and the amount. Then mark lines to skip and — if there is one — the line with the statement amount or balances, so the self-check works.",
          "Also choose whether amounts without a sign are expenses or income. The file is read again after every step. When you import, the app remembers what it learned for all future files of this kind.",
        ],
      },
      {
        id: "two-sources",
        title: "The same month from two sources",
        body: [
          "If you import e.g. both the PDF statement and the CSV export for the same period, the app recognizes the same bookings and counts them once. What only one of the files has (such as the merchant category) is added to the booking already there.",
        ],
      },
    ],
  },
  {
    id: "counting",
    title: "How things are counted",
    topics: [
      {
        id: "types",
        title: "Income, expense, refund, transfer",
        body: [
          [
            "Income: money you receive (salary, interest, gifts …).",
            "Expense: money you spend.",
            "Refund: an expense with a positive amount — money coming back for an expense (a return, a credit, a friend paying their share). It lowers the spending of its category and is not counted as income.",
            "Transfer: money between your own accounts, including paying a card bill from the checking account. Transfers count as neither income nor expense — otherwise a card purchase would be counted twice.",
          ],
          "Duplicates and the bookings of archived accounts are not counted anywhere.",
        ],
      },
      {
        id: "net-vs-balance",
        title: "Why isn't the net cash flow my account balance?",
        body: [
          "Net cash flow is income minus expenses in the chosen period across the chosen accounts — not a balance. It differs from your checking account's balance, for example because:",
          [
            "card purchases already count as expenses while the card bill hasn't been debited from checking yet;",
            "money was paid onto a card from elsewhere (e.g. before the first imported statement, or from an account that isn't in the app);",
            "the period doesn't cover all bookings, or an account is archived;",
            "the account's balance before its first statement isn't included.",
          ],
          "An account's balance is shown on the Accounts page.",
        ],
        link: { to: "/accounts", label: "Go to Accounts" },
      },
      {
        id: "transfers",
        title: "How are transfers recognized?",
        body: [
          "Two bookings on two of your accounts with exactly the same amount (out on one, in on the other) within a few days count as a transfer. Entered IBANs make this more reliable: a booking naming the other account's IBAN is paired first; one naming someone else's IBAN (a landlord, a friend) is never a transfer, even if the amount matches.",
          "Payments onto a credit card are transfers when they come from you. If the money comes from someone else's IBAN — say, someone paying back a flight you booked for them straight onto your card — it is a refund and lowers your spending. For that the app needs to know your own IBANs (enter them with your accounts, or they're read from your statements).",
        ],
      },
    ],
  },
  {
    id: "cards",
    title: "Credit cards and reconciliation",
    topics: [
      {
        id: "card-bills",
        title: "Statement and bank debit",
        body: [
          "The purchases on the card statement are the actual expenses. The debit of the statement from your checking account is a transfer — the app links the two so nothing is counted twice.",
          "They are linked automatically only if exactly one debit has exactly the statement amount. Otherwise the Reconciliation page suggests matching debits for you to confirm.",
          "If you haven't imported any statements for a card, its debit from checking counts as an expense in the category “Card bills” — so the spending isn't lost.",
        ],
        link: { to: "/reconciliation", label: "Go to Reconciliation" },
      },
    ],
  },
  {
    id: "categories",
    title: "Categories",
    topics: [
      {
        id: "assign",
        title: "Assigning and learning categories",
        body: [
          "Click a booking's category on the Transactions page (or in a list on the Overview) to change it. The app learns the payee and sorts similar existing and future bookings the same way. Lines naming no payee (e.g. a bare PayPal line) only change themselves.",
          "“Needs Review” groups uncertain bookings by payee: one category for the whole group is enough. A booking's type (income, expense, transfer) can be changed there too.",
          "Categories set by hand are never changed by a rule.",
        ],
        link: { to: "/needs-review", label: "Go to Needs Review" },
      },
      {
        id: "manage",
        title: "Own categories and learned rules",
        body: [
          "Under “Settings → Categories” you add your own categories, rename them (bookings, rules and budget move along) or delete them. “Learned categories” lists what the app learned; you can forget a rule there. “Categorization rules” applies the rules again to all existing bookings — your corrections are kept.",
        ],
        link: { to: "/settings", label: "Go to Settings" },
      },
    ],
  },
  {
    id: "pages",
    title: "The pages",
    topics: [
      {
        id: "overview",
        title: "Overview",
        body: [
          "Choose the period and account at the top; the choice is remembered. Clicking a month in the chart lists its bookings, clicking a category the bookings behind its amount — searchable and sortable by date, account, type and amount. Below: your budgets, the split by account, transfers, recurring bookings (subscriptions, rent, salary) and a forecast for the coming months.",
        ],
        link: { to: "/", label: "Go to Overview" },
      },
      {
        id: "transactions",
        title: "Transactions",
        body: [
          "All bookings, searchable (case and accents don't matter: “muller” finds “Müller”), filterable by account, type, category and period, sortable by clicking the column headings.",
        ],
        link: { to: "/transactions", label: "Go to Transactions" },
      },
      {
        id: "places",
        title: "Places",
        body: [
          "Spending by country and town, plus online purchases. The place is only read from what the statement states — never guessed. Bank transfers and direct debits name no place and are listed under “No place stated”.",
        ],
        link: { to: "/places", label: "Go to Places" },
      },
      {
        id: "points",
        title: "Bonus points",
        body: [
          "Points and miles listed on your card statements (PDF): points per booking, redemptions, balance and value in euros. The value per point can be changed per programme. CSV and Excel exports contain no points.",
        ],
        link: { to: "/points", label: "Go to Bonus points" },
      },
      {
        id: "budgets",
        title: "Budgets",
        body: ["A monthly spending target per category. The Overview shows how far along you are this month."],
        link: { to: "/budgets", label: "Go to Budgets" },
      },
    ],
  },
  {
    id: "data",
    title: "Your data",
    topics: [
      {
        id: "where",
        title: "Where is my data?",
        body: [
          "In your personal data folder, not in the program folder — on Linux ~/.local/share/finance-analyzer, on macOS ~/Library/Application Support/finance-analyzer, on Windows %LOCALAPPDATA%\\finance-analyzer. “Settings → Where your data lives” shows the exact place. Updating the program leaves your data alone.",
        ],
      },
      {
        id: "backup",
        title: "Backup and restore",
        body: [
          "“Settings → Backup” creates a ZIP file with the database and all original files. Backups are not encrypted — keep copies somewhere safe (e.g. an encrypted drive). “Restore from a backup file” brings a saved state back; the app backs up the current state first.",
          "“Reset everything” deletes all data for good — only a backup brings it back.",
        ],
        link: { to: "/settings", label: "Go to Settings" },
      },
      {
        id: "privacy",
        title: "Security",
        body: [
          "The app can only be reached from this computer (127.0.0.1) and refuses requests from other websites. There is no login: anyone using your user account on this computer can open it. On a shared computer, use separate user accounts.",
        ],
      },
    ],
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting",
    intro: "Common problems and what helps.",
    topics: [
      {
        id: "nothing-read",
        title: "No bookings, or the wrong ones, were read from a file",
        body: [
          [
            "Open “Check against the original”: lines marked orange look like bookings but were not read.",
            "Teach the reader with “Teach the reader with the original” (see “Teach the reader”). What it learns applies to all files of this kind.",
            "If the PDF is scanned (its text can't be selected), the app can't read it — use the bank's CSV export.",
          ],
        ],
      },
      {
        id: "selfcheck",
        title: "The self-check says a booking may be missing",
        body: [
          "The bookings read don't add up to the file's balance or statement amount. Compare the list with the original in “Check against the original” — often it's a booking split by a page break or a line laid out unusually. Teach the reader, or import anyway and add the rest from a CSV file.",
        ],
      },
      {
        id: "wrong-account",
        title: "A file went to the wrong account",
        body: [
          "Right after the import: “Undo” and choose the right account. Later: remove the import on the Imports page and import the file again. Reconciliations and transfers are recalculated.",
        ],
        link: { to: "/imports", label: "Go to Imports" },
      },
      {
        id: "double",
        title: "A booking appears twice",
        body: [
          "Possible duplicates (same amount, similar date, but not clearly the same) are kept to be safe. Check them in the preview under “Review duplicates”. If you imported the same file twice, remove one of the imports on the Imports page.",
        ],
      },
      {
        id: "card-twice",
        title: "Card spending counts twice — or the card bill counts as an expense",
        body: [
          "Then the card statement isn't linked to its debit from checking yet. The Reconciliation page lists it as open; confirm the matching debit there. If the statement is missing, import it — otherwise the debit deliberately counts as a “Card bills” expense.",
        ],
        link: { to: "/reconciliation", label: "Go to Reconciliation" },
      },
      {
        id: "transfer-counted",
        title: "Money between my accounts counts as income or expense",
        body: [
          "Enter your accounts' IBANs on the Accounts page and import the statements of both accounts for the period — a transfer is recognized when both sides are in the app. If the booking is in “Needs Review”, you can set its type to “Transfer” there.",
          "The other way round: if a payment from your own account onto the card counts as a refund, the app doesn't know that account's IBAN. Enter it with the account.",
        ],
        link: { to: "/accounts", label: "Go to Accounts" },
      },
      {
        id: "wrong-category",
        title: "Many bookings have the wrong category",
        body: [
          "Change the category of one of them — the app learns the payee and sorts the others along. Under “Settings → Learned categories” you can take back a rule learned wrongly.",
        ],
      },
      {
        id: "points-missing",
        title: "Bonus points are missing",
        body: [
          "Points are only in the PDF statements. Import this card's PDFs too; bookings already there from a CSV file aren't counted twice.",
        ],
      },
      {
        id: "outdated",
        title: "After an update something is missing or an error appears",
        body: [
          "Restart the program: ./run.sh --restart (Windows: run.bat --restart), then reload the page (Ctrl+Shift+R). If the page stays empty or at “Loading…”, run the installer again — it rebuilds the interface and keeps your data.",
        ],
      },
      {
        id: "start",
        title: "The app doesn't start",
        body: [
          [
            "“The app is already running”: it runs already, perhaps without a window — open http://127.0.0.1:8420 (or your port). Stop it with ./run.sh --stop, start it anew with ./run.sh --restart (Windows: run.bat …).",
            "“port … is used by another program”: start the app on another port: ./run.sh --port 8421.",
            "“the app is already running with the data in …”: another instance uses the same data folder. Use that one, or stop it with ./run.sh --stop.",
            "“Invalid Host header”: open the app via http://127.0.0.1:PORT or http://localhost:PORT.",
            "“The app is not installed yet”: run the installer first (install.sh or install.bat).",
          ],
        ],
      },
    ],
  },
];
