import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException

from app.routers import ChatRouter as router_module


def _app():
    app = FastAPI()
    app.include_router(router_module.chatRouter)
    return app


def _get(path: str, query: str = "", group: str = "g1"):
    captured = {"body": b""}
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    headers = [(b"groupselected", group.encode())] if group else []
    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    asyncio.run(_app()(scope, receive, send))
    return captured["status"], json.loads(captured["body"] or b"{}")


@pytest.fixture
def mocks():
    with patch.object(router_module, "require_authenticated_uid", return_value="u1") as auth, \
         patch.object(router_module, "assert_group_membership") as member, \
         patch.object(router_module, "conversationService") as svc:
        svc.list_conversations.return_value = {"items": [], "next_cursor": None, "unread_conversations": 0}
        svc.unread_summary.return_value = {"unread_conversations": 3}
        yield {"auth": auth, "member": member, "svc": svc}


def test_conversations_returns_service_output_under_body(mocks):
    code, payload = _get("/chat/conversations", "filter=unread&q=balata&cursor=20&limit=10")
    assert code == 200
    assert payload["body"] == {"items": [], "next_cursor": None, "unread_conversations": 0}
    mocks["svc"].list_conversations.assert_called_once_with(
        "g1", "u1", filter="unread", q="balata", cursor="20", limit=10
    )
    mocks["member"].assert_called_once_with("u1", "g1")


def test_conversations_membership_failure_is_403(mocks):
    mocks["member"].side_effect = HTTPException(status_code=403, detail="no")
    code, _ = _get("/chat/conversations")
    assert code == 403
    mocks["svc"].list_conversations.assert_not_called()


@pytest.mark.parametrize("raw, expected", [("0", 1), ("500", 50), ("7", 7)])
def test_conversations_limit_is_clamped(mocks, raw, expected):
    _get("/chat/conversations", f"limit={raw}")
    assert mocks["svc"].list_conversations.call_args.kwargs["limit"] == expected


def test_conversations_invalid_filter_is_400(mocks):
    code, _ = _get("/chat/conversations", "filter=everything")
    assert code == 400
    mocks["svc"].list_conversations.assert_not_called()


def test_unread_summary(mocks):
    code, payload = _get("/chat/unread-summary")
    assert code == 200
    assert payload["body"] == {"unread_conversations": 3}
    mocks["svc"].unread_summary.assert_called_once_with("g1", "u1")
