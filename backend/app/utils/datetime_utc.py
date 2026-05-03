"""Normalize datetimes for safe comparison with UTC-aware 'now'."""

from __future__ import annotations

from datetime import UTC, datetime


def to_utc_aware(dt: datetime | None) -> datetime | None:
    """
    If dt is None -> None.
    If naive -> treat as UTC (common for SQLite / legacy rows).
    If aware -> convert to UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
