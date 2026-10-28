import type { MessageKey } from "../i18n/core";

const EXPLANATIONS = new Set([
  "fee", "interest", "refund", "duplicate_transaction", "partial_payment", "currency_conversion", "previous_balance",
]);

export const RESOLUTION_TAG_OPTIONS: string[] = [
  "fee", "interest", "refund", "duplicate_transaction", "missing_transaction", "partial_payment",
  "currency_conversion", "previous_balance", "other",
];

/** Translation key of an engine-computed explanation tag (unknown tags are shown as is). */
export function explanationKey(tag: string): MessageKey | null {
  return EXPLANATIONS.has(tag) ? (`explanation.${tag}` as MessageKey) : null;
}

export function resolutionTagKey(tag: string): MessageKey {
  return `tag.${tag}` as MessageKey;
}

/** Display text of an engine-computed explanation tag. */
export function explanationLabel(t: (key: MessageKey) => string, tag: string): string {
  const key = explanationKey(tag);
  return key ? t(key) : tag;
}
