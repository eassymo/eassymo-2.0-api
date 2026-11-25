from app.utils.notification_routes import SELLER_OFFER_CREATOR_ROUTE, seller_offer_creator_path


def test_seller_notifications_open_the_v4_offer_creator():
    assert SELLER_OFFER_CREATOR_ROUTE == "/offer-creator-v4"
    assert seller_offer_creator_path("req-1") == "/offer-creator-v4/req-1"


def test_seller_path_falls_back_to_dashboard_without_id():
    assert seller_offer_creator_path("  ") == "/dashboard-v2"


def test_order_notifications_open_the_v3_orders_page():
    from app.utils.notification_routes import ORDERS_ROUTE, order_management_path

    assert ORDERS_ROUTE == "/order-management-v3"
    assert order_management_path("o1") == "/order-management-v3/o1"
    assert order_management_path("o1", current_role=2) == "/order-management-v3/o1?currentRole=2"
    assert order_management_path(" ") == "/order-management-v3"


def test_no_notification_still_links_to_the_v2_orders_page():
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if "/order-management-v2" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# ── list payload v2 ──────────────────────────────────────────────────────────
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from app.routers import NotificationRouter as router_mod
from tests.asgi_client import AsgiClient

SUMMARY = {"unread_buy": 90, "unread_sell": 11, "unread_total": 101, "decisions_open": 2}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router_mod.notificationRouter)
    page = [{"id": str(i), "type": "OFFER_CREATED", "message": "m", "read": False} for i in range(100)]
    with patch.object(router_mod, "require_authenticated_uid", return_value="u1"), \
         patch.object(router_mod, "assert_group_membership"), \
         patch.object(router_mod.notificationService, "list_for_user", return_value=page), \
         patch.object(router_mod.notificationService, "summary_for_user", return_value=SUMMARY) as summary:
        yield AsgiClient(app), summary


def test_v2_returns_items_and_summary_counted_beyond_the_page(client):
    c, summary = client
    body = c.get("/notifications?v=2", headers={"groupselected": "g1"}).json()["body"]
    assert len(body["items"]) == 100
    assert body["summary"]["unread_total"] == 101  # 101 unread, 100-item page
    summary.assert_called_once_with("u1", "g1")


def test_without_v2_the_old_bare_list_is_kept(client):
    c, summary = client
    body = c.get("/notifications", headers={"groupselected": "g1"}).json()["body"]
    assert isinstance(body, list) and len(body) == 100
    summary.assert_not_called()
