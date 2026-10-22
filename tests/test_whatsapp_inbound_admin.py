"""Unit tests for super-admin WhatsApp inbound monitor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.repositories import WhatsappInboundRepository as repo
from app.services.AdminWhatsappInboundService import AdminWhatsappInboundService


def _sample_doc(**overrides):
    oid = overrides.pop("_id", ObjectId())
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
    doc = {
        "_id": oid,
        "message_sid": "SM123",
        "from_number": "7772354004",
        "to_number": "14155238886",
        "body": "Jetta 2015 balatas delanteras",
        "profile_name": "Ian",
        "extraction_status": "failed",
        "extraction_error": "GLM timeout",
        "processing_status": "received",
        "created_at": now,
        "updated_at": now,
    }
    doc.update(overrides)
    return doc


class TestWhatsappInboundRepository:
    def test_list_messages_pagination_newest_first(self, monkeypatch):
        docs = [_sample_doc(), _sample_doc(message_sid="SM456")]
        col = MagicMock()
        col.count_documents.return_value = 2
        col.find.return_value.sort.return_value.skip.return_value.limit.return_value = docs
        monkeypatch.setattr(repo, "_col", lambda: col)

        result = repo.list_messages(page=1, page_size=20)

        assert result["total"] == 2
        assert result["total_pages"] == 1
        assert len(result["items"]) == 2
        assert isinstance(result["items"][0]["_id"], str)
        assert result["items"][0]["created_at"].endswith("+00:00")
        col.find.assert_called_once_with({})
        col.find.return_value.sort.assert_called_once_with("created_at", -1)

    def test_list_messages_filters(self, monkeypatch):
        col = MagicMock()
        col.count_documents.return_value = 0
        col.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
        monkeypatch.setattr(repo, "_col", lambda: col)

        repo.list_messages(
            page=1,
            page_size=10,
            from_number="7772354004",
            extraction_status="failed",
        )

        col.find.assert_called_once_with(
            {"from_number": "7772354004", "extraction_status": "failed"}
        )

    def test_find_by_id_returns_serialized_doc(self, monkeypatch):
        doc = _sample_doc()
        col = MagicMock()
        col.find_one.return_value = doc
        monkeypatch.setattr(repo, "_col", lambda: col)

        result = repo.find_by_id(str(doc["_id"]))

        assert result is not None
        assert result["_id"] == str(doc["_id"])
        assert result["body"] == doc["body"]
        assert result["extraction_error"] == "GLM timeout"

    def test_find_by_id_missing_returns_none(self, monkeypatch):
        col = MagicMock()
        col.find_one.return_value = None
        monkeypatch.setattr(repo, "_col", lambda: col)

        assert repo.find_by_id(str(ObjectId())) is None
        assert repo.find_by_id("not-an-object-id") is None


class TestAdminWhatsappInboundService:
    def test_get_message_not_found(self, monkeypatch):
        monkeypatch.setattr(repo, "find_by_id", lambda _id: None)
        with pytest.raises(HTTPException) as exc:
            AdminWhatsappInboundService.get_message(str(ObjectId()))
        assert exc.value.status_code == 404

    def test_get_message_returns_body_and_error(self, monkeypatch):
        payload = {
            "_id": str(ObjectId()),
            "body": "hello",
            "extraction_error": "bad json",
        }
        monkeypatch.setattr(repo, "find_by_id", lambda _id: payload)
        result = AdminWhatsappInboundService.get_message(payload["_id"])
        assert result["body"] == "hello"
        assert result["extraction_error"] == "bad json"
