"use client";

import type { Locale } from "./i18n";

type SuggestionSource = {
  displayName: string;
  relationshipGoal?: string;
  interests?: string;
  lifestyleTags?: string;
};

type SuggestionPack = {
  bioSuggestions: string[];
  openerSuggestions: string[];
  vibeLabel: string;
};

type VibeKey = "warm" | "playful" | "grounded" | "creative" | "adventurous";

function splitCsv(value: string | undefined): string[] {
  return (value || "")
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);
}

function deriveVibe(source: SuggestionSource): VibeKey {
  const interests = splitCsv(source.interests);
  const lifestyleTags = splitCsv(source.lifestyleTags);
  const goal = (source.relationshipGoal || "").trim().toLowerCase();

  if (goal === "casual") return "playful";
  if (interests.some((value) => ["travel", "hiking", "food"].includes(value))) return "adventurous";
  if (interests.some((value) => ["music", "art", "books", "films"].includes(value))) return "creative";
  if (lifestyleTags.some((value) => ["calm", "family", "earlybird"].includes(value))) return "grounded";
  return "warm";
}

function safeName(displayName: string): string {
  const trimmed = (displayName || "").trim();
  return trimmed || "You";
}

export function buildOnboardingSuggestions(locale: Locale, source: SuggestionSource): SuggestionPack {
  const name = safeName(source.displayName);
  const vibe = deriveVibe(source);

  const en = {
    vibeLabel: {
      warm: "Warm",
      playful: "Playful",
      grounded: "Grounded",
      creative: "Creative",
      adventurous: "Adventurous",
    } satisfies Record<VibeKey, string>,
    bios: {
      warm: [
        `${name} here for soft chemistry, clear energy, and dates that feel easy from minute one.`,
        `Equal parts thoughtful and easygoing. I like people who can turn a simple hello into a real connection.`,
        `I am into good taste, kind attention, and conversations that feel a little brighter after they happen.`,
      ],
      playful: [
        `${name} here for flirty banter, spontaneous plans, and a little mischief with good manners.`,
        `I like people who can keep things light, laugh quickly, and still mean what they say.`,
        `Fast spark, real curiosity, and the kind of energy that makes an ordinary night feel memorable.`,
      ],
      grounded: [
        `${name} here for steady chemistry, honest conversation, and the kind of connection that feels calm in the best way.`,
        `I like thoughtful people, easy plans, and relationships that feel clear instead of complicated.`,
        `A good evening for me is simple: real attention, relaxed energy, and someone worth staying present for.`,
      ],
      creative: [
        `${name} here for sharp taste, curious minds, and conversations with a little texture to them.`,
        `I notice details, love people with point of view, and gravitate toward chemistry that feels both smart and warm.`,
        `Artful energy, honest curiosity, and a soft spot for anyone who can make a first message feel original.`,
      ],
      adventurous: [
        `${name} here for momentum, good stories, and the kind of chemistry that makes saying yes feel easy.`,
        `I like people who are open to a last-minute plan, a long walk, or one more stop before heading home.`,
        `Curious, social, and usually up for turning a good vibe into an actual plan instead of endless texting.`,
      ],
    } satisfies Record<VibeKey, string[]>,
    openers: {
      warm: [
        `You feel easy to talk to already. What kind of first date actually sounds fun to you?`,
        `Okay, real question: what is something small that instantly makes you like someone's energy?`,
        `Your profile has calm confidence. What should I ask you about first?`,
      ],
      playful: [
        `Fast warm-up: are you more last-minute plan or beautifully planned chaos?`,
        `You get one great spontaneous evening this week. What are we doing?`,
        `You seem fun in a way that probably comes with stories. Which one do I get first?`,
      ],
      grounded: [
        `You feel refreshingly real. What kind of connection are you happiest building?`,
        `I am curious what your ideal low-pressure first date looks like.`,
        `Your profile gives steady energy. What always helps a conversation click for you?`,
      ],
      creative: [
        `You seem like someone with strong favorites. What is something you are delightfully opinionated about?`,
        `Your vibe feels curated in a good way. What are you into lately?`,
        `I have a feeling you notice details. What detail do people usually miss about you at first?`,
      ],
      adventurous: [
        `You feel like a yes to a good plan. What is the kind of invitation you never ignore?`,
        `Quick test: sunrise walk, hidden cocktail bar, or train somewhere new?`,
        `Your energy says there is a good story here. Which one should I ask for first?`,
      ],
    } satisfies Record<VibeKey, string[]>,
  };

  const uk = {
    vibeLabel: {
      warm: "Теплий",
      playful: "Грайливий",
      grounded: "Спокійний",
      creative: "Творчий",
      adventurous: "Сміливий",
    } satisfies Record<VibeKey, string>,
    bios: {
      warm: [
        `${name} тут заради м'якої хімії, ясної енергії й побачень, на яких легко з першої хвилини.`,
        `Поєдную уважність і легкість. Подобаються люди, з якими просте «привіт» швидко стає справжнім зв'язком.`,
        `Люблю смак, теплу увагу й розмови, після яких день ніби стає трохи кращим.`,
      ],
      playful: [
        `${name} тут заради флірту, спонтанних планів і трохи пустощів з хорошими манерами.`,
        `Люблю людей, які вміють тримати легкість, швидко сміятися і все ж говорити по-справжньому.`,
        `Швидка іскра, жива цікавість і та енергія, що робить звичайний вечір пам'ятним.`,
      ],
      grounded: [
        `${name} тут заради спокійної хімії, чесної розмови й зв'язку, в якому добре без зайвого шуму.`,
        `Мені подобаються уважні люди, легкі плани й стосунки, де все ясно, а не складно.`,
        `Для мене хороший вечір — це проста присутність, м'яка енергія й людина, поруч з якою хочеться залишатися.`,
      ],
      creative: [
        `${name} тут заради смаку, цікавих думок і розмов, у яких є фактура.`,
        `Люблю людей з власним поглядом і тягнуся до хімії, яка водночас розумна й тепла.`,
        `Творча енергія, чесна цікавість і слабкість до тих, хто вміє зробити перше повідомлення оригінальним.`,
      ],
      adventurous: [
        `${name} тут заради руху, хороших історій і тієї хімії, після якої легко сказати «так».`,
        `Мені близькі люди, які відкриті до плану в останню хвилину, довгої прогулянки чи ще однієї зупинки перед домом.`,
        `Цікава, соціальна і за те, щоб хороший вайб переходив у реальні плани, а не лишався в чаті.`,
      ],
    } satisfies Record<VibeKey, string[]>,
    openers: {
      warm: [
        `З тобою вже ніби легко говорити. Яке перше побачення для тебе справді в кайф?`,
        `Окей, чесне питання: яка дрібниця миттєво робить чиюсь енергію привабливою для тебе?`,
        `У твоєму профілі є спокійна впевненість. Про що тебе варто спитати спершу?`,
      ],
      playful: [
        `Швидкий розігрів: ти більше про план в останню хвилину чи про красиво організований хаос?`,
        `У тебе є один спонтанний вечір цього тижня. Що ми робимо?`,
        `Від тебе вайб веселощів із хорошими історіями. Яку я слухаю першою?`,
      ],
      grounded: [
        `У тебе дуже реальний вайб. Який зв'язок тобі найприємніше будувати?`,
        `Мені цікаво, яким для тебе виглядає ідеальне ненапружене перше побачення.`,
        `Твій профіль дає відчуття стабільності. Що завжди допомагає розмові скластися?`,
      ],
      creative: [
        `Ти схожа на людину з сильними смаками. У чому ти особливо приємно категорична?`,
        `Твій вайб дуже зібраний у хорошому сенсі. Чим живеш останнім часом?`,
        `Маю відчуття, що ти помічаєш деталі. Яку деталь про тебе люди часто пропускають спочатку?`,
      ],
      adventurous: [
        `Твій вайб схожий на «так» хорошому плану. Яке запрошення ти майже ніколи не ігноруєш?`,
        `Швидкий тест: світанкова прогулянка, прихований коктейль-бар чи поїзд кудись нове?`,
        `У тебе енергія хорошої історії. Яку варто попросити першою?`,
      ],
    } satisfies Record<VibeKey, string[]>,
  };

  const ru = {
    vibeLabel: {
      warm: "Теплый",
      playful: "Игривый",
      grounded: "Спокойный",
      creative: "Творческий",
      adventurous: "Смелый",
    } satisfies Record<VibeKey, string>,
    bios: {
      warm: [
        `${name} здесь ради мягкой химии, ясной энергии и свиданий, на которых легко уже с первой минуты.`,
        `Во мне есть и внимательность, и легкость. Нравятся люди, с которыми простое «привет» быстро превращается в настоящую связь.`,
        `Люблю вкус, теплое внимание и разговоры, после которых день будто становится чуть светлее.`,
      ],
      playful: [
        `${name} здесь ради флирта, спонтанных планов и немного озорства с хорошими манерами.`,
        `Мне нравятся люди, которые умеют держать легкость, быстро смеяться и все же говорить всерьез.`,
        `Быстрая искра, живая любопытность и та энергия, из-за которой обычный вечер становится запоминающимся.`,
      ],
      grounded: [
        `${name} здесь ради спокойной химии, честного разговора и связи, в которой хорошо без лишнего шума.`,
        `Мне нравятся вдумчивые люди, легкие планы и отношения, где все ясно, а не сложно.`,
        `Хороший вечер для меня — это простое внимание, мягкая энергия и человек, рядом с которым хочется оставаться.`,
      ],
      creative: [
        `${name} здесь ради вкуса, любопытных мыслей и разговоров, в которых есть фактура.`,
        `Мне нравятся люди с собственной оптикой, и тянет к химии, которая одновременно умная и теплая.`,
        `Творческая энергия, честное любопытство и слабость к тем, кто умеет сделать первое сообщение оригинальным.`,
      ],
      adventurous: [
        `${name} здесь ради движения, хороших историй и той химии, после которой легко сказать «да».`,
        `Мне близки люди, которые открыты к плану в последнюю минуту, длинной прогулке или еще одной остановке перед домом.`,
        `Любопытная, социальная и за то, чтобы хороший вайб переходил в реальные планы, а не оставался только в переписке.`,
      ],
    } satisfies Record<VibeKey, string[]>,
    openers: {
      warm: [
        `С тобой уже будто легко говорить. Какое первое свидание для тебя правда в удовольствие?`,
        `Окей, честный вопрос: какая мелочь сразу делает чью-то энергию притягательной для тебя?`,
        `В твоем профиле есть спокойная уверенность. О чем тебя стоит спросить сначала?`,
      ],
      playful: [
        `Быстрый разогрев: ты больше про план в последнюю минуту или про красиво организованный хаос?`,
        `У тебя есть один спонтанный вечер на этой неделе. Что мы делаем?`,
        `От тебя вайб веселья с хорошими историями. Какую я слышу первой?`,
      ],
      grounded: [
        `У тебя очень настоящий вайб. Какую связь тебе приятнее всего строить?`,
        `Мне интересно, как для тебя выглядит идеальное ненапряжное первое свидание.`,
        `Твой профиль дает ощущение устойчивости. Что всегда помогает разговору сложиться?`,
      ],
      creative: [
        `Ты похожа на человека с сильными вкусами. В чем ты особенно приятно категорична?`,
        `Твой вайб очень собранный в хорошем смысле. Чем живешь в последнее время?`,
        `Есть ощущение, что ты замечаешь детали. Какую деталь о тебе люди часто упускают сначала?`,
      ],
      adventurous: [
        `Твой вайб похож на «да» хорошему плану. Какое приглашение ты почти никогда не игнорируешь?`,
        `Быстрый тест: рассветная прогулка, скрытый коктейль-бар или поезд куда-то в новое место?`,
        `В тебе энергия хорошей истории. Какую стоит попросить первой?`,
      ],
    } satisfies Record<VibeKey, string[]>,
  };

  const bundle = locale === "uk" ? uk : locale === "ru" ? ru : en;

  return {
    bioSuggestions: bundle.bios[vibe],
    openerSuggestions: bundle.openers[vibe],
    vibeLabel: bundle.vibeLabel[vibe],
  };
}
