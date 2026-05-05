from datetime import UTC, date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


def _normalize_preferred_gender(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("", "auto", "default"):
        return ""
    if s in ("male", "m", "men", "man"):
        return "male"
    if s in ("female", "f", "women", "woman"):
        return "female"
    if s in ("everyone", "all", "any"):
        return "everyone"
    raise ValueError("preferred_gender must be '', 'male', 'female', or 'everyone'")


def _normalize_relationship_goal(raw: str) -> str:
    """Frontend onboarding uses: dating | relationship | chat (chat first). Keep tolerant for legacy clients."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in ("relationship", "relationships"):
        return "relationship"
    if s in ("dating", "date"):
        return "dating"
    if s in ("chat", "chat_first", "chat first"):
        return "chat"
    # Legacy profile page options
    if s in ("casual", "friends"):
        return s
    return s[:50]


def _normalize_interested_in(raw: str) -> str:
    """women | men | everyone (accept common aliases)."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in ("women", "woman", "female", "f"):
        return "women"
    if s in ("men", "man", "male", "m"):
        return "men"
    if s in ("everyone", "all", "any"):
        return "everyone"
    raise ValueError("interested_in must be 'women', 'men', or 'everyone'")


def _normalize_vibe(raw: str) -> str:
    """warm | playful | grounded | creative | adventurous"""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    allowed = {"warm", "playful", "grounded", "creative", "adventurous"}
    if s in allowed:
        return s
    raise ValueError("vibe must be 'warm', 'playful', 'grounded', 'creative', or 'adventurous'")


def _age_from_dob(dob: date, today: date | None = None) -> int:
    t = today or datetime.now(UTC).date()
    years = t.year - dob.year
    if (t.month, t.day) < (dob.month, dob.day):
        years -= 1
    return int(years)


class ProfileBase(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    bio: str = Field(default="", max_length=4000)
    age: int | None = Field(default=None, ge=18, le=99)
    date_of_birth: date | None = Field(default=None)
    city: str = Field(default="", max_length=100)
    gender: str = Field(default="", max_length=50)
    preferred_gender: str = Field(default="", max_length=32)
    interested_in: str = Field(default="", max_length=50)
    relationship_goal: str = Field(default="relationship", max_length=50)
    vibe: str = Field(default="", max_length=32)
    interests: str = Field(default="", max_length=2000)
    lifestyle_tags: str = Field(default="", max_length=2000)
    height_cm: int | None = Field(default=None, ge=120, le=230)
    job_title: str = Field(default="", max_length=100)
    photo_urls: str = Field(default="", max_length=8000)
    preferred_language: str = Field(default="en", max_length=8)
    native_language: str = Field(default="", max_length=8)
    additional_languages: str | list[str] = Field(default="", max_length=2000)
    min_preferred_age: int | None = Field(default=None, ge=18, le=80)
    max_preferred_age: int | None = Field(default=None, ge=18, le=80)

    @field_validator("preferred_gender", mode="before")
    @classmethod
    def validate_preferred_gender(cls, v: object) -> str:
        if v is None:
            return ""
        return _normalize_preferred_gender(str(v))

    @field_validator("interested_in", mode="before")
    @classmethod
    def validate_interested_in(cls, v: object) -> str:
        if v is None:
            return ""
        return _normalize_interested_in(str(v))

    @field_validator("relationship_goal", mode="before")
    @classmethod
    def validate_relationship_goal(cls, v: object) -> str:
        if v is None:
            return "relationship"
        out = _normalize_relationship_goal(str(v))
        return out or "relationship"

    @field_validator("vibe", mode="before")
    @classmethod
    def validate_vibe(cls, v: object) -> str:
        if v is None:
            return ""
        return _normalize_vibe(str(v)) if str(v).strip() else ""

    @model_validator(mode="before")
    @classmethod
    def coerce_age_from_date_of_birth(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        dob = out.get("date_of_birth")
        if dob and out.get("age") in (None, "", 0):
            try:
                if isinstance(dob, str):
                    dob_val = date.fromisoformat(dob)
                else:
                    dob_val = dob
                if isinstance(dob_val, date):
                    out["age"] = _age_from_dob(dob_val)
            except Exception:
                pass
        return out

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("Display name is required")
        return s[:100]

    @field_validator("photo_urls")
    @classmethod
    def normalize_photo_urls(cls, v: str) -> str:
        parts = [p.strip() for p in (v or "").split(",") if p.strip()]
        return ",".join(parts[:12])

    @model_validator(mode="before")
    @classmethod
    def coerce_preferred_age_fields(cls, data: object) -> object:
        """Coerce preferred ages to ints and validate range (18..80)."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for k in ("min_preferred_age", "max_preferred_age"):
            if k not in out:
                continue
            v = out.get(k)
            if v is None or v == "":
                out[k] = None
                continue
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be an integer") from None
            if iv < 18 or iv > 80:
                raise ValueError(f"{k} must be between 18 and 80") from None
            out[k] = iv
        mn, mx = out.get("min_preferred_age"), out.get("max_preferred_age")
        if mn is not None and mx is not None and mn > mx:
            raise ValueError("max_preferred_age must be >= min_preferred_age")
        return out


class ProfileUpdate(ProfileBase):
    pass


class ProfilePatch(BaseModel):
    """Partial profile update without requiring a full ProfileBase payload.

    NOTE: Full updates must continue to use PUT + ProfileUpdate (strict).
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=4000)
    age: int | None = Field(default=None, ge=18, le=99)
    date_of_birth: date | None = Field(default=None)
    city: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=50)
    preferred_gender: str | None = Field(default=None, max_length=32)
    interested_in: str | None = Field(default=None, max_length=50)
    relationship_goal: str | None = Field(default=None, max_length=50)
    vibe: str | None = Field(default=None, max_length=32)
    interests: str | None = Field(default=None, max_length=2000)
    lifestyle_tags: str | None = Field(default=None, max_length=2000)
    height_cm: int | None = Field(default=None, ge=120, le=230)
    job_title: str | None = Field(default=None, max_length=100)
    photo_urls: str | None = Field(default=None, max_length=8000)
    preferred_language: str | None = Field(default=None, max_length=8)
    native_language: str | None = Field(default=None, max_length=8)
    additional_languages: str | list[str] | None = Field(default=None, max_length=2000)
    min_preferred_age: int | None = Field(default=None, ge=18, le=80)
    max_preferred_age: int | None = Field(default=None, ge=18, le=80)
    onboarding_completed: bool | None = Field(default=None)

    # Onboarding-friendly aliases (frontend may send these)
    looking_for: str | None = Field(default=None, max_length=50)
    partner_age_min: int | None = Field(default=None, ge=18, le=80)
    partner_age_max: int | None = Field(default=None, ge=18, le=80)

    # Convenience aliases (frontend can send these for photo persistence)
    photo_url: str | None = Field(default=None, max_length=2000)
    primary_photo_url: str | None = Field(default=None, max_length=2000)

    @field_validator("preferred_gender", mode="before")
    @classmethod
    def validate_preferred_gender_patch(cls, v: object) -> str | None:
        if v is None:
            return None
        return _normalize_preferred_gender(str(v))

    @field_validator("interested_in", mode="before")
    @classmethod
    def validate_interested_in_patch(cls, v: object) -> str | None:
        if v is None:
            return None
        return _normalize_interested_in(str(v))

    @field_validator("relationship_goal", "looking_for", mode="before")
    @classmethod
    def validate_relationship_goal_patch(cls, v: object) -> str | None:
        if v is None:
            return None
        out = _normalize_relationship_goal(str(v))
        return out or None

    @field_validator("vibe", mode="before")
    @classmethod
    def validate_vibe_patch(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return _normalize_vibe(s) if s else None

    @field_validator("display_name")
    @classmethod
    def strip_display_name_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = (v or "").strip()
        return s[:100] if s else None

    @field_validator("preferred_language")
    @classmethod
    def strip_language(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = (v or "").strip()
        return s[:8] if s else None

    @field_validator("native_language")
    @classmethod
    def strip_native_language(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return (v or "").strip()

    @field_validator("additional_languages", mode="before")
    @classmethod
    def coerce_additional_languages(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, list):
            parts = [str(x or "").strip() for x in v]
            parts = [p for p in parts if p]
            return ",".join(parts)
        return str(v or "").strip()

    @field_validator("photo_urls")
    @classmethod
    def normalize_photo_urls_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parts = [p.strip() for p in (v or "").split(",") if p.strip()]
        return ",".join(parts[:12]) if parts else ""

    @field_validator("photo_url", "primary_photo_url")
    @classmethod
    def strip_photo_url_fields(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = (v or "").strip()
        return s if s else None

    @model_validator(mode="before")
    @classmethod
    def coerce_preferred_age_fields_patch(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        # Aliases
        if "partner_age_min" in out and "min_preferred_age" not in out:
            out["min_preferred_age"] = out.get("partner_age_min")
        if "partner_age_max" in out and "max_preferred_age" not in out:
            out["max_preferred_age"] = out.get("partner_age_max")
        if "looking_for" in out and "relationship_goal" not in out:
            out["relationship_goal"] = out.get("looking_for")
        for k in ("min_preferred_age", "max_preferred_age"):
            if k not in out:
                continue
            v = out.get(k)
            if v is None or v == "":
                out[k] = None
                continue
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be an integer") from None
            if iv < 18 or iv > 80:
                raise ValueError(f"{k} must be between 18 and 80") from None
            out[k] = iv
        mn, mx = out.get("min_preferred_age"), out.get("max_preferred_age")
        if mn is not None and mx is not None and mn > mx:
            raise ValueError("max_preferred_age must be >= min_preferred_age")
        return out

class ProfileOut(ProfileBase):
    id: int
    user_id: int
    last_active_at: datetime | None = None
    verified: bool = False
    verified_at: datetime | None = None
    onboarding_completed: bool = False
    founder_welcome_seen: bool = False
    is_demo_profile: bool = False
    demo_label: str | None = None
    demo_disclaimer: str | None = None
    verification_status: str = "none"
    verification_type: str = "manual"
    verification_level: str = "none"
    verification_badge_visible: bool = True
    is_verified: bool = False
    is_premium: bool = False
    premium_until: datetime | None = None
    demo_premium_feed_active: bool = False

    class Config:
        from_attributes = True


class PartnerProfilePublic(BaseModel):
    """Public fields only — for matched users viewing each other."""

    user_id: int
    ignored_by_me: bool = False
    display_name: str
    age: int | None = None
    city: str = ""
    bio: str = ""
    interests: list[str] = Field(default_factory=list)
    lifestyle_tags: list[str] = Field(default_factory=list)
    photo_urls: list[str] = Field(default_factory=list)
    relationship_goal: str = "relationship"
    verified: bool = False
    is_verified: bool = False
    verification_level: str = "none"
    verification_badge_visible: bool = True
    is_premium: bool = False
    premium_until: datetime | None = None
    is_demo_profile: bool = False
    demo_label: str | None = None
    demo_disclaimer: str | None = None
