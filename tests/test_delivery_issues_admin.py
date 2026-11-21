"""GET /admin/delivery-issues: Eassymo support's list of delivery issues, oldest first."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from bson import ObjectId

import main
from app.services import DeliveryIssueAdminService as svc
from tests.asgi_client import AsgiClient

NOW = datetime(2026, 11, 21, 18, 0)


def _order(n, at, resolution=None, kind="delivery", reason="no_answer", status="DISPATCHED"):
    return {
        "_id": ObjectId(), "order_id": f"21-11-26-{n:04d}", "status": status,
        "offer": {"group_id": "g-store"}, "group": "g-buyer",
        "offer_group": {"name": f"Tienda {n}", "phone": "9840000000"},
        "request_group": {"name": f"Taller {n}"},
        "part_request": {"part": {"tipoParteDescripcion": "Balata"}, "creatorGroup": "g-buyer"},
        "delivery_assignment": {"type": "guest", "guest_name": "Beto", "guest_phone": "9841112233",
                                "guest_token": "SECRET-TOKEN", "assigned_at": at},
        "delivery_failures": [
            {"reason": "other", "at": at - timedelta(days=1), "resolution": {"action": "x"}, "id": "old"},
            {"id": f"f{n}", "kind": kind, "reason": reason, "note": "n", "at": at, "resolution": resolution,
             "by": {"type": "guest", "name": "Beto"}},
        ],
    }


class FakeRepo:
    def __init__(self, orders):
        self.orders = orders
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return list(self.orders)


def _list(orders, **kw):
    repo = FakeRepo(orders)
    with patch.object(svc, "orderRepository", repo):
        return svc.list_issues(now=NOW, **kw), repo


def test_lists_only_open_issues_by_default_oldest_first():
    older, newer = _order(1, NOW - timedelta(hours=5)), _order(2, NOW - timedelta(hours=1))
    out, repo = _list([older, newer])
    assert [i["order_code"] for i in out["items"]] == ["21-11-26-0001", "21-11-26-0002"]
    match = repo.pipelines[0][2]["$match"]
    assert match["last.resolution"] is None and match["last.id"] == {"$exists": True}
    assert {"$sort": {"last.at": 1}} in repo.pipelines[0]


def test_resolved_status_flips_the_filter_and_sorts_newest_first():
    _, repo = _list([], status="resolved")
    assert repo.pipelines[0][2]["$match"]["last.resolution"] == {"$ne": None}
    assert {"$sort": {"last.at": -1}} in repo.pipelines[0]


def test_row_has_order_store_buyer_rider_reason_and_age_but_no_secrets():
    out, _ = _list([_order(1, NOW - timedelta(hours=5), kind="pickup", reason="store_closed", status="WAITING_FOR_COLLECTION")])
    row = out["items"][0]
    assert row["store"] == "Tienda 1" and row["buyer"] == "Taller 1" and row["part"] == "Balata"
    assert row["rider"] == {"name": "Beto", "phone": "9841112233"}
    assert row["kind"] == "pickup" and row["reason"] == "store_closed" and row["age_minutes"] == 300
    assert row["issue_id"] == "f1" and row["status"] == "WAITING_FOR_COLLECTION"
    assert "SECRET-TOKEN" not in str(out) and "pickup_code" not in str(out)


def test_pagination_is_clamped_and_passed_down():
    _, repo = _list([], skip=40, limit=500)
    stages = repo.pipelines[0]
    assert {"$skip": 40} in stages and {"$limit": 100} in stages
    _, repo = _list([], skip=-5, limit=0)
    assert {"$skip": 0} in repo.pipelines[0] and {"$limit": 1} in repo.pipelines[0]


# ── route ────────────────────────────────────────────────────────────────────

def _auth(user):
    async def verify(request):
        request.state.user = user
        return user
    return patch.object(main, "verify_token", side_effect=verify)


def test_needs_super_admin_403_without_it():
    with _auth({"uid": "u1"}), patch.object(svc, "list_issues") as go:
        res = AsgiClient(main.app).get("/admin/delivery-issues")
    assert res.status_code == 403
    go.assert_not_called()


def test_super_admin_gets_the_list_with_paging():
    with _auth({"uid": "u1", "super_admin": True}), patch.object(svc, "list_issues", return_value={"items": [], "total": 0}) as go:
        res = AsgiClient(main.app).get("/admin/delivery-issues?status=resolved&skip=10&limit=20")
    assert res.status_code == 200
    assert go.call_args.kwargs == {"status": "resolved", "skip": 10, "limit": 20}
