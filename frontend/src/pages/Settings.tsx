import { PageHeader } from "../components/ui";
import { BackupSection } from "../components/settings/BackupSection";
import { DataLocationSection } from "../components/settings/DataLocationSection";
import { RestoreFromFileSection } from "../components/settings/RestoreFromFileSection";
import { RulesSection } from "../components/settings/RulesSection";
import { LanguageSection } from "../components/settings/LanguageSection";
import { LearnedRulesSection } from "../components/settings/LearnedRulesSection";
import { CategoriesSection } from "../components/settings/CategoriesSection";
import { ResetSection } from "../components/settings/ResetSection";
import { useI18n } from "../i18n/useI18n";

export function Settings() {
  const { t } = useI18n();
  return (
    <div>
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <div className="p-8 space-y-6 max-w-4xl">
        <LanguageSection />
        <CategoriesSection />
        <LearnedRulesSection />
        <RulesSection />
        <DataLocationSection />
        <BackupSection />
        <RestoreFromFileSection />
        <ResetSection />
      </div>
    </div>
  );
}
