import { Suspense, useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { LANGUAGES, type Lang } from "../i18n/core";
import { useI18n } from "../i18n/useI18n";
import { useRestartNeeded, useSystemInfo } from "../hooks/useSystem";
import { NAV_ITEMS } from "./nav";

export function AppShell() {
  const location = useLocation();
  const { t, lang, setLang } = useI18n();
  const queryClient = useQueryClient();
  const restartNeeded = useRestartNeeded();
  const version = useSystemInfo().data?.version;
  const shownLang = useRef(lang);

  // Texts the backend words (review reasons, import warnings) come in the
  // requested language: fetch them again after a switch.
  useEffect(() => {
    if (shownLang.current === lang) return;
    shownLang.current = lang;
    void queryClient.invalidateQueries();
  }, [lang, queryClient]);

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      {/* Narrow windows get an icon rail; the language also lives in Settings. */}
      <aside className="w-14 md:w-60 shrink-0 border-r border-border bg-surface flex flex-col">
        <div className="hidden md:block px-5 py-5 border-b border-border">
          <div className="text-[15px] font-semibold tracking-tight text-ink">{t("app.name")}</div>
          {version && <div className="text-xs text-ink-faint mt-0.5">{t("app.version", { version })}</div>}
        </div>
        <nav className="flex-1 py-3 px-2 space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              title={t(item.labelKey)}
              className={({ isActive }) =>
                [
                  "flex items-center justify-center md:justify-start gap-2.5 px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-accent-soft text-accent-strong font-medium"
                    : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                ].join(" ")
              }
            >
              <span className="w-4 text-center text-[13px] opacity-70" aria-hidden>
                {item.icon}
              </span>
              <span className="sr-only md:not-sr-only">{t(item.labelKey)}</span>
            </NavLink>
          ))}
        </nav>
        <div className="hidden md:block px-5 py-4 border-t border-border text-[11px] text-ink-faint leading-relaxed space-y-3">
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <span>{t("app.language")}</span>
            <select
              aria-label={t("app.language")}
              className="text-xs border border-border-strong rounded px-1.5 py-1 bg-surface text-ink"
              value={lang}
              onChange={(e) => setLang(e.target.value as Lang)}
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          <div>
            {t("app.privacy1")}
            <br />
            {t("app.privacy2")}
          </div>
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        {restartNeeded && (
          <div role="alert" className="px-8 py-2.5 text-sm bg-warning-soft text-warning border-b border-warning/20">
            {t("app.restartNeeded")}
          </div>
        )}
        <ErrorBoundary key={location.pathname}>
          {/* Inner Suspense: while a page bundle loads, the sidebar stays visible. */}
          <Suspense fallback={<div className="p-8 text-sm text-ink-muted">{t("app.loading")}</div>}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}
