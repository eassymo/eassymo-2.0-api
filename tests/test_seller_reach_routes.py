import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.routers import AdminSellerReachRouter as admin_mod
from app.routers import SellerReachRouter as store_mod

ADMIN = {"uid": "admin1", "super_admin": True}
GID = str(ObjectId())
OTHER = str(ObjectId())
TODAY = {"day": "2026-11-25", "wide_used": 1, "wide_per_day": 2, "wide_left": 1, "wide_threshold": 50,
         "capped_max": 20, "renews_at": "x", "enforcement": "shadow"}
SETTINGS = {"wide_threshold": 50, "wide_per_day": 2, "capped_max": 20, "enforcement": "shadow"}


class _Resp:
    def __init__(self, status_code, raw, headers):
        self.status_code = status_code
        self.raw = raw
        self.headers = headers

    @property
    def text(self):
        return self.raw.decode()

    def json(self):
        return json.loads(self.raw)


class _Client:
    """Minimal ASGI client (httpx, which TestClient needs, is not installed)."""

    def __init__(self, app, user):
        self.app, self.user = app, user

    def _call(self, method, path, params=None, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        sent, out = [False], {"body": b"", "headers": {}}

        async def receive():
            if not sent[0]:
                sent[0] = True
                return {"type": "http.request", "body": raw, "more_body": False}
            await asyncio.Event().wait()  # never disconnect (StreamingResponse listens for it)

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
                out["headers"] = {k.decode(): v.decode() for k, v in msg["headers"]}
            elif msg["type"] == "http.response.body":
                out["body"] += msg.get("body", b"")

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
            "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": urlencode(params or {}).encode(),
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())],
            "client": ("127.0.0.1", 1), "server": ("test", 80),
            "state": {"user": self.user},
        }
        asyncio.run(self.app(scope, receive, send))
        return _Resp(out["status"], out["body"], out["headers"])

    def get(self, path, params=None):
        return self._call("GET", path, params)

    def post(self, path, params=None, json=None):
        return self._call("POST", path, params, json)

    def patch(self, path, json=None):
        return self._call("PATCH", path, None, json)

    def put(self, path, json=None):
        return self._call("PUT", path, None, json)

    def delete(self, path):
        return self._call("DELETE", path)


def _doc(oid, tier=None, sellers=None):
    return {
        "_id": ObjectId(oid), "creatorGroup": GID, "creatorUser": "u1", "vehicleId": "v1",
        "subscribedSellers": sellers or [f"s{i}" for i in range(20)], "subscribedFollowers": [],
        "part": {"tipoParteDescripcion": "Balata", "amount": 2, "unitOfMeasure": "Juego"},
        "specific_order_uid": "so1", "reach": {"tier": tier} if tier else None,
    }


@pytest.fixture
def env():
    ns = SimpleNamespace()
    app = FastAPI()
    app.include_router(store_mod.sellerReachRouter)
    app.include_router(admin_mod.adminSellerReachRouter)
    members = {("u1", GID)}
    with patch.object(store_mod.group_auth, "user_belongs_to_group", side_effect=lambda u, g: (u, g) in members), \
         patch.object(store_mod, "reach") as svc, patch.object(store_mod, "partRequestRepository") as prr, \
         patch.object(store_mod, "offerRepository") as offr, patch.object(admin_mod, "repo") as repo:
        svc.today.return_value = TODAY
        svc.audience.side_effect = lambda s, f: len(set(s or []) | set(f or []))
        svc.room.return_value = 0
        svc.preview.return_value = {"today": TODAY, "parts": []}
        a, b = str(ObjectId()), str(ObjectId())
        prr.find_by_specific_order_uid.return_value = [_doc(a, "capped"), _doc(b, "wide", [f"s{i}" for i in range(60)])]
        offr.find.return_value = [{"group_id": "gA", "price": 900.0}, {"group_id": "gB", "price": 750.0}]
        repo.get_settings.return_value = dict(SETTINGS)
        repo.update_settings.side_effect = lambda f, actor: {**SETTINGS, **f}
        repo.get_override.return_value = None
        repo.set_override.side_effect = lambda gid, f, actor: {"group_id": gid, **f}
        repo.list_events.return_value = {"items": [], "total": 0, "page": 1, "page_size": 50}
        repo.list_overrides.return_value = [{"group_id": GID, "capped_max": 30}]
        ns.svc, ns.prr, ns.offr, ns.repo, ns.ids = svc, prr, offr, repo, (a, b)
        ns.user = _Client(app, {"uid": "u1"})
        ns.admin = _Client(app, ADMIN)
        ns.as_user = lambda u: _Client(app, u)
        yield ns


def test_today_requires_group_member(env):
    assert env.as_user({"uid": "outsider"}).get("/seller-reach/today", {"group_id": GID}).status_code == 403
    env.svc.today.assert_not_called()
    r = env.user.get("/seller-reach/today", {"group_id": GID})
    assert r.status_code == 200 and r.json()["body"]["wide_left"] == 1


def test_preview_requires_group_member(env):
    body = {"group_id": GID, "vehicle_id": "v", "part_list": [], "subscribed_sellers": []}
    assert env.as_user({"uid": "outsider"}).post("/seller-reach/preview", json=body).status_code == 403
    r = env.user.post("/seller-reach/preview", json=body)
    assert r.status_code == 200 and r.json()["body"]["parts"] == []


def test_requests_reach_shape(env):
    env.svc.room.side_effect = [0, None]
    r = env.user.get("/seller-reach/requests/so1")
    assert r.status_code == 200
    body = r.json()["body"]
    assert set(body) == {"today", "audience_total", "responded_total", "offers_total", "lowest_price", "parts"}
    assert body["audience_total"] == 60 and body["responded_total"] == 2
    assert body["offers_total"] == 2 and body["lowest_price"] == 750.0
    a, b = env.ids
    assert body["parts"] == [
        {"id": a, "name": "Balata", "amount": 2, "unit": "Juego", "audience": 20, "tier": "capped", "room": 0},
        {"id": b, "name": "Balata", "amount": 2, "unit": "Juego", "audience": 60, "tier": "wide", "room": None},
    ]
    env.offr.find.assert_called_once_with(
        {"request_id": {"$in": [a, b]}, "status": {"$in": ["Created", "Selected"]}}, {"group_id": 1, "price": 1}
    )


def test_requests_reach_forbidden_and_missing(env):
    assert env.as_user({"uid": "outsider"}).get("/seller-reach/requests/so1").status_code == 403
    env.prr.find_by_specific_order_uid.return_value = []
    assert env.user.get("/seller-reach/requests/none").status_code == 404


def test_admin_settings_requires_super_admin(env):
    for method, path in (("get", "/admin/seller-reach/settings"), ("put", "/admin/seller-reach/settings"),
                         ("put", f"/admin/seller-reach/stores/{GID}"), ("delete", f"/admin/seller-reach/stores/{GID}"),
                         ("get", "/admin/seller-reach/events"), ("get", "/admin/seller-reach/stores")):
        c = env.as_user({"uid": "u1"})
        r = getattr(c, method)(path, json={}) if method == "put" else getattr(c, method)(path)
        assert r.status_code == 403, path
    env.repo.update_settings.assert_not_called()
    assert env.admin.get("/admin/seller-reach/settings").json()["body"]["capped_max"] == 20


@pytest.mark.parametrize("payload", [
    {"wide_per_day": -1}, {"capped_max": 0}, {"wide_threshold": 20}, {"capped_max": 50},
    {"enforcement": "maybe"}, {"wide_threshold": 10, "capped_max": 10},
])
def test_admin_put_settings_validates(env, payload):
    r = env.admin.put("/admin/seller-reach/settings", json=payload)
    assert r.status_code == 422
    env.repo.update_settings.assert_not_called()


def test_admin_put_settings_saves_with_actor(env):
    r = env.admin.put("/admin/seller-reach/settings", json={"wide_per_day": 0, "enforcement": "enforce"})
    assert r.status_code == 200 and r.json()["body"]["enforcement"] == "enforce"
    env.repo.update_settings.assert_called_once_with({"wide_per_day": 0, "enforcement": "enforce"}, "admin1")


def test_admin_store_override_put_and_delete(env):
    assert env.admin.put(f"/admin/seller-reach/stores/{GID}", json={"capped_max": 60}).status_code == 422
    r = env.admin.put(f"/admin/seller-reach/stores/{GID}", json={"capped_max": 30})
    assert r.status_code == 200
    env.repo.set_override.assert_called_once_with(GID, {"capped_max": 30}, "admin1")
    assert env.admin.delete(f"/admin/seller-reach/stores/{GID}").status_code == 200
    env.repo.clear_override.assert_called_once_with(GID, "admin1")


def test_admin_events_paginates(env):
    assert env.admin.get("/admin/seller-reach/events", {"page": 2, "group_id": GID}).status_code == 200
    env.repo.list_events.assert_called_once_with(2, 50, GID)


def test_admin_lists_store_overrides(env):
    r = env.admin.get("/admin/seller-reach/stores")
    assert r.status_code == 200
    assert r.json()["body"] == {"items": [{"group_id": GID, "capped_max": 30}]}
    env.repo.list_overrides.assert_called_once_with()
