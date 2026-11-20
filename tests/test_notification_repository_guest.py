"""Guest feed storage: a guest token only ever sees and touches its own notifications."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId

from app.repositories import NotificationRepository as repo


def _matches(doc, query):
    for key, cond in query.items():
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$exists" in cond and (key in doc) != cond["$exists"]:
                return False
        elif value != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction):
        self.docs = sorted(self.docs, key=lambda d: d[key], reverse=direction < 0)
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter(self.docs)


class _FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query)])

    def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    def update_many(self, query, update):
        hit = [d for d in self.docs if _matches(d, query)]
        for d in hit:
            d.update(update["$set"])
        return SimpleNamespace(modified_count=len(hit))


T0 = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def _doc(token, minutes, read=False, owner=""):
    return {
        "_id": ObjectId(),
        "type": "DELIVERY_ASSIGNED",
        "message": "m",
        "owner": owner,
        "ownerGroup": "",
        "guest_token": token,
        "read": read,
        "createdAt": T0 + timedelta(minutes=minutes),
    }


@pytest.fixture
def docs():
    return [
        _doc("tok-a", 1),
        _doc("tok-a", 3),
        _doc("tok-a", 2, read=True),
        _doc("tok-b", 4),
        {**_doc(None, 5, owner="uid-1"), "ownerGroup": "g1"},
    ]


@pytest.fixture
def fake_db(docs):
    with patch.object(repo, "db", {repo.COLLECTION: _FakeCollection(docs)}):
        yield


def test_returns_only_that_tokens_notifications_newest_first(fake_db, docs):
    items = repo.find_for_guest("tok-a", 0, 50)
    assert [i["id"] for i in items] == [str(docs[1]["_id"]), str(docs[2]["_id"]), str(docs[0]["_id"])]
    assert all(i["guest_token"] == "tok-a" for i in items)
    assert items[0]["timestamp"] is not None


def test_unread_count_ignores_read_ones(fake_db):
    assert repo.count_unread_for_guest("tok-a") == 2


def test_mark_read_with_ids_touches_only_those(fake_db, docs):
    assert repo.mark_read_for_guest("tok-a", [str(docs[0]["_id"])]) == 1
    assert docs[0]["read"] is True
    assert docs[1]["read"] is False


def test_mark_read_with_no_ids_marks_all_of_that_token(fake_db, docs):
    assert repo.mark_read_for_guest("tok-a", None) == 2
    assert docs[3]["read"] is False


def test_another_tokens_ids_are_not_touched(fake_db, docs):
    assert repo.mark_read_for_guest("tok-a", [str(docs[3]["_id"]), "not-an-id"]) == 0
    assert docs[3]["read"] is False


@pytest.mark.parametrize("token", ["", None])
def test_empty_token_never_matches(fake_db, token):
    assert repo.find_for_guest(token, 0, 50) == []
    assert repo.count_unread_for_guest(token) == 0
    assert repo.mark_read_for_guest(token, None) == 0


def test_guest_token_survives_notification_service_document():
    from app.services import NotificationService

    doc = NotificationService._to_document({"type": "DELIVERY_ASSIGNED", "message": "m", "guest_token": "tok-a"})
    assert doc["guest_token"] == "tok-a"
    assert doc["owner"] == ""


def test_account_notification_document_has_no_guest_token_key():
    from app.services import NotificationService

    doc = NotificationService._to_document({"type": "ORDER_SENT", "message": "m", "owner": "u1"})
    assert "guest_token" not in doc
