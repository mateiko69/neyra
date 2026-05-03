/**
 * Mirrors backend `detect_contextual_fallback_bucket` / `_UK_TRIPLES` for client-side
 * copilot fallback when API is empty or rejects the pack — keeps UA UI contextual without extra AI.
 */
import type { ChatFallbackPack } from "./chatFallbackReplies";
import { getChatFallbackPack } from "./chatFallbackReplies";
import type { AppLocale } from "../i18n/locales";
import { normalizeLocaleInput } from "../i18n/locales";

const UK_CTX: Record<
  "weekend" | "mood" | "interests" | "meet",
  readonly [easy: string, flirty: string, deep: string]
> = {
  weekend: [
    "Я б обрав щось між спокійним днем і маленькою пригодою 😄 А ти більше за релакс чи актив?",
    "Ідеальні вихідні дуже залежать від компанії 😉 А ти більше про прогулянку, каву чи спонтанну поїздку?",
    "Для мене ідеальні вихідні — це коли можна видихнути й зробити щось для себе. А тобі важливіше відпочити чи отримати нові емоції?",
  ],
  mood: [
    "Зараз добре розвантажуюсь після роботи 😄 А в тебе який сьогодні настрій?",
    "Тримаюсь спокійно 🙂 Що тебе найбільше заряджає цими днями?",
    "Є маленькі речі, за які вдячний(на). Який у тебе простий спосіб побалувати себе після роботи?",
  ],
  interests: [
    "Я люблю просто поблукати містом із подкастом і пробувати маленькі кав’ярні 🙂 Що тобі входить легко і робить щасливішим?",
    "Тягне до руху: велика прогулянка або зал без фанату 😄 Який «безглуздо улюблений» актив у тебе?",
    "Стараюся залишати час на щось майже домашнє — кіно або щось робити руками. Є у тебе таке хобі, про яке говорять рідко?",
  ],
  meet: [
    "Звучить приємно і без перегрузу 😄 Я б спробував(ла) легкий кавовий формат — тобі ближче будень чи вечір?",
    "Мені зручно якщо це недовго й можна просто побалакати 🙂 Коли найменше галасу у твоєму тижні?",
    "Згодна(ний) без «офіційного» тону — маленька кава чи короткий вихід надвір. На вихідних тобі вільніше?",
  ],
};

export type ContextualSuggestionBucket = keyof typeof UK_CTX;

export function detectContextualSuggestionBucket(raw: string | null | undefined): ContextualSuggestionBucket | null {
  const rawText = String(raw ?? "").trim();
  if (!rawText) return null;
  const low = rawText.toLowerCase();

  if (/(вихідн|weekend|викенд|выходные|на вихідних)/u.test(low)) return "weekend";
  if (/(як справи|як у тебе справи|що робиш|how are you|how've you been|hows your day|how's your day|how is your day)/iu.test(low)) {
    return "mood";
  }
  if (/(що любиш|любиш робити|цікавить|подобається|хобі|інтерес|what do you love|what are you into|interests)/iu.test(low)) {
    return "interests";
  }
  if (/(зустріт|зустрин|кава|каву|прогулян|випий|зустрітися|grab coffee|meet up|go for a walk)/iu.test(low)) return "meet";
  return null;
}

/** Apply contextual UA triple to client fallback pack (`uk` only). */
export function getChatFallbackPackForChatSuggestions(
  locale: AppLocale | string | null | undefined,
  partnerLastPlain: string | null | undefined,
): ChatFallbackPack {
  const base = getChatFallbackPack(locale);
  const canon = normalizeLocaleInput(String(locale ?? "")) ?? "en";
  if (canon !== "uk") return base;

  const bucket = detectContextualSuggestionBucket(partnerLastPlain);
  if (!bucket) return base;

  const [easy, flirty, deep] = UK_CTX[bucket];
  return { ...base, easySuggestion: easy, flirtySuggestion: flirty, deepSuggestion: deep };
}
