from unittest.mock import MagicMock, patch

from app.repositories import WhatsappUsageRepository as repo


def test_seed_normal_tier_uses_set_on_insert_with_placeholder_values():
    col = MagicMock()
    with patch.object(repo, "_tiers", return_value=col):
        repo.seed_normal_tier()
    args, kwargs = col.update_one.call_args
    assert args[0] == {"tier_id": "normal"}
    assert kwargs["upsert"] is True
    doc = args[1]["$setOnInsert"]
    assert "$set" not in args[1]
    assert doc["name"] == "Normal"
    assert doc["solicitudes_per_window"] == 50
    assert doc["window_seconds"] == 28800
    assert doc["token_ceiling_per_window"] == 300000
    assert doc["burst_messages_per_minute"] == 30
    assert doc["warn_at_percent"] == 80
    assert doc["per_seller_cap_percent"] is None
    assert doc["enforcement"] == "shadow"
    assert doc["active"] is True


def test_get_store_tier_id_defaults_to_normal_without_row():
    store_tiers = MagicMock()
    store_tiers.find_one.return_value = None
    with patch.object(repo, "_store_tiers", return_value=store_tiers):
        assert repo.get_store_tier_id("g1") == "normal"
    assert store_tiers.find_one.call_args[0][0] == {"group_id": "g1"}


def test_get_store_tier_id_falls_back_to_normal_when_tier_inactive_or_missing():
    store_tiers = MagicMock()
    store_tiers.find_one.return_value = {"group_id": "g1", "tier_id": "pro"}
    tiers = MagicMock()
    with patch.object(repo, "_store_tiers", return_value=store_tiers), patch.object(
        repo, "_tiers", return_value=tiers
    ):
        tiers.find_one.return_value = {"tier_id": "pro", "active": False}
        assert repo.get_store_tier_id("g1") == "normal"
        tiers.find_one.return_value = None
        assert repo.get_store_tier_id("g1") == "normal"
        tiers.find_one.return_value = {"tier_id": "pro", "active": True}
        assert repo.get_store_tier_id("g1") == "pro"


def test_get_settings_merges_defaults():
    col = MagicMock()
    col.find_one.return_value = {"_id": "global", "shadow_all": False, "meter_errors": 3}
    with patch.object(repo, "_settings", return_value=col):
        s = repo.get_settings()
    assert s["shadow_all"] is False
    assert s["enforcement_enabled"] is True
    assert s["price_per_1k_prompt_tokens"] == 0.0
    assert s["price_per_1k_completion_tokens"] == 0.0
    assert s["error_alert_threshold"] == 5
    assert s["notice_cooldown_seconds"] == 1800
    assert s["meter_errors"] == 3
    assert "_id" not in s


def test_get_settings_without_doc_returns_defaults():
    col = MagicMock()
    col.find_one.return_value = None
    with patch.object(repo, "_settings", return_value=col):
        s = repo.get_settings()
    assert s["enforcement_enabled"] is True
    assert s["shadow_all"] is True


def test_write_audit_stores_before_and_after():
    col = MagicMock()
    with patch.object(repo, "_audit", return_value=col):
        repo.write_audit("u1", "tier.update", "pro", {"a": 1}, {"a": 2}, reason="why")
    doc = col.insert_one.call_args[0][0]
    assert doc["actor_uid"] == "u1"
    assert doc["action"] == "tier.update"
    assert doc["target"] == "pro"
    assert doc["before"] == {"a": 1}
    assert doc["after"] == {"a": 2}
    assert doc["reason"] == "why"
    assert doc["at"] is not None


def test_count_stores_on_tier_normal_includes_stores_without_row():
    store_tiers = MagicMock()
    groups = MagicMock()
    groups.count_documents.return_value = 10
    store_tiers.count_documents.side_effect = [4]  # rows on other tiers
    with patch.object(repo, "_store_tiers", return_value=store_tiers), patch.object(
        repo, "_groups", return_value=groups
    ):
        assert repo.count_stores_on_tier("normal") == 6
    assert store_tiers.count_documents.call_args[0][0] == {"tier_id": {"$ne": "normal"}}


def test_count_stores_on_tier_other_counts_rows():
    store_tiers = MagicMock()
    store_tiers.count_documents.return_value = 3
    with patch.object(repo, "_store_tiers", return_value=store_tiers):
        assert repo.count_stores_on_tier("pro") == 3
    assert store_tiers.count_documents.call_args[0][0] == {"tier_id": "pro"}


def test_assign_store_tier_upserts_and_audit_fields():
    col = MagicMock()
    col.find_one.return_value = {"group_id": "g1", "tier_id": "pro"}
    with patch.object(repo, "_store_tiers", return_value=col):
        out = repo.assign_store_tier("g1", "pro", "admin")
    args, kwargs = col.update_one.call_args
    assert args[0] == {"group_id": "g1"}
    assert args[1]["$set"]["tier_id"] == "pro"
    assert args[1]["$set"]["assigned_by"] == "admin"
    assert kwargs["upsert"] is True
    assert out == {"group_id": "g1", "tier_id": "pro"}


def test_incr_meter_errors_returns_new_count():
    col = MagicMock()
    col.find_one_and_update.return_value = {"meter_errors": 7}
    with patch.object(repo, "_settings", return_value=col):
        assert repo.incr_meter_errors() == 7
    assert col.find_one_and_update.call_args[0][1] == {"$inc": {"meter_errors": 1}}


def test_update_tier_returns_none_when_missing():
    col = MagicMock()
    col.find_one_and_update.return_value = None
    with patch.object(repo, "_tiers", return_value=col):
        assert repo.update_tier("nope", {"name": "x"}) is None


def test_list_audit_paginates_newest_first():
    col = MagicMock()
    col.count_documents.return_value = 25
    cursor = MagicMock()
    cursor.sort.return_value.skip.return_value.limit.return_value = [{"action": "a"}]
    col.find.return_value = cursor
    with patch.object(repo, "_audit", return_value=col):
        out = repo.list_audit(2, 10)
    cursor.sort.assert_called_once_with("at", -1)
    cursor.sort.return_value.skip.assert_called_once_with(10)
    cursor.sort.return_value.skip.return_value.limit.assert_called_once_with(10)
    assert out == {"items": [{"action": "a"}], "total": 25, "page": 2, "page_size": 10}
