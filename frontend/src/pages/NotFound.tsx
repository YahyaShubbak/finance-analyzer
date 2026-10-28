import { Link } from "react-router-dom";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { useI18n } from "../i18n/useI18n";

/** Unknown addresses (an old bookmark, a typo) — instead of a blank page. */
export function NotFound() {
  const { t } = useI18n();
  return (
    <div>
      <PageHeader title={t("notFound.title")} />
      <div className="p-8">
        <Card>
          <EmptyState title={t("notFound.title")} description={t("notFound.body")} />
          <div className="pb-6 text-center">
            <Link to="/" className="text-sm text-accent-strong underline underline-offset-2">
              {t("notFound.home")}
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
