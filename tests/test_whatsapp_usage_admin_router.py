import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI

from app.routers import AdminWhatsappUsageRouter as router_mod
from app.services.WhatsappUsageService import UsageSnapshot

ADMIN = {"uid": "admin1", "super_admin": True}

TIER = {
    "name": "Pro", "solicitudes_per_window": 100, "window_seconds": 28800,
    "token_ceiling_per_window": 500000, "burst_messages_per_minute": 30, "warn_at_percent": 80,
    "per_seller_cap_percent": None, "enforcement": "enforce", "active": True,
}


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


def _snap(end=None, start=None):
    return UsageSnapshot(
        tier_id="normal", tier_name="Normal", used=3, limit=50, tokens_used=0, token_ceiling=300000,
        percent=6, window_start=start, window_end=end, window_seconds=28800, state="ok", enforcement="enforce",
    )


@pytest.fixture
def env():
    ns = SimpleNamespace()
    app = FastAPI()
    app.include_router(router_mod.adminWhatsappUsageRouter)
    with patch.object(router_mod, "usage_repo") as repo, patch.object(router_mod, "usage_service") as svc, \
         patch.object(router_mod, "notifier") as notif, patch.object(router_mod, "groupRepository") as grp:
        repo.NORMAL_TIER_ID = "normal"
        repo.get_tier.return_value = {**TIER, "tier_id": "t1"}
        repo.count_stores_on_tier.return_value = 4
        repo.update_tier.side_effect = lambda tid, f: {**f, "tier_id": tid}
        repo.get_settings.return_value = {"enforcement_enabled": True, "shadow_all": True, "meter_errors": 2}
        repo.update_settings.side_effect = lambda f: {"enforcement_enabled": True, "shadow_all": True, **f}
        repo.add_grant.side_effect = lambda gid, amount, reason, by, ws: {"group_id": gid, "amount": amount}
        svc.snapshot.return_value = _snap()
        grp.find_by_id.return_value = {"name": "Refaccionaria Sur"}
        ns.repo, ns.svc, ns.notif, ns.grp = repo, svc, notif, grp
        ns.client = _Client(app, ADMIN)
        ns.as_user = lambda user: _Client(app, user)
        yield ns


def test_non_super_admin_gets_403(env):
    r = env.as_user({"uid": "u1"}).get("/admin/whatsapp/tiers")
    assert r.status_code == 403
    env.repo.list_tiers.assert_not_called()


def test_patch_tier_writes_audit_with_before_and_after(env):
    r = env.client.patch("/admin/whatsapp/tiers/t1", json={**TIER, "solicitudes_per_window": 200})
    assert r.status_code == 200
    assert r.json()["body"]["stores_count"] == 4
    args = env.repo.write_audit.call_args[0]
    assert args[0] == "admin1" and args[1] == "tier.update" and args[2] == "t1"
    assert args[3]["solicitudes_per_window"] == 100
    assert args[4]["solicitudes_per_window"] == 200


def test_patch_tier_rejects_window_under_one_hour(env):
    r = env.client.patch("/admin/whatsapp/tiers/t1", json={**TIER, "window_seconds": 3599})
    assert r.status_code == 422
    env.repo.update_tier.assert_not_called()


def test_assign_store_tier_unknown_tier_404(env):
    env.repo.get_tier.return_value = None
    r = env.client.put("/admin/whatsapp/stores/g1/tier", json={"tier_id": "nope"})
    assert r.status_code == 404
    env.repo.assign_store_tier.assert_not_called()


def test_credit_grant_audited_and_resolves_request(env):
    pending = {"id": "r1", "group_id": "g1", "status": "pending"}
    env.repo.get_credit_request.return_value = pending
    env.repo.resolve_credit_request.return_value = {"id": "r1", "group_id": "g1", "status": "granted"}
    r = env.client.post("/admin/whatsapp/stores/g1/credits", params={"request_id": "r1"},
                        json={"amount": 25, "reason": "Campaña"})
    assert r.status_code == 200
    env.repo.add_grant.assert_called_once_with("g1", 25, "Campaña", "admin1", None)
    env.repo.resolve_credit_request.assert_called_once_with("r1", "granted", "admin1")
    audit = env.repo.write_audit.call_args[0]
    assert audit[1] == "credits.grant" and audit[3] == pending and audit[4]["request"]["status"] == "granted"


def test_credit_grant_binds_to_active_window(env):
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    env.svc.snapshot.return_value = _snap(end=start + timedelta(hours=8), start=start)
    env.client.post("/admin/whatsapp/stores/g1/credits", json={"amount": 5, "reason": "x"})
    assert env.repo.add_grant.call_args[0][4] == start


def test_credit_grant_with_wrong_request_404(env):
    env.repo.get_credit_request.return_value = {"id": "r1", "group_id": "other", "status": "pending"}
    r = env.client.post("/admin/whatsapp/stores/g1/credits", params={"request_id": "r1"},
                        json={"amount": 25, "reason": "x"})
    assert r.status_code == 404
    env.repo.add_grant.assert_not_called()


def test_export_csv_streams_header_and_rows(env):
    env.repo.iter_events.return_value = iter(
        [{"created_at": datetime(2026, 11, 18, 12, 0), "group_id": "g1", "uid": "u1", "counted": True,
          "status": "ok", "prompt_tokens": 10, "completion_tokens": 5}]
    )
    r = env.client.get("/admin/whatsapp/usage/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("created_at,group_id,uid")
    assert lines[1].startswith("2026-11-18T12:00:00+00:00,g1,u1")
    assert len(lines) == 2


def test_settings_patch_toggles_kill_switch(env):
    r = env.client.patch("/admin/whatsapp/settings", json={"enforcement_enabled": False, "meter_errors": 0})
    assert r.status_code == 200
    env.repo.update_settings.assert_called_once_with({"enforcement_enabled": False})
    assert r.json()["body"]["enforcement_enabled"] is False
    assert env.repo.write_audit.call_args[0][1] == "settings.update"


def test_normal_tier_cannot_be_deactivated(env):
    r = env.client.patch("/admin/whatsapp/tiers/normal", json={**TIER, "active": False})
    assert r.status_code == 400
    env.repo.update_tier.assert_not_called()


def test_store_usage_empty_by_seller_when_window_not_active(env):
    r = env.client.get("/admin/whatsapp/stores/g1/usage")
    body = r.json()["body"]
    assert body["by_seller"] == [] and body["used"] == 0
    env.repo.by_seller.assert_not_called()


def test_resolve_granted_requires_amount(env):
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "granted"})
    assert r.status_code == 422
    env.repo.resolve_credit_request.assert_not_called()


def _credit(env, pending, resolved):
    env.repo.get_credit_request.return_value = pending
    env.repo.resolve_credit_request.return_value = resolved
    return env.client.post("/admin/whatsapp/stores/g1/credits", params={"request_id": "r2"},
                           json={"amount": 5, "reason": "x"})


def test_credit_grant_second_pending_request_of_store_resolves(env):
    r = _credit(env, {"id": "r2", "group_id": "g1", "status": "pending"}, {"id": "r2", "status": "granted"})
    assert r.status_code == 200
    env.repo.resolve_credit_request.assert_called_once_with("r2", "granted", "admin1")


def test_credit_grant_resolve_lost_race_writes_no_grant(env):
    r = _credit(env, {"id": "r2", "group_id": "g1", "status": "pending"}, None)
    assert r.status_code == 404
    env.repo.add_grant.assert_not_called()
    env.repo.write_audit.assert_not_called()


def test_credit_grant_already_resolved_request_404(env):
    r = _credit(env, {"id": "r2", "group_id": "g1", "status": "granted"}, None)
    assert r.status_code == 404
    env.repo.resolve_credit_request.assert_not_called()


def test_assign_store_tier_inactive_tier_404(env):
    env.repo.get_tier.return_value = {**TIER, "tier_id": "t1", "active": False}
    r = env.client.put("/admin/whatsapp/stores/g1/tier", json={"tier_id": "t1"})
    assert r.status_code == 404
    env.repo.assign_store_tier.assert_not_called()


def test_assign_store_tier_audit_payload(env):
    env.repo.get_store_tier_id.return_value = "normal"
    env.client.put("/admin/whatsapp/stores/g1/tier", json={"tier_id": "t1"})
    args = env.repo.write_audit.call_args[0]
    assert args[1:] == ("store.tier", "g1", {"tier_id": "normal"}, {"tier_id": "t1"})
    env.repo.assign_store_tier.assert_called_once_with("g1", "t1", "admin1")


def test_create_tier_slug_audit_and_count(env):
    env.repo.get_tier.return_value = None
    env.repo.create_tier.side_effect = lambda tid, d: {**d, "tier_id": tid}
    r = env.client.post("/admin/whatsapp/tiers", json={**TIER, "name": "Súper Plan!"})
    assert r.status_code == 200
    assert env.repo.create_tier.call_args[0][0] == "super-plan"
    assert r.json()["body"]["stores_count"] == 4
    assert env.repo.write_audit.call_args[0][1:3] == ("tier.create", "super-plan")


def test_create_tier_slug_collision_suffixes_and_reserves_normal(env):
    taken = {"pro", "pro-2"}
    env.repo.get_tier.side_effect = lambda tid: {"tier_id": tid} if tid in taken else None
    env.repo.create_tier.side_effect = lambda tid, d: {**d, "tier_id": tid}
    env.client.post("/admin/whatsapp/tiers", json={**TIER, "name": "Pro"})
    assert env.repo.create_tier.call_args[0][0] == "pro-3"
    env.client.post("/admin/whatsapp/tiers", json={**TIER, "name": "Normal"})
    assert env.repo.create_tier.call_args[0][0] == "normal-2"


def test_create_tier_duplicate_key_409(env):
    from pymongo.errors import DuplicateKeyError
    env.repo.get_tier.return_value = None
    env.repo.create_tier.side_effect = DuplicateKeyError("dup")
    assert env.client.post("/admin/whatsapp/tiers", json=TIER).status_code == 409


def test_resolve_granted_happy_path(env):
    env.repo.get_credit_request.return_value = {"id": "r1", "group_id": "g1", "status": "pending"}
    env.repo.resolve_credit_request.return_value = {"id": "r1", "group_id": "g1", "status": "granted"}
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "granted", "amount": 20})
    assert r.status_code == 200
    env.repo.add_grant.assert_called_once_with("g1", 20, "Solicitud aprobada", "admin1", None)
    audit = env.repo.write_audit.call_args[0]
    assert audit[1] == "credit_request.granted" and audit[3]["status"] == "pending"


def test_resolve_unknown_request_404(env):
    env.repo.get_credit_request.return_value = None
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "declined"})
    assert r.status_code == 404


def test_usage_reports_current_near_limit_stores_independent_of_top_stores(env):
    env.repo.aggregate_usage.return_value = {"totals": {}, "by_day": [], "top_stores": [{"group_id": "big"}]}
    env.repo.list_active_usage.return_value = [{"group_id": "small", "percent": 95, "state": "warning", "enforcement_mode": "shadow"}]
    body = env.client.get("/admin/whatsapp/usage").json()["body"]
    assert [s["group_id"] for s in body["stores_near_limit"]] == ["small"]
    assert body["stores_near_limit"][0]["enforcement_mode"] == "shadow"
    env.svc.snapshot.assert_not_called()


def test_export_csv_quotes_commas_and_quotes(env):
    env.repo.iter_events.return_value = iter([{"group_id": "g1", "model": 'glm,"4"'}])
    lines = env.client.get("/admin/whatsapp/usage/export.csv").text.strip().splitlines()
    assert '"glm,""4"""' in lines[1]


# --- Final-review fixes ------------------------------------------------------

def _has_utc_offset(value: str) -> bool:
    return value.endswith("+00:00") or value.endswith("Z")


def test_naive_datetimes_are_serialized_with_utc_offset(env):
    naive = datetime(2026, 11, 18, 18, 12, 0, 123000)  # Mongo returns naive UTC
    env.svc.snapshot.return_value = _snap(end=naive + timedelta(hours=8), start=naive)
    env.repo.list_grants.return_value = [{"amount": 5, "created_at": naive, "window_start": naive}]
    body = env.client.get("/admin/whatsapp/stores/g1/usage").json()["body"]
    assert _has_utc_offset(body["window_start"]) and _has_utc_offset(body["window_end"])
    assert _has_utc_offset(body["grants"][0]["created_at"])

    env.repo.list_audit.return_value = {"items": [{"at": naive, "action": "x"}], "total": 1, "page": 1, "page_size": 50}
    assert _has_utc_offset(env.client.get("/admin/whatsapp/audit").json()["body"]["items"][0]["at"])

    env.repo.list_credit_requests.return_value = [{"id": "r1", "created_at": naive, "resolved_at": None}]
    row = env.client.get("/admin/whatsapp/credit-requests").json()["body"][0]
    assert _has_utc_offset(row["created_at"]) and row["resolved_at"] is None


def test_object_ids_still_serialize(env):
    from bson import ObjectId

    oid = ObjectId()
    env.repo.list_tiers.return_value = [{"_id": oid, "tier_id": "t1"}]
    assert env.client.get("/admin/whatsapp/tiers").json()["body"][0]["_id"] == str(oid)


def _pending(env, uid="seller1"):
    env.repo.get_credit_request.return_value = {"id": "r1", "group_id": "g1", "status": "pending", "requested_by": uid}
    return {"id": "r1", "group_id": "g1", "requested_by": uid}


def test_resolve_granted_pushes_requester(env):
    env.repo.resolve_credit_request.return_value = {**_pending(env), "status": "granted"}
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "granted", "amount": 20})
    assert r.status_code == 200
    env.notif.push_requester_resolved.assert_called_once_with("seller1", "Refaccionaria Sur", "granted", 20)


def test_resolve_declined_pushes_requester_without_amount(env):
    env.repo.resolve_credit_request.return_value = {**_pending(env), "status": "declined"}
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "declined"})
    assert r.status_code == 200
    env.notif.push_requester_resolved.assert_called_once_with("seller1", "Refaccionaria Sur", "declined", None)


def test_credits_endpoint_resolving_request_pushes_requester(env):
    env.repo.resolve_credit_request.return_value = {**_pending(env), "status": "granted"}
    r = env.client.post("/admin/whatsapp/stores/g1/credits", params={"request_id": "r1"},
                        json={"amount": 25, "reason": "x"})
    assert r.status_code == 200
    env.notif.push_requester_resolved.assert_called_once_with("seller1", "Refaccionaria Sur", "granted", 25)


def test_credits_endpoint_without_request_pushes_nobody(env):
    env.client.post("/admin/whatsapp/stores/g1/credits", json={"amount": 5, "reason": "x"})
    env.notif.push_requester_resolved.assert_not_called()


def test_requester_push_failure_never_fails_resolve(env):
    env.repo.resolve_credit_request.return_value = {**_pending(env), "status": "declined"}
    env.notif.push_requester_resolved.side_effect = RuntimeError("push down")
    env.grp.find_by_id.side_effect = RuntimeError("db down")
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "declined"})
    assert r.status_code == 200


def test_resolve_reverts_to_pending_when_add_grant_fails(env):
    env.repo.resolve_credit_request.return_value = {**_pending(env), "status": "granted"}
    env.repo.add_grant.side_effect = RuntimeError("mongo down")
    r = env.client.post("/admin/whatsapp/credit-requests/r1/resolve", json={"status": "granted", "amount": 20})
    assert r.status_code == 500
    env.repo.reopen_credit_request.assert_called_once_with("r1", "granted")
    env.repo.write_audit.assert_not_called()
    env.notif.push_requester_resolved.assert_not_called()


def test_credits_endpoint_reverts_request_when_add_grant_fails(env):
    env.repo.resolve_credit_request.return_value = {**_pending(env), "status": "granted"}
    env.repo.add_grant.side_effect = RuntimeError("mongo down")
    r = env.client.post("/admin/whatsapp/stores/g1/credits", params={"request_id": "r1"},
                        json={"amount": 25, "reason": "x"})
    assert r.status_code == 500
    env.repo.reopen_credit_request.assert_called_once_with("r1", "granted")
    env.repo.write_audit.assert_not_called()
    env.notif.push_requester_resolved.assert_not_called()
