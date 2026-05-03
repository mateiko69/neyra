from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from datetime import date, datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str] = mapped_column(Text, default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    city: Mapped[str] = mapped_column(String(100), default="")
    gender: Mapped[str] = mapped_column(String(50), default="")
    # Discover deck: "", male, female, everyone — overrides hetero default when set.
    preferred_gender: Mapped[str] = mapped_column(String(32), default="")
    interested_in: Mapped[str] = mapped_column(String(50), default="")
    relationship_goal: Mapped[str] = mapped_column(String(50), default="relationship")
    vibe: Mapped[str] = mapped_column(String(32), default="")
    interests: Mapped[str] = mapped_column(Text, default="")
    lifestyle_tags: Mapped[str] = mapped_column(Text, default="")
    # Optional personal details (v2).
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_title: Mapped[str] = mapped_column(String(100), default="")
    photo_urls: Mapped[str] = mapped_column(Text, default="")
    # Internal-only visual embedding (comma-separated floats).
    visual_embedding: Mapped[str] = mapped_column(Text, default="")
    # Verification state (optional, lightweight).
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Internal-only embedding from selfie verification capture.
    verification_embedding: Mapped[str] = mapped_column(Text, default="")
    # Verification state machine (v1).
    verification_type: Mapped[str] = mapped_column(String(16), default="manual")  # manual|selfie
    # none | pending | verified (legacy DB may still contain approved until migration)
    verification_status: Mapped[str] = mapped_column(String(16), default="none")
    # none | photo | id
    verification_level: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    verification_badge_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verification_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Selfie reference (stored separately from profile gallery).
    verification_selfie_url: Mapped[str] = mapped_column(Text, default="")
    # User language preference (optional).
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    # Onboarding language fields (v1).
    # Stored as short locale codes: "en", "uk", "ru", etc.
    native_language: Mapped[str] = mapped_column(String(8), default="")
    # Comma-separated list of additional locale codes.
    additional_languages: Mapped[str] = mapped_column(Text, default="")
    # Normalized location fields (v1, optional; keeps existing `city` as primary UI field for now).
    city_original: Mapped[str] = mapped_column(String(100), default="")
    city_en: Mapped[str] = mapped_column(String(100), default="")
    city_local: Mapped[str] = mapped_column(String(100), default="")
    city_locative_uk: Mapped[str] = mapped_column(String(100), default="")
    country_code: Mapped[str] = mapped_column(String(2), default="")
    region: Mapped[str] = mapped_column(String(64), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    min_preferred_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_preferred_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sticky onboarding flag: once a user completes onboarding, we should not send them back
    # unless they explicitly reset their profile.
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    founder_welcome_seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo_profile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    demo_disclaimer: Mapped[str] = mapped_column(Text, default="")
    # Living demo: personality + scheduled outbound simulation (demo users only).
    demo_personality_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    demo_reply_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_first_message_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_last_auto_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_pending_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    user = relationship("User", back_populates="profile")
