import { useId, useState } from "react";
import { Button } from "../ui";
import { categoryLabel } from "../../lib/categories";
import { useCategoryNames } from "../../hooks/useCategories";
import { useI18n } from "../../i18n/useI18n";
import { useUpdateTransaction } from "../../hooks/useTransactions";
import { useCreateCategoryRule, useCreateMerchantRule } from "../../hooks/useRules";
import { loadLearnPreference, saveLearnPreference } from "../../state/learnPreference";
import type { Transaction, TransactionType } from "../../types";

export function TransactionCorrectionForm({
  transaction,
  onResolved,
  onNotice,
}: {
  transaction: Transaction;
  onResolved?: () => void;
  /** shows what was learned outside the form — the transaction may leave the list right away */
  onNotice?: (text: string) => void;
}) {
  const { t, tn } = useI18n();
  const ids = useId();
  const categories = useCategoryNames();
  const [merchant, setMerchant] = useState(transaction.merchant ?? "");
  // Off by default: a rule changes FUTURE imports too, so it should be a
  // deliberate choice — and the derived pattern is shown afterwards.
  const [merchantAsRule, setMerchantAsRule] = useState(false);
  const [category, setCategory] = useState(transaction.category ?? "");
  // Same preference as on the Transactions page (on by default).
  const [categoryAsRule, setCategoryAsRuleState] = useState(loadLearnPreference);
  const [ruleNotice, setRuleNotice] = useState<{ text: string; merchantRule: boolean } | null>(null);

  function setCategoryAsRule(value: boolean) {
    setCategoryAsRuleState(value);
    saveLearnPreference(value);
  }
  const [type, setType] = useState<TransactionType>(transaction.transaction_type);

  const updateTx = useUpdateTransaction();
  const createMerchantRule = useCreateMerchantRule();
  const createCategoryRule = useCreateCategoryRule();

  const merchantChanged = merchant.trim() !== "" && merchant.trim() !== (transaction.merchant ?? "");
  const categoryChanged = category !== "" && category !== (transaction.category ?? "");

  const anyPending = updateTx.isPending || createMerchantRule.isPending || createCategoryRule.isPending;

  function handleSaveMerchant() {
    if (!merchantChanged) return;
    if (merchantAsRule) {
      // (a promise, not mutate's callbacks: those are dropped when the corrected
      // transaction leaves the review list — and this form with it — first)
      createMerchantRule
        .mutateAsync({ transactionId: transaction.id, normalizedMerchant: merchant.trim() })
        .then((result) => {
          const text =
            t("correct.merchantRuleSaved", {
              pattern: result.merchant_rule?.pattern ?? "",
              merchant: result.merchant_rule?.normalized_merchant ?? "",
            }) + (result.applied_to > 0 ? tn("correct.merchantRuleApplied", result.applied_to) : "");
          if (onNotice) onNotice(`${text} ${t("correct.ruleFuture")}`);
          else setRuleNotice({ text, merchantRule: true });
        })
        .catch(() => undefined); // shown from the mutation's error state
    } else {
      updateTx.mutate({ id: transaction.id, patch: { merchant: merchant.trim() } }, { onSuccess: onResolved });
    }
  }

  function handleSaveCategory() {
    if (!categoryChanged) return;
    if (categoryAsRule) {
      createCategoryRule
        .mutateAsync({ transactionId: transaction.id, category })
        .then((result) => {
          const label = categoryLabel(t, category);
          const rule = result.category_rule;
          const text = !rule
            ? t("tx.notLearnable", { category: label })
            : result.applied_to > 0
              ? tn("tx.learned", result.applied_to, { pattern: rule.pattern, category: label })
              : t("tx.learnedNone", { pattern: rule.pattern, category: label });
          if (onNotice) onNotice(text);
          else setRuleNotice({ text, merchantRule: false });
        })
        .catch(() => undefined); // shown from the mutation's error state
    } else {
      updateTx
        .mutateAsync({ id: transaction.id, patch: { category } })
        .then(() => (onNotice ? onNotice(t("tx.changedOnly", { category: categoryLabel(t, category) })) : onResolved?.()))
        .catch(() => undefined);
    }
  }

  function handleSaveType(newType: TransactionType) {
    const previous = type;
    setType(newType);
    updateTx.mutate({ id: transaction.id, patch: { transaction_type: newType } }, { onError: () => setType(previous) });
  }

  return (
    <div className="space-y-3 text-sm">
      <div>
        <label htmlFor={`${ids}-merchant`} className="text-xs text-ink-muted block mb-1">{t("correct.merchant")}</label>
        <div className="flex items-center gap-2">
          <input
            id={`${ids}-merchant`}
            type="text"
            value={merchant}
            onChange={(e) => setMerchant(e.target.value)}
            className="flex-1 text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
          />
          <Button variant="secondary" className="!px-2.5 !py-1.5 text-xs" disabled={!merchantChanged || anyPending} onClick={handleSaveMerchant}>
            {t("common.save")}
          </Button>
        </div>
        <label className="flex items-center gap-1.5 mt-1.5 text-xs text-ink-muted">
          <input type="checkbox" checked={merchantAsRule} onChange={(e) => setMerchantAsRule(e.target.checked)} />
          {t("correct.merchantRule")}
        </label>
      </div>

      <div>
        <label htmlFor={`${ids}-category`} className="text-xs text-ink-muted block mb-1">{t("correct.category")}</label>
        <div className="flex items-center gap-2">
          <select
            id={`${ids}-category`}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="flex-1 text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
          >
            <option value="">{t("correct.selectCategory")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(t, c)}
              </option>
            ))}
          </select>
          <Button variant="secondary" className="!px-2.5 !py-1.5 text-xs" disabled={!categoryChanged || anyPending} onClick={handleSaveCategory}>
            {t("common.save")}
          </Button>
        </div>
        <label className="flex items-center gap-1.5 mt-1.5 text-xs text-ink-muted">
          <input type="checkbox" checked={categoryAsRule} onChange={(e) => setCategoryAsRule(e.target.checked)} />
          {t("correct.categoryRule")}
        </label>
      </div>

      <div>
        <label htmlFor={`${ids}-type`} className="text-xs text-ink-muted block mb-1">{t("correct.type")}</label>
        <select
          id={`${ids}-type`}
          value={type}
          onChange={(e) => handleSaveType(e.target.value as TransactionType)}
          className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
          disabled={anyPending}
        >
          {type === "unknown" && <option value="unknown">{t("txType.unknown")}</option>}
          <option value="income">{t("txType.income")}</option>
          <option value="expense">{t("txType.expense")}</option>
          <option value="transfer">{t("txType.transfer")}</option>
        </select>
        <p className="text-[11px] text-ink-faint mt-1">
          {t("correct.typeHint")}
        </p>
      </div>

      {ruleNotice && (
        <div className="rounded-md bg-accent-soft px-3 py-2 text-xs text-accent-strong space-y-1.5">
          <div>{ruleNotice.text}</div>
          {ruleNotice.merchantRule && <div className="text-ink-muted">{t("correct.ruleFuture")}</div>}
          {onResolved && (
            <Button variant="secondary" className="!px-2.5 !py-1 text-xs" onClick={onResolved}>
              {t("common.done")}
            </Button>
          )}
        </div>
      )}

      {(updateTx.error || createMerchantRule.error || createCategoryRule.error) && (
        <div className="text-xs text-danger">
          {((updateTx.error ?? createMerchantRule.error ?? createCategoryRule.error) as Error).message}
        </div>
      )}
    </div>
  );
}
