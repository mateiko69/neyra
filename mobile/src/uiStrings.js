/** Mobile shell strings (EN/UK). Keys align with web where possible; use tx(key). */

const STR = {
  en: {
    "brand.tagline": "AI wingman for real conversations.",
    "mobile.configWarning.title": "Config warning",
    "auth.email.placeholder": "Email",
    "auth.password.placeholder": "Password",
    "common.continue": "Continue",
    "mobile.login.tip": "Tip: use seed user credentials from README.",
    "mobile.error.login": "Could not sign in. Check email/password and backend URL.",
    "mobile.error.discover": "Could not load Discover. Check EXPO_PUBLIC_API_URL.",
    "nav.discover": "Discover",
    "nav.matches": "Matches",
    "nav.chat": "Chat",
    "nav.premium": "Premium",
    "common.loading": "Loading…",
    "discover.empty.title": "No profiles right now",
    "discover.empty.subtitle": "Try again later or check your backend seed data.",
    "matches.header.subtitle": "Verify API connectivity and pagination.",
    "matches.empty.title": "No matches yet",
    "matches.empty.subtitle": "Create matches by liking reciprocal profiles in Discover.",
    "matches.field.userId": "User ID:",
    "mobile.chat.bannerNote": "This checks WebSocket reachability from your phone.",
    "mobile.chat.title": "Chat connectivity test",
    "mobile.chat.apiLine": "API:",
    "mobile.chat.wsLine": "WS:",
    "mobile.chat.testWs": "Test WebSocket",
    "mobile.chat.status": "Status:",
    "mobile.chat.wsNote": "Note: backend WS path is `/ws/chat/{user_id}` — this test appends `/1`.",
    "mobile.ws.missingUrl": "Missing EXPO_PUBLIC_WS_URL",
    "mobile.ws.error": "WebSocket error",
    "mobile.ws.failedStart": "WebSocket failed to start",
    "mobile.ws.status.disconnected": "Disconnected",
    "mobile.ws.status.connecting": "Connecting…",
    "mobile.ws.status.connected": "Connected",
    "mobile.ws.status.error": "Error",
    "mobile.config.valueMissing": "(not set)",
    "mobile.premium.subtitle":
      "Premium unlocks extra AI features and supports NEYRA development while the project grows.",
    "demo.profile.label": "Demo profile",
    "demo.profile.disclaimer":
      "This is a demo profile for product walkthroughs. It is not a real member.",
    "demo.chat.banner":
      "Demo threads use AI simulation — the other side is not a real person.",
  },
  uk: {
    "brand.tagline": "AI-крило для справжніх розмов.",
    "mobile.configWarning.title": "Попередження конфігурації",
    "auth.email.placeholder": "Електронна пошта",
    "auth.password.placeholder": "Пароль",
    "common.continue": "Продовжити",
    "mobile.login.tip": "Підказка: облікові дані тестового користувача — у README.",
    "mobile.error.login": "Не вдалося увійти. Перевір email/пароль і URL бекенду.",
    "mobile.error.discover": "Не вдалося завантажити Discover. Перевір EXPO_PUBLIC_API_URL.",
    "nav.discover": "Знайомства",
    "nav.matches": "Матчі",
    "nav.chat": "Чат",
    "nav.premium": "Преміум",
    "common.loading": "Завантаження…",
    "discover.empty.title": "Зараз немає профілів",
    "discover.empty.subtitle": "Спробуй пізніше або перевір тестові дані на бекенді.",
    "matches.header.subtitle": "Перевір з’єднання з API та пагінацію.",
    "matches.empty.title": "Поки без матчів",
    "matches.empty.subtitle": "Створюй матчі, ставлячи взаємні лайки в Discover.",
    "matches.field.userId": "ID користувача:",
    "mobile.chat.bannerNote": "Перевіряємо доступність WebSocket з телефону.",
    "mobile.chat.title": "Тест з’єднання чату",
    "mobile.chat.apiLine": "API:",
    "mobile.chat.wsLine": "WS:",
    "mobile.chat.testWs": "Тест WebSocket",
    "mobile.chat.status": "Статус:",
    "mobile.chat.wsNote": "Примітка: WS на бекенді — `/ws/chat/{user_id}`; тут додаємо `/1`.",
    "mobile.ws.missingUrl": "Немає EXPO_PUBLIC_WS_URL",
    "mobile.ws.error": "Помилка WebSocket",
    "mobile.ws.failedStart": "Не вдалося запустити WebSocket",
    "mobile.ws.status.disconnected": "Від’єднано",
    "mobile.ws.status.connecting": "З’єднання…",
    "mobile.ws.status.connected": "З’єднано",
    "mobile.ws.status.error": "Помилка",
    "mobile.config.valueMissing": "(не задано)",
    "mobile.premium.subtitle":
      "Premium відкриває додаткові AI-функції й підтримує розвиток NEYRA.",
    "demo.profile.label": "Демо-профіль",
    "demo.profile.disclaimer":
      "Це демо-профіль для показу продукту. Це не справжній учасник.",
    "demo.chat.banner":
      "Демо-чати — симуляція AI; з іншого боку не справжня людина.",
  },
};

export function appLang() {
  try {
    const loc = (Intl.DateTimeFormat().resolvedOptions().locale || "en").toLowerCase();
    return loc.startsWith("uk") ? "uk" : "en";
  } catch {
    return "en";
  }
}

export function tx(key) {
  const lang = appLang();
  const row = STR[lang] || STR.en;
  return row[key] || STR.en[key] || key;
}
