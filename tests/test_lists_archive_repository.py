"""ListsRepository.archive_and_delete: archive copy first, then delete by the original _id."""
import sys
from datetime import timedelta
from unittest.mock import MagicMock, patch

sys.modules.setdefault("app.config.database", MagicMock())

from bson import ObjectId

from app.repositories import ListsRepository as repo

LIST_OID = ObjectId("64b000000000000000000001")


def test_archive_and_delete_copies_then_deletes_by_original_id():
    collections = {"Lists": MagicMock(), "ListsArchive": MagicMock()}
    fake_db = MagicMock()
    fake_db.__getitem__.side_effect = collections.__getitem__
    doc = {"_id": LIST_OID, "name": "frenos", "user_uid": "u1", "group_id": "g1", "groups": ["x"]}

    with patch.object(repo.database, "db", fake_db):
        repo.archive_and_delete(doc, deleted_by="u1")

    archived = collections["ListsArchive"].insert_one.call_args.args[0]
    assert "_id" not in archived
    assert archived["original_id"] == LIST_OID
    assert archived["deleted_by"] == "u1"
    assert archived["deleted_at"].utcoffset() == timedelta(0)
    assert archived["name"] == "frenos" and archived["groups"] == ["x"]
    collections["Lists"].delete_one.assert_called_once_with({"_id": LIST_OID})
    assert "_id" in doc  # the caller's document is not mutated
