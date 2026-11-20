"""Guest notification feed: token only from X-Guest-Token, scoped to that token,
deactivated link -> 401 {code: guest_token_inactive}. Runs through main.app with
Firebase auth forced to fail, so these routes must not need an account."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from tests.asgi_client import AsgiClient

import main
from app.repositories import NotificationRepository as notificationRepository
from app.schemas.GuestDeliveryProfile import GuestDeliveryProfileStatus
from app.services import DeliveryService

TOKEN = "tok-guest-a"
H = {"X-Guest-Token": TOKEN}


async def _no_firebase(_request):
    raise HTTPException(status_code=401, detail="Missing or invalid token")


@pytest.fixture
def client():
    with patch.object(main, "verify_token", side_effect=_no_firebase):
        yield AsgiClient(main.app)


@pytest.fixture
def active():
    profile = {"token": TOKEN, "name": "Beto", "status": GuestDeliveryProfileStatus.ACTIVE}
    with patch.object(DeliveryService.guestProfileRepository, "find_by_token", return_value=profile):
        yield


@pytest.fixture
def inactive():
    profile = {"token": TOKEN, "name": "Beto", "status": "inactive"}
    with patch.object(DeliveryService.guestProfileRepository, "find_by_token", return_value=profile), \
         patch.object(DeliveryService, "_ensure_guest_profile") as reactivate:
        yield reactivate


STORED = {
    "id": "n1", "type": "DELIVERY_ASSIGNED", "message": "Te asignaron una entrega. Recoger en X, entregar a Y",
    "owner": "", "ownerGroup": "seller", "guest_token": TOKEN, "uid": "u-1",
    "metaData": {"orderId": "o1", "title": "Te asignaron una entrega", "body": "Recoger en X, entregar a Y"},
    "navigateToUrl": f"/delivery/guest/o1?token={TOKEN}", "read": False,
    "createdAt": datetime(2026, 11, 19, tzinfo=timezone.utc), "timestamp": 1763510400000,
}


def test_missing_header_is_401(client):
    assert client.get("/delivery/guest-notifications").status_code == 401
    assert client.post("/delivery/guest-notifications/read", json={}).status_code == 401


def test_token_in_query_or_body_is_ignored(client, active):
    assert client.get(f"/delivery/guest-notifications?token={TOKEN}").status_code == 401
    assert client.post("/delivery/guest-notifications/read", json={"token": TOKEN}).status_code == 401


def test_inactive_profile_is_401_with_code_guest_token_inactive(client, inactive):
    for res in (
        client.get("/delivery/guest-notifications", headers=H),
        client.post("/delivery/guest-notifications/read", json={}, headers=H),
    ):
        assert res.status_code == 401
        assert res.json()["code"] == "guest_token_inactive"
    inactive.assert_not_called()  # a deactivated link is never silently re-activated


def test_lists_only_own_notifications_with_unread_count(client, active):
    with patch.object(notificationRepository, "find_for_guest", return_value=[STORED]) as find, \
         patch.object(notificationRepository, "count_unread_for_guest", return_value=3) as count:
        res = client.get("/delivery/guest-notifications?skip=5&limit=20", headers=H)
    assert res.status_code == 200
    find.assert_called_once_with(TOKEN, 5, 20)
    count.assert_called_once_with(TOKEN)
    body = res.json()["body"]
    assert body["unread"] == 3
    assert body["items"] == [{
        "id": "n1", "type": "DELIVERY_ASSIGNED",
        "message": "Te asignaron una entrega. Recoger en X, entregar a Y",
        "orderId": "o1", "navigateToUrl": f"/delivery/guest/o1?token={TOKEN}",
        "read": False, "timestamp": 1763510400000,
    }]


def test_mark_read_updates_only_own(client, active):
    with patch.object(notificationRepository, "mark_read_for_guest", return_value=2) as mark:
        res = client.post("/delivery/guest-notifications/read", json={"ids": ["a", "b"]}, headers=H)
        res_all = client.post("/delivery/guest-notifications/read", json={}, headers=H)
    assert res.status_code == 200 and res.json()["body"] == {"updated": 2}
    assert res_all.status_code == 200
    assert mark.call_args_list[0].args == (TOKEN, ["a", "b"])
    assert mark.call_args_list[1].args == (TOKEN, None)


def test_mark_read_rejects_non_list_ids(client, active):
    assert client.post("/delivery/guest-notifications/read", json={"ids": "a"}, headers=H).status_code == 422


def test_limit_is_capped_at_100(client, active):
    with patch.object(notificationRepository, "find_for_guest", return_value=[]) as find, \
         patch.object(notificationRepository, "count_unread_for_guest", return_value=0):
        res = client.get("/delivery/guest-notifications?limit=500", headers=H)
    assert res.status_code == 200
    assert find.call_args.args == (TOKEN, 0, 100)
