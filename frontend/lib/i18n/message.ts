import type { TranslationVars } from ".";

export type I18nText =
  | {
      key: string;
      vars?: TranslationVars;
    }
  | {
      raw: string;
    }
  | null
  | undefined;

export function i18nKey(key: string, vars?: TranslationVars): NonNullable<I18nText> {
  return vars ? { key, vars } : { key };
}

export function rawI18nText(raw: string): NonNullable<I18nText> {
  return { raw };
}

export function resolveI18nText(
  message: I18nText,
  t: (key: string, vars?: TranslationVars) => string,
): string {
  if (!message) return "";
  if ("raw" in message) return message.raw;
  return t(message.key, message.vars);
}

export function isRawI18nText(message: I18nText): boolean {
  return Boolean(message && "raw" in message && message.raw.trim());
}
