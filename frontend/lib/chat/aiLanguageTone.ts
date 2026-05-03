import { normalizeLocaleInput, SUPPORTED_LOCALE_CODES, type AppLocale } from "../i18n/locales";

export type ChatUserLanguageProfile = {
  nativeLanguage?: string | null;
  additionalLanguages?: string[] | null;
};

export type ChatLanguageResolutionReason = "ui_locale" | "partner_native" | "shared" | "fallback";

export function resolveChatLanguage(
  currentUser: ChatUserLanguageProfile | null | undefined,
  partnerUser: ChatUserLanguageProfile | null | undefined,
  uiLocale: string | null | undefined,
): { language: AppLocale; reason: ChatLanguageResolutionReason } {
  const normalize = (raw: string | null | undefined): AppLocale | null => normalizeLocaleInput(raw);
  const safeList = (raw: unknown): AppLocale[] => {
    const arr = Array.isArray(raw) ? raw : [];
    const out: AppLocale[] = [];
    for (const item of arr) {
      const code = normalize(typeof item === "string" ? item : String(item ?? ""));
      if (code) out.push(code);
    }
    return [...new Set(out)];
  };

  const uiFirst = normalize(uiLocale);
  if (uiFirst) return { language: uiFirst, reason: "ui_locale" };

  const partnerNative = normalize(partnerUser?.nativeLanguage ?? null);
  if (partnerNative) return { language: partnerNative, reason: "partner_native" };

  const currentNative = normalize(currentUser?.nativeLanguage ?? null);
  const currentAdditional = safeList(currentUser?.additionalLanguages ?? []);
  const partnerAdditional = safeList(partnerUser?.additionalLanguages ?? []);

  const currentSet = new Set<AppLocale>([...(currentNative ? [currentNative] : []), ...currentAdditional]);
  for (const code of partnerAdditional) {
    if (currentSet.has(code)) return { language: code, reason: "shared" };
  }

  return { language: "en", reason: "fallback" };
}

export type ChatTone =
  | "flirty"
  | "playful"
  | "confident"
  | "warm"
  | "direct"
  | "teasing"
  | "thoughtful";

export type ConversationState = "new" | "active" | "dead";

export function resolveTone(options: {
  conversationState: ConversationState;
  /** For first message (thread empty), bias to playful/confident. */
  isFirstMessage: boolean;
  /** Manual override from UI. */
  override?: ChatTone | null;
}): ChatTone {
  if (options.override) return options.override;
  if (options.isFirstMessage) return "playful";
  if (options.conversationState === "dead") return "teasing";
  if (options.conversationState === "new") return "confident";
  return "warm";
}

export type ScriptGroup =
  | "latin"
  | "cyrillic"
  | "arabic"
  | "hebrew"
  | "devanagari"
  | "han"
  | "kana"
  | "hangul"
  | "thai"
  | "other";

function scriptGroupForLocale(locale: AppLocale): ScriptGroup {
  if (locale === "uk" || locale === "ru") return "cyrillic";
  if (locale === "ar") return "arabic";
  if (locale === "he") return "hebrew";
  if (locale === "hi") return "devanagari";
  if (locale === "th") return "thai";
  if (locale === "ja") return "kana";
  if (locale === "ko") return "hangul";
  if (locale === "zh-CN" || locale === "zh-TW") return "han";
  // Default: treat everything else as Latin-script UI languages for this heuristic.
  return "latin";
}

function letterCounts(text: string): Record<ScriptGroup, number> {
  const s = String(text || "");
  const counts: Record<ScriptGroup, number> = {
    latin: 0,
    cyrillic: 0,
    arabic: 0,
    hebrew: 0,
    devanagari: 0,
    han: 0,
    kana: 0,
    hangul: 0,
    thai: 0,
    other: 0,
  };

  for (const ch of s) {
    const code = ch.codePointAt(0) ?? 0;
    if ((code >= 0x0041 && code <= 0x007a) || (code >= 0x00c0 && code <= 0x024f)) counts.latin += 1;
    else if (code >= 0x0400 && code <= 0x052f) counts.cyrillic += 1;
    else if (code >= 0x0600 && code <= 0x06ff) counts.arabic += 1;
    else if (code >= 0x0590 && code <= 0x05ff) counts.hebrew += 1;
    else if (code >= 0x0900 && code <= 0x097f) counts.devanagari += 1;
    else if (code >= 0x4e00 && code <= 0x9fff) counts.han += 1;
    else if ((code >= 0x3040 && code <= 0x30ff) || (code >= 0x31f0 && code <= 0x31ff)) counts.kana += 1;
    else if (code >= 0xac00 && code <= 0xd7af) counts.hangul += 1;
    else if (code >= 0x0e00 && code <= 0x0e7f) counts.thai += 1;
    else if ((ch >= "0" && ch <= "9") || /\s/.test(ch) || /[.,!?'"“”‘’—–:;()\[\]{}]/.test(ch)) {
      // ignore neutral
    } else {
      counts.other += 1;
    }
  }
  return counts;
}

export function detectMixedScripts(text: string): boolean {
  const c = letterCounts(text);
  const alphaTotal =
    c.latin + c.cyrillic + c.arabic + c.hebrew + c.devanagari + c.han + c.kana + c.hangul + c.thai;
  if (alphaTotal < 6) return false;
  const active = Object.entries(c)
    .filter(([k]) => k !== "other")
    .filter(([, v]) => v >= 3);
  // Mixed if at least 2 script buckets have meaningful presence.
  return active.length >= 2;
}

export function isTextLikelyInExpectedLanguage(expected: string, text: string): boolean {
  const locale = normalizeLocaleInput(expected) ?? "en";
  const expectedGroup = scriptGroupForLocale(locale);
  const c = letterCounts(text);
  const alphaTotal =
    c.latin + c.cyrillic + c.arabic + c.hebrew + c.devanagari + c.han + c.kana + c.hangul + c.thai;
  if (alphaTotal < 6) return true; // short replies: don't be strict

  if (detectMixedScripts(text)) return false;

  const dominant = Object.entries(c)
    .filter(([k]) => k !== "other")
    .sort(([, a], [, b]) => b - a)[0]?.[0] as ScriptGroup | undefined;
  if (!dominant) return true;
  if (expectedGroup === "latin") {
    // Allow some emoji/other; require not strongly cyrillic/arabic/etc.
    return dominant === "latin";
  }
  return dominant === expectedGroup;
}

export function isSupportedLocale(code: string | null | undefined): code is AppLocale {
  const normalized = normalizeLocaleInput(code);
  return Boolean(normalized && (SUPPORTED_LOCALE_CODES as readonly string[]).includes(normalized));
}

