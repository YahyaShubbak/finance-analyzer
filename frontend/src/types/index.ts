export type AccountType = "checking" | "savings" | "credit_card" | "other";
export type DocumentType = "bank_statement" | "credit_card_statement" | "unknown";
export type TransactionType = "income" | "expense" | "transfer" | "unknown";
export type ReconciliationStatus = "reconciled" | "mismatch" | "unresolved" | "pending";

export interface Account {
  id: number;
  name: string;
  account_type: AccountType;
  currency: string;
  iban: string | null;
  created_at: string;
  is_archived: boolean;
  transaction_count: number;
  transactions_balance_minor: number;
  opening_balance_minor: number | null;
  opening_balance_date: string | null;
  current_balance_minor: number;
}

export interface Transaction {
  id: number;
  account_id: number;
  account_name: string;
  transaction_date: string;
  normalized_description: string;
  merchant: string | null;
  category: string | null;
  amount_minor: number;
  currency: string;
  transaction_type: TransactionType;
  is_duplicate: boolean;
  is_transfer: boolean;
  needs_review: boolean;
  review_reason: string | null;
  notes: string | null;
  source_filename: string | null;
  /** where it took place: ISO country code and town, or an online purchase; all empty: unknown */
  country: string | null;
  city: string | null;
  online: boolean;
  /** review queue only: what similar sorted transactions are — to confirm, not set */
  suggested_category?: string | null;
  /** bonus points the booking earned, as its statement says */
  points?: number | null;
}

export interface TransactionListResponse {
  items: Transaction[];
  total: number;
  page: number;
  page_size: number;
}

export interface MerchantRule {
  id: number;
  pattern: string;
  is_regex: boolean;
  normalized_merchant: string;
  is_user_defined: boolean;
}

export interface CategoryRule {
  id: number;
  pattern: string;
  is_regex: boolean;
  match_field: string;
  category: string;
  priority: number;
  is_user_defined: boolean;
}

export interface CreateRuleResult {
  transaction: Transaction;
  merchant_rule: MerchantRule | null;
  /** null for a category assignment the app could not learn from (no identifiable payee) */
  category_rule: CategoryRule | null;
  /** other existing transactions the learned category was applied to */
  applied_to: number;
}

/** A category rule the app learned from the user's assignments. */
export interface LearnedCategoryRule {
  id: number;
  pattern: string;
  match_field: string;
  category: string;
  matching_transactions: number;
  created_at: string;
}

export type TransactionSortKey = "date" | "amount" | "account" | "type";

export interface TransactionSort {
  key: TransactionSortKey;
  order: "asc" | "desc";
}

export interface TransactionFilters {
  sort?: TransactionSortKey;
  order?: "asc" | "desc";
  account_id?: number;
  category?: string;
  merchant?: string;
  transaction_type?: TransactionType;
  start?: string;
  end?: string;
  search?: string;
  include_transfers?: boolean;
  needs_review?: boolean;
  /** as the reports count: archived accounts left out */
  active_accounts_only?: boolean;
  page?: number;
  page_size?: number;
}

export interface ImportIssue {
  severity: "warning" | "error";
  message: string;
  row_index: number | null;
}

export interface ParsedTransactionPreview {
  source_row_index: number;
  original_date_text: string | null;
  original_description: string | null;
  original_amount_text: string | null;
  original_currency_text: string | null;
  parsed_amount_minor: number | null;
  parsed_date: string | null;
  parsed_currency: string | null;
  counterparty: string | null;
  /** the lines printed under it (purpose, reference, branch) */
  details: string | null;
  /** where it is printed: PDF page box (points) or spreadsheet row */
  location: PdfBox | { row: number } | null;
}

/** A box on a PDF page, in PDF points (page = 0-based). */
export interface PdfBox {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export type LayoutLineRole = "booking" | "detail" | "unreadable" | "balance" | "text";

export interface LayoutWord {
  text: string;
  x0: number;
  x1: number;
}

export interface LayoutLine extends PdfBox {
  index: number;
  text: string;
  role: LayoutLineRole;
  words: LayoutWord[];
}

export interface DuplicateMatch {
  transaction_id: number;
  transaction_date: string;
  merchant: string | null;
  normalized_description: string;
  amount_minor: number;
  currency: string;
}

export type RowStatus = "new" | "exact_duplicate" | "possible_duplicate";

export interface RowClassification {
  source_row_index: number;
  status: RowStatus;
  parsed_merchant: string | null;
  parsed_category: string | null;
  transaction_type: TransactionType | null;
  needs_review: boolean;
  review_reason: string | null;
  match: DuplicateMatch | null;
  match_reason: string | null;
  repeated_in_file: boolean;
}

/** Logical fields the column-mapping dialog can assign (backend LOGICAL_FIELDS). */
export type MappableField =
  | "date"
  | "value_date"
  | "amount"
  | "debit"
  | "credit"
  | "currency"
  | "counterparty_iban"
  | "payee"
  | "payer"
  | "counterparty"
  | "description"
  | "booking_text";

export interface ParseOptions {
  column_mapping: Partial<Record<MappableField, string | null>> | null;
  header_row: number | null; // 0-based
  date_format: string | null;
  decimal_separator: "," | "." | null;
  invert_signs: boolean | null;
  /** how to read a PDF the built-in readers don't understand (taught in the import review) */
  pdf_template?: PdfTemplate | null;
}

export type TemplateColumn = "date" | "value_date" | "text" | "amount" | "sign";
export type TemplateLabel = "total" | "opening" | "closing";

export interface PdfTemplate {
  /** x-range (PDF points) of each part of the example booking line */
  columns: Partial<Record<TemplateColumn, [number, number]>>;
  sign_rule: "as_printed" | "unsigned_is_expense" | "unsigned_is_income";
  /** lines to skip, as printed (numbers don't matter) */
  ignore: string[];
  labels: Partial<Record<TemplateLabel, string>>;
  document_type: "credit_card_statement" | "bank_statement";
}

export interface ImportPreview {
  staging_id: string;
  filename: string;
  /** null: neither given nor recognized — the user chooses the account */
  account_id: number | null;
  account_name: string | null;
  /** how the account was recognized without asking */
  account_recognized: "iban" | "history" | "format" | "replaced" | null;
  /** recognized account and nothing to look at: may be imported without confirmation */
  auto_import: boolean;
  /** why the import review opens by itself (empty: no need) */
  review_reasons: string[];
  page_count: number;
  layout_lines: LayoutLine[];
  source_rows: string[][];
  document_type: DocumentType;
  detected_columns: Record<string, string | null>;
  detected_layout: string | null;
  period_start: string | null;
  period_end: string | null;
  transaction_count: number;
  transactions: ParsedTransactionPreview[];
  issues: ImportIssue[];
  ambiguous: boolean;
  has_errors: boolean;
  statement_total_minor: number | null;
  other_totals: Record<string, number>;
  /** Do the bookings add up to what the document states itself? */
  total_check: TotalCheck | null;
  available_columns: string[];
  header_row_index: number | null;
  date_format: string | null;
  date_format_candidates: string[];
  decimal_separator: "," | "." | null;
  needs_decimal_separator: boolean;
  options: ParseOptions;
  new_count: number;
  exact_duplicate_count: number;
  possible_duplicate_count: number;
  needs_review_count: number;
  unusable_row_count: number;
  warning_count: number;
  row_classifications: RowClassification[];
}

export type RowDecisionValue = "keep" | "skip";

export interface RowDecision {
  source_row_index: number;
  decision: RowDecisionValue;
}

export interface ImportCommitResult {
  import_id: number;
  filename: string;
  transactions_created: number;
  duplicates_flagged: number;
  rows_skipped: number;
  credit_card_statement_id: number | null;
  transactions_enriched: number;
}

export interface ImportRemovalResult {
  import_id: number;
  filename: string;
  transactions_removed: number;
  raw_transactions_removed: number;
  transfer_partners_reverted: number;
  statements_removed: number;
  reconciliations_recomputed: number;
}

export interface ImportRecord {
  id: number;
  filename: string;
  document_type: DocumentType;
  account_id: number;
  account_name: string;
  imported_at: string;
  period_start: string | null;
  period_end: string | null;
  status: string;
  detected_transaction_count: number;
}

export interface CurrencyTotals {
  currency: string;
  income_minor: number;
  expenses_minor: number;
  net_minor: number;
  transaction_count: number;
}

export interface Totals {
  income_minor: number | null;
  expenses_minor: number | null;
  net_minor: number | null;
  transaction_count: number;
  currency: string | null;
  is_mixed_currency: boolean;
  by_currency: CurrencyTotals[] | null;
}

export interface CategoryBreakdownItem {
  category: string;
  currency: string;
  amount_minor: number;
}

export interface CategoryTransactions extends TransactionListResponse {
  /** net spending of all matching transactions (not just this page) */
  amount_minor: number;
}

export interface LocationBreakdownItem {
  /** ISO 3166-1 alpha-2; null (and online false): no known place */
  country: string | null;
  city: string | null;
  online: boolean;
  currency: string;
  amount_minor: number;
  transaction_count: number;
}

export interface MonthlyPoint {
  month: string;
  currency: string;
  income_minor: number;
  expenses_minor: number;
}

export interface StatementSummary {
  id: number;
  account_id: number;
  statement_period_start: string | null;
  statement_period_end: string | null;
  statement_total_minor: number | null;
  currency: string;
  transaction_count: number;
  reconciliation_status: ReconciliationStatus;
  difference_minor: number | null;
}

export interface CreditCardSummary {
  account: Account;
  statement_count: number;
  latest_statement: StatementSummary | null;
  /** payments onto the card outside statements: paired with their bank debit, or not */
  payments_linked: number;
  payments_unlinked: number;
}

export interface TransactionBrief {
  id: number;
  transaction_date: string;
  merchant: string | null;
  normalized_description: string;
  category: string | null;
  amount_minor: number;
  currency: string;
  transaction_type: TransactionType;
  account_id: number;
  account_name: string;
  is_duplicate: boolean;
  is_transfer: boolean;
  source_filename: string | null;
}

export interface BankPaymentInfo {
  status: "matched" | "suggested" | "not_found";
  transaction: TransactionBrief | null;
  candidates: TransactionBrief[];
  /** Exact, unambiguous match the user can confirm with one click. */
  recommended_transaction_id: number | null;
}

export interface ReconciliationDetail {
  /** null until the first explicit action (choose payment, resolve) stores one. */
  reconciliation_id: number | null;
  statement_id: number;
  account_id: number;
  account_name: string;
  statement_period_start: string | null;
  statement_period_end: string | null;
  currency: string;

  transactions: TransactionBrief[];
  transaction_total_minor: number;

  statement_total_minor: number | null;
  other_totals: Record<string, number>;

  bank_payment: BankPaymentInfo;

  diff_transactions_vs_statement_minor: number | null;
  diff_statement_vs_bank_minor: number | null;

  status: ReconciliationStatus;
  explanation_tags: string[];
  user_resolution_tags: string[];

  resolved_by_user: boolean;
  resolution_notes: string | null;

  source_import_filename: string | null;
}

export interface AccountBreakdownItem {
  account_id: number;
  account_name: string;
  account_type: AccountType;
  currency: string;
  income_minor: number;
  expenses_minor: number;
  net_minor: number;
  transaction_count: number;
}

export interface CurrencyTransfersSummary {
  currency: string;
  total_transferred_minor: number;
  transfer_count: number;
}

export interface TransfersSummary {
  total_transferred_minor: number | null;
  transfer_count: number;
  currency: string | null;
  is_mixed_currency: boolean;
  by_currency: CurrencyTransfersSummary[] | null;
}

export interface TransferDetectionResult {
  transactions_considered: number;
  pairs_matched: number;
  transactions_marked_as_transfer: number;
  transactions_reverted_to_ordinary: number;
}

export interface Budget {
  id: number;
  category: string;
  amount_minor: number;
  currency: string;
  created_at: string;
  updated_at: string;
}

export interface BudgetStatusItem {
  category: string;
  budget_minor: number;
  actual_minor: number;
  remaining_minor: number;
  percent_used: number;
  over_budget: boolean;
  currency: string;
}

export interface BudgetStatusResponse {
  month: string;
  items: BudgetStatusItem[];
}

export type RecurringInterval = "weekly" | "monthly" | "quarterly" | "yearly";
export type RecurringSign = "income" | "expense";

export interface RecurringSeriesItem {
  key: string;
  /** the merchant as written on its latest transaction */
  label: string;
  sign: RecurringSign;
  interval: RecurringInterval;
  occurrence_count: number;
  average_amount_minor: number;
  last_amount_minor: number;
  last_date: string;
  next_expected_date: string;
  currency: string;
  /** false once expected occurrences stopped arriving (e.g. a cancelled subscription). */
  is_active: boolean;
}

export interface RecurringSeriesResponse {
  series: RecurringSeriesItem[];
}

export interface MonthlyForecastPoint {
  month: string;
  currency: string;
  recurring_net_minor: number;
  baseline_net_minor: number;
  projected_net_minor: number;
}

export interface ForecastResponse {
  as_of: string;
  months: number;
  series_count: number;
  points: MonthlyForecastPoint[];
}

export interface BackupInfo {
  filename: string;
  created_at: string;
  size_bytes: number;
  counts: Record<string, number>;
}

export interface RestoreResult {
  restored_from: string;
  safety_backup: string;
  counts: Record<string, number>;
}

export interface ReapplyRulesResult {
  transactions_checked: number;
  merchants_changed: number;
  categories_changed: number;
}

export interface SystemInfo {
  version: string;
  data_dir: string;
  database_path: string;
  imports_dir: string;
  backups_dir: string;
  using_legacy_layout: boolean;
  /** the program's code changed on disk since it started (absent on older servers) */
  restart_needed?: boolean;
}

/** A built-in or user-created category. */
export interface CategoryInfo {
  name: string;
  built_in: boolean;
  id: number | null;
  transaction_count: number;
}

export interface PointsMonth {
  month: string; // YYYY-MM
  earned: number;
  redeemed: number; // negative
  balance: number; // at the month's end
}

export interface PointsProgram {
  id: number;
  name: string;
  unit: string;
  /** cents that 100 points are worth */
  value_per_100: number;
  value_set_by_user: boolean;
  balance: number;
  balance_value_minor: number;
  /** from a statement's stated balance (else the sum of what was read) */
  balance_stated: boolean;
  balance_as_of: string;
  earned: number;
  redeemed: number;
  earned_this_year: number;
  redeemed_this_year: number;
  cashback_percent: number | null;
  months: PointsMonth[];
  merchants: { merchant: string; points: number; bookings: number; spent_minor: number }[];
  redemptions: { date: string; points: number; value_minor: number | null }[];
  bookings: { transaction_id: number; date: string; merchant: string; amount_minor: number; currency: string; points: number }[];
}

/** Do the bookings add up to what the document states itself? */
export interface TotalCheck {
  kind: "balance" | "statement_total";
  ok: boolean;
  difference_minor: number;
}

/** Transactions to review that one learned category would cover together (same payee). */
export interface ReviewGroup {
  key: string;
  label: string;
  /** a rule can be learned for them (false: a booking without a usable payee) */
  learnable: boolean;
  count: number;
  total_minor: number;
  currency: string;
  suggested_category: string | null;
  /** the newest members (up to 200) */
  transactions: Transaction[];
  /** every member */
  member_ids: number[];
}

export interface ReviewGroupsResponse {
  groups: ReviewGroup[];
  total_groups: number;
  total_transactions: number;
  page: number;
  page_size: number;
}

export interface AssignCategoryResult {
  updated: number;
  rule: CategoryRule | null;
  applied_to: number;
}
