import { Button, Card } from "../ui";
import { useReapplyRules } from "../../hooks/useSystem";
import { useI18n } from "../../i18n/useI18n";

export function RulesSection() {
  const { t, tn } = useI18n();
  const reapply = useReapplyRules();

  return (
    <Card>
      <div className="px-5 py-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">{t("rules.title")}</h2>
          <p className="text-xs text-ink-muted mt-1 max-w-lg">
            {t("rules.body")}
          </p>
          {reapply.data && (
            <p className="text-xs text-income mt-2">
              {t("rules.result", {
                checked: reapply.data.transactions_checked,
                merchants: tn("rules.merchants", reapply.data.merchants_changed),
                categories: tn("rules.categories", reapply.data.categories_changed),
              })}
            </p>
          )}
          {reapply.isError && <p className="text-xs text-danger mt-2">{(reapply.error as Error).message}</p>}
        </div>
        <Button variant="secondary" onClick={() => reapply.mutate()} disabled={reapply.isPending}>
          {reapply.isPending ? t("rules.applying") : t("rules.reapply")}
        </Button>
      </div>
    </Card>
  );
}
