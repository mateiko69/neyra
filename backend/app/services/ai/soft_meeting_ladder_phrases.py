"""
Soft meeting-hint triples for every UI locale.

Used when closer_stage suggests an optional offline continuation (coffee / walk framing).
Keeps wording low-pressure across locales — never mixes English unless locale is en.
"""

from __future__ import annotations

import logging

from app.services.ai.ai_fallback_phrases import resolve_fallback_locale_key

logger = logging.getLogger("neyra.ai.soft_meeting")

_SOFT_MEETING: dict[str, tuple[str, str, str]] = {
    "en": (
        "This already feels like a conversation that’s easier to continue away from the keyboard 😄",
        "Maybe coffee or a walk sometime?",
        "No pressure 🙂",
    ),
    "uk": (
        "це вже звучить як розмова, яку краще продовжити не в чаті 😄",
        "може якось кава чи прогулянка?",
        "без напрягу 🙂",
    ),
    "ru": (
        "это уже звучит как разговор, который логичнее продолжить не в чате 😄",
        "может как-нибудь кофе или прогулка?",
        "без давления 🙂",
    ),
    "es": (
        "Esto ya suena como una charla más fácil de seguir lejos del teclado 😄",
        "¿Un café o un paseo algún día?",
        "Sin presión 🙂",
    ),
    "pt": (
        "Isso já parece uma conversa que flui melhor longe do teclado 😄",
        "Que tal um café ou um passeio qualquer dia?",
        "Sem pressão 🙂",
    ),
    "fr": (
        "On dirait déjà une discussion plus simple à poursuivre loin du clavier 😄",
        "Un café ou une balade un de ces quatre ?",
        "Sans pression 🙂",
    ),
    "de": (
        "Das fühlt sich schon wie ein Gespräch an, das leichter jenseits des Chats weitergeht 😄",
        "Vielleicht mal Kaffee oder ein Spaziergang?",
        "Kein Stress 🙂",
    ),
    "it": (
        "Sembra già una chiacchierata che è più naturale continuare fuori dalla chat 😄",
        "Che ne dici di un caffè o una passeggiata un giorno?",
        "Zero pressioni 🙂",
    ),
    "pl": (
        "To już brzmi jak rozmowa, którą łatwiej kontynuować poza czatem 😄",
        "Może kiedyś kawa albo spacer?",
        "Bez presji 🙂",
    ),
    "tr": (
        "Bu sanki yazı yazmadan daha kolay sürecek bir sohbete döndü 😄",
        "Belki bir gün kahve ya da kısa bir yürüyüş?",
        "Baskı yok 🙂",
    ),
    "zh": (
        "感觉这已经像是一段更适合在线下继续聊的对话了 😄",
        "哪天方便的话，喝杯咖啡或散个步？",
        "慢慢来，没压力 🙂",
    ),
    "zh-TW": (
        "感覺這已經像是一段更適合在線下繼續聊的對話了 😄",
        "哪天方便的話，喝杯咖啡或散個步？",
        "慢慢來，沒壓力 🙂",
    ),
    "ja": (
        "これ、チャットよりオフラインで続けたほうが自然な流れになりそうだね 😄",
        "気が向いたらコーヒーか散歩とかどう？",
        "強くないからね 🙂",
    ),
    "ko": (
        "벌써 채팅창보다 현실에서 이어지기 더 자연스러운 대화 같아 😄",
        "시간 되면 커피나 산책 어때?",
        "부담 없이 🙂",
    ),
    "hi": (
        "ऐसा लग रहा है जैसे ये बातचीत चैट से बाहर जारी रखना आसान होगी 😄",
        "कभी चाय/कॉफ़ी या टहल?",
        "बिना दबाव के 🙂",
    ),
    "id": (
        "Ini rasanya seperti obrolan yang lebih enak lanjut di luar chat 😄",
        "Mungkin kopinya atau jalan santai lain kali?",
        "Tanpa tekanan 🙂",
    ),
    "vi": (
        "Giờ đoạn chat này nghe cứ như nên tiếp tục ngoài đời cho tự nhiên 😄",
        "Một ngày nào đó cafe hoặc đi bộ nhé?",
        "Không ép 🙂",
    ),
    "th": (
        "ตอนนี้เหมือนเป็นการคุยที่ต่อในโลกจริงจะลื่นกว่าหน้าจอนะ 😄",
        "วันไหนสะดวกไปคาเฟ่หรือเดินเล่นสั้นๆไหม?",
        "ไม่กด 🙂",
    ),
    "ar": (
        "دلوقتي الموضو بيحس إنه أحلى يكمّل برّا الشات 😄",
        "نقهوى أو نقعد نتمشّى وقت ما يسهل?",
        "من غير أي ضغط 🙂",
    ),
    "he": (
        "כבר נשמע כמו שיחה שNatural יותר להמשיך אותה מעבר למסך 😄",
        "אולי מתישהו קפה או טיול קצר?",
        "בלי לחץ 🙂",
    ),
    "nl": (
        "Voelt al als een gesprek dat makkelijker verder kan buiten het scherm 😄",
        "Zin in koffie of een wandeling ooit?",
        "Geen druk 🙂",
    ),
    "sv": (
        "Det känns redan som en konversation som liksom passar bättre bortom chatten 😄",
        "Fika eller en promenad någon gång?",
        "Ingen press 🙂",
    ),
    "cs": (
        "Už to zní jako řeč, kterou je přirozenější pokračovat mimo chat 😄",
        "Co takhle někdy káva nebo procházka?",
        "Bez tlaku 🙂",
    ),
    "ro": (
        "Deja sună ca o conversație pe care mai ușor o continui și înafară de chat 😄",
        "Poate o cafea sau o plimbare când ai chef?",
        "Fără presiune 🙂",
    ),
    "hu": (
        "Már olyan, mintha ez a beszélgetés könnyebben folytatódna chaten kívül 😄",
        "Majd legyen kávé vagy egy séta?",
        "Nincs nyomás 🙂",
    ),
    "el": (
        "Πια μοιάζει με συζήτηση που θα ήταν φυσικότερη να συνεχίσει εκτός chat 😄",
        "Καφές ή ήρεμος περίπατος ένα πρωί;",
        "Χωρίς πίεση 🙂",
    ),
    "da": (
        "Det føles allerede som en samtale, der er nemmere at føre væk fra tastaturet 😄",
        "Måske kaffe eller en gåtur en dag?",
        "Ingen stress 🙂",
    ),
    "fi": (
        "Tuntuu jo siltä että tämän jatkaminen kahvipöydässä olisi luontevinta 😄",
        "kahvi tai kävelylenkki joku päivä?",
        "ei painetta 🙂",
    ),
    "no": (
        "Dette kjennes allerede ut som noe lettere å fortelle videre uten keyboard 😄",
        "Kanskje en kaffe eller en tur neste gang?",
        "Null press 🙂",
    ),
    "bg": (
        "Вече звучи като разговор, който е по-естествено да продължи извън чата 😄",
        "Може ли някой ден кафе или кратка разходка?",
        "Без натиск 🙂",
    ),
}


def soft_meeting_ladder_triple(locale: str | None) -> tuple[str, str, str]:
    key = resolve_fallback_locale_key(locale or "en")
    row = _SOFT_MEETING.get(key)
    if row is None and key.startswith("zh") and key != "zh-TW":
        row = _SOFT_MEETING.get("zh")
    if row:
        return row
    fallback_chain = ("de", "fr", "es", "pt", "it", "pl", "ru", "uk", "en")
    for fb in fallback_chain:
        alt = _SOFT_MEETING.get(fb)
        if alt:
            if fb == "en" and key != "en":
                logger.warning(
                    "soft_meeting_ladder_fallback_non_en_used_en_rows",
                    extra={"requested": key},
                )
            return alt
    return _SOFT_MEETING["en"]
