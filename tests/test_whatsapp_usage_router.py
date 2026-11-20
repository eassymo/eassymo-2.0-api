import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import FastAPI
from urllib.parse import urlencode

from app.authz import grant_keys as g
from app.routers import WhatsappUsageRouter as router_mod
from app.services.WhatsappUsageService import UsageSnapshot

GID = str(ObjectId())
UID = "u1"


def _snap(state="ok", used=10, limit=50, end=None):
    return UsageSnapshot(
        tier_id="normal", tier_name="Normal", used=used, limit=limit, tokens_used=0,
        token_ceiling=300000, percent=int(used * 100 / limit), window_start=None,
        window_end=end, window_seconds=28800, state=state, enforcement="enforce",
    )


class _Resp:
    def __init__(self, status_code, raw):
        self.status_code = status_code
        self._raw = raw

    def json(self):
        return json.loads(self._raw)


class _Client:
    """Minimal ASGI client (httpx, which TestClient needs, is not installed)."""

    def __init__(self, app):
        self.app = app

    def _call(self, method, path, params=None, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        sent, out = [False], {"body": b""}

        async def receive():
            if not sent[0]:
                sent[0] = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
            elif msg["type"] == "http.response.body":
                out["body"] += msg.get("body", b"")

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
            "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": urlencode(params or {}).encode(),
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())],
            "client": ("127.0.0.1", 1), "server": ("test", 80),
            "state": {"user": {"uid": UID}},
        }
        asyncio.run(self.app(scope, receive, send))
        return _Resp(out["status"], out["body"])

    def get(self, path, params=None):
        return self._call("GET", path, params)

    def post(self, path, params=None, json=None):
        return self._call("POST", path, params, json)


@pytest.fixture
def env():
    ns = SimpleNamespace()
    app = FastAPI()

    app.include_router(router_mod.whatsappUsageRouter)
    grants = {g.WHATSAPP_POS_INTAKE, g.WHATSAPP_VIEW_USAGE, g.WHATSAPP_REQUEST_CREDITS}
    with patch.object(router_mod, "authz") as az, \
         patch.object(router_mod, "usage_service") as svc, \
         patch.object(router_mod, "usage_repo") as repo, \
         patch.object(router_mod, "notifier") as notif, \
         patch.object(router_mod, "groupRepository") as grp, \
         patch.object(router_mod, "userRepository") as usr:
        az.caller_uid.return_value = UID
        az.selected_group.side_effect = lambda request, override=None: override
        az.effective_grants.side_effect = lambda uid, gid, request=None: frozenset(ns.grants)
        notif.is_manager.return_value = False
        repo.find_pending_credit_request.return_value = None
        grp.find_by_id.return_value = {"name": "Refaccionaria Sur"}
        usr.find.return_value = []
        svc.snapshot.return_value = _snap()
        ns.grants = grants
        ns.client = _Client(app)
        ns.az, ns.svc, ns.repo, ns.notif, ns.grp, ns.usr = az, svc, repo, notif, grp, usr
        yield ns


def test_usage_requires_pos_intake_grant(env):
    env.grants = {g.WHATSAPP_VIEW_USAGE}
    r = env.client.get("/whatsapp/usage", params={"group_id": GID})
    assert r.status_code == 403


def test_usage_returns_snapshot_fields(env):
    end = datetime.now(timezone.utc) + timedelta(hours=3)
    env.svc.snapshot.return_value = _snap(state="warning", used=42, end=end)
    env.notif.is_manager.return_value = True
    env.repo.find_pending_credit_request.return_value = {"created_at": datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)}
    body = env.client.get("/whatsapp/usage", params={"group_id": GID}).json()["body"]
    assert body["tier"] == {"name": "Normal", "solicitudes_per_window": 50, "window_seconds": 28800}
    assert (body["used"], body["limit"], body["percent"], body["state"]) == (42, 50, 84, "warning")
    assert body["window_end"] == end.isoformat()
    assert body["is_manager"] is True
    assert body["can_request"] is True
    assert body["pending_request_at"].startswith("2026-11-18T12:00:00")
    env.svc.snapshot.assert_called_once()
    assert env.svc.snapshot.call_args[0][0] == GID


def test_usage_shadow_returns_shadow_state(env):
    env.svc.snapshot.return_value = _snap(state="shadow")
    body = env.client.get("/whatsapp/usage", params={"group_id": GID}).json()["body"]
    assert body["state"] == "shadow"
    assert body["window_end"] is None
    assert body["pending_request_at"] is None


def test_can_request_follows_grant(env):
    env.grants = {g.WHATSAPP_POS_INTAKE}
    body = env.client.get("/whatsapp/usage", params={"group_id": GID}).json()["body"]
    assert body["can_request"] is False


def test_by_seller_requires_view_usage(env):
    env.grants = {g.WHATSAPP_POS_INTAKE}
    r = env.client.get("/whatsapp/usage/by-seller", params={"group_id": GID})
    assert r.status_code == 403


def test_by_seller_shares_and_names(env):
    env.svc.snapshot.return_value = _snap(used=10, end=datetime.now(timezone.utc) + timedelta(hours=1))
    env.repo.by_seller.return_value = [
        {"uid": "a", "solicitudes": 6, "tokens": 100},
        {"uid": "b", "solicitudes": 4, "tokens": 50},
    ]
    env.usr.find.return_value = [{"uid": "a", "name": "Ana"}]
    rows = env.client.get("/whatsapp/usage/by-seller", params={"group_id": GID}).json()["body"]
    assert rows == [
        {"uid": "a", "name": "Ana", "solicitudes": 6, "tokens": 100, "share_percent": 60},
        {"uid": "b", "name": "", "solicitudes": 4, "tokens": 50, "share_percent": 40},
    ]


def test_by_seller_empty_when_window_expired(env):
    env.svc.snapshot.return_value = _snap(used=0, end=None)
    env.repo.by_seller.return_value = [{"uid": "a", "solicitudes": 6, "tokens": 100}]
    rows = env.client.get("/whatsapp/usage/by-seller", params={"group_id": GID}).json()["body"]
    assert rows == []


def test_credit_request_requires_grant(env):
    env.grants = {g.WHATSAPP_POS_INTAKE}
    r = env.client.post("/whatsapp/usage/credit-requests", params={"group_id": GID}, json={})
    assert r.status_code == 403
    env.repo.create_credit_request.assert_not_called()


def test_credit_request_creates_and_notifies_admins(env):
    env.repo.create_credit_request.return_value = {"id": "r1", "status": "pending"}
    r = env.client.post("/whatsapp/usage/credit-requests", params={"group_id": GID}, json={"note": "más"})
    assert r.status_code == 200
    assert r.json()["body"]["id"] == "r1"
    env.repo.create_credit_request.assert_called_once_with(GID, UID, "más")
    env.notif.push_admins_credit_request.assert_called_once_with(GID, "Refaccionaria Sur", UID)


def test_duplicate_pending_credit_request_is_reused(env):
    env.repo.find_pending_credit_request.return_value = {"id": "r0", "status": "pending"}
    r = env.client.post("/whatsapp/usage/credit-requests", params={"group_id": GID}, json={})
    assert r.status_code == 200
    assert r.json()["body"]["id"] == "r0"
    env.repo.create_credit_request.assert_not_called()
    env.notif.push_admins_credit_request.assert_not_called()


def test_push_failure_does_not_fail_request(env):
    env.repo.create_credit_request.return_value = {"id": "r1"}
    env.notif.push_admins_credit_request.side_effect = RuntimeError("boom")
    r = env.client.post("/whatsapp/usage/credit-requests", params={"group_id": GID}, json={})
    assert r.status_code == 200


def test_naive_mongo_datetimes_carry_utc_offset(env):
    naive = datetime(2026, 11, 18, 18, 12, 0, 123000)  # Mongo returns naive UTC
    env.svc.snapshot.return_value = _snap(end=naive + timedelta(hours=3))
    env.repo.find_pending_credit_request.return_value = {"created_at": naive}
    body = env.client.get("/whatsapp/usage", params={"group_id": GID}).json()["body"]
    assert body["pending_request_at"] == "2026-11-18T18:12:00.123000+00:00"
    assert body["window_end"].endswith("+00:00")

    env.repo.find_pending_credit_request.return_value = None
    env.repo.create_credit_request.return_value = {"id": "r1", "created_at": naive}
    r = env.client.post("/whatsapp/usage/credit-requests", params={"group_id": GID}, json={})
    assert r.json()["body"]["created_at"].endswith("+00:00")
