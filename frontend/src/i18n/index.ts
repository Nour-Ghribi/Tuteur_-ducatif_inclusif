import { fr, type MessageKey } from "./fr";
import { ar } from "./ar";
import { en } from "./en";

export type { MessageKey };
export type Messages = Record<MessageKey, string>;

export const SUPPORTED_LANGUAGES = ["fr", "ar", "en"] as const;
export type SupportedLanguage = typeof SUPPORTED_LANGUAGES[number];

export const RTL_LANGUAGES = new Set<SupportedLanguage>(["ar"]);

/** Add a language by adding a file with the same keys; unknown languages fall back to French. */
const locales: Record<string, Messages> = {
  fr: fr as unknown as Messages,
  ar: ar as unknown as Messages,
  en: en as unknown as Messages,
};
export const DEFAULT_LANGUAGE: SupportedLanguage = "fr";

export type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;

export function createTranslator(language: string = DEFAULT_LANGUAGE): Translate {
  const messages = locales[language] ?? locales[DEFAULT_LANGUAGE];
  return (key, values) => {
    let message: string = messages[key] ?? (locales[DEFAULT_LANGUAGE][key] ?? key);
    for (const [name, value] of Object.entries(values ?? {})) {
      message = message.replace(`{${name}}`, String(value));
    }
    return message;
  };
}

/** Translation of a backend code (``reason_code``, ``message_code``…); never throws on unknown codes. */
export function translateCode(
  t: Translate,
  prefix: "reason" | "msg" | "label" | "warn" | "obs",
  code: string,
): string {
  const key = `${prefix}.${code}` as MessageKey;
  if (key in fr) return t(key);
  if (prefix === "reason") return t("reason.internal_error");
  return prefix === "obs" ? code : code.replaceAll("_", " ");
}

export function hasCode(prefix: "reason" | "msg" | "label" | "warn" | "obs", code: string): boolean {
  return `${prefix}.${code}` in fr;
}

/** App-level language state — updated by the LanguageContext. */
let _currentLanguage: SupportedLanguage = DEFAULT_LANGUAGE;

export function setAppLanguage(lang: SupportedLanguage): void {
  _currentLanguage = lang;
  // Update the document direction and lang attribute for RTL support
  document.documentElement.lang = lang;
  document.documentElement.dir = RTL_LANGUAGES.has(lang) ? "rtl" : "ltr";
}

export function getAppLanguage(): SupportedLanguage {
  return _currentLanguage;
}

export const t: Translate = (key, values) =>
  createTranslator(_currentLanguage)(key, values);
