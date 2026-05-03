"""Localized short advice strings for /ai/coach/next-move (no mixing with English when a locale block exists)."""

from __future__ import annotations

from app.services.ai.ai_request_locale import normalize_chat_ai_locale

_ADVICE: dict[str, dict[str, str]] = {
    "en": {
        "wait": "Give it a little space before sending another message.",
        "revive": "Reopen the thread with a light, pressure-free question.",
        "ask_question": "Ask one specific question that is easy to answer.",
        "flirt": "Add a little playful warmth without pushing.",
        "deepen": "Share one personal detail and invite them in.",
        "suggest_meet": "Softly float coffee or a simple low-pressure plan.",
        "reply": "Send a short natural reply and keep the rhythm easy.",
    },
    "uk": {
        "wait": "Зараз краще трохи почекати.",
        "revive": "Поверни розмову легким питанням без тиску.",
        "ask_question": "Постав одне конкретне питання, на яке легко відповісти.",
        "flirt": "Можна додати легкий флірт, але без різкого тиску.",
        "deepen": "Додай трохи особистого контексту і м'яке питання.",
        "suggest_meet": "Можна м'яко натякнути на каву або коротку зустріч.",
        "reply": "Відповідай коротко і природно.",
    },
    "ru": {
        "wait": "Сейчас лучше дать немного пространства.",
        "revive": "Вернись к диалогу лёгким вопросом без давления.",
        "ask_question": "Задай один конкретный вопрос, на который легко ответить.",
        "flirt": "Можно добавить лёгкий флирт — без навязчивости.",
        "deepen": "Добавь немного личного контекста и мягкий вопрос.",
        "suggest_meet": "Можно мягко намекнуть на кофе или простой план.",
        "reply": "Ответь коротко и естественно.",
    },
    "fr": {
        "wait": "Laisse un peu d’air avant d’envoyer un autre message.",
        "revive": "Réouvre avec une question légère, sans pression.",
        "ask_question": "Pose une question précise et facile à répondre.",
        "flirt": "Ajoute une touche de jeu, sans insister.",
        "deepen": "Partage un détail personnel et invite à répondre.",
        "suggest_meet": "Propose doucement un café ou un plan simple.",
        "reply": "Réponds court et naturel, garde le rythme léger.",
    },
    "de": {
        "wait": "Gib der Situation kurz Luft, bevor du wieder schreibst.",
        "revive": "Öffne wieder mit einer leichten Frage ohne Druck.",
        "ask_question": "Stell eine konkrete Frage, die leicht zu beantworten ist.",
        "flirt": "Ein bisschen spielerische Wärme — ohne zu drängen.",
        "deepen": "Teil eine kleine persönliche Nuance und lade ein.",
        "suggest_meet": "Schlag Kaffee oder einen entspannten Plan sanft vor.",
        "reply": "Antworte kurz und natürlich.",
    },
    "es": {
        "wait": "Da un poco de espacio antes de mandar otro mensaje.",
        "revive": "Retoma con una pregunta ligera y sin presión.",
        "ask_question": "Haz una pregunta concreta que sea fácil de responder.",
        "flirt": "Añade un toque juguetón sin insistir.",
        "deepen": "Comparte un detalle personal y abre la puerta.",
        "suggest_meet": "Propón suavemente un café o un plan sencillo.",
        "reply": "Responde corto y natural.",
    },
    "ar": {
        "wait": "سيب مسافة بسيطة قبل ما تبعت رسالة تانية.",
        "revive": "ارجع للمحادثة بسؤال خفيف من غير ضغط.",
        "ask_question": "اسأل سؤال واحد محدد وسهل الإجابة.",
        "flirt": "زوّدها بلمسة مرحة من غير إلحاح.",
        "deepen": "شارك تفصيلة شخصية خفيفة ووجّه سؤال لطيف.",
        "suggest_meet": "اقترح قهوة أو خطة بسيطة بهدوء.",
        "reply": "رد باختصار وبطبيعية.",
    },
    "ja": {
        "wait": "次のメッセージの前に少し間を置こう。",
        "revive": "プレッシャーじゃない軽い質問で再開して。",
        "ask_question": "答えやすい具体的な質問を一つ。",
        "flirt": "軽いユーモアはOK、押しつけはしない。",
        "deepen": "ちょっとした自分のことを添えて誘う。",
        "suggest_meet": "カフェやゆるい予定をさりげなく提案。",
        "reply": "短く自然に返そう。",
    },
    "zh": {
        "wait": "下一条消息前先留一点空间。",
        "revive": "用轻松、无压力的问题重新打开话题。",
        "ask_question": "问一个具体又好回答的问题。",
        "flirt": "可以带点俏皮感，但不要用力过猛。",
        "deepen": "分享一点个人信息，再轻轻抛个问题。",
        "suggest_meet": "顺势提一下咖啡或很轻松的见面安排。",
        "reply": "简短自然地回复，保持节奏舒服。",
    },
    "zh-TW": {
        "wait": "下一則訊息前先留一點空間。",
        "revive": "用輕鬆、不施壓的問題重新開話題。",
        "ask_question": "問一個具體又好回答的問題。",
        "flirt": "可以帶點俏皮感，但不要用力過猛。",
        "deepen": "分享一點個人資訊，再輕輕拋個問題。",
        "suggest_meet": "順勢提一下咖啡或很輕鬆的見面安排。",
        "reply": "簡短自然地回覆，保持節奏舒服。",
    },
}


def coach_advice_for_move(move: str, *, locale: str) -> str:
    loc = normalize_chat_ai_locale(locale or "en")
    block = _ADVICE.get(loc)
    if block is None and "-" in loc:
        block = _ADVICE.get(loc.split("-", 1)[0])
    if block is None:
        block = _ADVICE["en"]
    m = str(move or "").strip()
    return block.get(m) or block.get("reply") or _ADVICE["en"]["reply"]
