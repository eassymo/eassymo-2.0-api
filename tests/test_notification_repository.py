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


from unittest.mock import MagicMock, patch

from app.repositories import NotificationRepository as repo


def _fake_db():
    coll = MagicMock()
    return MagicMock(__getitem__=lambda self, name: coll), coll


def test_resolve_by_decision_key_only_touches_open_docs():
    fake, coll = _fake_db()
    coll.update_many.return_value.modified_count = 2
    with patch.object(repo, "db", fake):
        assert repo.resolve_by_decision_key("order:o1:confirm", 123) == 2
    query, update = coll.update_many.call_args.args
    assert query == {"decision_key": "order:o1:confirm", "resolved_at": None}
    assert update["$set"]["resolved_at"] == 123


def test_summary_for_user_counts_by_side_and_open_decisions():
    fake, coll = _fake_db()
    answers = {"buy": 3, "sell": 1, "total": 101, "decisions": 2}

    def count(query):
        assert query["owner"] == "u1" and query["ownerGroup"] == "g1"
        if "decision_key" in query:
            assert query["resolved_at"] is None
            return answers["decisions"]
        assert query["read"] is False
        return answers.get(query.get("side"), answers["total"]) if query.get("side") else answers["total"]

    coll.count_documents.side_effect = count
    with patch.object(repo, "db", fake):
        summary = repo.summary_for_user("u1", "g1")
    assert summary == {"unread_buy": 3, "unread_sell": 1, "unread_total": 101, "decisions_open": 2}


def test_mark_read_resolves_opened_is_resolved_types():
    fake, coll = _fake_db()
    coll.update_one.return_value.modified_count = 1
    oid = "64b7f0f0f0f0f0f0f0f0f0f0"
    with patch.object(repo, "db", fake):
        assert repo.mark_read(oid, "u1") is True
    assert coll.update_one.call_count == 2
    resolve_query, resolve_update = coll.update_one.call_args_list[1].args
    assert resolve_query["owner"] == "u1" and resolve_query["resolved_at"] is None
    assert "resolved_at" in resolve_update["$set"]
    types = [c for c in resolve_query["$or"]]
    assert {"type": {"$in": ["MOSTRADOR_FOLIO_SHARED", "MOSTRADOR_FOLIO_ASSIGNED"]}} in types
    assert {"type": "DELIVERY_HANDED_OFF", "decision_key": {"$ne": None}} in types
