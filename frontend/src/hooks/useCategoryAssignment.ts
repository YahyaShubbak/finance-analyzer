import { useState } from "react";
import { useUpdateTransaction } from "./useTransactions";
import { useCreateCategoryRule, useForgetCategoryRule } from "./useRules";
import { loadLearnPreference, saveLearnPreference } from "../state/learnPreference";
import type { Transaction } from "../types";

export type CategoryNotice =
  | { kind: "learned"; ruleId: number; pattern: string; category: string; applied: number }
  | { kind: "notLearnable"; category: string }
  | { kind: "only"; category: string }
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

  function assign(tx: Transaction, category: string) {
    setNotice(null);
    setError(null);
    setSavingId(tx.id);
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
    saved
      .catch((failure: Error) => setError(failure))
      // (a later assignment may be the one that is being saved now)
      .finally(() => setSavingId((current) => (current === tx.id ? null : current)));
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
