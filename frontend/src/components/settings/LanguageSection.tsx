import { Card } from "../ui";
import { LANGUAGES, type Lang } from "../../i18n/core";
import { useI18n } from "../../i18n/useI18n";

export function LanguageSection() {
  const { t, lang, setLang } = useI18n();

  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold text-ink">{t("settings.language")}</h2>
      <p className="text-xs text-ink-muted mt-1 max-w-lg">{t("settings.languageHint")}</p>
      <div className="mt-3 flex gap-2" role="radiogroup" aria-label={t("settings.language")}>
        {LANGUAGES.map((l) => (
          <label
            key={l.code}
            className={`text-sm px-3 py-1.5 rounded-md border cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent ${
              lang === l.code ? "bg-accent-soft border-accent text-accent-strong" : "border-border-strong text-ink-muted"
            }`}
          >
            <input
              type="radio"
              name="language"
              value={l.code}
              checked={lang === l.code}
              onChange={() => setLang(l.code as Lang)}
              className="sr-only"
            />
            {l.label}
          </label>
        ))}
      </div>
    </Card>
  );
}
