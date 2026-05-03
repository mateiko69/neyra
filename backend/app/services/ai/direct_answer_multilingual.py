"""Localized direct-answer snippets for dating chat (MVP locales)."""

from __future__ import annotations

from app.services.ai.ai_fallback_phrases import resolve_fallback_locale_key, timed_now_emergency_triple


def _loc(lang: str) -> str:
    return resolve_fallback_locale_key(lang or "en")


def city_answer(lang: str, city: str, partner_city: str) -> str:
    c = city or ""
    pc = (partner_city or "").strip()
    L = _loc(lang)
    if L == "es":
        base = f"Soy de {c} 🙂" if c else "Soy de aquí cerca 🙂"
        follow = f"¿Llevas mucho en {pc}?" if pc else "¿Y tú de dónde eres?"
        return f"{base} {follow}"
    if L == "de":
        base = f"Ich komme aus {c} 🙂" if c else "Ich wohne hier in der Gegend 🙂"
        follow = f"Bist du schon lange in {pc}?" if pc else "Und du — woher kommst du?"
        return f"{base} {follow}"
    if L == "fr":
        base = f"Je viens de {c} 🙂" if c else "Je suis d’ici 🙂"
        follow = f"Tu es à {pc} depuis longtemps ?" if pc else "Et toi, tu viens d’où ?"
        return f"{base} {follow}"
    if L == "it":
        base = f"Vengo da {c} 🙂" if c else "Sono di qui 🙂"
        follow = f"Sei da {pc} da molto?" if pc else "E tu di dove sei?"
        return f"{base} {follow}"
    if L == "pl":
        base = f"Jestem z {c} 🙂" if c else "Jestem stąd 🙂"
        follow = f"Dawno jesteś w {pc}?" if pc else "A ty skąd jesteś?"
        return f"{base} {follow}"
    if L == "pt":
        base = f"Sou de {c} 🙂" if c else "Sou daqui 🙂"
        follow = f"Você está em {pc} há muito tempo?" if pc else "E você, de onde é?"
        return f"{base} {follow}"
    if L == "hi":
        base = f"मैं {c} से हूँ 🙂" if c else "मैं यहीं आसपास से हूँ 🙂"
        follow = f"तुम {pc} में कब से हो?" if pc else "और तुम कहाँ से हो?"
        return f"{base} {follow}"
    if L == "ar":
        base = f"أنا من {c} 🙂" if c else "أنا من هنا 🙂"
        follow = f"إنت من زمان في {pc}؟" if pc else "وإنت منين؟"
        return f"{base} {follow}"
    if L == "zh-TW":
        base = f"我來自{c}～" if c else "我住這附近～"
        follow = f"你在{pc}很久了嗎？" if pc else "你呢，住哪？"
        return f"{base}{follow}"
    if L == "zh":
        base = f"我来自{c}～" if c else "我住这附近～"
        follow = f"你在{pc}很久了吗？" if pc else "你呢，住哪？"
        return f"{base}{follow}"
    return ""


def age_answer(lang: str, age: int) -> str:
    a = int(age)
    L = _loc(lang)
    if L == "es":
        return f"Tengo {a} 🙂 ¿Y tú? ¿La edad te importa mucho?"
    if L == "de":
        return f"Ich bin {a} 🙂 Und du? Ist dir das Alter wichtig?"
    if L == "fr":
        return f"J’ai {a} 🙂 Et toi ? L’âge compte beaucoup pour toi ?"
    if L == "it":
        return f"Ho {a} anni 🙂 E tu? L’età conta molto per te?"
    if L == "pl":
        return f"Mam {a} lat 🙂 A ty? Wiek jest dla Ciebie ważny?"
    if L == "pt":
        return f"Tenho {a} 🙂 E você? Idade importa pra você?"
    if L == "hi":
        return f"मेरी उम्र {a} है 🙂 और तुम्हारी? उम्र तुम्हारे लिए मायने रखती है?"
    if L == "ar":
        return f"عندي {a} سنة 🙂 وإنت؟ العمر مهم عندك؟"
    if L == "zh-TW":
        return f"我{a}歲～你呢？年齡對你重要嗎？"
    if L == "zh":
        return f"我{a}岁～你呢？年龄对你重要吗？"
    return ""


def hobby_answer(lang: str, interests_csv: str) -> str:
    L = _loc(lang)
    top = ", ".join([x.strip() for x in (interests_csv or "").split(",") if x.strip()][:3])
    if L == "es":
        if top:
            return f"Me gusta {top} 🙂 ¿Y tú qué te gusta hacer?"
        return "Me gusta salir y tomar algo tranquilo 🙂 ¿Y tú?"
    if L == "de":
        if top:
            return f"Ich mag {top} 🙂 Was machst du gern?"
        return "Ich mag Spaziergänge und guten Kaffee 🙂 Und du?"
    if L == "fr":
        if top:
            return f"J’aime {top} 🙂 Et toi, tu aimes quoi?"
        return "J’aime sortir prendre un verre 🙂 Et toi ?"
    if L == "it":
        if top:
            return f"Mi piace {top} 🙂 E tu cosa ti piace fare?"
        return "Mi piace uscire e prendere qualcosa 🙂 E tu?"
    if L == "pl":
        if top:
            return f"Lubię {top} 🙂 A ty co lubisz?"
        return "Lubię spacery i dobrą kawę 🙂 A ty?"
    if L == "pt":
        if top:
            return f"Curto {top} 🙂 E você, o que gosta de fazer?"
        return "Curto sair pra tomar algo 🙂 E você?"
    if L == "hi":
        if top:
            return f"मुझे {top} पसंद है 🙂 और तुम्हें क्या पसंद है?"
        return "मुझे घूमना और कॉफ़ी पसंद है 🙂 और तुम्हें?"
    if L == "ar":
        if top:
            return f"بحب {top} 🙂 وإنت إيه اللي بتحبه؟"
        return "بحب أطلع وأشرب حاجة هادية 🙂 وإنت؟"
    if L == "zh-TW":
        if top:
            return f"我喜歡{top}～你呢？"
        return "我喜歡散步、喝咖啡～你呢？"
    if L == "zh":
        if top:
            return f"我喜欢{top}～你呢？"
        return "我喜欢散步、喝咖啡～你呢？"
    return ""


def generic_bucket_answer(lang: str, intent: str) -> str:
    """Weekend / travel / music_movies_food_fashion / goal — safe localized line + timed line."""
    L = _loc(lang)
    a, _, _ = timed_now_emergency_triple(L)
    if L == "es":
        opener = "Sí, me gusta eso 🙂" if intent != "goal" else "Busco algo real, sin juegos 🙂"
    elif L == "de":
        opener = "Ja, mag ich 🙂" if intent != "goal" else "Ich suche was Echtes — ohne Spielchen 🙂"
    elif L == "fr":
        opener = "Oui, j’aime bien 🙂" if intent != "goal" else "Je cherche quelque chose de vrai 🙂"
    elif L == "it":
        opener = "Sì, mi piace 🙂" if intent != "goal" else "Cerco qualcosa di vero 🙂"
    elif L == "pl":
        opener = "Tak, lubię 🙂" if intent != "goal" else "Szukam czegoś realnego 🙂"
    elif L == "pt":
        opener = "Sim, curto 🙂" if intent != "goal" else "Busco algo real 🙂"
    elif L == "hi":
        opener = "हाँ, मुझे पसंद है 🙂" if intent != "goal" else "मैं कुछ असली चाहती/चाहता हूँ 🙂"
    elif L == "ar":
        opener = "أيوه بحب كده 🙂" if intent != "goal" else "بدور على حاجة جدية 🙂"
    elif L in ("zh", "zh-TW"):
        opener = "嗯，我也喜歡～" if L == "zh-TW" else "嗯，我也喜欢～"
        if intent == "goal":
            opener = "我想認真一點～" if L == "zh-TW" else "我想认真一点～"
    else:
        opener = "Yeah, I’m into that 🙂" if intent != "goal" else "I’m looking for something real 🙂"
    return f"{opener} {a}".strip()
