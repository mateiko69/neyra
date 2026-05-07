"""
Static AI-facing UI phrases (Discover / Matches shell / badges). Strict: every supported locale needs every key.
"""

from __future__ import annotations

from app.constants.supported_app_locales import ALL_SUPPORTED_APP_LOCALES
from app.services.ai.ai_request_locale import normalize_ai_request_locale

LABEL_AI_MATCH = "label_ai_match"
LABEL_BEST_OPTION = "label_best_option"
HEADLINE_START_CHAT = "headline_start_chat"
LINE_PARTNER_WAITING = "line_partner_waiting"
BADGE_AI_DEMO = "badge_ai_demo"
DISCOVER_AI_BADGE = "discover_ai_badge_short"
MATCHES_PROMPT_OPEN = "matches_prompt_open"
DEMO_TYPING_HINT = "demo_typing_hint"

REQUIRED_SURFACE_KEYS: tuple[str, ...] = (
    LABEL_AI_MATCH,
    LABEL_BEST_OPTION,
    HEADLINE_START_CHAT,
    LINE_PARTNER_WAITING,
    BADGE_AI_DEMO,
    DISCOVER_AI_BADGE,
    MATCHES_PROMPT_OPEN,
    DEMO_TYPING_HINT,
)

_EN_ROW: dict[str, str] = {
    LABEL_AI_MATCH: "AI match",
    LABEL_BEST_OPTION: "Best option",
    HEADLINE_START_CHAT: "Start the conversation",
    LINE_PARTNER_WAITING: "They're waiting — say hi first.",
    BADGE_AI_DEMO: "AI demo profile",
    DISCOVER_AI_BADGE: "AI compatibility",
    MATCHES_PROMPT_OPEN: "Pick a starter message you like",
    DEMO_TYPING_HINT: "Crafting something natural…",
}

# Non-English lines must avoid ENGLISH_LEAK_MARKERS probes (see english_leak.py).
_ROWS: dict[str, dict[str, str]] = {
    "en": dict(_EN_ROW),
    "uk": {
        LABEL_AI_MATCH: "ШІ-збіг",
        LABEL_BEST_OPTION: "Найкращий варіант",
        HEADLINE_START_CHAT: "Почніть розмову",
        LINE_PARTNER_WAITING: "Вас уже чекають — напишіть першими.",
        BADGE_AI_DEMO: "Демопрофіль зі ШІ",
        DISCOVER_AI_BADGE: "Сумісність ШІ",
        MATCHES_PROMPT_OPEN: "Оберіть початкове повідомлення",
        DEMO_TYPING_HINT: "Шукаю природню фразу…",
    },
    "ru": {
        LABEL_AI_MATCH: "ИИ‑совпадение",
        LABEL_BEST_OPTION: "Лучший вариант",
        HEADLINE_START_CHAT: "Начните разговор",
        LINE_PARTNER_WAITING: "Вас уже ждут — напишите первыми.",
        BADGE_AI_DEMO: "Демо профиль ИИ",
        DISCOVER_AI_BADGE: "Совместимость ИИ",
        MATCHES_PROMPT_OPEN: "Выберите первое сообщение",
        DEMO_TYPING_HINT: "Подбираю живую формулировку…",
    },
    "de": {
        LABEL_AI_MATCH: "KI‑Match",
        LABEL_BEST_OPTION: "Beste Option",
        HEADLINE_START_CHAT: "Starte das Gespräch",
        LINE_PARTNER_WAITING: "Es wird gewartet — schreib als Erste*r.",
        BADGE_AI_DEMO: "KI‑Demoprofil",
        DISCOVER_AI_BADGE: "KI‑Kompatibilität",
        MATCHES_PROMPT_OPEN: "Wähle eine erste Nachricht",
        DEMO_TYPING_HINT: "Formuliere etwas Natürliches…",
    },
    "fr": {
        LABEL_AI_MATCH: "Match IA",
        LABEL_BEST_OPTION: "Meilleure option",
        HEADLINE_START_CHAT: "Commence la conversation",
        LINE_PARTNER_WAITING: "On t’attend — écris en premier.",
        BADGE_AI_DEMO: "Profil démo IA",
        DISCOVER_AI_BADGE: "Compatibilité IA",
        MATCHES_PROMPT_OPEN: "Choisis un premier message",
        DEMO_TYPING_HINT: "Je rédige un message naturel…",
    },
    "es": {
        LABEL_AI_MATCH: "Coincidencia IA",
        LABEL_BEST_OPTION: "Mejor opción",
        HEADLINE_START_CHAT: "Empieza la conversación",
        LINE_PARTNER_WAITING: "Te están esperando — escribe primero.",
        BADGE_AI_DEMO: "Perfil demo IA",
        DISCOVER_AI_BADGE: "Compatibilidad IA",
        MATCHES_PROMPT_OPEN: "Elige un mensaje inicial",
        DEMO_TYPING_HINT: "Escribiendo algo natural…",
    },
    "pt": {
        LABEL_AI_MATCH: "Match IA",
        LABEL_BEST_OPTION: "Melhor opção",
        HEADLINE_START_CHAT: "Comece a conversa",
        LINE_PARTNER_WAITING: "Estão esperando você — mande primeiro.",
        BADGE_AI_DEMO: "Perfil demo IA",
        DISCOVER_AI_BADGE: "Compatibilidade IA",
        MATCHES_PROMPT_OPEN: "Escolha a primeira mensagem",
        DEMO_TYPING_HINT: "Escrevendo algo natural…",
    },
    "it": {
        LABEL_AI_MATCH: "Match IA",
        LABEL_BEST_OPTION: "Opzione migliore",
        HEADLINE_START_CHAT: "Apri la conversazione",
        LINE_PARTNER_WAITING: "Ti stanno aspettando — scrivi tu per primo.",
        BADGE_AI_DEMO: "Profilo demo IA",
        DISCOVER_AI_BADGE: "Compatibilità IA",
        MATCHES_PROMPT_OPEN: "Scegli un messaggio iniziale",
        DEMO_TYPING_HINT: "Sto formulando qualcosa di naturale…",
    },
    "pl": {
        LABEL_AI_MATCH: "Para AI",
        LABEL_BEST_OPTION: "Najlepsza opcja",
        HEADLINE_START_CHAT: "Zacznij rozmowę",
        LINE_PARTNER_WAITING: "Czekają na Ciebie — napisz pierwszy.",
        BADGE_AI_DEMO: "Profil demo AI",
        DISCOVER_AI_BADGE: "Zgodność AI",
        MATCHES_PROMPT_OPEN: "Wybierz pierwszą wiadomość",
        DEMO_TYPING_HINT: "Układam naturalną wiadomość…",
    },
    "tr": {
        LABEL_AI_MATCH: "YZ eşleşmesi",
        LABEL_BEST_OPTION: "En iyi seçenek",
        HEADLINE_START_CHAT: "Konuşmayı başlat",
        LINE_PARTNER_WAITING: "Bekliyorlar — ilk mesajı sen at.",
        BADGE_AI_DEMO: "YZ demo profili",
        DISCOVER_AI_BADGE: "YZ uyumu",
        MATCHES_PROMPT_OPEN: "İlk mesajı seç",
        DEMO_TYPING_HINT: "Doğal bir şey yazıyorum…",
    },
    "ar": {
        LABEL_AI_MATCH: "تطابق ذكاء اصطناعي",
        LABEL_BEST_OPTION: "أفضل خيار",
        HEADLINE_START_CHAT: "ابدأ المحادثة",
        LINE_PARTNER_WAITING: "في انتظارك — اكتب أول رسالة.",
        BADGE_AI_DEMO: "ملف تجريبي بالذكاء الاصطناعي",
        DISCOVER_AI_BADGE: "توافق بالذكاء الاصطناعي",
        MATCHES_PROMPT_OPEN: "اختر رسالة البداية",
        DEMO_TYPING_HINT: "أصيغ شيئًا طبيعيًا…",
    },
    "he": {
        LABEL_AI_MATCH: "התאמה בבינה",
        LABEL_BEST_OPTION: "אפשרות הכי טובה",
        HEADLINE_START_CHAT: "פתח את השיחה",
        LINE_PARTNER_WAITING: "מחכים לך — שלח מהר.",
        BADGE_AI_DEMO: "פרופיל דמו עם בינה",
        DISCOVER_AI_BADGE: "תאימות בינה מלאכותית",
        MATCHES_PROMPT_OPEN: "בחר הודעת פתיחה",
        DEMO_TYPING_HINT: "נסח משהו טבעי…",
    },
    "nl": {
        LABEL_AI_MATCH: "AI‑match",
        LABEL_BEST_OPTION: "Beste optie",
        HEADLINE_START_CHAT: "Begin het gesprek",
        LINE_PARTNER_WAITING: "Ze wachten op je — stuur eerst een bericht.",
        BADGE_AI_DEMO: "AI‑demo profiel",
        DISCOVER_AI_BADGE: "AI‑compatibiliteit",
        MATCHES_PROMPT_OPEN: "Kies een eerste bericht",
        DEMO_TYPING_HINT: "Iets natuurlijks aan het typen…",
    },
    "sv": {
        LABEL_AI_MATCH: "AI‑match",
        LABEL_BEST_OPTION: "Bästa alternativ",
        HEADLINE_START_CHAT: "Starta konversationen",
        LINE_PARTNER_WAITING: "De väntar — skriv först.",
        BADGE_AI_DEMO: "AI‑demoprofil",
        DISCOVER_AI_BADGE: "AI‑kompatibilitet",
        MATCHES_PROMPT_OPEN: "Välj ett första meddelande",
        DEMO_TYPING_HINT: "Formulerar något naturligt…",
    },
    "cs": {
        LABEL_AI_MATCH: "AI shoda",
        LABEL_BEST_OPTION: "Nejlepší možnost",
        HEADLINE_START_CHAT: "Začni konverzaci",
        LINE_PARTNER_WAITING: "Čekají — napiš první.",
        BADGE_AI_DEMO: "AI demo profil",
        DISCOVER_AI_BADGE: "AI kompatibilita",
        MATCHES_PROMPT_OPEN: "Vyber první zprávu",
        DEMO_TYPING_HINT: "Skládám přirozenou zprávu…",
    },
    "da": {
        LABEL_AI_MATCH: "AI‑match",
        LABEL_BEST_OPTION: "Bedste mulighed",
        HEADLINE_START_CHAT: "Start samtalen",
        LINE_PARTNER_WAITING: "De venter — skriv først.",
        BADGE_AI_DEMO: "AI‑demoprofil",
        DISCOVER_AI_BADGE: "AI‑kompatibilitet",
        MATCHES_PROMPT_OPEN: "Vælg en første besked",
        DEMO_TYPING_HINT: "Skriver noget naturligt…",
    },
    "fi": {
        LABEL_AI_MATCH: "Tekoäly‑sopimus",
        LABEL_BEST_OPTION: "Paras vaihtoehto",
        HEADLINE_START_CHAT: "Aloita keskustelu",
        LINE_PARTNER_WAITING: "Odotellaan vastaustasi — kirjoita ensin.",
        BADGE_AI_DEMO: "Tekoäly‑demoprofiili",
        DISCOVER_AI_BADGE: "Tekoäly‑yhteensopivuus",
        MATCHES_PROMPT_OPEN: "Valitse aloitusviesti",
        DEMO_TYPING_HINT: "Luon luontevaa tekstiä…",
    },
    "no": {
        LABEL_AI_MATCH: "KI‑match",
        LABEL_BEST_OPTION: "Beste valg",
        HEADLINE_START_CHAT: "Start samtalen",
        LINE_PARTNER_WAITING: "Venter på deg — skriv først.",
        BADGE_AI_DEMO: "KI‑demoprofil",
        DISCOVER_AI_BADGE: "KI‑kompatibilitet",
        MATCHES_PROMPT_OPEN: "Velg første melding",
        DEMO_TYPING_HINT: "Ordlegger noe naturlig…",
    },
    "ro": {
        LABEL_AI_MATCH: "Potrivire IA",
        LABEL_BEST_OPTION: "Cea mai bună opțiune",
        HEADLINE_START_CHAT: "Începe conversația",
        LINE_PARTNER_WAITING: "Te așteaptă — scrie prima dată.",
        BADGE_AI_DEMO: "Profil demo IA",
        DISCOVER_AI_BADGE: "Compatibilitate IA",
        MATCHES_PROMPT_OPEN: "Alege primul mesaj",
        DEMO_TYPING_HINT: "Formulez ceva natural…",
    },
    "hu": {
        LABEL_AI_MATCH: "MI‑párosítás",
        LABEL_BEST_OPTION: "Legjobb opció",
        HEADLINE_START_CHAT: "Kezdd el a beszélgetést",
        LINE_PARTNER_WAITING: "Várnak — írj először.",
        BADGE_AI_DEMO: "MI‑demó profil",
        DISCOVER_AI_BADGE: "MI‑illeszkedés",
        MATCHES_PROMPT_OPEN: "Válaszd az első üzenetet",
        DEMO_TYPING_HINT: "Természetes szöveget írok…",
    },
    "el": {
        LABEL_AI_MATCH: "Ταιριάζει με ΤΝ",
        LABEL_BEST_OPTION: "Καλύτερη επιλογή",
        HEADLINE_START_CHAT: "Ξεκίνα τη συζήτηση",
        LINE_PARTNER_WAITING: "Σε περιμένουν — γράψε πρώτος.",
        BADGE_AI_DEMO: "Δημόσιο προφίλ επίδειξης ΤΝ",
        DISCOVER_AI_BADGE: "Συμβατότητα ΤΝ",
        MATCHES_PROMPT_OPEN: "Διάλεξε πρώτο μήνυμα",
        DEMO_TYPING_HINT: "Γράφω κάτι φυσικό…",
    },
    "bg": {
        LABEL_AI_MATCH: "ИИ съвпадение",
        LABEL_BEST_OPTION: "Най-добрият избор",
        HEADLINE_START_CHAT: "Започни разговора",
        LINE_PARTNER_WAITING: "Те те чакат — първо ти напиши.",
        BADGE_AI_DEMO: "ИИ демо профил",
        DISCOVER_AI_BADGE: "ИИ съвместимост",
        MATCHES_PROMPT_OPEN: "Избери първо съобщение",
        DEMO_TYPING_HINT: "Съчинявам нещо естествено…",
    },
    "ja": {
        LABEL_AI_MATCH: "AIマッチ",
        LABEL_BEST_OPTION: "ベストな案",
        HEADLINE_START_CHAT: "会話を始める",
        LINE_PARTNER_WAITING: "待っています。まず話しかけて。",
        BADGE_AI_DEMO: "AIデモプロフィール",
        DISCOVER_AI_BADGE: "AI相性",
        MATCHES_PROMPT_OPEN: "最初の一言を選ぶ",
        DEMO_TYPING_HINT: "自然な一文を用意中…",
    },
    "ko": {
        LABEL_AI_MATCH: "AI 매칭",
        LABEL_BEST_OPTION: "추천 문구",
        HEADLINE_START_CHAT: "대화를 시작해요",
        LINE_PARTNER_WAITING: "기다리고 있어요 — 먼저 메시지를 보내요.",
        BADGE_AI_DEMO: "AI 데모 프로필",
        DISCOVER_AI_BADGE: "AI 궁합",
        MATCHES_PROMPT_OPEN: "첫 메시지를 고르세요",
        DEMO_TYPING_HINT: "자연스러운 문구를 준비 중…",
    },
    "zh-CN": {
        LABEL_AI_MATCH: "AI 配对",
        LABEL_BEST_OPTION: "更合适的一条",
        HEADLINE_START_CHAT: "开口打个招呼吧",
        LINE_PARTNER_WAITING: "对方在等你——先发一条试试。",
        BADGE_AI_DEMO: "AI 演示档案",
        DISCOVER_AI_BADGE: "AI 契合度",
        MATCHES_PROMPT_OPEN: "选择你想发的开场白",
        DEMO_TYPING_HINT: "帮你写句更自然的…",
    },
    "zh-TW": {
        LABEL_AI_MATCH: "AI 配對",
        LABEL_BEST_OPTION: "首推選項",
        HEADLINE_START_CHAT: "開始聊天吧",
        LINE_PARTNER_WAITING: "對方正在等你——先傳個訊息。",
        BADGE_AI_DEMO: "AI 示範檔案",
        DISCOVER_AI_BADGE: "AI 合拍度",
        MATCHES_PROMPT_OPEN: "挑一句開場訊息",
        DEMO_TYPING_HINT: "幫你想句更自然的話…",
    },
    "hi": {
        LABEL_AI_MATCH: "एआई मैच",
        LABEL_BEST_OPTION: "सबसे अच्छा विकल्प",
        HEADLINE_START_CHAT: "बातचीत शुरू करें",
        LINE_PARTNER_WAITING: "वे इंतज़ार में हैं — पहले आप लिखें।",
        BADGE_AI_DEMO: "एआई डेमो प्रोफ़ाइल",
        DISCOVER_AI_BADGE: "एआई मेल",
        MATCHES_PROMPT_OPEN: "पहला संदेश चुनें",
        DEMO_TYPING_HINT: "कुछ स्वाभाविक लिख रहे हैं…",
    },
    "id": {
        LABEL_AI_MATCH: "Pasangan AI",
        LABEL_BEST_OPTION: "Pilihan terbaik",
        HEADLINE_START_CHAT: "Mulai percakapan",
        LINE_PARTNER_WAITING: "Mereka menunggumu — kirim lebih dulu.",
        BADGE_AI_DEMO: "Profil demo AI",
        DISCOVER_AI_BADGE: "Kompatibilitas AI",
        MATCHES_PROMPT_OPEN: "Pilih pesan pembuka",
        DEMO_TYPING_HINT: "Menyusun kata yang lebih natural…",
    },
    "vi": {
        LABEL_AI_MATCH: "Ghép AI",
        LABEL_BEST_OPTION: "Tuỳ chọn hay nhất",
        HEADLINE_START_CHAT: "Mở lời nhé",
        LINE_PARTNER_WAITING: "Họ đang chờ — bạn nhắn trước nhé.",
        BADGE_AI_DEMO: "Hồ sơ demo AI",
        DISCOVER_AI_BADGE: "Độ hợp AI",
        MATCHES_PROMPT_OPEN: "Chọn một câu mở đầu",
        DEMO_TYPING_HINT: "Đang viết câu tự nhiên hơn…",
    },
    "th": {
        LABEL_AI_MATCH: "แมตช์จาก AI",
        LABEL_BEST_OPTION: "ตัวเลือกที่ดีที่สุด",
        HEADLINE_START_CHAT: "เริ่มบทสนทนา",
        LINE_PARTNER_WAITING: "อีกฝั่งกำลังรอ — ส่งข้อความก่อนนะ",
        BADGE_AI_DEMO: "โปรไฟล์โชว์จาก AI",
        DISCOVER_AI_BADGE: "ความเข้ากันแบบ AI",
        MATCHES_PROMPT_OPEN: "เลือกข้อความเปิดประโยค",
        DEMO_TYPING_HINT: "กำลังคิดข้อความให้ฟังดูเป็นธรรมชาติ…",
    },
}


def _validate_closure() -> None:
    missing_locales = sorted(set(ALL_SUPPORTED_APP_LOCALES) - set(_ROWS.keys()))
    if missing_locales:
        raise RuntimeError(f"ai_surface_catalog missing locales: {missing_locales}")
    base_keys = tuple(sorted(_ROWS["en"].keys()))
    if base_keys != tuple(sorted(REQUIRED_SURFACE_KEYS)):
        raise RuntimeError("ai_surface_catalog en keys mismatch")
    for loc, row in _ROWS.items():
        for k in REQUIRED_SURFACE_KEYS:
            if k not in row or not str(row[k] or "").strip():
                raise RuntimeError(f"ai_surface_catalog empty: {loc}.{k}")


_validate_closure()


def ai_surface_must(locale: str | None, key: str) -> str:
    if key not in REQUIRED_SURFACE_KEYS:
        raise KeyError(key)
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "zh" or (loc.startswith("zh") and loc != "zh-TW"):
        lookup = _ROWS.get("zh-CN")
    else:
        lookup = _ROWS.get(loc)
    if not lookup:
        raise KeyError(f"unknown_locale_surface:{loc}")
    return str(lookup[key])


def all_surface_strings_for_locale(locale: str | None) -> dict[str, str]:
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "zh" or (loc.startswith("zh") and loc != "zh-TW"):
        row = _ROWS.get("zh-CN")
    else:
        row = _ROWS.get(loc) or _ROWS["en"]
    return {k: str(row[k]) for k in REQUIRED_SURFACE_KEYS}


def catalog_integrity_checked() -> bool:
    """False if catalogue failed internal validation during import."""
    try:
        _validate_closure()
        return True
    except RuntimeError:
        return False


__all__ = [
    "REQUIRED_SURFACE_KEYS",
    "LABEL_AI_MATCH",
    "LABEL_BEST_OPTION",
    "HEADLINE_START_CHAT",
    "LINE_PARTNER_WAITING",
    "BADGE_AI_DEMO",
    "DISCOVER_AI_BADGE",
    "MATCHES_PROMPT_OPEN",
    "DEMO_TYPING_HINT",
    "ai_surface_must",
    "all_surface_strings_for_locale",
    "catalog_integrity_checked",
]
