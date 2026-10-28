import { Badge, Card } from "../ui";
import { formatDate, formatSignedMoney } from "../../lib/format";
import { categoryLabel } from "../../lib/categories";
import type { TransactionBrief } from "../../types";
import { useI18n } from "../../i18n/useI18n";

export function StatementTransactionsTable({ transactions }: { transactions: TransactionBrief[] }) {
  const { t, tn } = useI18n();
  const counted = transactions.filter((tx) => !tx.is_transfer).length;
  const payments = transactions.length - counted;
  return (
    <Card>
      <div className="px-5 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-ink">{t("recon.purchasesTitle")}</h2>
        <p className="text-xs text-ink-muted mt-0.5">
          {tn("recon.makeUp", counted)}
          {payments > 0 && tn("recon.paymentLines", payments)}
        </p>
      </div>
      <div className="overflow-x-auto">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-ink-muted text-xs">
              <tr className="border-b border-border">
                <th className="text-left font-medium px-5 py-2">{t("col.date")}</th>
                <th className="text-left font-medium px-5 py-2">{t("col.merchant")}</th>
                <th className="text-left font-medium px-5 py-2">{t("col.description")}</th>
                <th className="text-left font-medium px-5 py-2">{t("col.category")}</th>
                <th className="text-right font-medium px-5 py-2">{t("col.amount")}</th>
                <th className="text-left font-medium px-5 py-2">{t("col.flags")}</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx) => (
                <tr key={tx.id} className="border-b border-border last:border-0">
                  <td className="px-5 py-2.5 text-ink-muted whitespace-nowrap">{formatDate(tx.transaction_date)}</td>
                  <td className="px-5 py-2.5 text-ink">{tx.merchant ?? "—"}</td>
                  <td className="px-5 py-2.5 text-ink-muted truncate max-w-[220px]">{tx.normalized_description}</td>
                  <td className="px-5 py-2.5 text-ink-muted">{categoryLabel(t, tx.category)}</td>
                  <td
                    className={`px-5 py-2.5 text-right tabular-nums font-medium ${
                      tx.is_duplicate ? "text-ink-faint" : tx.amount_minor > 0 ? "text-income" : tx.amount_minor < 0 ? "text-expense" : "text-ink-muted"
                    }`}
                  >
                    {formatSignedMoney(tx.amount_minor, tx.currency)}
                  </td>
                  <td className="px-5 py-2.5">
                    <div className="flex gap-1.5">
                      {tx.is_duplicate && <Badge tone="neutral">{t("flag.duplicateExcluded")}</Badge>}
                      {tx.is_transfer && <Badge tone="neutral">{t("flag.transfer")}</Badge>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}
