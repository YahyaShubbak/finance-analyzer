import { Badge } from "./index";
import { useI18n } from "../../i18n/useI18n";
import type { AccountType } from "../../types";

export function AccountTypeBadge({ type }: { type: AccountType }) {
  const { t } = useI18n();
  const label = t(`accountType.${type}`);
  if (type === "credit_card") return <Badge tone="warning">{label}</Badge>;
  if (type === "savings") return <Badge tone="accent">{label}</Badge>;
  return <Badge tone="neutral">{label}</Badge>;
}
