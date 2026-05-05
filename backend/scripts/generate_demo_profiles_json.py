#!/usr/bin/env python3
"""Build demo_profiles.json by scanning frontend/public/demo-profiles for demo_*/main.jpg.

Gender comes from path only: `/women/` vs `/men/`. Catalog ids are `{gender}_{folder}` e.g. woman_demo_001.
Resolves output path for both monorepo (backend next to frontend) and Docker (/app + /app/frontend).

Run:
  python backend/scripts/generate_demo_profiles_json.py
  docker compose exec api python scripts/generate_demo_profiles_json.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.demo_mode import demo_profiles_json_path, demo_profiles_public_dir  # noqa: E402

log = logging.getLogger("neyra.generate_demo_profiles_json")

DEMO_LINE_EN = "Demo profile 🤖 — AI simulation. Just testing how the app works."

_FOLDER_RE = re.compile(r"^demo_(\d+)$")


def detect_gender_from_path(path: str) -> str:
    """Folder is source of truth: a `women` or `men` path segment (e.g. women/demo_001/main.jpg)."""
    p = (path or "").replace("\\", "/").lower()
    segs = [s for s in p.split("/") if s]
    if "women" in segs:
        return "woman"
    if "men" in segs:
        return "man"
    if "/women/" in p:
        return "woman"
    if "/men/" in p:
        return "man"
    return "woman"


CITIES = [
    "Kyiv",
    "Warsaw",
    "Berlin",
    "Lisbon",
    "Prague",
    "Barcelona",
    "Amsterdam",
    "Vienna",
    "Tallinn",
    "Paris",
    "London",
    "Copenhagen",
    "Rome",
    "Milan",
    "Budapest",
    "Kraków",
    "Porto",
    "Dublin",
    "Edinburgh",
    "Munich",
    "Hamburg",
    "Geneva",
    "Nice",
    "Split",
    "Riga",
]

FEMALE_NAMES = [
    "Maya",
    "Nora",
    "Sofia",
    "Elena",
    "Anna",
    "Giulia",
    "Claire",
    "Freja",
    "Lena",
    "Iris",
    "Zoe",
    "Mila",
]

PERSONALITY_CYCLE = ("playful", "deep", "calm", "teasing")

MALE_NAMES = [
    "Leo",
    "Adam",
    "Milan",
    "Tom",
    "Erik",
    "Alex",
    "Oskar",
    "Mark",
    "Jonas",
    "Felix",
    "Damian",
    "Victor",
    "Hugo",
]

FEMALE_BIOS = [
    "Coffee shops, weekend markets, and playlists that feel like a hug.",
    "Runner, reader, and always up for trying one new restaurant.",
    "Art galleries, long walks, and honest conversation over small talk.",
    "Yoga mornings, spicy food, and friends who show up on time.",
    "Film nights, city lights, and slow Sunday mornings.",
    "Photography, thrift finds, and people who ask good questions.",
    "Beach person in summer, tea person year-round.",
    "Dancing when the song is right; quiet when the moment is better.",
    "Loves languages, live music, and plans with room to wander.",
    "Cooking experiments, board games, and cozy chaos.",
    "Hikes, podcasts, and the kind of chemistry that feels easy.",
    "Design-minded, playlist-curious, and allergic to drama.",
]

MALE_BIOS = [
    "Gym, good coffee, and conversations that go past midnight.",
    "Cooks on weeknights, explores on weekends, replies thoughtfully.",
    "Cycling, documentaries, and dry humor with a soft heart.",
    "Board games, craft beer, and loyal friendships.",
    "Photography, football, and making time for people who matter.",
    "Startup hours but still saves Sundays for nothing serious.",
    "Climbing gym regular; museum pass holder.",
    "Jazz bars, early runs, and straightforward kindness.",
    "Dog person, pasta person, plans-ahead-but-flexible person.",
    "Nature on Saturday, city on Sunday; balance matters.",
    "Chess, synth music, and zero patience for games in dating.",
    "Volunteer shifts, audiobooks, and real follow-through.",
    "Night owl with a morning coffee ritual—work in progress.",
]

INTEREST_POOL = [
    "travel",
    "food",
    "music",
    "hiking",
    "photography",
    "reading",
    "cooking",
    "running",
    "yoga",
    "art",
    "film",
    "coffee",
    "nature",
    "tech",
    "volunteering",
    "climbing",
    "swimming",
    "dancing",
    "podcasts",
    "design",
]

LIFESTYLE_POOL = [
    "social",
    "curious",
    "easygoing",
    "active",
    "calm",
    "creative",
    "outdoorsy",
    "city-minded",
    "thoughtful",
    "spontaneous",
]


def _folder_hash(folder_id: str) -> int:
    return int(hashlib.md5(folder_id.encode("utf-8"), usedforsecurity=False).hexdigest(), 16)


def _pick_city(folder_id: str) -> str:
    return CITIES[_folder_hash(folder_id) % len(CITIES)]


def _pick_interests(folder_id: str) -> str:
    h = _folder_hash(folder_id)
    n = 3 + (h % 3)
    order = list(range(len(INTEREST_POOL)))
    x = h
    for i in range(len(order) - 1, 0, -1):
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        j = x % (i + 1)
        order[i], order[j] = order[j], order[i]
    picks = [INTEREST_POOL[order[k]] for k in range(n)]
    return ", ".join(picks)


def _pick_lifestyle_tags(folder_id: str) -> str:
    h = _folder_hash(folder_id)
    chosen: list[str] = []
    x = h
    for _ in range(24):
        if len(chosen) >= 3:
            break
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        t = LIFESTYLE_POOL[x % len(LIFESTYLE_POOL)]
        if t not in chosen:
            chosen.append(t)
    while len(chosen) < 3:
        chosen.append("easygoing")
    return ", ".join(chosen[:3])


def _age_for_folder(folder_id: str, gender_profile: str) -> int:
    h = _folder_hash(folder_id)
    if gender_profile == "woman":
        return 18 + (h % 13)
    return 20 + (h % 16)


def _response_speed(folder_id: str) -> str:
    return ("fast", "normal", "slow")[_folder_hash(folder_id) % 3]


def _engagement_level(folder_id: str) -> float:
    h = _folder_hash(folder_id)
    v = 0.55 + (h % 36) * 0.01
    return round(min(0.92, v), 2)


def _ex(en: list[str], uk: list[str]) -> dict[str, list[str]]:
    return {"en": list(en), "uk": list(uk)}


def _examples_for(personality: str, name: str, city: str) -> dict[str, dict[str, list[str]]]:
    """Multilingual catalog lines (en + uk); demo_behavior falls back to en for other locales."""
    if personality == "teasing":
        return {
            "opener_examples": _ex(
                [
                    "Quick vibe check 🙂 are you more spontaneous or do you like planning the week?",
                    f"Hey — I'm {name}. What's something small that instantly lifts your mood?",
                ],
                [
                    "Хей 🙂 ти більше про спонтанність чи любиш планувати?",
                    f"Привіт — я {name}. Що маленьке одразу піднімає настрій?",
                ],
            ),
            "reply_examples": _ex(
                [
                    "Haha fair 🙂 I'd push back gently — coffee first or straight to adventure?",
                    "I'm listening — what's one thing you're picky about (in a cute way)?",
                ],
                [
                    "Справедливо 🙂 тоді обережно спитаю — спочатку кава чи одразу пригода?",
                    "Слухаю — будь до чого ти вибірковий (в гарному сенсі)?",
                ],
            ),
            "revive_examples": _ex(
                ["Still curious about you — no pressure, just checking in 🙂"],
                ["Досі цікаво про тебе — без тиску, просто заглядаю 🙂"],
            ),
        }
    if personality == "deep":
        return {
            "opener_examples": _ex(
                [
                    f"Hey — I'm {name}. What's something you've changed your mind about lately?",
                    "Hi. What's a lesson from this year that stuck with you?",
                ],
                [
                    f"Привіт — я {name}. Над чим ти нещодавно змінив думку?",
                    "Привіт. Який урок цього року запам'ятався найбільше?",
                ],
            ),
            "reply_examples": _ex(
                [
                    "That resonates. What made it click for you?",
                    "Thanks for sharing — what's one thing you're hoping for next month?",
                ],
                [
                    "Відгукується. Що для тебе стало переломним?",
                    "Дякую, що поділився — на що сподіваєшся в наступному місяці?",
                ],
            ),
            "revive_examples": _ex(
                ["Hey — random check-in. Still around? No pressure either way."],
                ["Привіт — короткий чек-ін. Ти ще тут? Без тиску."],
            ),
        }
    if personality in ("flirty", "playful"):
        return {
            "opener_examples": _ex(
                [
                    f"Okay, your profile made me smile — what's your go-to weekend plan?",
                    f"Hi 🙂 I'm {name}. Tell me one thing you're oddly picky about.",
                ],
                [
                    "Твій профіль змусив посміхнутися — який план на вихідні тобі ближчий?",
                    f"Привіт 🙂 Я {name}. Розкажи одну річ, до якої ти дивишся вибірково.",
                ],
            ),
            "reply_examples": _ex(
                [
                    "Love that energy 😊 what would you want to do if we met up?",
                    "Okay I'm curious — what's your favorite way to spend a free evening?",
                ],
                [
                    "Класна енергія 😊 що б ти хотіла зробити, якби зустрілися?",
                    "Цікаво — як ти любиш проводити вільний вечір?",
                ],
            ),
            "revive_examples": _ex(
                ["Popping back in 🙂 if you're still curious, I'd like to keep chatting."],
                ["Заглядаю знову 🙂 якщо ще цікаво — хочу продовжити розмову."],
            ),
        }
    if personality == "warm":
        return {
            "opener_examples": _ex(
                [
                    "Hey! I'd love to hear what you're into lately.",
                    f"Hi — warm hello from {city}. What's been on your mind this week?",
                ],
                [
                    "Привіт! Розкажи, чим ти зараз живеш.",
                    f"Привіт — тепле привітання з {city}. Що у тебе на думці цього тижня?",
                ],
            ),
            "reply_examples": _ex(
                [
                    "That sounds nice — I'd like to hear more. What drew you to that?",
                    "Haha, fair. What would you want to do on a first meetup—coffee or a walk?",
                ],
                [
                    "Звучить приємно — розкажи більше. Що тебе до цього підштовхнуло?",
                    "Справедливо 🙂 На першу зустріч — кава чи прогулянка?",
                ],
            ),
            "revive_examples": _ex(
                ["Hey — random check-in. Still around? No pressure either way."],
                ["Привіт — короткий чек-ін. Ти ще тут? Без тиску."],
            ),
        }
    if personality == "calm":
        return {
            "opener_examples": _ex(
                [
                    f"Hey. I'm {name}. What's been a good moment recently?",
                    "Hi — low-pressure question: tea or coffee, and why?",
                ],
                [
                    f"Привіт. Я {name}. Що нещодавно було хорошим моментом?",
                    "Привіт — питання без тиску: чай чи кава, і чому?",
                ],
            ),
            "reply_examples": _ex(
                [
                    "Makes sense. Want to keep it simple—coffee or a walk sometime?",
                    "I hear you. What's been taking most of your attention lately?",
                ],
                [
                    "Логічно. Може простіше — кава чи прогулянка колись?",
                    "Чую. Що зараз займає більшість уваги?",
                ],
            ),
            "revive_examples": _ex(
                ["Hey — random check-in. Still around? No pressure either way."],
                ["Привіт — короткий чек-ін. Ти ще тут? Без тиску."],
            ),
        }
    if personality == "confident":
        return {
            "opener_examples": _ex(
                [
                    f"Hi — I'm {name}. What's one goal you're working on right now?",
                    "Hey. What would a perfect Sunday look like for you?",
                ],
                [
                    f"Привіт — я {name}. Над якою однією ціллю ти зараз працюєш?",
                    "Привіт. Як виглядав би ідеальна неділя для тебе?",
                ],
            ),
            "reply_examples": _ex(
                [
                    "Solid. I'd match that with: what's your non-negotiable in dating?",
                    "Interesting. Tell me one thing you're proud of from this month.",
                ],
                [
                    "Сильно. А що для тебе принципово в знайомствах?",
                    "Цікаво. Назви одну річ, яку ти пишаєшся цього місяця.",
                ],
            ),
            "revive_examples": _ex(
                ["Hey — random check-in. Still around? No pressure either way."],
                ["Привіт — короткий чек-ін. Ти ще тут? Без тиску."],
            ),
        }
    return {
        "opener_examples": _ex(
            [
                "Hey! What's something you're learning or trying lately?",
                f"Hi from {city} — what's a place here you'd recommend?",
            ],
            [
                "Привіт! Чого ти зараз навчаєшся або що пробуєш?",
                f"Привіт з {city} — яке місце тут варто порадити?",
            ],
        ),
        "reply_examples": _ex(
            [
                "That sounds nice — I'd like to hear more. What drew you to that?",
                "Haha, fair. What would you want to do on a first meetup—coffee or a walk?",
            ],
            [
                "Звучить приємно — розкажи більше. Що тебе до цього підштовхнуло?",
                "Справедливо 🙂 На першу зустріч — кава чи прогулянка?",
            ],
        ),
        "revive_examples": _ex(
            ["Hey — random check-in. Still around? No pressure either way."],
            ["Привіт — короткий чек-ін. Ти ще тут? Без тиску."],
        ),
    }


def scan_demo_folders(demo_dir: Path) -> tuple[list[dict], list[tuple[str, str]]]:
    """
    Find demo_<digits>/main.jpg under demo_dir (e.g. women/demo_001/main.jpg).

    Catalog id is {woman|man}_{folder_name} so women/demo_001 and men/demo_001 can both exist.
    """
    valid: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []
    try:
        if not demo_dir.is_dir():
            log.warning("demo profiles directory missing or not a directory: %s", demo_dir)
            return [], [("<none>", "demo_dir_missing")]
    except OSError as e:
        log.warning("cannot read demo directory %s: %s", demo_dir, e)
        return [], [("<none>", f"demo_dir_unreadable:{e}")]

    try:
        candidates = sorted(demo_dir.rglob("main.jpg"), key=lambda x: str(x))
    except OSError as e:
        return [], [("<none>", f"rglob_failed:{e}")]

    for main_jpg in candidates:
        try:
            rel = main_jpg.relative_to(demo_dir)
        except ValueError:
            continue
        rel_posix = rel.as_posix()
        parent = main_jpg.parent
        try:
            if not parent.is_dir():
                continue
        except OSError:
            skipped.append((rel_posix, "parent_stat_failed"))
            continue
        folder_name = parent.name
        m = _FOLDER_RE.match(folder_name)
        if not m:
            skipped.append((rel_posix, "parent_not_demo_digits"))
            continue
        sort_n = int(m.group(1))
        gender_profile = detect_gender_from_path(rel_posix)
        catalog_id = f"{gender_profile}_{folder_name}"
        if catalog_id in valid:
            skipped.append((rel_posix, "duplicate_catalog_id"))
            continue
        valid[catalog_id] = {
            "id": catalog_id,
            "folder_name": folder_name,
            "sort_n": sort_n,
            "rel_posix": rel_posix,
            "gender_profile": gender_profile,
        }

    ordered = sorted(valid.values(), key=lambda e: (e["sort_n"], e["gender_profile"]))
    return ordered, skipped


def build_profiles_from_scan_entries(entries: list[dict]) -> list[dict]:
    """Build catalog rows from scan entries (gender and id fixed at scan time)."""
    out: list[dict] = []
    f_idx = 0
    m_idx = 0
    for global_idx, e in enumerate(entries):
        catalog_id = str(e["id"])
        folder_name = str(e["folder_name"])
        rel_posix = str(e["rel_posix"])
        gender_profile = str(e["gender_profile"])
        parent_rel = Path(rel_posix).parent.as_posix()
        photo_path = f"/demo-profiles/{parent_rel}/main.jpg"
        personality = PERSONALITY_CYCLE[global_idx % len(PERSONALITY_CYCLE)]

        if gender_profile == "woman":
            name = FEMALE_NAMES[f_idx % len(FEMALE_NAMES)]
            bio_core = FEMALE_BIOS[f_idx % len(FEMALE_BIOS)]
            interested_in = "men"
            f_idx += 1
        else:
            name = MALE_NAMES[m_idx % len(MALE_NAMES)]
            bio_core = MALE_BIOS[m_idx % len(MALE_BIOS)]
            interested_in = "women"
            m_idx += 1

        city = _pick_city(folder_name)
        age = _age_for_folder(folder_name, gender_profile)
        response_speed = _response_speed(folder_name)
        engagement = _engagement_level(folder_name)
        bio = f"{bio_core}\n\n{DEMO_LINE_EN}"
        ml = _examples_for(personality, name, city)
        interests = _pick_interests(folder_name)
        lifestyle_tags = _pick_lifestyle_tags(folder_name)

        out.append(
            {
                "id": catalog_id,
                "gender": gender_profile,
                "display_name": name,
                "age": age,
                "city": city,
                "gender_profile": gender_profile,
                "interested_in": interested_in,
                "relationship_goal": "relationship",
                "interests": interests,
                "lifestyle_tags": lifestyle_tags,
                "bio": bio,
                "photo_main_path": photo_path,
                "demo_personality": {
                    "personality": personality,
                    "personality_type": personality,
                    "response_speed": response_speed,
                    "engagement_level": engagement,
                    "opener_examples": ml["opener_examples"],
                    "reply_examples": ml["reply_examples"],
                    "revive_examples": ml["revive_examples"],
                },
            }
        )
    return out


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON; replace target only after temp file succeeds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    demo_dir = demo_profiles_public_dir()
    out_path = demo_profiles_json_path()

    entries, skipped = scan_demo_folders(demo_dir)
    for name, reason in skipped:
        log.info("skipped %s: %s", name, reason)

    profiles = build_profiles_from_scan_entries(entries)
    payload = {"version": 8, "profiles": profiles}

    if entries:
        rels = [str(e.get("rel_posix") or "").replace("\\", "/").lower() for e in entries]
        if not any("/women/" in r or "/men/" in r for r in rels):
            log.warning(
                "no photo paths under women/ or men/ — all profiles default to woman; "
                "see frontend/public/demo-profiles/README.md"
            )

    try:
        write_json_atomic(out_path, payload)
    except OSError as e:
        log.error("failed to write catalog: %s", e)
        raise SystemExit(1) from e

    log.info("profiles_written=%d catalog=%s skipped_folders=%d", len(profiles), out_path, len(skipped))
    if not profiles:
        log.warning("no profiles generated — add demo_<number> folders with main.jpg under %s", demo_dir)


if __name__ == "__main__":
    main()
    sys.exit(0)
