from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    referral_code: str | None = Field(default=None, max_length=32)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, v: str) -> str:
        s = (v or "").strip()
        if len(s) < 1:
            raise ValueError("Display name is required")
        if len(s) > 100:
            s = s[:100]
        return s

    @field_validator("password")
    @classmethod
    def password_not_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Password is required")
        return v

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # If true, the account is soft-deleted; client should route to restore screen.
    is_deleted: bool = False
    deleted_at: str | None = None
    deletion_scheduled_for: str | None = None


class AuthMeResponse(BaseModel):
    user_id: int
    email: EmailStr
    display_name: str
    email_verified: bool
    onboarding_completed: bool = False
    is_admin: bool
    is_premium: bool
    premium_until: str | None = None
    is_trial_used: bool
    trial_started_at: str | None = None
    trial_days_left: int | None = None
    verified: bool
    avatar_url: str
    social_provider: str | None = None
    social_provider_id: str | None = None
    onboarding_required: bool
    founder_welcome_seen: bool
    founder_welcome_required: bool
    is_deleted: bool
    deleted_at: str | None = None
    deletion_scheduled_for: str | None = None
