from unittest.mock import MagicMock, patch

from app.repositories import SellerReachRepository as repo

DAY = "2026-11-25"


def test_get_settings_merges_defaults():
    col = MagicMock()
    col.find_one.return_value = None
    with patch.object(repo, "_settings", return_value=col):
        out = repo.get_settings()
    assert out == {"wide_threshold": 50, "wide_per_day": 2, "capped_max": 20, "enforcement": "shadow"}


def test_get_settings_stored_values_win_and_id_is_dropped():
    col = MagicMock()
    col.find_one.return_value = {"_id": "global", "capped_max": 15, "updated_at": "x"}
    with patch.object(repo, "_settings", return_value=col):
        out = repo.get_settings()
    assert out["capped_max"] == 15 and out["wide_per_day"] == 2 and "_id" not in out


def test_try_reserve_wide_filter_is_atomic():
    col = MagicMock()
    col.find_one_and_update.return_value = {"group_id": "g1"}
    with patch.object(repo, "_usage", return_value=col):
        assert repo.try_reserve_wide("g1", DAY, "r1", 2) == "reserved"
    upsert_call = col.update_one.call_args
    assert upsert_call[0][0] == {"group_id": "g1", "day": DAY}
    assert "$setOnInsert" in upsert_call[0][1]
    assert upsert_call[1] == {"upsert": True}
    flt, update = col.find_one_and_update.call_args[0]
    assert flt == {"group_id": "g1", "day": DAY, "wide_request_ids": {"$ne": "r1"}, "wide_used": {"$lt": 2}}
    assert update == {"$inc": {"wide_used": 1}, "$push": {"wide_request_ids": "r1"}}


def test_try_reserve_wide_classifies_miss():
    col = MagicMock()
    col.find_one_and_update.return_value = None
    with patch.object(repo, "_usage", return_value=col):
        col.find_one.return_value = {"wide_used": 1, "wide_request_ids": ["r1"]}
        assert repo.try_reserve_wide("g1", DAY, "r1", 2) == "already_reserved"
        col.find_one.return_value = {"wide_used": 2, "wide_request_ids": ["a", "b"]}
        assert repo.try_reserve_wide("g1", DAY, "r1", 2) == "exhausted"


def test_release_wide_only_decrements_when_present():
    col = MagicMock()
    with patch.object(repo, "_usage", return_value=col):
        repo.release_wide("g1", DAY, "r1")
    flt, update = col.update_one.call_args[0]
    assert flt == {"group_id": "g1", "day": DAY, "wide_request_ids": "r1"}
    assert update == {"$inc": {"wide_used": -1}, "$pull": {"wide_request_ids": "r1"}}


def test_get_usage_default_when_missing():
    col = MagicMock()
    col.find_one.return_value = None
    with patch.object(repo, "_usage", return_value=col):
        assert repo.get_usage("g1", DAY) == {"wide_used": 0, "wide_request_ids": []}


def test_set_override_writes_settings_changed_event():
    overrides, events = MagicMock(), MagicMock()
    overrides.find_one.return_value = {"_id": "x", "group_id": "g1", "capped_max": 10}
    with patch.object(repo, "_overrides", return_value=overrides), patch.object(repo, "_events", return_value=events):
        out = repo.set_override("g1", {"capped_max": 10}, "admin1")
    assert out == {"group_id": "g1", "capped_max": 10}
    ev = events.insert_one.call_args[0][0]
    assert ev["kind"] == "settings_changed" and ev["group_id"] == "g1" and ev["actor_uid"] == "admin1"
    assert ev["created_at"].tzinfo is not None


def test_clear_override_deletes_and_audits():
    overrides, events = MagicMock(), MagicMock()
    with patch.object(repo, "_overrides", return_value=overrides), patch.object(repo, "_events", return_value=events):
        repo.clear_override("g1", "admin1")
    overrides.delete_one.assert_called_once_with({"group_id": "g1"})
    assert events.insert_one.call_args[0][0]["kind"] == "settings_changed"


def test_update_settings_audits_global():
    settings, events = MagicMock(), MagicMock()
    settings.find_one.return_value = {"_id": "global", "capped_max": 25}
    with patch.object(repo, "_settings", return_value=settings), patch.object(repo, "_events", return_value=events):
        out = repo.update_settings({"capped_max": 25}, "admin1")
    assert out["capped_max"] == 25
    assert events.insert_one.call_args[0][0]["actor_uid"] == "admin1"


def test_write_event_rejects_unknown_kind():
    import pytest

    with pytest.raises(ValueError):
        repo.write_event("nope", "g1")


def test_list_events_newest_first_with_paging():
    col = MagicMock()
    col.count_documents.return_value = 7
    cursor = col.find.return_value.sort.return_value.skip.return_value.limit.return_value
    cursor.__iter__.return_value = iter([{"kind": "capped"}])
    with patch.object(repo, "_events", return_value=col):
        out = repo.list_events(2, 3, group_id="g1")
    col.count_documents.assert_called_once_with({"group_id": "g1"})
    col.find.assert_called_once_with({"group_id": "g1"}, {"_id": 0})
    col.find.return_value.sort.assert_called_once_with("created_at", -1)
    col.find.return_value.sort.return_value.skip.assert_called_once_with(3)
    assert out == {"items": [{"kind": "capped"}], "total": 7, "page": 2, "page_size": 3}
