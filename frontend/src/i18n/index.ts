import { fr, type MessageKey } from "./fr";

export type { MessageKey };
export type Messages = Record<MessageKey, string>;

/** Add a language by adding a file with the same keys; unknown languages fall back to French. */
const locales: Record<string, Messages> = { fr };
export const DEFAULT_LANGUAGE = "fr";

export type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;

export function createTranslator(language: string = DEFAULT_LANGUAGE): Translate {
  const messages = locales[language] ?? locales[DEFAULT_LANGUAGE];
  return (key, values) => {
    let message: string = messages[key] ?? key;
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

export const t: Translate = createTranslator();
