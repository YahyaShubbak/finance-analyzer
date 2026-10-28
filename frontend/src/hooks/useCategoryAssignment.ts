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
  const learnCategory = useCreateCategoryRule();
  const updateTransaction = useUpdateTransaction();
  const forgetRule = useForgetCategoryRule();

  function setLearn(value: boolean) {
    setLearnState(value);
    saveLearnPreference(value);
  }

  function assign(tx: Transaction, category: string) {
    setNotice(null);
    learnCategory.reset();
    updateTransaction.reset();
    forgetRule.reset();
    setSavingId(tx.id);
    const onSettled = () => setSavingId(null);
    if (learn) {
      learnCategory.mutate(
        { transactionId: tx.id, category },
        {
          onSuccess: (result) =>
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
            ),
          onSettled,
        }
      );
    } else {
      updateTransaction.mutate(
        { id: tx.id, patch: { category } },
        { onSuccess: () => setNotice({ kind: "only", category }), onSettled }
      );
    }
  }

  function forget(ruleId: number) {
    forgetRule.mutate(ruleId, {
      onSuccess: (result) => setNotice({ kind: "forgotten", count: result.transactions_changed }),
    });
  }

  const error = (learnCategory.error ?? updateTransaction.error ?? forgetRule.error) as Error | null;

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
