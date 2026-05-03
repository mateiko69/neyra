from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Locale = str


@dataclass(frozen=True)
class NormalizedLocation:
    city_original: str
    city_en: str
    city_local: str
    city_locative_uk: str | None
    country_code: str
    region: str | None
    timezone: str | None

    def to_dict(self) -> dict:
        return asdict(self)


_UA_CITY_MAP: dict[str, NormalizedLocation] = {
    "kyiv": NormalizedLocation(
        city_original="Kyiv",
        city_en="Kyiv",
        city_local="Київ",
        city_locative_uk="Києві",
        country_code="UA",
        region=None,
        timezone="Europe/Kyiv",
    ),
    "kiev": NormalizedLocation(
        city_original="Kiev",
        city_en="Kyiv",
        city_local="Київ",
        city_locative_uk="Києві",
        country_code="UA",
        region=None,
        timezone="Europe/Kyiv",
    ),
    "lviv": NormalizedLocation(
        city_original="Lviv",
        city_en="Lviv",
        city_local="Львів",
        city_locative_uk="Львові",
        country_code="UA",
        region=None,
        timezone="Europe/Kyiv",
    ),
    "verkhovyna": NormalizedLocation(
        city_original="Verkhovyna",
        city_en="Verkhovyna",
        city_local="Верховина",
        city_locative_uk="Верховині",
        country_code="UA",
        region=None,
        timezone="Europe/Kyiv",
    ),
    "chernivtsi": NormalizedLocation(
        city_original="Chernivtsi",
        city_en="Chernivtsi",
        city_local="Чернівці",
        city_locative_uk="Чернівцях",
        country_code="UA",
        region=None,
        timezone="Europe/Kyiv",
    ),
}


def normalize_city_key(city: str | None) -> str:
    return (city or "").strip().lower()


def normalize_location(
    *,
    city: str | None,
    country_code: str | None = None,
    timezone: str | None = None,
) -> NormalizedLocation | None:
    """Normalize a freeform city into a structured location when we can.

    Non-goals (for now): full world geocoding. This stays deterministic and offline.
    """
    key = normalize_city_key(city)
    if not key:
        return None
    if key in _UA_CITY_MAP:
        return _UA_CITY_MAP[key]

    # Minimal fallback: preserve original + use best-effort country/timezone if given.
    cc = (country_code or "").strip().upper() or "XX"
    tz = (timezone or "").strip() or None
    return NormalizedLocation(
        city_original=(city or "").strip()[:100],
        city_en=(city or "").strip()[:100],
        city_local=(city or "").strip()[:100],
        city_locative_uk=None,
        country_code=cc,
        region=None,
        timezone=tz,
    )


def get_display_city(loc: NormalizedLocation | None, locale: Locale) -> str:
    if not loc:
        return ""
    l = (locale or "").strip().lower()
    if l.startswith("uk"):
        return loc.city_local or loc.city_en or loc.city_original
    if l.startswith("ru"):
        # We don't store a ru-specific form yet; fall back to local (Cyrillic) or en.
        return loc.city_local or loc.city_en or loc.city_original
    return loc.city_en or loc.city_original


def get_city_locative(city: NormalizedLocation | None, locale: Locale) -> str:
    if not city:
        return ""
    l = (locale or "").strip().lower()
    if l.startswith("uk") and city.city_locative_uk:
        return city.city_locative_uk
    return get_display_city(city, locale)


def choose_preposition(locale: Locale) -> str:
    """Return the location preposition.

    - English: "in"
    - Ukrainian/Russian: "у" (neutral default; "в" can be phonetic but we keep deterministic)
    """
    l = (locale or "").strip().lower()
    if l.startswith("en"):
        return "in"
    if l.startswith("uk") or l.startswith("ru"):
        return "у"
    return "in"


def format_location(city: NormalizedLocation | None, country_code: str | None, locale: Locale) -> str:
    if not city:
        return ""
    pre = choose_preposition(locale)
    name = get_city_locative(city, locale) if pre in {"у", "в"} else get_display_city(city, locale)
    cc = (country_code or city.country_code or "").strip().upper()
    if cc and cc not in {"XX"} and (locale or "").strip().lower().startswith("en"):
        return f"{pre} {name}, {cc}"
    return f"{pre} {name}"

