// UI text. Keys live in illumio_ops/i18n/{en,zh_TW}.json; a missing key shows the key
// itself (and logs), so a gap is visible rather than blank.
import { createContext, useContext } from "react";

import { call } from "../api/client";

export type Lang = "en" | "zh_TW";
type Dict = Record<string, string>;

let current: Dict = {};

export function initialLang(): Lang {
  try {
    const saved = window.localStorage.getItem("illumio-ops.lang");
    if (saved === "en" || saved === "zh_TW") return saved;
  } catch {
    // storage unavailable: fall back to the browser language
  }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh_TW" : "en";
}

export function rememberLang(lang: Lang): void {
  try {
    window.localStorage.setItem("illumio-ops.lang", lang);
  } catch {
    // not remembered; harmless
  }
}

export async function loadDictionary(lang: Lang): Promise<boolean> {
  const env = await call("i18n.dictionary", undefined, { lang });
  if (env.ok && env.data) {
    current = env.data;
    document.documentElement.lang = lang === "zh_TW" ? "zh-Hant-TW" : "en";
    return true;
  }
  return false;
}

export function t(key: string, params?: Record<string, string>): string {
  const text = current[key];
  if (text === undefined) {
    console.error(`missing i18n key: ${key}`);
    return key;
  }
  return params ? text.replace(/\{(\w+)\}/g, (m, name: string) => params[name] ?? m) : text;
}

/** Re-render consumers when the language changes. */
export const LangContext = createContext<Lang>("en");

export function useLang(): Lang {
  return useContext(LangContext);
}
