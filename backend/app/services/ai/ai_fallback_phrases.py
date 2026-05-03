"""
Localized deterministic fallbacks for AI surfaces (no English leakage for non-English UI).

All keys MUST match normalize_ai_request_locale() outputs (e.g. zh-TW).
"""

from __future__ import annotations

from typing import Literal

from app.services.ai.ai_request_locale import normalize_ai_request_locale

TimedNudge = Literal["reengage", "revive", "now_emergency"]

# (light, flirty, deep) — same lane meanings as /ai/timed-replies
_TIMED_REENGAGE: dict[str, tuple[str, str, str]] = {
    "en": (
        "Hey 🙂 How’s your day going — anything good so far?",
        "Random thought — you popped into my head 🙂 What was the nicest part of your day?",
        "What matters most to you right now — work, people, or something you’re building?",
    ),
    "uk": (
        "Привіт 🙂 Як твій день — є щось приємне поки що?",
        "Рандомна думка — ти згадував(ла)ся мені 🙂 Яка була найприємніша частина дня?",
        "Що зараз для тебе важливіше — робота, люди чи щось, що ти будуєш?",
    ),
    "ru": (
        "Привет 🙂 Как день — есть что-то хорошее уже?",
        "Рандомная мысль — ты всплывал(а) в голове 🙂 Какая часть дня была самой приятной?",
        "Что для тебя сейчас важнее всего — работа, люди или то, что ты строишь?",
    ),
    "es": (
        "Hola 🙂 ¿Cómo va tu día — algo bueno hasta ahora?",
        "Pensamiento random — me acordé de ti 🙂 ¿Qué fue lo más lindo de tu día?",
        "¿Qué es lo que más te importa ahora — trabajo, personas o algo que estás construyendo?",
    ),
    "pt": (
        "Oi 🙂 Como tá seu dia — alguma coisa boa até agora?",
        "Pensamento aleatório — você veio na minha cabeça 🙂 Qual foi a parte mais legal do seu dia?",
        "O que mais importa pra você agora — trabalho, pessoas ou algo que você tá construindo?",
    ),
    "fr": (
        "Salut 🙂 Ta journée se passe comment — quelque chose de bien pour l’instant?",
        "Pensée random — t’as traversé mon esprit 🙂 C’était quoi le plus beau moment de ta journée?",
        "Qu’est-ce qui compte le plus pour toi là — le boulot, les gens ou un truc que tu construis?",
    ),
    "de": (
        "Hey 🙂 Wie läuft dein Tag — gibt’s schon was Gutes?",
        "Random-Gedanke — du bist mir durch den Kopf gegangen 🙂 Was war der schönste Teil deines Tages?",
        "Was ist dir gerade am wichtigsten — Arbeit, Menschen oder etwas, das du aufbaust?",
    ),
    "it": (
        "Ehi 🙂 Com’è la tua giornata — c’è qualcosa di bello finora?",
        "Pensiero a caso — mi sei venuto/a in mente 🙂 Qual è stata la parte più bella della giornata?",
        "Cosa conta di più per te adesso — lavoro, persone o qualcosa che stai costruendo?",
    ),
    "pl": (
        "Hej 🙂 Jak leci dzień — jest coś fajnego na razie?",
        "Losowa myśl — przypomniałem/am sobie o Tobie 🙂 Co było najmilszą częścią dnia?",
        "Co jest dla Ciebie teraz najważniejsze — praca, ludzie czy coś, co budujesz?",
    ),
    "tr": (
        "Selam 🙂 Günün nasıl gidiyor — şimdilik güzel bir şey oldu mu?",
        "Random bir düşünce — aklıma düştün 🙂 Gününün en güzel kısmı neydi?",
        "Şu an senin için en önemlisi ne — iş, insanlar yoksa kurduğun bir şey mi?",
    ),
    "zh": (
        "嘿～今天过得怎么样，有什么开心的小事吗？",
        "突然想到你～今天最棒的一刻是什么？",
        "现在对你来说什么最重要——工作、身边的人，还是你在努力做的事？",
    ),
    "zh-TW": (
        "嗨～今天好嗎，有沒有什麼小確幸？",
        "突然想到你～今天最棒的一刻是什麼？",
        "現在對你來說什麼最重要——工作、身邊的人，還是你在努力做的事？",
    ),
    "ja": (
        "やっほー🙂 今日どう？いいことあった？",
        "ふと思い出した——今日いちばん嬉しかったのは何？",
        "今いちばん大事なのは仕事、人、それとも作ってること？",
    ),
    "ko": (
        "안녕 🙂 오늘 하루 어때 — 지금까지 좋은 일 있었어?",
        "문득 생각났어 — 오늘 가장 좋았던 순간이 뭐야?",
        "지금 너한테 가장 중요한 건 뭐야 — 일, 사람들, 아니면 만들어가는 무언가?",
    ),
    "hi": (
        "हैलो 🙂 आज का दिन कैसा चल रहा है — अब तक कुछ अच्छा हुआ?",
        "अचानक याद आया — आज का सबसे प्यारा पल क्या रहा?",
        "अभी तुम्हारे लिए सबसे ज़्यादा क्या मायने रखता है — काम, लोग, या कुछ बनाना?",
    ),
    "id": (
        "Hai 🙂 Hari kamu gimana — ada yang menyenangkan sejauh ini?",
        "Random kepikiran kamu 🙂 Bagian paling enak dari harimu apa?",
        "Yang paling penting buat kamu sekarang — kerja, orang, atau sesuatu yang kamu bangun?",
    ),
    "vi": (
        "Chào 🙂 Hôm nay của bạn thế nào — có điều gì vui chưa?",
        "Chợt nhớ bạn 🙂 Phần đẹp nhất trong ngày của bạn là gì?",
        "Điều quan trọng nhất với bạn lúc này là gì — công việc, con người, hay điều bạn đang xây dựng?",
    ),
    "th": (
        "เฮย์ 🙂 วันนี้เป็นยังไงบ้าง — มีเรื่องดีๆ มั้ย?",
        "นึกขึ้นมาแบบสุ่มๆ — วันนี้ช่วงที่ชอบที่สุดคืออะไร?",
        "ตอนนี้สำหรับคุณอะไรสำคัญที่สุด — งาน คน หรือสิ่งที่กำลังสร้าง?",
    ),
    "ar": (
        "أهلاً 🙂 كيف يومك — في شيء حلو لحد دلوقتي؟",
        "فكرة فجأة — خطرت لي 🙂 إيه أحلى جزء في يومك؟",
        "إيه الأهم ليك دلوقتي — الشغل، الناس، ولا حاجة بتبنيها؟",
    ),
    "he": (
        "היי 🙂 איך היום שלך — יש משהו טוב עד עכשיו?",
        "מחשבה רנדומלית — עלית לי בראש 🙂 מה היה הרגע הכי נעים ביום שלך?",
        "מה הכי חשוב לך עכשיו — עבודה, אנשים, או משהו שאת/ה בונה?",
    ),
    "nl": (
        "Hoi 🙂 Hoe is je dag — al iets leuks gehad?",
        "Random gedachte — je schoot door m’n hoofd 🙂 Wat was het fijnste deel van je dag?",
        "Wat telt voor jou nu het meest — werk, mensen, of iets dat je opbouwt?",
    ),
    "sv": (
        "Hej 🙂 Hur är din dag — något bra hittills?",
        "Random tanke — du dök upp i huvudet 🙂 Vad var den mysigaste delen av din dag?",
        "Vad är viktigast för dig just nu — jobb, människor eller något du bygger?",
    ),
    "cs": (
        "Ahoj 🙂 Jak se máš dnes — něco příjemného zatím?",
        "Náhodná myšlenka — vybavil/a jsem si tě 🙂 Co byl nejpříjemnější moment dne?",
        "Co je pro tebe teď nejdůležitější — práce, lidi, nebo něco, co buduješ?",
    ),
    "ro": (
        "Hei 🙂 Cum îți merge ziua — ceva fain până acum?",
        "Gând random — mi-ai trecut prin minte 🙂 Care a fost partea cea mai frumoasă a zilei?",
        "Ce contează cel mai mult pentru tine acum — munca, oamenii sau ceva ce construiești?",
    ),
    "hu": (
        "Szia 🙂 Milyen a napod — volt már valami jó?",
        "Random gondolat — eszedbe jutottál 🙂 Mi volt a napod legjobb része?",
        "Mi a legfontosabb neked most — munka, emberek, vagy valami, amit építesz?",
    ),
    "el": (
        "Γεια 🙂 Πώς πάει η μέρα σου — κάτι καλό μέχρι τώρα;",
        "Τυχαία σκέψη — μου ήρθες στο μυαλό 🙂 Ποιο ήταν το πιο όμορφο κομμάτι της μέρας σου;",
        "Τι μετράει πιο πολύ για σένα τώρα — δουλειά, άνθρωποι ή κάτι που χτίζεις;",
    ),
    "da": (
        "Hej 🙂 Hvordan er din dag — noget godt indtil videre?",
        "Random tanke — du poppede op i hovedet 🙂 Hvad var den bedste del af din dag?",
        "Hvad betyder mest for dig lige nu — arbejde, mennesker eller noget du bygger?",
    ),
    "fi": (
        "Hei 🙂 Miten päiväsi menee — jotain hyvää tähän mennessä?",
        "Random ajatus — muistin sinut 🙂 Mikä oli päiväsi paras hetki?",
        "Mikä on sinulle tärkeintä nyt — työ, ihmiset vai joku mitä rakennat?",
    ),
    "no": (
        "Hei 🙂 Hvordan er dagen din — noe bra så langt?",
        "Tilfeldig tanke — du dukket opp i hodet 🙂 Hva var den fineste delen av dagen din?",
        "Hva betyr mest for deg nå — jobb, mennesker eller noe du bygger?",
    ),
    "bg": (
        "Здрасти 🙂 Как мина денят ти — има ли нещо хубаво досега?",
        "Случайна мисъл — изникна ми 😄 Коя част от деня ти беше най-приятна?",
        "Кое е най-важно за теб в момента — работа, хора или нещо, което строиш?",
    ),
}

_TIMED_REVIVE: dict[str, tuple[str, str, str]] = {
    "en": (
        "Okay, new angle 🙂 What’s been genuinely exciting for you lately?",
        "I feel like there’s more to that story 😄 What’s the real version?",
        "After a long day, do you recharge with people, movement, or quiet time?",
    ),
    "uk": (
        "Окей, новий кут 🙂 Що тебе справді хвилює останнім часом?",
        "Здається, в тій історії є продовження 😄 Яка «реальна» версія?",
        "Після довгого дня ти набираєшся енергії від людей, руху чи тиші?",
    ),
    "ru": (
        "Окей, новый угол 🙂 Что тебя реально цепляет в последнее время?",
        "Кажется, в этой истории есть продолжение 😄 Какая «настоящая» версия?",
        "После долгого дня ты заряжаешься от людей, движения или тишины?",
    ),
    "es": (
        "Vale, nuevo ángulo 🙂 ¿Qué te está emocionando de verdad últimamente?",
        "Siento que hay más en esa historia 😄 ¿Cuál es la versión real?",
        "Después de un día largo, ¿recargas con gente, movimiento o calma?",
    ),
    "pt": (
        "Beleza, novo ângulo 🙂 O que tem te animado de verdade ultimamente?",
        "Sinto que tem mais nessa história 😄 Qual é a versão real?",
        "Depois de um dia longo, você recarrega com gente, movimento ou um tempo quieto?",
    ),
    "fr": (
        "Ok, nouvel angle 🙂 Qu’est-ce qui t’excite vraiment en ce moment?",
        "J’ai l’impression qu’il y a une suite à cette histoire 😄 La vraie version, c’est quoi?",
        "Après une longue journée, tu recharges avec des gens, le mouvement, ou le calme?",
    ),
    "de": (
        "Okay, neuer Blickwinkel 🙂 Was hat dich in letzter Zeit wirklich geflasht?",
        "Ich hab das Gefühl, da gibt’s mehr zu der Story 😄 Was ist die echte Version?",
        "Nach einem langen Tag tankst du lieber bei Menschen, Bewegung oder Ruhe?",
    ),
    "it": (
        "Ok, nuova angolazione 🙂 Cosa ti sta davvero entusiasmando ultimamente?",
        "Sento che c’è altro in quella storia 😄 Qual è la versione vera?",
        "Dopo una giornata lunga ti ricarichi con persone, movimento o calma?",
    ),
    "pl": (
        "Ok, nowy kąt 🙂 Co naprawdę Cię ostatnio kręci?",
        "Mam wrażenie, że jest ciąg dalszy tej historii 😄 Jaka jest „prawdziwa” wersja?",
        "Po długim dniu ładujesz baterie przy ludziach, ruchu czy spokoju?",
    ),
    "tr": (
        "Tamam, yeni açı 🙂 Son zamanlarda seni gerçekten heyecanlandıran ne?",
        "O hikâyede devamı var gibi 😄 Gerçek versiyonu ne?",
        "Uzun bir günün ardından insanlarla, hareketle mi yoksa sessizlikle mi yenilenirsin?",
    ),
    "zh": (
        "换个角度聊聊～最近有什么让你真心期待的事？",
        "感觉这故事还有下文😄真实版本是什么？",
        "累了一天之后，你更喜欢用聊天、运动还是安静来充电？",
    ),
    "zh-TW": (
        "換個角度聊聊～最近有什麼讓你真心期待的事？",
        "感覺這故事還有下文😄真實版本是什麼？",
        "累了一天之後，你更喜歡用人際、活動還是安靜來充電？",
    ),
    "ja": (
        "じゃあ視点チェンジ 🙂 最近ワクワクしてることある？",
        "なんか続きがありそうな話😄本当のバージョン教えて？",
        "長い一日のあと、人と過ごす・動く・静かに、どれで回復するタイプ？",
    ),
    "ko": (
        "좋아, 새 각도로 🙂 요즘 진짜 설레는 일이 뭐야?",
        "그 이야기에 더 있을 것 같아 😄 리얼 버전이 뭐야?",
        "긴 하루 뒤엔 사람들이랑, 움직임, 아니면 조용한 시간으로 충전해?",
    ),
    "hi": (
        "ठीक है, नया एंगल 🙂 हाल में तुम्हें सच में क्या एक्साइट कर रहा है?",
        "लगता है उस कहानी में और भी है 😄 असली वर्ज़न क्या है?",
        "लंबे दिन के बाद तुम लोगों से, हरकत से, या शांति से रिचार्ज करते हो?",
    ),
    "id": (
        "Oke, sudut baru 🙂 Apa yang bikin kamu excited akhir-akhir ini?",
        "Kayaknya ceritanya masih ada lanjutannya 😄 Versi aslinya apa?",
        "Setelah hari panjang, kamu recharge dengan orang, gerak, atau waktu tenang?",
    ),
    "vi": (
        "Ok, góc mới 🙂 Dạo này điều gì khiến bạn thật sự hào hứng?",
        "Mình cảm giác câu chuyện đó còn tiếp 😄 Bản thật là gì?",
        "Sau một ngày dài, bạn nạp lại năng lượng bằng người, vận động hay yên tĩnh?",
    ),
    "th": (
        "โอเค มุมใหม่ 🙂 ช่วงนี้อะไรที่ทำให้คุณตื่นเต้นจริงๆ?",
        "รู้สึกว่าเรื่องนั้นยังมีต่อ 😄 เวอร์ชันจริงคืออะไร?",
        "หลังวันยาวๆ คุณชาร์จพลังด้วยคน การขยับ หรือความเงียบ?",
    ),
    "ar": (
        "تمام، زاوية جديدة 🙂 إيه اللي مفتحك فعلاً الفترة دي?",
        "حاسس إن في تكملة للقصة دي 😄 النسخة الحقيقية إيه?",
        "بعد يوم طويل بتتشحن بأناس، حركة، ولا هدوء؟",
    ),
    "he": (
        "אוקיי, זווית חדשה 🙂 מה באמת מרגש אותך לאחרונה?",
        "יש לי תחושה שיש עוד לסיפור הזה 😄 מה הגרסה האמיתית?",
        "אחרי יום ארוך את/ה נטען/ת עם אנשים, תנועה או שקט?",
    ),
    "nl": (
        "Oké, nieuwe hoek 🙂 Wat maakt je de laatste tijd echt enthousiast?",
        "Ik heb het gevoel dat er meer aan dat verhaal zit 😄 Wat is de echte versie?",
        "Na een lange dag laad je op met mensen, beweging of stilte?",
    ),
    "sv": (
        "Okej, ny vinkel 🙂 Vad har känts spännande för dig på riktigt på sistone?",
        "Känns som det finns mer i den historien 😄 Vad är den riktiga versionen?",
        "Efter en lång dag — laddar du med människor, rörelse eller lugn?",
    ),
    "cs": (
        "Ok, nový úhel 🙂 Co tě teď opravdu baví?",
        "Mám pocit, že v tom příběhu je víc 😄 Jaká je ta opravdová verze?",
        "Po dlouhém dni dobíjíš u lidí, pohybu, nebo v klidu?",
    ),
    "ro": (
        "Ok, unghi nou 🙂 Ce te entuziasmează cu adevărat în ultima vreme?",
        "Simt că mai e ceva la povestea aia 😄 Care e varianta reală?",
        "După o zi lungă te reîncarci cu oameni, mișcare sau liniște?",
    ),
    "hu": (
        "Oké, új szög 🙂 Mi izgat igazán mostanában?",
        "Olyan érzésem van, van folytatása a sztorinak 😄 Mi az igazi verzió?",
        "Hosszú nap után emberekkel, mozgással vagy csenddel töltődsz?",
    ),
    "el": (
        "Οκ, νέα γωνία 🙂 Τι σε ενθουσιάζει πραγματικά τελευταία;",
        "Νιώθω πως υπάρχει συνέχεια σε αυτή την ιστορία 😄 Ποια είναι η αληθινή εκδοχή;",
        "Μετά από μια μεγάλη μέρα φορτίζεις με ανθρώπους, κίνηση ή ησυχία;",
    ),
    "da": (
        "Okay, ny vinkel 🙂 Hvad har været ægte spændende for dig på det seneste?",
        "Jeg har en fornemmelse af, der er mere i den historie 😄 Hvad er den rigtige version?",
        "Efter en lang dag — lader du op med mennesker, bevægelse eller ro?",
    ),
    "fi": (
        "Okei, uusi kulma 🙂 Mikä on oikeasti innostanut sinua viime aikoina?",
        "Tuntuu että siinä tarinassa on lisää 😄 Mikä on oikea versio?",
        "Pitkän päivän jälkeen lataudut ihmisillä, liikkeellä vai hiljaisuudella?",
    ),
    "no": (
        "Greit, ny vinkel 🙂 Hva har vært ekte spennende for deg i det siste?",
        "Føles som det er mer i den historien 😄 Hva er den ekte versjonen?",
        "Etter en lang dag — lader du med folk, bevegelse eller ro?",
    ),
    "bg": (
        "Добре, нова гледна точка 🙂 Кое те вълнува напоследък наистина?",
        "Усещам, че има още по историята 😄 Коя е истинската версия?",
        "След дълъг ден зареждаш ли се с хора, движение или тишина?",
    ),
}

_TIMED_NOW_EMERGENCY: dict[str, tuple[str, str, str]] = {
    "en": (
        "Nice 🙂 I’m in a cozy mood tonight—long chat or quick warm text?",
        "Okay 🙂 I’d keep it playful—plans-this-week energy or full improvisation?",
        "Love that you brought it up 🙂 after work do you recharge with people or quiet?",
    ),
    "uk": (
        "Клас 🙂 яка частина цього для тебе найцікавіша?",
        "Ок 🙂 що саме в цьому відгукнулося тобі найсильніше?",
        "Хочу зрозуміти точніше — про який саме момент ти говориш?",
    ),
    "ru": (
        "Класс 🙂 Что думаешь об этом?",
        "Ок 🙂 Что зацепило больше всего?",
        "Хочу понять чуть лучше — что именно ты имеешь в виду?",
    ),
    "es": (
        "Qué bien 🙂 ¿Qué piensas de eso?",
        "Vale 🙂 ¿Qué fue lo que más te enganchó?",
        "Quiero entender un poco más — ¿qué quieres decir exactamente?",
    ),
    "pt": (
        "Legal 🙂 O que você acha disso?",
        "Beleza 🙂 O que mais te prendeu nisso?",
        "Quero entender um pouco mais — o que você quer dizer exatamente?",
    ),
    "fr": (
        "Sympa 🙂 Tu en penses quoi?",
        "Ok 🙂 Qu’est-ce qui t’a le plus accroché?",
        "Je veux mieux comprendre — tu veux dire quoi exactement?",
    ),
    "de": (
        "Nice 🙂 Was denkst du dazu?",
        "Okay 🙂 Was hat dich am meisten geholt?",
        "Ich will’s besser verstehen — was meinst du genau?",
    ),
    "it": (
        "Bene 🙂 Che ne pensi?",
        "Ok 🙂 Cosa ti ha colpito di più?",
        "Voglio capire un po’ meglio — cosa intendi esattamente?",
    ),
    "pl": (
        "Super 🙂 Co o tym myślisz?",
        "Ok 🙂 Co najbardziej Cię w tym złapało?",
        "Chcę lepiej zrozumieć — co dokładnie masz na myśli?",
    ),
    "tr": (
        "Güzel 🙂 Bunun hakkında ne düşünüyorsun?",
        "Tamam 🙂 Seni en çok ne yakaladı?",
        "Biraz daha anlamak istiyorum — tam olarak ne demek istiyorsun?",
    ),
    "zh": (
        "不错～你怎么看待这个？",
        "好呀～哪一点最吸引你？",
        "我想多懂一点——你具体是什么意思？",
    ),
    "zh-TW": (
        "不錯～你怎麼看待這個？",
        "好呀～哪一點最吸引你？",
        "我想多懂一點——你具體是什麼意思？",
    ),
    "ja": (
        "いいね～それどう思う？",
        "OK～いちばん引っかかったのはどこ？",
        "もう少し理解したい — 具体的にどういう意味？",
    ),
    "ko": (
        "좋아 🙂 그거 어떻게 생각해?",
        "오케이 🙂 뭐가 제일 끌렸어?",
        "조금 더 이해하고 싶어 — 정확히 무슨 뜻이야?",
    ),
    "hi": (
        "अच्छा 🙂 इस बारे में तुम क्या सोचते हो?",
        "ठीक 🙂 सबसे ज़्यादा क्या चुभा?",
        "थोड़ा और समझना चाहता हूँ — सटीक मतलब क्या है?",
    ),
    "id": (
        "Asik 🙂 Gimana menurutmu?",
        "Oke 🙂 Yang paling nancep di kamu apa?",
        "Aku mau paham lebih — maksudmu persisnya apa?",
    ),
    "vi": (
        "Hay đấy 🙂 Bạn nghĩ sao về chuyện đó?",
        "Ok 🙂 Điều gì khiến bạn thích nhất?",
        "Mình muốn hiểu hơn — bạn ý là gì chính xác?",
    ),
    "th": (
        "ดีเลย 🙂 คุณคิดยังไงกับเรื่องนั้น?",
        "โอเค 🙂 อะไรที่โดนใจคุณที่สุด?",
        "อยากเข้าใจมากขึ้น — หมายถึงยังไงแบบชัดๆ?",
    ),
    "ar": (
        "حلو 🙂 إيه رأيك في ده?",
        "تمام 🙂 إيه اللي مسكك أكتر?",
        "عايز أفهم أكتر — تقصد إيه بالظبط?",
    ),
    "he": (
        "נחמד 🙂 מה דעתך על זה?",
        "אוקיי 🙂 מה הכי תפס אותך?",
        "רוצה להבין קצת יותר — למה בדיוק את/ה מתכוון/ת?",
    ),
    "nl": (
        "Leuk 🙂 Wat vind je ervan?",
        "Oké 🙂 Wat pakte je het meest?",
        "Ik wil het beter snappen — wat bedoel je precies?",
    ),
    "sv": (
        "Nice 🙂 Vad tycker du om det?",
        "Okej 🙂 Vad fastnade mest hos dig?",
        "Vill förstå lite mer — vad menar du exakt?",
    ),
    "cs": (
        "Super 🙂 Co si o tom myslíš?",
        "Ok 🙂 Co tě na tom nejvíc chytilo?",
        "Chci tomu líp rozumět — co přesně myslíš?",
    ),
    "ro": (
        "Fain 🙂 Ce crezi despre asta?",
        "Ok 🙂 Ce te-a prins cel mai tare?",
        "Vreau să înțeleg mai bine — ce vrei să spui exact?",
    ),
    "hu": (
        "Király 🙂 Mit gondolsz róla?",
        "Oké 🙂 Mi fogott meg legjobban?",
        "Jobban meg szeretném érteni — pontosan mire gondolsz?",
    ),
    "el": (
        "Ωραία 🙂 Τι πιστεύεις γι’ αυτό;",
        "Οκ 🙂 Τι σε τράβηξε περισσότερο;",
        "Θέλω να καταλάβω καλύτερα — τι εννοείς ακριβώς;",
    ),
    "da": (
        "Nice 🙂 Hvad synes du om det?",
        "Okay 🙂 Hvad fangede dig mest?",
        "Vil gerne forstå lidt mere — hvad mener du præcist?",
    ),
    "fi": (
        "Kiva 🙂 Mitä mieltä olet?",
        "Okei 🙂 Mikä napautti eniten?",
        "Haluan ymmärtää paremmin — mitä tarkalleen tarkoitat?",
    ),
    "no": (
        "Nice 🙂 Hva synes du om det?",
        "Greit 🙂 Hva fanget deg mest?",
        "Vil gjerne forstå bedre — hva mener du nøyaktig?",
    ),
    "bg": (
        "Супер 🙂 Какво мислиш за това?",
        "Ок 🙂 Кое те грабна най-много?",
        "Искам да разбера малко повече — какво точно имаш предвид?",
    ),
}

_OPENER_TYPED: dict[str, tuple[str, str, str]] = {
    "en": (
        "Coffee or wine—what feels more like you today?",
        "Are you more of a planner or a ‘see what happens’ person?",
        "What’s been the best tiny moment of your week so far?",
    ),
    "uk": (
        "Кава чи вино — що більше про тебе сьогодні?",
        "Ти більше планувальник чи «подивимось, що буде»?",
        "Який був найкращий маленький момент твого тижня?",
    ),
    "ru": (
        "Кофе или вино — что больше про тебя сегодня?",
        "Ты больше планер или «посмотрим, что будет»?",
        "Какой был лучший маленький момент твоей недели?",
    ),
    "es": (
        "¿Café o vino — qué va más contigo hoy?",
        "¿Eres más de planificar o de ‘vemos qué pasa’?",
        "¿Cuál fue el mejor mini-momento de tu semana?",
    ),
    "pt": (
        "Café ou vinho — o que combina mais com você hoje?",
        "Você é mais planejador ou de ‘vamos ver no que dá’?",
        "Qual foi o melhor micro-momento da sua semana?",
    ),
    "fr": (
        "Café ou vin — qu’est-ce qui te ressemble le plus aujourd’hui?",
        "Tu es plutôt planificateur ou ‘on verra ce qui arrive’?",
        "C’était quoi le plus beau petit moment de ta semaine?",
    ),
    "de": (
        "Kaffee oder Wein — was passt heute mehr zu dir?",
        "Bist du eher Planer oder ‘mal schauen, was passiert’?",
        "Was war der beste kleine Moment deiner Woche?",
    ),
    "it": (
        "Caffè o vino — cosa ti rappresenta di più oggi?",
        "Sei più da pianificare o da ‘vediamo che succede’?",
        "Qual è stato il miglior micro-momento della tua settimana?",
    ),
    "pl": (
        "Kawa czy wino — co bardziej do Ciebie pasuje dziś?",
        "Jesteś raczej planistą czy ‘zobaczymy, co będzie’?",
        "Jaki był najlepszy mały moment Twojego tygodnia?",
    ),
    "tr": (
        "Kahve mi şarap mı — bugün hangisi daha çok sen?",
        "Daha çok planlayıcı mısın yoksa ‘bakalım ne olacak’ mı?",
        "Haftanın en iyi küçük anı neydi?",
    ),
    "zh": (
        "咖啡还是酒——今天哪种更像你？",
        "你更像计划型还是顺其自然型？",
        "这周最棒的一个小瞬间是什么？",
    ),
    "zh-TW": (
        "咖啡還是酒——今天哪種更像你？",
        "你更像計畫型還是順其自然型？",
        "這週最棒的一個小瞬間是什麼？",
    ),
    "ja": (
        "コーヒーとワイン、今日のあなたはどっち寄り？",
        "計画派？それとも流れに任せる派？",
        "今週いちばん小さくて良かった瞬間は？",
    ),
    "ko": (
        "커피 vs 와인 — 오늘 너한테 더 어울리는 건?",
        "계획형이야, 아니면 ‘되게 두자’ 타입이야?",
        "이번 주 가장 좋았던 작은 순간이 뭐야?",
    ),
    "hi": (
        "कॉफ़ी या वाइन — आज तुम्हें क्या ज़्यादा सूट करता है?",
        "तुम ज़्यादा प्लानर हो या ‘देखते हैं क्या होता है’ वाले?",
        "इस हफ़्ते अब तक सबसे अच्छा छोटा पल क्या रहा?",
    ),
    "id": (
        "Kopi atau anggur — yang mana lebih kamu hari ini?",
        "Kamu lebih suka merencanakan atau ‘lihat nanti’?",
        "Apa momen kecil terbaik minggumu sejauh ini?",
    ),
    "vi": (
        "Cà phê hay rượu vang — hôm nay cái nào ‘đúng vibe’ bạn hơn?",
        "Bạn kiểu hay lên kế hoạch hay ‘cứ để mọi thứ diễn ra’?",
        "Khoảnh khắc nhỏ đẹp nhất tuần này của bạn là gì?",
    ),
    "th": (
        "กาแฟหรือไวน์ — วันนี้แบบไหนเหมาะกับคุณกว่า?",
        "คุณสายวางแผนหรือสาย ‘ปล่อยให้เป็นไป’?",
        "ช่วงเวลาเล็กๆ ที่ดีที่สุดของสัปดาห์นี้คืออะไร?",
    ),
    "ar": (
        "قهوة ولا خمر — إيه اللي يشبهك أكتر النهاردة?",
        "أنت أكتر مخطط ولا ‘نشوف إيه اللي هيحصل’?",
        "إيه أحلى لحظة صغيرة في أسبوعك لحد دلوقتي?",
    ),
    "he": (
        "קפה או יין — מה מרגיש יותר את/ה היום?",
        "את/ה יותר סוג שמתכנן או ‘נראה מה יהיה’?",
        "מה הרגע הקטן הכי טוב בשבוע שלך עד עכשיו?",
    ),
    "nl": (
        "Koffie of wijn — wat voelt meer als jij vandaag?",
        "Ben je meer een planner of een ‘we zien wel’-persoon?",
        "Wat was het beste kleine moment van je week tot nu toe?",
    ),
    "sv": (
        "Kaffe eller vin — vad känns mest du idag?",
        "Är du mer planerare eller ‘vi får se’?",
        "Vad var veckans bästa lilla stund hittills?",
    ),
    "cs": (
        "Káva nebo víno — co je dnes víc ty?",
        "Jsi spíš plánovač, nebo ‘uvidíme, co bude’?",
        "Co byl nejlepší malý moment tvého týdne?",
    ),
    "ro": (
        "Cafea sau vin — ce te reprezintă mai mult azi?",
        "Ești mai mult organizator sau ‘vedem ce se întâmplă’?",
        "Care a fost cel mai bun mic moment al săptămânii tale până acum?",
    ),
    "hu": (
        "Kávé vagy bor — mi illik hozzád jobban ma?",
        "Inkább tervező vagy ‘majd alakul’ típus vagy?",
        "Mi volt a heted legjobb kis pillanata eddig?",
    ),
    "el": (
        "Καφές ή κρασί — τι σε εκφράζει περισσότερο σήμερα;",
        "Είσαι περισσότερο τύπος που σχεδιάζει ή ‘αφήνουμε να έρθει’;",
        "Ποιο ήταν το καλύτερο μικρό στιγμιότυπο της εβδομάδας σου μέχρι τώρα;",
    ),
    "da": (
        "Kaffe eller vin — hvad føles mest som dig i dag?",
        "Er du mere planlægger eller ‘vi ser, hvad der sker’?",
        "Hvad var det bedste små øjeblik i din uge indtil videre?",
    ),
    "fi": (
        "Kahvi vai viini — kumpi on enemmän sinua tänään?",
        "Oletko enemmän suunnittelija vai ‘katsotaan miten käy’?",
        "Mikä oli viikkosi paras pieni hetki tähän mennessä?",
    ),
    "no": (
        "Kaffe eller vin — hva føles mest som deg i dag?",
        "Er du mer planlegger eller ‘vi får se’?",
        "Hva var det beste lille øyeblikket i uken din så langt?",
    ),
    "bg": (
        "Кафе или вино — кое те описва по-добре днес?",
        "Повече ли си планиращ или „да видим какво ще стане“?",
        "Какъв беше най-добрият малък момент от седмицата ти досега?",
    ),
}

# One-line “wait / don’t spam” strategy hint for start-strategy deterministic fallback (same keys as phrase banks).
_START_STRATEGY_WAIT: dict[str, str] = {
    "en": "Better to wait a little so it does not feel like spam.",
    "uk": "Краще трохи зачекати, щоб це не виглядало як спам.",
    "ru": "Лучше чуть подождать, чтобы это не выглядело как спам.",
    "es": "Mejor esperar un poco para que no parezca spam.",
    "pt": "Melhor esperar um pouco para não parecer spam.",
    "fr": "Mieux vaut attendre un peu pour éviter l’effet spam.",
    "de": "Warte lieber kurz, damit es nicht wie Spam wirkt.",
    "it": "Meglio aspettare un attimo così non sembra spam.",
    "pl": "Lepiej chwilę poczekać, żeby to nie wyglądało jak spam.",
    "tr": "Spam gibi durmaması için biraz beklemek daha iyi.",
    "zh": "稍微等一下比较好，这样不会像骚扰信息。",
    "zh-TW": "稍微等一下比較好，這樣比較不像騷擾訊息。",
    "ja": "スパムっぽくならないよう、少し間を置くのがおすすめ。",
    "ko": "스팸처럼 보이지 않게 조금 기다리는 게 좋아요.",
    "hi": "थोड़ा इंतज़ार करना बेहतर है ताकि यह स्पैम जैसा न लगे।",
    "id": "Lebih baik tunggu sebentar biar nggak kayak spam.",
    "vi": "Nên chờ một chút để không giống spam.",
    "th": "รอสักครู่ดีกว่าเพื่อไม่ให้ดูเหมือนสแปม",
    "ar": "الأحسن تستنى شوية عشان مايبقاش شكلها سبام.",
    "he": "עדיף לחכות קצת כדי שלא ייראה כמו ספאם.",
    "nl": "Beter even wachten, zodat het niet als spam overkomt.",
    "sv": "Vänta gärna lite så det inte känns som spam.",
    "cs": "Radši chvíli počkej, ať to nepůsobí jako spam.",
    "ro": "Mai bine aștepți puțin ca să nu pară spam.",
    "hu": "Jobb egy kicsit várni, hogy ne tűnjön spamnak.",
    "el": "Καλύτερα να περιμένεις λίγο ώστε να μη φαίνεται σαν spam.",
    "da": "Vent lidt, så det ikke virker som spam.",
    "fi": "Odota hetki, ettei vaikuta roskapostilta.",
    "no": "Vent litt så det ikke virker som spam.",
    "bg": "По-добре изчакай малко, за да не изглежда като спам.",
}


def start_strategy_wait_reason(locale: str | None) -> str:
    key = resolve_fallback_locale_key(locale or "en")
    return _START_STRATEGY_WAIT.get(key) or _START_STRATEGY_WAIT["en"]


def resolve_fallback_locale_key(locale: str | None) -> str:
    """Map UI locale tags to phrase-bank keys (e.g. zh-CN → zh)."""
    canon = normalize_ai_request_locale(locale or "en")
    if canon == "zh-TW":
        return "zh-TW"
    if canon.startswith("zh"):
        return "zh"
    return canon


def _phrase_triple(table: dict[str, tuple[str, str, str]], loc: str) -> tuple[str, str, str]:
    key = resolve_fallback_locale_key(loc)
    row = table.get(key) or table.get("en")
    if not row:
        row = table["en"]
    return row


def _triple(kind: TimedNudge, loc: str) -> tuple[str, str, str]:
    if kind == "reengage":
        m = _TIMED_REENGAGE
    elif kind == "revive":
        m = _TIMED_REVIVE
    else:
        m = _TIMED_NOW_EMERGENCY
    return _phrase_triple(m, loc)


def timed_reengage_triple(locale: str | None) -> tuple[str, str, str]:
    return _triple("reengage", locale or "en")


def timed_revive_triple(locale: str | None) -> tuple[str, str, str]:
    return _triple("revive", locale or "en")


def timed_now_emergency_triple(locale: str | None) -> tuple[str, str, str]:
    canon = resolve_fallback_locale_key(locale or "en")
    if canon == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import uk_emergency_fallback_triple

        return uk_emergency_fallback_triple()
    return _triple("now_emergency", locale or "en")


def opener_typed_fallback(locale: str | None) -> list[tuple[str, str]]:
    """Return [(type, text), ...] safe/flirty/smart."""
    a, b, c = _phrase_triple(_OPENER_TYPED, locale or "en")
    return [("safe", a), ("flirty", b), ("smart", c)]


def compose_chat_brain_packs(lang: str | None) -> dict[str, tuple[str, str, str]]:
    """
    Localized chat-brain fallback for locales without hand-tuned packs (fr, de, zh, …).
    Reuses opener + timed phrase banks so tone stays dating-appropriate.
    """
    canon = resolve_fallback_locale_key(lang or "en")
    op = opener_typed_fallback(canon)
    fe = timed_now_emergency_triple(canon)
    tr = timed_revive_triple(canon)
    rg = timed_reengage_triple(canon)
    return {
        "opener": (op[0][1], op[1][1], op[2][1]),
        "reply": fe,
        "revive": tr,
        "deepen": (rg[2], tr[2], fe[2]),
        "flirty": (rg[1], tr[1], op[1][1]),
    }


def timed_rows_for_nudge(nudge: str, locale: str | None) -> tuple[list[dict[str, str]], str]:
    """
    Deterministic localized rows for reengage/revive.
    Returns (options, source_locale) where source_locale == normalized target (no translate step).
    """
    loc = normalize_ai_request_locale(locale or "en")
    n = (nudge or "").strip().lower()
    if n == "reengage":
        light, flirty, deep = timed_reengage_triple(loc)
    elif n == "revive":
        light, flirty, deep = timed_revive_triple(loc)
    else:
        return [], loc
    return (
        [
            {"style": "light", "text": light},
            {"style": "flirty", "text": flirty},
            {"style": "deep", "text": deep},
        ],
        loc,
    )
