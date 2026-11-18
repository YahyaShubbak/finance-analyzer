import { useState } from "react";
import { useUpdateTransaction } from "./useTransactions";
import { useCreateCategoryRule, useForgetCategoryRule } from "./useRules";
import { loadLearnPreference, saveLearnPreference } from "../state/learnPreference";
import type { CountAs, Transaction } from "../types";

export type CategoryNotice =
  | { kind: "learned"; ruleId: number; pattern: string; category: string; applied: number }
  | { kind: "notLearnable"; category: string }
  | { kind: "only"; category: string }
  | { kind: "refund"; category: string }
  | { kind: "forgotten"; count: number };

/** Assigning a category from a transaction list: either learned for
 * similar transactions (a category rule) or just this one, as the user
 * chose. Render `<CategoryAssignmentBar {...assignment} />` above the list
 * for the choice and the outcome. */
export function useCategoryAssignment() {
  const [learn, setLearnState] = useState(loadLearnPreference);
  const [notice, setNotice] = useState<CategoryNotice | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  // Kept here, not read from the mutations: they only know their latest
  // call, so a failure of the one before (still under way when the next
  // category was chosen) would never be shown.
  const [error, setError] = useState<Error | null>(null);
  const learnCategory = useCreateCategoryRule();
  const updateTransaction = useUpdateTransaction();
  const forgetRule = useForgetCategoryRule();

  function setLearn(value: boolean) {
    setLearnState(value);
    saveLearnPreference(value);
  }

  /** `countAs`: how a booking that came in counts with this category — a
   * refund lowers the category's spending, income is income (see CategoryCell). */
  function assign(tx: Transaction, category: string, countAs?: CountAs) {
    setNotice(null);
    setError(null);
    setSavingId(tx.id);
    const type = countAs === "refund" ? "expense" : countAs === "income" ? "income" : undefined;
    if (type !== undefined && type !== tx.transaction_type) {
      // Only this booking, never learned: a lesson teaches a payer's category, and the payer of a
      // refund often pays other things, too - the employer who reimburses travel pays the salary.
      const saved = updateTransaction
        .mutateAsync({ id: tx.id, patch: tx.category === category ? { transaction_type: type } : { category, transaction_type: type } })
        .then(() => setNotice(countAs === "refund" ? { kind: "refund", category } : { kind: "only", category }));
      settle(saved, tx.id);
      return;
    }
    const saved = learn
      ? learnCategory.mutateAsync({ transactionId: tx.id, category }).then((result) =>
          setNotice(
            result.category_rule
              ? {
                  kind: "learned",
                  ruleId: result.category_rule.id,
                  pattern: result.category_rule.pattern,
                  category,
                  applied: result.applied_to,
                }
              : { kind: "notLearnable", category }
          )
        )
      : updateTransaction
          .mutateAsync({ id: tx.id, patch: { category } })
          .then(() => setNotice({ kind: "only", category }));
    settle(saved, tx.id);
  }

  function settle(saved: Promise<unknown>, id: number) {
    saved
      .catch((failure: Error) => setError(failure))
      // (a later assignment may be the one that is being saved now)
      .finally(() => setSavingId((current) => (current === id ? null : current)));
  }

  function forget(ruleId: number) {
    setError(null);
    forgetRule
      .mutateAsync(ruleId)
      .then((result) => setNotice({ kind: "forgotten", count: result.transactions_changed }))
      .catch((failure: Error) => setError(failure));
  }

  return {
    assign,
    savingId,
    learn,
    setLearn,
    notice,
    dismiss: () => setNotice(null),
    forget,
    forgetting: forgetRule.isPending,
    error,
  };
}
