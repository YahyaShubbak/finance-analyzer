import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { HELP_DE } from "../help/de";
import { HELP_EN } from "../help/en";
import type { HelpSection, HelpTopic } from "../help/types";
import { useI18n } from "../i18n/useI18n";
import { useSystemInfo } from "../hooks/useSystem";

/** Lower case without accents, ß as ss: "muller" finds "Müller". */
function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").replace(/ß/g, "ss").toLowerCase();
}

function topicText(topic: HelpTopic): string {
  return fold([topic.title, ...topic.body.flat()].join(" "));
}

/** How the app works and what to do when something goes wrong. A search
 * shows only the topics containing every word typed, opened. */
export function Help() {
  const { t, lang } = useI18n();
  const [search, setSearch] = useState("");
  const version = useSystemInfo().data?.version;
  const sections: HelpSection[] = lang === "de" ? HELP_DE : HELP_EN;
  const words = fold(search).split(/\s+/).filter(Boolean);
  const shown = sections
    .map((s) => ({
      ...s,
      topics: words.length ? s.topics.filter((topic) => words.every((w) => topicText(topic).includes(w))) : s.topics,
    }))
    .filter((s) => s.topics.length > 0);

  return (
    <div>
      <PageHeader title={t("help.title")} subtitle={t("help.subtitle")} />
      <div className="p-8 space-y-6 max-w-4xl">
        <Card className="p-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <input
            type="search"
            placeholder={t("help.search")}
            aria-label={t("help.search")}
            className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink w-64"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {!words.length && (
            <nav aria-label={t("help.contents")} className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {sections.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className="text-accent-strong underline underline-offset-2"
                  onClick={() => document.getElementById(`help-${s.id}`)?.scrollIntoView({ behavior: "smooth" })}
                >
                  {s.title}
                </button>
              ))}
            </nav>
          )}
        </Card>

        {shown.length === 0 && (
          <Card className="px-5 py-6">
            <EmptyState title={t("help.nothingFound")} />
          </Card>
        )}

        {shown.map((section) => (
          <Card key={section.id}>
            <div id={`help-${section.id}`} className="px-5 py-4 border-b border-border scroll-mt-4">
              <h2 className="text-sm font-semibold text-ink">{section.title}</h2>
              {section.intro && <p className="text-xs text-ink-muted mt-0.5">{section.intro}</p>}
            </div>
            <div className="divide-y divide-border">
              {section.topics.map((topic) => (
                // a search changes the key, so found topics open and the rest reset
                <details key={`${topic.id}-${words.length > 0}`} open={words.length > 0} className="group px-5 py-3">
                  <summary className="cursor-pointer text-sm font-medium text-ink list-none flex items-center gap-2">
                    <span aria-hidden className="text-ink-faint text-xs transition-transform group-open:rotate-90">▶</span>
                    {topic.title}
                  </summary>
                  <div className="mt-2 ml-5 space-y-2 text-sm text-ink-muted leading-relaxed">
                    {topic.body.map((part, i) =>
                      typeof part === "string" ? (
                        <p key={i}>{part}</p>
                      ) : (
                        <ul key={i} className="list-disc pl-5 space-y-1">
                          {part.map((item, j) => (
                            <li key={j}>{item}</li>
                          ))}
                        </ul>
                      )
                    )}
                    {topic.link && (
                      <Link to={topic.link.to} className="inline-block text-xs text-accent-strong underline underline-offset-2">
                        {topic.link.label} →
                      </Link>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </Card>
        ))}

        {!words.length && (
          <Card className="px-5 py-4 text-xs text-ink-muted space-y-1">
            <h2 className="text-sm font-semibold text-ink">{t("help.aboutTitle")}</h2>
            <p>
              {t("app.name")}
              {version && ` · ${t("app.version", { version })}`}
            </p>
            <p>{t("help.aboutLicense")}</p>
            <p>
              {t("help.aboutPlaces")}{" "}
              <a href="https://www.geonames.org" target="_blank" rel="noreferrer" className="underline underline-offset-2">
                GeoNames
              </a>{" "}
              (CC BY 4.0)
            </p>
            <p>{t("help.aboutWarranty")}</p>
          </Card>
        )}
      </div>
    </div>
  );
}
