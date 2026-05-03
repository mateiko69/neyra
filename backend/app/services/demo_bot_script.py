"""
Human-feel scripted lines for demo bots: first 5 outbound messages arc + interest injection.
Steps: warm opener → playful hook → topic expansion → personal detail → soft flirt / deeper hook.
"""

from __future__ import annotations

import random
import re
from typing import Any

from app.services.app_language import normalize_app_language

# --- Interest snippets (short, natural) ---------------------------------

_INTEREST_HOOKS_EN: dict[str, list[str]] = {
    "travel": ["I'm low-key obsessed with planning tiny trips", "I keep a running list of places I want to see"],
    "food": ["I'm always hunting for a new spot for coffee or ramen", "Food is my love language, honestly"],
    "music": ["I'm that person who makes playlists for every mood", "Live music > everything else for me"],
    "movies": ["I watch way too many trailers", "I'm picky about endings — they matter"],
    "fitness": ["I need movement most days or I get restless", "Gym or a long walk — either works"],
    "books": ["I read slower than I buy books", "Fiction at night, non-fiction when I'm pretending to be productive"],
    "nightlife": ["I like going out, but small bars > huge clubs", "I'm a 'one good drink and good chat' person"],
    "pets": ["If you have a pet, I will ask for photos immediately", "Animals make people 10x more trustworthy 😄"],
    "art": ["I drag friends to random galleries", "I notice fonts and packaging way too much"],
    "coffee": ["I'm picky about coffee in the best/worst way", "A good flat white can fix my morning"],
    "hiking": ["Weekend hikes are my reset button", "I like trails where phone signal dies"],
    "gaming": ["I game to unwind — nothing too competitive", "Cozy games > rage games for me"],
}

_INTEREST_HOOKS_UK: dict[str, list[str]] = {
    "travel": ["Я та, хто збирає міні-подорожі в нотатках", "Тримаю список місць, куди хочу з'їздити"],
    "food": ["Постійно шукаю нове місце на каву чи рамен", "Їжа для мене — мова турботи"],
    "music": ["Роблю плейлисти під настрій", "Жива музика — топ"],
    "movies": ["Дивлюсь забагато трейлерів", "Фінал фільму для мене важливий"],
    "fitness": ["Без руху день — і я неспокійна", "Зал або довга прогулянка — ок обидва"],
    "books": ["Купую книжки швидше, ніж читаю", "Ввечері фікшн, вдень ніби продуктивна нон-фікшн"],
    "nightlife": ["Люблю вийти, але маленькі бари > величезні клуби", "Один гарний напій і розмова — ідеал"],
    "pets": ["Якщо є домашня тварина — одразу прошу фото", "Тварини додають людям +10 до довіри 😄"],
    "art": ["Веду друзів у випадкові галереї", "Занадто помічаю шрифти на упаковці"],
    "coffee": ["До кави вибаглива в хорошому сенсі", "Гарний флет вайт рятує ранок"],
    "hiking": ["Похід на вихідних — мій ресет", "Люблю стежки, де пропадає зв'язок"],
    "gaming": ["Граю, щоб відключити голову", "Козі-ігри, не токсик"],
}


def _interest_pool(pers: dict[str, Any]) -> list[str]:
    raw = pers.get("interests")
    out: list[str] = []
    if isinstance(raw, list):
        out.extend(str(x).strip().lower() for x in raw if str(x).strip())
    elif isinstance(raw, str) and raw.strip():
        out.extend(re.split(r"[,;|]", raw.lower()))
    legacy = pers.get("preferred_topics")
    if isinstance(legacy, list):
        out.extend(str(x).strip().lower() for x in legacy if str(x).strip())
    # normalize tokens
    cleaned = []
    for x in out:
        t = re.sub(r"\s+", " ", x).strip()
        if t and t not in cleaned:
            cleaned.append(t)
    return cleaned


def _pick_interest_hook(pers: dict[str, Any], lang: str) -> str:
    pool = _interest_pool(pers)
    code = normalize_app_language(lang)
    hooks = _INTEREST_HOOKS_UK if code == "uk" else _INTEREST_HOOKS_EN
    # match longest key substring
    for topic in sorted(hooks.keys(), key=len, reverse=True):
        if any(topic in p or p in topic for p in pool):
            return random.choice(hooks[topic])
    if pool:
        return pool[0] if code != "uk" else f"мене цікавить {pool[0]}"
    if code == "uk":
        return random.choice(_INTEREST_HOOKS_UK["coffee"])
    return random.choice(_INTEREST_HOOKS_EN["coffee"])


def _flirt_suffix(lang: str, level: int) -> str:
    level = max(0, min(3, int(level)))
    if normalize_app_language(lang) == "uk":
        opts = {
            0: [" Тобі як — більше писати чи інколи голосом?", " Що тебе зараз найбільше цепляє в людях?"],
            1: [" Можу уявити, як ми вибрали б кав'ярню і посміялись з дрібниць 🙂", " У тебе є якийсь 'ред флаг' у чатах, на який одразу дивишся?"],
            2: [" Трохи відверто: ти б скоріше написала перша, чи чекала б знаку?", " Мені подобається твій тон — хочеться дізнатись більше."],
            3: [" Якщо це не занадто різко: ти виглядаєш як людина з характером — це рідкість.", " Скажи чесно — ти більше про глибокі розмови чи про легкий флірт спочатку?"],
        }
    else:
        opts = {
            0: [" What pulls you in more — texting or voice notes?", " What are you picky about in people lately?"],
            1: [" I can picture us picking a cafe and laughing at something tiny 🙂", " Do you have a chat 'red flag' you notice fast?"],
            2: [" Honestly: are you more likely to text first, or wait for a signal?", " I like your vibe — I want to know more."],
            3: [" If this isn't too forward: you give 'has opinions' energy — I like that.", " Be real: deep talks first, or a little flirt upfront?"],
        }
    return random.choice(opts.get(level, opts[1]))


def _maybe_disagree(lang: str) -> str:
    if normalize_app_language(lang) == "uk":
        return random.choice(
            [
                "Чесно, я б сперечалась трохи 😄 ",
                "Не на 100% згодна, але це цікаво: ",
                "Трохи інший кут, але ок: ",
            ]
        )
    return random.choice(
        [
            "Okay I'm gonna slightly disagree 😄 ",
            "Not sure I buy that 100%, but I like it: ",
            "Different take, but I'm into it: ",
        ]
    )


def scripted_demo_message(
    *,
    step: int,
    pers: dict[str, Any],
    lang: str,
    partner_name: str,
) -> str:
    """
    step: 0..4 = first-five arc; >=5 returns "" (caller uses AI/template).
    """
    step = int(step)
    if step < 0 or step > 4:
        return ""
    code = normalize_app_language(lang)
    name = (partner_name or "there").strip() or ("там" if code == "uk" else "there")
    personality = str(pers.get("personality") or "warm").strip().lower()
    if personality in {"flirty", "playful"}:
        personality = "playful"
    elif personality in {"dry", "cold", "sarcastic"}:
        personality = "sarcastic"
    elif personality in {"curious", "deep"}:
        personality = "deep"
    elif personality not in {"warm", "playful", "deep", "sarcastic"}:
        personality = "warm"
    flirt_level = int(pers.get("flirt_level") if pers.get("flirt_level") is not None else 1)
    hook = _pick_interest_hook(pers, lang)
    disagree = _maybe_disagree(lang) if step >= 2 and random.random() < 0.14 else ""

    def en() -> str:
        if step == 0:
            if personality == "sarcastic":
                return f"Hey {name} — okay, we matched. I'll keep this human: what's the least boring thing about your week?"
            if personality == "deep":
                return f"Hi {name}. Glad this matched — what's been on your mind lately, even something small?"
            if personality == "playful":
                return f"Hey {name} 🙂 okay, real question: are you more 'plans' or 'see what happens' this weekend?"
            return f"Hey {name} — glad we matched. How's your week actually going?"
        if step == 1:
            if personality == "sarcastic":
                return f"Alright {name}, I'll bite — tell me something you're into that isn't on your profile."
            if personality == "deep":
                return f"I like how you text. What's something you're quietly proud of right now?"
            if personality == "playful":
                return f"Quick vibe check {name}: coffee shop date or sunset walk — pick one, no essays 😄"
            return f"I'm curious {name} — what's one thing you're looking forward to?"
        if step == 2:
            base = f"{disagree}{hook} — what about you, anything similar or totally opposite?"
            if personality == "playful":
                return f"{disagree}Random: {hook}. Your turn — what are you obsessed with lately?"
            if personality == "deep":
                return f"{disagree}I've been thinking about that kind of thing too. {hook} — does that resonate or nah?"
            return base
        if step == 3:
            if personality == "sarcastic":
                return f"{disagree}Tiny real detail: I once missed a flight because I was eating something stupidly good. What's your chaos story?"
            if personality == "deep":
                return f"{disagree}I'll share first: I recharge alone, but I like one-on-one energy. What fills your cup?"
            if personality == "playful":
                return f"{disagree}Okay story time (short): I tried something new last month and laughed at myself the whole way. Ever do that?"
            return f"{disagree}I'll go first: I'm picky about the little things, in a good way. What are you picky about?"
        # step 4
        if personality == "sarcastic":
            return f"Not gonna oversell it {name}, but you're easy to talk to.{_flirt_suffix(lang, flirt_level)}"
        if personality == "deep":
            return f"I like this thread {name}. It feels easy.{_flirt_suffix(lang, min(3, flirt_level + 1))}"
        if personality == "playful":
            return f"This is fun {name} — I'm gonna risk a slightly bold question.{_flirt_suffix(lang, min(3, flirt_level + 1))}"
        return f"I'm enjoying this {name}.{_flirt_suffix(lang, flirt_level)}"

    def uk() -> str:
        if step == 0:
            if personality == "sarcastic":
                return f"Привіт, {name} — окей, ми зійшлися. По-людськи: що найменш нудне сталося цього тижня?"
            if personality == "deep":
                return f"Привіт, {name}. Рада, що зійшлися — що останнім часом крутиться в голові, навіть дрібниця?"
            if personality == "playful":
                return f"Привіт, {name} 🙂 реальне питання: ти більше про 'плани' чи 'подивимось' на вихідних?"
            return f"Привіт, {name} — приємно зійтися. Як насправді твій тиждень?"
        if step == 1:
            if personality == "sarcastic":
                return f"Добре, {name}, я кусаюсь — скажи щось, чого нема в профілі."
            if personality == "deep":
                return f"Мені подобається, як ти пишеш. Чим ти зараз тихо пишаєшся?"
            if personality == "playful":
                return f"Швидкий чек {name}: кав'ярня чи захід сонця — одне слово, без есе 😄"
            return f"Цікаво, {name} — на що ти зараз чекаєш?"
        if step == 2:
            if personality == "playful":
                return f"{disagree}Рандом: {hook}. Твоя черга — чим ти зараз 'хворієш'?"
            if personality == "deep":
                return f"{disagree}Я теж про таке думала. {hook} — відгукується чи ні?"
            return f"{disagree}{hook} — а в тебе схоже чи навпаки?"
        if step == 3:
            if personality == "sarcastic":
                return f"{disagree}Дрібниця: я колись спізнилась на рейс через їжу. Твоя історія хаосу?"
            if personality == "deep":
                return f"{disagree}Я заряджаюсь наодинці, але люблю розмови один на один. Що тебе наповнює?"
            if personality == "playful":
                return f"{disagree}Коротка історія: я пробувала щось нове і сміялась з себе. Бувало?"
            return f"{disagree}Я спочатку: я вибаглива до дрібниць у хорошому сенсі. А ти до чого вибаглива?"
        if personality == "sarcastic":
            return f"Не буду продавати ідеал, {name}, але з тобою легко.{_flirt_suffix(lang, flirt_level)}"
        if personality == "deep":
            return f"Мені подобається ця нитка, {name}. Легко.{_flirt_suffix(lang, min(3, flirt_level + 1))}"
        if personality == "playful":
            return f"Це весело, {name} — ризикну трохи сміливішим питанням.{_flirt_suffix(lang, min(3, flirt_level + 1))}"
        return f"Мені подобається ця розмова, {name}.{_flirt_suffix(lang, flirt_level)}"

    text = uk() if code == "uk" else en()
    text = re.sub(r"\s+", " ", text).strip()
    # Scripted first-5 arc should always contain a question to keep momentum.
    if text and ("?" not in text and "？" not in text):
        text = text.rstrip(".! ") + "?"
    if len(text) > 220:
        text = text[:217].rsplit(" ", 1)[0] + "…"
    return text


def demo_outbound_step(db: Any, demo_uid: int, partner_id: int) -> int:
    """Count of messages already sent by demo bot to partner (next line uses this index)."""
    from sqlalchemy import and_

    from app.models.message import Message

    n = (
        db.query(Message)
        .filter(and_(Message.sender_id == int(demo_uid), Message.receiver_id == int(partner_id)))
        .count()
    )
    return int(n or 0)
