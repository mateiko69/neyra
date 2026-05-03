"""
Exclude admin / QA / internal test profiles from real Discover (not end-user matches).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.profile import Profile
    from app.models.user import User

_QA_NAME_PREFIX = re.compile(r"(?i)^qa[\s_]")
_INTERNAL_NAME_PATTERN = re.compile(
    r"(?i)(localeprobe|\bdbg\b|disposable|internal\s*test|@\s*qa\b)"
)


def internal_test_discover_match(*, user: User | None, profile: Profile | None) -> bool:
    """
    True → hide from real Discover for normal viewers (still allow explicit demo/dev tooling elsewhere).
    """
    if not user:
        return False
    try:
        admin_emails = set(settings.admin_emails_list())
        raw_email = str(getattr(user, "email", "") or "").strip()
        if admin_emails and raw_email in admin_emails:
            return True
    except Exception:
        pass
    if bool(getattr(user, "is_admin", False)):
        return True
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role in {"admin", "superadmin"}:
        return True
    if bool(getattr(profile, "is_admin", False)):
        return True
    pr_role = str(getattr(profile, "role", "") or "").strip().lower()
    if pr_role in {"admin", "superadmin"}:
        return True

    em = str(getattr(user, "email", "") or "").strip().lower()
    local = em.split("@", 1)[0] if "@" in em else em

    email_needles = (
        "localeprobe",
        "disposable",
        "+qa",
        "@test.",
        ".test@",
        "probe@",
        "@qa.",
        "dbg@",
        "@dbg.",
        "mailinator",
        "guerrillamail",
        "tempmail",
    )
    if any(n in em for n in email_needles):
        return True
    if local.startswith("qa_") or local.startswith("test_") or local in {"test", "admin", "qa", "dbg"}:
        return True
    if em.startswith("qa.") or ".qa@" in em:
        return True

    nm = str(getattr(profile, "display_name", "") or "").strip()
    nml = nm.lower()
    if nm.strip().lower() == "admin":
        return True
    if _QA_NAME_PREFIX.match(nm.strip()):
        return True
    if _INTERNAL_NAME_PATTERN.search(nm):
        return True
    if "localeprobe" in nml or "disposable" in nml:
        return True
    return False


def internal_test_discover_match_loose(*, email: str | None, display_name: str | None) -> bool:
    """Same rules when only email + display_name are known (e.g. cached discover cards)."""
    em = str(email or "").strip()
    nm = str(display_name or "").strip()
    if em:

        class _U:
            pass

        class _P:
            pass

        u = _U()
        p = _P()
        u.email = em
        u.is_admin = False
        u.role = ""
        p.display_name = nm
        p.is_admin = False
        p.role = ""
        return internal_test_discover_match(user=u, profile=p)  # type: ignore[arg-type]
    if not nm:
        return False
    if nm.strip().lower() == "admin":
        return True
    if _QA_NAME_PREFIX.match(nm.strip()):
        return True
    if _INTERNAL_NAME_PATTERN.search(nm):
        return True
    if "localeprobe" in nm.lower() or "disposable" in nm.lower():
        return True
    return False
