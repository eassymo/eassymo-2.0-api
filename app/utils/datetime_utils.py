"""UTC datetime helpers for Mongo-backed values and API serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_timestamp_ms(value: datetime) -> int:
    return int(ensure_utc(value).timestamp() * 1000)


def serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    """Serialize a UTC instant for JSON (always includes ``Z`` suffix)."""
    if value is None:
        return None
    normalized = ensure_utc(value)
    text = normalized.isoformat(timespec="milliseconds")
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text
