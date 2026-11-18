"""Admin endpoints return raw Mongo documents; dates and ObjectIds must not turn into a 500."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from app.routers import AdminRouter


def _request():
    return SimpleNamespace(state=SimpleNamespace(user={"uid": "admin"}))


def test_update_user_role_with_datetime_created_at_returns_200():
    doc = {"_id": "6afc85637e8caf898f07aa90", "user_uid": "u", "group": "g", "role": 215, "active": True,
           "created_at": datetime(2026, 11, 17, 16, 48, 35, tzinfo=timezone.utc)}
    with patch.object(AdminRouter.AdminWriteService, "update_user_role", return_value=doc):
        resp = AdminRouter.update_user_role(_request(), "6afc85637e8caf898f07aa90", {"active": True})
    assert resp.status_code == 200
    body = json.loads(resp.body)["body"]
    assert body["created_at"] == "2026-11-17T16:48:35+00:00"


def test_ok_serializes_nested_object_ids_and_dates():
    oid = ObjectId()
    resp = AdminRouter._ok({"items": [{"_id": oid, "at": datetime(2026, 1, 2)}]})
    assert json.loads(resp.body)["body"] == {"items": [{"_id": str(oid), "at": "2026-01-02T00:00:00"}]}


def test_unexpected_errors_are_logged_with_traceback(caplog):
    import logging
    from app.routers import AdminRouter

    try:
        raise ValueError("boom")
    except ValueError as exc:
        with caplog.at_level(logging.ERROR):
            resp = AdminRouter._err(exc)
    assert resp.status_code == 500
    assert any(r.exc_info and "boom" in r.getMessage() + str(r.exc_info[1]) for r in caplog.records)
