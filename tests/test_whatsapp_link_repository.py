from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.repositories import WhatsappLinkRepository as repo
from app.utils.phone_normalize import canonical_pos_phone

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def test_canonical_pos_phone_ten_digits():
    assert canonical_pos_phone("777 931 3704") == "+5217779313704"


def test_canonical_pos_phone_52_prefixed():
    assert canonical_pos_phone("527779313704") == "+5217779313704"


def test_canonical_pos_phone_already_canonical():
    assert canonical_pos_phone("+5217779313704") == "+5217779313704"


def test_canonical_pos_phone_too_short():
    with pytest.raises(ValueError, match="Ingresa un WhatsApp válido de 10 dígitos."):
        canonical_pos_phone("12345")


def test_find_any_by_phone_uses_variants():
    col = MagicMock()
    col.find.return_value = [{"uid": "u"}]
    with patch.object(repo, "_col", return_value=col):
        assert repo.find_any_by_phone("7779313704") == [{"uid": "u"}]
    flt = col.find.call_args[0][0]
    assert "+5217779313704" in flt["phone"]["$in"]
    assert "+527779313704" in flt["phone"]["$in"]


def test_find_and_list_by_uid():
    col = MagicMock()
    col.find_one.return_value = {"uid": "u"}
    col.find.return_value = [{"uid": "u"}]
    with patch.object(repo, "_col", return_value=col):
        assert repo.find("u", "g") == {"uid": "u"}
        assert repo.list_by_uid("u") == [{"uid": "u"}]
    assert col.find_one.call_args[0][0] == {"uid": "u", "group_id": "g"}
    assert col.find.call_args[0][0] == {"uid": "u"}


def test_upsert_status_only_on_insert():
    col = MagicMock()
    with patch.object(repo, "_col", return_value=col):
        repo.upsert("u", "g", "+5217779313704", NOW)
    col.update_one.assert_called_once()
    args, kwargs = col.update_one.call_args
    assert args[0] == {"uid": "u", "group_id": "g"}
    assert kwargs["upsert"] is True
    update = args[1]
    assert "status" not in update["$set"]
    assert update["$set"]["phone"] == "+5217779313704"
    assert update["$set"]["verified_at"] == NOW
    assert "updated_at" in update["$set"]
    assert update["$setOnInsert"]["status"] == "active"
    assert "created_at" in update["$setOnInsert"]


@pytest.mark.parametrize("upserted,expected", [("id1", True), (None, False)])
def test_insert_if_absent(upserted, expected):
    col = MagicMock()
    col.update_one.return_value = MagicMock(upserted_id=upserted)
    with patch.object(repo, "_col", return_value=col):
        assert repo.insert_if_absent("u", "g", "+5217779313704", NOW) is expected
    args, kwargs = col.update_one.call_args
    assert set(args[1]) == {"$setOnInsert"}
    assert kwargs["upsert"] is True


def test_set_status_disabled_sets_actor():
    col = MagicMock()
    col.update_one.return_value = MagicMock(matched_count=1)
    with patch.object(repo, "_col", return_value=col):
        assert repo.set_status("u", "g", "disabled", "owner") is True
    args, _ = col.update_one.call_args
    assert args[0] == {"uid": "u", "group_id": "g"}
    assert args[1]["$set"]["status"] == "disabled"
    assert args[1]["$set"]["disabled_by"] == "owner"
    assert "disabled_at" in args[1]["$set"]


def test_set_status_active_clears_and_reports_no_match():
    col = MagicMock()
    col.update_one.return_value = MagicMock(matched_count=0)
    with patch.object(repo, "_col", return_value=col):
        assert repo.set_status("u", "g", "active", None) is False
    update = col.update_one.call_args[0][1]
    assert update["$set"]["status"] == "active"
    assert update["$set"]["disabled_by"] is None
    assert update["$set"]["disabled_at"] is None
