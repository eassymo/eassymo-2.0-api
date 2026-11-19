from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import DuplicateKeyError

from app.repositories import WhatsappUsageRepository as repo

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
WS = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


def _reserve(col, **overrides):
    kwargs = dict(limit=5, token_ceiling=1000, seller_cap=None, window_start=WS)
    kwargs.update(overrides)
    with patch.object(repo, "_usage", return_value=col):
        return repo.try_reserve("g1", "u1", "b1", **kwargs)


def test_try_reserve_filter_requires_under_limit_and_unseen_burst():
    col = MagicMock()
    col.find_one_and_update.return_value = {"group_id": "g1"}
    assert _reserve(col) == "reserved"
    args, _ = col.find_one_and_update.call_args
    flt, update = args[0], args[1]
    assert flt == {
        "group_id": "g1",
        "window_start": WS,
        "reserved_bursts": {"$ne": "b1"},
        "solicitudes_used": {"$lt": 5},
        "tokens_used": {"$lt": 1000},
    }
    assert update["$inc"] == {"solicitudes_used": 1, "by_uid.u1": 1}
    assert update["$push"] == {"reserved_bursts": {"$each": ["b1"], "$slice": -200}}
    col.find_one.assert_not_called()


def test_try_reserve_cap_filter_matches_missing_seller_key():
    col = MagicMock()
    col.find_one_and_update.return_value = {"group_id": "g1"}
    assert _reserve(col, seller_cap=2) == "reserved"
    flt = col.find_one_and_update.call_args[0][0]
    # `$lt` would not match a missing key; `$not: {$gte}` does.
    assert flt["by_uid.u1"] == {"$not": {"$gte": 2}}


def test_try_reserve_returns_already_reserved_for_known_burst():
    col = MagicMock()
    col.find_one_and_update.return_value = None
    # Known burst wins even when the store is now at the limit.
    col.find_one.return_value = {
        "group_id": "g1",
        "window_start": WS,
        "reserved_bursts": ["b0", "b1"],
        "solicitudes_used": 5,
        "tokens_used": 2000,
        "by_uid": {"u1": 5},
    }
    assert _reserve(col, seller_cap=1) == "already_reserved"


def _blocked_doc(**fields):
    doc = {
        "group_id": "g1",
        "window_start": WS,
        "reserved_bursts": [],
        "solicitudes_used": 0,
        "tokens_used": 0,
        "by_uid": {},
    }
    doc.update(fields)
    return doc


@pytest.mark.parametrize(
    "doc,expected",
    [
        (_blocked_doc(solicitudes_used=5), "blocked_quota"),
        (_blocked_doc(solicitudes_used=7, tokens_used=1000), "blocked_quota"),
        (_blocked_doc(solicitudes_used=2, tokens_used=1000), "blocked_tokens"),
        (_blocked_doc(solicitudes_used=2, by_uid={"u1": 2}), "blocked_seller_cap"),
    ],
)
def test_try_reserve_classifies_blocked_reasons(doc, expected):
    col = MagicMock()
    col.find_one_and_update.return_value = None
    col.find_one.return_value = doc
    assert _reserve(col, seller_cap=2) == expected


def test_try_reserve_retries_into_window_reset_by_another_instance():
    col = MagicMock()
    new_ws = WS + timedelta(hours=8)
    col.find_one_and_update.side_effect = [None, {"group_id": "g1"}]
    col.find_one.return_value = _blocked_doc(window_start=new_ws)
    assert _reserve(col) == "reserved"
    assert col.find_one_and_update.call_args_list[1][0][0]["window_start"] == new_ws


def test_try_reserve_raises_when_usage_doc_missing():
    col = MagicMock()
    col.find_one_and_update.return_value = None
    col.find_one.return_value = None
    with pytest.raises(RuntimeError):
        _reserve(col)


def test_ensure_window_creates_missing_doc_with_set_on_insert():
    col = MagicMock()
    created = {"group_id": "g1", "window_start": NOW, "solicitudes_used": 0}
    col.find_one.side_effect = [None, created]
    with patch.object(repo, "_usage", return_value=col):
        doc = repo.ensure_window("g1", "normal", 28800, NOW)
    assert doc == created
    args, kwargs = col.update_one.call_args
    assert args[0] == {"group_id": "g1"}
    assert kwargs["upsert"] is True
    ins = args[1]["$setOnInsert"]
    assert ins["window_start"] == NOW
    assert ins["tier_id"] == "normal"
    assert ins["solicitudes_used"] == 0
    assert ins["tokens_used"] == 0
    assert ins["by_uid"] == {}
    assert ins["reserved_bursts"] == []


def test_ensure_window_reset_filters_on_old_window_start():
    col = MagicMock()
    old = NOW - timedelta(hours=9)
    col.find_one.return_value = {"group_id": "g1", "window_start": old, "solicitudes_used": 50}
    reset = {"group_id": "g1", "window_start": NOW, "solicitudes_used": 0}
    col.find_one_and_update.return_value = reset
    with patch.object(repo, "_usage", return_value=col):
        doc = repo.ensure_window("g1", "normal", 28800, NOW)
    assert doc == reset
    args, _ = col.find_one_and_update.call_args
    assert args[0] == {"group_id": "g1", "window_start": old}
    s = args[1]["$set"]
    assert s["window_start"] == NOW
    assert s["solicitudes_used"] == 0
    assert s["tokens_used"] == 0
    assert s["by_uid"] == {}
    assert s["reserved_bursts"] == []
    assert s["warned_window"] is None


def test_ensure_window_rereads_when_other_instance_reset_first():
    col = MagicMock()
    old = NOW - timedelta(hours=9)
    other = {"group_id": "g1", "window_start": NOW - timedelta(seconds=1), "solicitudes_used": 1}
    col.find_one.side_effect = [{"group_id": "g1", "window_start": old}, other]
    col.find_one_and_update.return_value = None
    with patch.object(repo, "_usage", return_value=col):
        assert repo.ensure_window("g1", "normal", 28800, NOW) == other


def test_ensure_window_keeps_active_window():
    col = MagicMock()
    active = {"group_id": "g1", "window_start": NOW - timedelta(hours=1), "solicitudes_used": 3}
    col.find_one.return_value = active
    with patch.object(repo, "_usage", return_value=col):
        assert repo.ensure_window("g1", "normal", 28800, NOW) == active
    col.find_one_and_update.assert_not_called()
    col.update_one.assert_not_called()


def test_refund_pulls_burst_and_decrements():
    col = MagicMock()
    with patch.object(repo, "_usage", return_value=col):
        repo.refund("g1", "u1", "b1")
    args, _ = col.update_one.call_args
    # Only refunds a burst still reserved in this window: idempotent.
    assert args[0] == {"group_id": "g1", "reserved_bursts": "b1"}
    assert args[1]["$inc"] == {"solicitudes_used": -1, "by_uid.u1": -1}
    assert args[1]["$pull"] == {"reserved_bursts": "b1"}


def test_add_tokens_increments_and_skips_zero():
    col = MagicMock()
    with patch.object(repo, "_usage", return_value=col):
        repo.add_tokens("g1", 0)
        col.update_one.assert_not_called()
        repo.add_tokens("g1", 1234)
    args, _ = col.update_one.call_args
    assert args[0] == {"group_id": "g1"}
    assert args[1] == {"$inc": {"tokens_used": 1234}}


def test_insert_event_duplicate_returns_false():
    col = MagicMock()
    event = {"event_id": "b1:0", "group_id": "g1"}
    with patch.object(repo, "_events", return_value=col):
        assert repo.insert_event(event) is True
        col.insert_one.side_effect = DuplicateKeyError("dup")
        assert repo.insert_event(event) is False
    assert "_id" not in event


def test_claim_warning_once_per_window():
    col = MagicMock()
    with patch.object(repo, "_usage", return_value=col):
        col.update_one.return_value = MagicMock(modified_count=1)
        assert repo.claim_warning("g1", WS) is True
        col.update_one.return_value = MagicMock(modified_count=0)
        assert repo.claim_warning("g1", WS) is False
    args, _ = col.update_one.call_args
    assert args[0] == {"group_id": "g1", "window_start": WS, "warned_window": {"$ne": WS}}
    assert args[1]["$set"]["warned_window"] == WS


def test_claim_notice_respects_cooldown():
    col = MagicMock()
    with patch.object(repo, "_usage", return_value=col):
        col.update_one.return_value = MagicMock(modified_count=1, upserted_id=None)
        assert repo.claim_notice("g1", "blocked_notified_at", 1800, NOW) is True
        args, kwargs = col.update_one.call_args
        assert args[0] == {
            "group_id": "g1",
            "$or": [
                {"blocked_notified_at": None},
                {"blocked_notified_at": {"$lte": NOW - timedelta(seconds=1800)}},
            ],
        }
        assert args[1] == {"$set": {"blocked_notified_at": NOW}}
        assert kwargs["upsert"] is True

        # Doc exists but cooldown not elapsed: upsert collides on unique group_id.
        col.update_one.side_effect = DuplicateKeyError("dup")
        assert repo.claim_notice("g1", "guard_notified_at", 1800, NOW) is False

        col.update_one.side_effect = None
        col.update_one.return_value = MagicMock(modified_count=0, upserted_id="new")
        assert repo.claim_notice("g1", "guard_notified_at", 1800, NOW) is True


def test_claim_notice_rejects_unknown_field():
    with pytest.raises(ValueError):
        repo.claim_notice("g1", "solicitudes_used", 1800, NOW)


def test_get_usage_strips_id():
    col = MagicMock()
    col.find_one.return_value = {"_id": "x", "group_id": "g1"}
    with patch.object(repo, "_usage", return_value=col):
        assert repo.get_usage("g1") == {"group_id": "g1"}


def test_ensure_window_handles_naive_datetimes_from_mongo():
    # The Mongo client is not tz_aware: stored datetimes come back naive (UTC).
    col = MagicMock()
    naive_active = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    col.find_one.return_value = {"group_id": "g1", "window_start": naive_active}
    with patch.object(repo, "_usage", return_value=col):
        doc = repo.ensure_window("g1", "normal", 28800, NOW)
    col.find_one_and_update.assert_not_called()
    assert doc["window_start"] == NOW - timedelta(hours=1)
    assert doc["window_start"].tzinfo is not None

    naive_old = (NOW - timedelta(hours=9)).replace(tzinfo=None)
    col.find_one.return_value = {"group_id": "g1", "window_start": naive_old}
    col.find_one_and_update.return_value = {"group_id": "g1", "window_start": NOW.replace(tzinfo=None)}
    with patch.object(repo, "_usage", return_value=col):
        doc = repo.ensure_window("g1", "normal", 28800, NOW)
    assert col.find_one_and_update.call_args[0][0]["window_start"] == naive_old
    assert doc["window_start"] == NOW
