import { createContext } from "react";
import { de } from "./de";
import { en, type MessageKey } from "./en";

export type Lang = "de" | "en";
export type { MessageKey };
export type Params = Record<string, string | number>;

export const LANGUAGES: { code: Lang; label: string }[] = [
  { code: "de", label: "Deutsch" },
  { code: "en", label: "English" },
];
export const LOCALES: Record<Lang, string> = { de: "de-DE", en: "en-GB" };
export const DEFAULT_LANG: Lang = "de";
export const LANG_STORAGE_KEY = "finance.lang";

const CATALOGS: Record<Lang, Record<MessageKey, string>> = { de, en };

export function loadStoredLang(): Lang {
  try {
    const stored = localStorage.getItem(LANG_STORAGE_KEY);
    return stored === "en" || stored === "de" ? stored : DEFAULT_LANG;
  } catch {
    return DEFAULT_LANG;
  }
}

let currentLang: Lang = loadStoredLang();

/** Current language outside React (e.g. the API client's Accept-Language). */
export function getLang(): Lang {
  return currentLang;
}

export function setCurrentLang(lang: Lang) {
  currentLang = lang;
}

export function translate(lang: Lang, key: MessageKey, params?: Params): string {
  let text = CATALOGS[lang][key] ?? en[key] ?? key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

export interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** Translate a key; "{name}" placeholders are filled from params. */
  t: (key: MessageKey, params?: Params) => string;
  /** Picks "<key>.one" or "<key>.other" by count; {count} is available in the text. */
  tn: (key: string, count: number, params?: Params) => string;
  locale: string;
}

export const I18nContext = createContext<I18n | null>(null);
