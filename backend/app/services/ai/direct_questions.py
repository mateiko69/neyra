from __future__ import annotations

import re
import zlib

from app.models.profile import Profile
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.output_script_locale import _letter_counts

DirectIntent = str  # "city"|"age"|"job"|"hobbies"|"goal"|"weekend"|"travel"|"music_movies_food_fashion"

_RE_UK = re.compile(r"[іїєґ]", re.IGNORECASE)
_RE_CYR = re.compile(r"[а-яёіїєґ]", re.IGNORECASE)


def guess_lang(text: str, *, default: str = "en") -> str:
    s = (text or "").strip().lower()
    if not s:
        return default
    if _RE_UK.search(s):
        return "uk"
    if _RE_CYR.search(s):
        return "ru"
    return "en"


def resolve_output_locale(last_user_message: str, ui_locale: str | None) -> str:
    """
    Prefer explicit script (Arabic, Hindi, CJK, Cyrillic); for Latin text prefer UI locale
    when set (e.g. Spanish UI + Spanish question).
    """
    ui = normalize_ai_request_locale(ui_locale or "en")
    raw = (last_user_message or "").strip()
    if not raw:
        return ui
    counts = _letter_counts(raw)
    if counts["arabic"] >= 2:
        return "ar"
    if counts["devanagari"] >= 2:
        return "hi"
    if counts["han"] >= 1:
        return "zh-TW" if ui == "zh-TW" else "zh"
    if _RE_UK.search(raw):
        return "uk"
    if _RE_CYR.search(raw) and not _RE_UK.search(raw):
        return "ru"
    if counts["latin"] >= 2 and ui and ui != "en":
        return ui
    gl = guess_lang(raw, default=ui)
    if gl in {"uk", "ru"}:
        return gl
    return ui if ui else "en"


def detect_direct_intent(last_user_message: str) -> DirectIntent | None:
    s = (last_user_message or "").strip().lower()
    if not s:
        return None

    # Location / city — English + Ukrainian + Russian
    if re.search(r"\b(where are you from|where do you live|what city)\b", s) or re.search(
        r"(з якого міста|звідки ти|де живеш|ти звідки|звідки родом|из какого города|откуда ты|где живёшь)",
        s,
    ):
        return "city"
    # Spanish / Portuguese / French / Italian / German / Polish
    if re.search(
        r"\b(de qué ciudad|de donde eres|dónde vives|de que cidade|de onde você é|où habites-tu|d’où viens-tu|"
        r"di dove sei|da dove vieni|wo wohnst du|woher kommst du|aus welcher stadt|z jakiego miasta|skąd jesteś)\b",
        s,
    ):
        return "city"
    # Chinese
    if re.search(r"(哪[里裡]|哪儿|住哪|哪个城市|你是哪|在哪座城市)", last_user_message or ""):
        return "city"
    # Arabic (colloquial + MSA fragments)
    if re.search(r"(من وين|منين|وين ساكن|فين ساكن|من أي مدينة|من أين أنت)", s):
        return "city"

    # Age
    if re.search(r"\b(how old are you|your age)\b", s) or re.search(
        r"(скільки тобі років|скільки років|який вік|тобі скільки|сколько тебе лет|какой возраст)",
        s,
    ):
        return "age"
    if re.search(
        r"\b(cuántos años tienes|quantos anos você tem|quel âge as-tu|quanti anni hai|wie alt bist du|"
        r"ile masz lat|कितने साल के|عندك كام سنة|كم عمرك|你多大|幾歲)\b",
        s,
    ) or re.search(r"(多大|几岁|年齡|年龄)", last_user_message or ""):
        return "age"

    # Job / work
    if re.search(r"\b(what do you do|job|work)\b", s) or re.search(
        r"(чим займаєшся|де працюєш|робота|працюєш\\?|професія|кем работаешь|чем занимаешься|работаешь\\?)",
        s,
    ):
        return "job"
    if re.search(
        r"\b(a qué te dedicas|trabajas de|o que você faz|tu fais quoi dans la vie|che lavoro fai|"
        r"was machst du beruflich|czym się zajmujesz|तुम क्या काम करते|بتشتغل إيه|你做什么工作)\b",
        s,
    ):
        return "job"

    # Hobbies / interests
    if re.search(r"\b(hobbies|interests|what do you like)\b", s) or re.search(
        r"(хобі|що любиш|що тобі подобається|інтереси|чим захоплюєшся|увлечения|что любишь|интересы|чем увлекаешься)",
        s,
    ):
        return "hobbies"
    if re.search(
        r"\b(qué te gusta hacer|passatempos|loisirs|hobby|hobbys|zainteresowania|शौक|اهتمامات|有什么爱好|喜歡做什麼)\b",
        s,
    ):
        return "hobbies"

    # Relationship goal
    if re.search(r"\b(looking for|relationship goal)\b", s) or re.search(
        r"(що шукаєш|які наміри|стосунки|серйозно\\?|що тобі потрібно тут|что ищешь|какие намерения|отношения)",
        s,
    ):
        return "goal"
    if re.search(
        r"\b(qué buscas|buscas algo serio|o que você procura|tu cherches quoi|cosa cerchi|was suchst du|"
        r"czego szukasz|क्या ढूँढ रहे|بتدور على إيه|找对象吗|找什麼)\b",
        s,
    ):
        return "goal"

    # Weekend / plans
    if re.search(r"\b(weekend|plans)\b", s) or re.search(
        r"(вихідн(і|их)|плани на|що робиш на вихідних|чим займешся|планы на выходные|что делаешь на выходных)",
        s,
    ):
        return "weekend"
    if re.search(
        r"\b(fin de semana|fim de semana|week-end|wochenende|weekendowe|सप्ताहांत|إيه خططك|周末|週末)\b", s
    ):
        return "weekend"

    # Travel
    if re.search(r"\b(travel|trip)\b", s) or re.search(r"(подорож(і|уєш)|любиш подорожувати|путешеств|куда ездил)", s):
        return "travel"
    if re.search(r"\b(viajes|viajar|voyages|reisen|podróże|यात्रा|سفر|旅行)\b", s):
        return "travel"

    # Taste buckets
    if re.search(r"\b(music|movie|food|fashion)\b", s) or re.search(
        r"(музик|фільм|кіно|їжа|кава|стиль|одяг|музыка|фильм|кино|еда|стиль|одежда)",
        s,
    ):
        return "music_movies_food_fashion"
    if re.search(r"(música|cinema|comida|moda|musique|musik|muzyka|संगीत|موسيقى|电影|電影)", s):
        return "music_movies_food_fashion"

    return None


def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _seed_i32(*parts: object) -> int:
    blob = "|".join(str(p) for p in parts if p is not None).encode("utf-8", errors="ignore")
    return int(zlib.adler32(blob) & 0xFFFFFFFF)


def _pick(seed: int, options: list[str]) -> str:
    if not options:
        return ""
    idx = int(seed % max(1, len(options)))
    return options[idx]


def _chance(seed: int, *, p: float) -> bool:
    x = (seed % 10_000) / 10_000.0
    return x < max(0.0, min(1.0, float(p)))


def _with_microflirt(lang: str, seed: int) -> str:
    if not _chance(seed, p=0.30):
        return ""
    loc = normalize_ai_request_locale(lang or "en")
    if loc == "uk":
        return _pick(seed + 17, [" 🙂", " …окей, вже інтригуєш 🙂", " ти звучиш цікаво 🙂"])
    if loc == "ru":
        return _pick(seed + 17, [" 🙂", " …окей, уже интригуешь 🙂", " ты звучишь интересно 🙂"])
    if loc == "es":
        return _pick(seed + 17, [" 🙂", " …vale, me intrigas 🙂", " me gusta cómo suenas 🙂"])
    if loc == "de":
        return _pick(seed + 17, [" 🙂", " …okay, spannend 🙂", " klingt gut 🙂"])
    if loc == "fr":
        return _pick(seed + 17, [" 🙂", " …ok, tu m’intrigues 🙂", " j’aime bien ton énergie 🙂"])
    if loc == "ar":
        return _pick(seed + 17, [" 🙂", " …تمام، بدأت أتفاعل 🙂", " حلو كلامك 🙂"])
    return _pick(seed + 17, [" 🙂", " okay… you're kinda intriguing 🙂", " you sound interesting 🙂"])


def _join_short(a: str, b: str) -> str:
    a0 = (a or "").strip()
    b0 = (b or "").strip()
    if not a0:
        return b0
    if not b0:
        return a0
    if a0.endswith((".", "!", "?", "…")):
        return f"{a0} {b0}"
    return f"{a0}. {b0}"


def _follow_up_for_city(lang: str, partner_city: str, seed: int) -> str:
    if _chance(seed + 101, p=0.28):
        if lang == "uk":
            return _pick(seed + 3, ["Люблю там атмосферу, особливо ввечері.", "Іноді хочеться втекти кудись тихіше.", "Там є свій ритм."])
        if lang == "ru":
            return _pick(seed + 3, ["Люблю там атмосферу, особенно вечером.", "Иногда хочется сбежать куда-то потише.", "Там свой ритм."])
        return _pick(seed + 3, ["I love the vibe there, especially in the evenings.", "Sometimes I want to escape somewhere quieter.", "It has its own rhythm."])
    if lang == "uk":
        if partner_city:
            return _pick(seed + 5, [f"А ти давно у {partner_city}?", f"Ти зараз у {partner_city}?", f"І як тобі {partner_city} останнім часом?"])
        return _pick(seed + 5, ["А ти звідки?", "А ти де живеш?", "Ти зараз у своєму місті?"])
    if lang == "ru":
        if partner_city:
            return _pick(seed + 5, [f"А ты давно в {partner_city}?", f"Ты сейчас в {partner_city}?", f"И как тебе {partner_city} в последнее время?"])
        return _pick(seed + 5, ["А ты откуда?", "А ты где живёшь?", "Ты сейчас в своём городе?"])
    return _pick(seed + 5, ["Where are you from?", "Where do you live?", "Are you in your city right now?"])


def render_direct_answer(
    *,
    speaker_profile: Profile | None = None,
    partner_profile: Profile | None = None,
    last_user_message: str,
    seed: int | None = None,
    demo_profile: Profile | None = None,
    ui_locale: str | None = None,
) -> str | None:
    """
    Answer partner direct questions using the *speaker* (current replier) profile.
    `demo_profile` is deprecated — use `speaker_profile`.
    """
    if demo_profile is not None and speaker_profile is None:
        speaker_profile = demo_profile
    intent = detect_direct_intent(last_user_message)
    if not intent or not speaker_profile:
        return None

    lang = resolve_output_locale(last_user_message, ui_locale or getattr(speaker_profile, "preferred_language", None))
    lang = normalize_ai_request_locale(lang)

    name = (getattr(speaker_profile, "display_name", "") or "").strip()
    city = (getattr(speaker_profile, "city_local", "") or getattr(speaker_profile, "city", "") or "").strip()
    partner_city = (getattr(partner_profile, "city_locative_uk", "") or getattr(partner_profile, "city", "") or "").strip()

    age = getattr(speaker_profile, "age", None)
    job = (getattr(speaker_profile, "job_title", "") or "").strip()
    interests = _split_csv(getattr(speaker_profile, "interests", "") or "")
    vibe = (getattr(speaker_profile, "vibe", "") or "").strip()
    goal = (getattr(speaker_profile, "relationship_goal", "") or "").strip()
    bio = (getattr(speaker_profile, "bio", "") or "").strip()
    sid = int(seed) if seed is not None else _seed_i32(getattr(speaker_profile, "user_id", None), name, last_user_message, intent, city, age, job)

    from app.services.ai.direct_answer_multilingual import city_answer, age_answer, hobby_answer, generic_bucket_answer

    if intent == "city":
        ml = city_answer(lang, city, partner_city)
        if ml:
            return ml.strip()
        if lang not in {"en", "uk", "ru"}:
            return generic_bucket_answer(lang, intent)
        if not city:
            city = "Kyiv" if lang == "en" else "Києва" if lang == "uk" else "Киева"
        if lang == "uk":
            base = _pick(sid, [f"Я з {city}", f"Я з {city} 🙂", f"З {city}"])
        elif lang == "ru":
            base = _pick(sid, [f"Я из {city}", f"Я из {city} 🙂", f"Из {city}"])
        else:
            base = _pick(sid, [f"I'm from {city}", f"I'm from {city} 🙂", f"From {city}"])
        vibe = _follow_up_for_city(lang, partner_city, sid)
        flirt = _with_microflirt(lang, sid)
        return _join_short(base + flirt, vibe).strip()

    if intent == "age":
        a = int(age) if age is not None else 25
        ml = age_answer(lang, a)
        if ml and lang not in {"en", "uk", "ru"}:
            return ml.strip()
        if lang == "uk":
            base = _pick(sid, [f"Мені {a}", f"Мені {a} 🙂", f"{a} років"])
            vibe_line = _pick(sid + 11, ["Не відчуваюся на свій паспорт, чесно.", "Іноді думаю, що я старша/молодша за відчуттями 🙂", "Це той вік, коли вже знаєш, що хочеш."])
            follow = _pick(sid + 13, ["А тобі?", "Тобі скільки?", "Для тебе вік має значення?"])
        elif lang == "ru":
            base = _pick(sid, [f"Мне {a}", f"Мне {a} 🙂", f"{a} лет"])
            vibe_line = _pick(sid + 11, ["Честно — не чувствую себя на паспорт.", "Иногда думаю, что по ощущениям я старше/младше 🙂", "Это возраст, когда уже понимаешь, чего хочешь."])
            follow = _pick(sid + 13, ["А тебе?", "Тебе сколько?", "Для тебя возраст важен?"])
        else:
            base = _pick(sid, [f"I'm {a}", f"I'm {a} 🙂", f"{a}"])
            vibe_line = _pick(sid + 11, ["Honestly, I don't feel like my passport age.", "Sometimes I feel older/younger depending on the day 🙂", "It’s that age where you know what you want."])
            follow = _pick(sid + 13, ["How about you?", "And you?", "Does age matter to you?"])
        second = vibe_line if _chance(sid + 77, p=0.34) else follow
        return _join_short(base + _with_microflirt(lang, sid), second).strip()

    if intent == "job":
        if lang not in {"en", "uk", "ru"}:
            return generic_bucket_answer(lang, intent)
        if not job:
            opener = (
                "Працюю в своїй сфері, нічого пафосного 🙂"
                if lang == "uk"
                else "Работаю в своей сфере, без пафоса 🙂"
                if lang == "ru"
                else "I work in my field 🙂"
            )
        else:
            opener = f"Я працюю {job}" if lang == "uk" else f"Я работаю {job}" if lang == "ru" else f"I work as {job}"
        vibe_line = (
            _pick(sid + 21, ["Люблю, коли день має ритм.", "Мені важливо, щоб робота не з'їдала життя 🙂", "Іноді там весело, іноді — просто робота."])
            if lang == "uk"
            else _pick(sid + 21, ["Люблю, когда у дня есть ритм.", "Мне важно, чтобы работа не съедала жизнь 🙂", "Иногда там весело, иногда — просто работа."])
            if lang == "ru"
            else _pick(sid + 21, ["I like when the day has a rhythm.", "I care that work doesn't eat life 🙂", "Sometimes it's fun, sometimes it's just work."])
        )
        follow = "А ти чим займаєшся?" if lang == "uk" else "А ты чем занимаешься?" if lang == "ru" else "What about you?"
        second = vibe_line if _chance(sid + 79, p=0.32) else follow
        return _join_short(opener + _with_microflirt(lang, sid), second).strip()

    if intent == "hobbies":
        h = hobby_answer(lang, getattr(speaker_profile, "interests", "") or "")
        if h and lang not in {"en", "uk", "ru"}:
            return h.strip()
        if interests:
            top = ", ".join(interests[:3])
            opener = f"Люблю {top}" if lang in {"uk", "ru"} else f"I'm into {top}"
        elif vibe:
            opener = f"Я більше про вайб “{vibe}” 🙂" if lang == "uk" else f"Я скорее про вайб “{vibe}” 🙂" if lang == "ru" else f"My vibe is “{vibe}” 🙂"
        elif bio:
            opener = (bio[:140]).strip()
        else:
            opener = "Я люблю прості штуки: прогулянки, каву і хороший вайб 🙂" if lang == "uk" else "Люблю простые вещи: прогулки, кофе и хороший вайб 🙂" if lang == "ru" else "I like simple things: walks, coffee, and good vibes 🙂"
        vibe_line = (
            _pick(sid + 33, ["Звучить просто, але це реально тримає мене в тонусі 🙂", "Я від цього реально кайфую.", "Мені подобається, коли в цьому є смак, а не “для галочки”."])
            if lang == "uk"
            else _pick(sid + 33, ["Звучит просто, но это реально держит меня в тонусе 🙂", "Я от этого правда кайфую.", "Мне нравится, когда в этом есть вкус, а не “для галочки”."])
            if lang == "ru"
            else _pick(sid + 33, ["Sounds simple, but it keeps me grounded 🙂", "I genuinely enjoy it.", "I like when it has taste, not just “for show”."])
        )
        follow = "А ти що любиш?" if lang == "uk" else "А ты что любишь?" if lang == "ru" else "What do you like?"
        second = vibe_line if _chance(sid + 91, p=0.35) else follow
        return _join_short(opener + _with_microflirt(lang, sid), second).strip()

    if intent == "goal":
        if lang not in {"en", "uk", "ru"}:
            return generic_bucket_answer(lang, intent)
        if not goal:
            goal = "relationship"
        if lang == "uk":
            opener = "Я тут за нормальними стосунками, без ігор" if goal == "relationship" else f"Я тут більше про {goal}"
            vibe_line = _pick(sid + 41, ["Мені важлива ясність, а не “як піде”.", "Хочеться легко, але по-справжньому.", "Я не люблю витрачати час дарма 🙂"])
            follow = _pick(sid + 43, ["А ти що шукаєш?", "Ти за легкість чи за серйозно?", "Тобі важливіше хімія чи стабільність?"])
        elif lang == "ru":
            opener = "Я здесь за нормальные отношения, без игр" if goal == "relationship" else f"Я здесь скорее про {goal}"
            vibe_line = _pick(sid + 41, ["Мне важна ясность, а не “как пойдёт”.", "Хочется легко, но по‑настоящему.", "Я не люблю тратить время зря 🙂"])
            follow = _pick(sid + 43, ["А ты что ищешь?", "Ты за лёгкость или за серьёзно?", "Тебе важнее химия или стабильность?"])
        else:
            opener = "I'm looking for something real (no games)" if goal == "relationship" else f"I'm looking for {goal}"
            vibe_line = _pick(sid + 41, ["I like clarity, not “we'll see”.", "I want it light, but real.", "I don't like wasting time 🙂"])
            follow = _pick(sid + 43, ["What about you?", "Do you prefer light or serious?", "More chemistry or stability for you?"])
        second = vibe_line if _chance(sid + 103, p=0.33) else follow
        return _join_short(opener + _with_microflirt(lang, sid), second).strip()

    if lang not in {"en", "uk", "ru"}:
        return generic_bucket_answer(lang, intent)

    if lang == "uk":
        opener = "Скоріше так" if intent in {"weekend", "travel", "music_movies_food_fashion"} else "Цікаво"
        vibe_line = _pick(sid + 51, ["Люблю, коли це не втомлює.", "Мені заходить, коли є настрій.", "Я від цього точно стаю м'якша 🙂"])
        follow = _pick(sid + 53, ["А ти?", "А в тебе як?", "Ти більше за спонтанність чи план?"])
    elif lang == "ru":
        opener = "Скорее да" if intent in {"weekend", "travel", "music_movies_food_fashion"} else "Интересно"
        vibe_line = _pick(sid + 51, ["Люблю, когда это не утомляет.", "Мне нравится, когда есть настроение.", "От этого я точно становлюсь мягче 🙂"])
        follow = _pick(sid + 53, ["А ты?", "А у тебя как?", "Ты больше за спонтанность или план?"])
    else:
        opener = "Honestly, yes" if intent in {"weekend", "travel", "music_movies_food_fashion"} else "Interesting"
        vibe_line = _pick(sid + 51, ["I like it when it doesn’t drain me.", "It hits different when the mood is right.", "It definitely softens me a bit 🙂"])
        follow = _pick(sid + 53, ["And you?", "How about you?", "More spontaneous or planned?"])
    second = vibe_line if _chance(sid + 121, p=0.38) else follow
    return _join_short(opener + _with_microflirt(lang, sid), second).strip()
