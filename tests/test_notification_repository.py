import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.modules.setdefault("app.config.database", MagicMock())

from app.repositories.NotificationRepository import _serialize


def test_serialize_treats_naive_created_at_as_utc():
    created_at = datetime(2026, 9, 4, 17, 55, 0)
    expected_ms = int(datetime(2026, 9, 4, 17, 55, 0, tzinfo=timezone.utc).timestamp() * 1000)

    serialized = _serialize({"_id": "abc123", "createdAt": created_at, "message": "hello"})

    assert serialized is not None
    assert serialized["timestamp"] == expected_ms


def test_serialize_preserves_aware_created_at():
    created_at = datetime(2026, 9, 4, 17, 55, 0, tzinfo=timezone.utc)
    expected_ms = int(created_at.timestamp() * 1000)

    serialized = _serialize({"createdAt": created_at})

    assert serialized is not None
    assert serialized["timestamp"] == expected_ms
