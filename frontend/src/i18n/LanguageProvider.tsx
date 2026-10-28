import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { setFormatLocale } from "../lib/format";
import {
  I18nContext,
  LANG_STORAGE_KEY,
  LOCALES,
  getLang,
  setCurrentLang,
  translate,
  type I18n,
  type Lang,
  type MessageKey,
  type Params,
} from "./core";

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(getLang);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = translate(lang, "app.name");
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setCurrentLang(next);
    setFormatLocale(LOCALES[next]);
    try {
      localStorage.setItem(LANG_STORAGE_KEY, next);
    } catch {
      // private mode: the choice just isn't remembered
    }
    setLangState(next);
  }, []);

  const value = useMemo<I18n>(() => {
    const t = (key: MessageKey, params?: Params) => translate(lang, key, params);
    const tn = (key: string, count: number, params?: Params) =>
      translate(lang, `${key}.${count === 1 ? "one" : "other"}` as MessageKey, { count, ...params });
    return { lang, setLang, t, tn, locale: LOCALES[lang] };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
