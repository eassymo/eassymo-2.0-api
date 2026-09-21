from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.schemas.GuestDeliveryProfile import GuestDeliveryProfileStatus
from app.schemas.Order import OrderStatus
from app.services import DeliveryService as svc

TOKEN = "38fc8d30-da09-4211-8d39-83acdfd1e2df"
USER_UID = "driver-uid"
GROUP_A = "seller-group-a"
GROUP_B = "seller-group-b"
ORDER_A_ID = str(ObjectId())
ORDER_B_ID = str(ObjectId())


def _active_profile() -> dict:
    return {
        "token": TOKEN,
        "name": "Guest Driver",
        "phone": "+5215512345678",
        "status": GuestDeliveryProfileStatus.ACTIVE,
    }


def _order_json(order_id: str, group_id: str) -> dict:
    return {
        "_id": order_id,
        "order_id": f"ord-{order_id[-4:]}",
        "status": OrderStatus.WAITING_FOR_COLLECTION.value,
        "offer_group": {"_id": group_id, "name": f"Shop {group_id}"},
        "request_group": {"_id": "buyer-1", "name": "Buyer Shop"},
        "delivery_assignment": {
            "type": "guest",
            "guest_token": TOKEN,
            "guest_name": "Guest Driver",
        },
    }


def _order_doc(order_id: str, group_id: str) -> dict:
    return {
        "_id": ObjectId(order_id),
        "order_id": f"ord-{order_id[-4:]}",
        "status": OrderStatus.WAITING_FOR_COLLECTION.value,
        "offer": {"_id": "offer-1", "group_id": group_id},
        "part_request": {
            "_id": "req-1",
            "creatorGroup": "buyer-1",
            "creatorUser": "buyer-user",
            "vehicleId": "veh-1",
            "isActive": True,
            "partList": [],
            "status": "CREATED",
            "part": {"tipoParteDescripcion": "Balata"},
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        },
        "status_history": [],
        "delivery_assignment": {
            "type": "guest",
            "guest_token": TOKEN,
            "guest_name": "Guest Driver",
            "assigned_at": datetime.utcnow(),
        },
        "updated_at": datetime.utcnow(),
    }


@patch("app.services.DeliveryService.userRolesRepository.find")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_invite_eligibility_returns_eligible_orders(
    mock_find_profile,
    mock_fetch_orders,
    mock_find_roles,
):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = [
        _order_json(ORDER_A_ID, GROUP_A),
        _order_json(ORDER_B_ID, GROUP_B),
    ]

    def role_side_effect(query):
        if query.get("group") == GROUP_A:
            return [MagicMock()]
        return []

    mock_find_roles.side_effect = role_side_effect

    result = svc.get_invite_eligibility(TOKEN, USER_UID)

    assert result["has_any_eligible_order"] is True
    assert len(result["eligible_orders"]) == 1
    assert result["eligible_orders"][0]["_id"] == ORDER_A_ID
    mock_fetch_orders.assert_called_once_with({
        "delivery_assignment.guest_token": TOKEN,
        "status": OrderStatus.WAITING_FOR_COLLECTION.value,
    })


@patch("app.services.DeliveryService.userRolesRepository.find")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_invite_eligibility_returns_empty_when_no_role(
    mock_find_profile,
    mock_fetch_orders,
    mock_find_roles,
):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = [_order_json(ORDER_A_ID, GROUP_A)]
    mock_find_roles.return_value = []

    result = svc.get_invite_eligibility(TOKEN, USER_UID)

    assert result["has_any_eligible_order"] is False
    assert result["eligible_orders"] == []


@patch("app.services.DeliveryService.userRolesRepository.find")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_invite_eligibility_excludes_dispatched_orders(
    mock_find_profile,
    mock_fetch_orders,
    mock_find_roles,
):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = []
    mock_find_roles.return_value = [MagicMock()]

    result = svc.get_invite_eligibility(TOKEN, USER_UID)

    assert result["has_any_eligible_order"] is False
    mock_fetch_orders.assert_called_once_with({
        "delivery_assignment.guest_token": TOKEN,
        "status": OrderStatus.WAITING_FOR_COLLECTION.value,
    })


@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_invite_eligibility_raises_for_inactive_token(mock_find_profile):
    mock_find_profile.return_value = None

    with pytest.raises(HTTPException) as exc:
        svc.get_invite_eligibility(TOKEN, USER_UID)

    assert exc.value.status_code == 404


@patch("app.services.DeliveryService.Order")
@patch("app.services.DeliveryService.orderRepository.edit")
@patch("app.services.DeliveryService.orderRepository.find_one")
@patch("app.services.DeliveryService.get_invite_eligibility")
def test_link_authenticated_delivery_person_links_eligible_orders(
    mock_eligibility,
    mock_find_one,
    mock_edit,
    mock_order_cls,
):
    mock_eligibility.return_value = {
        "has_any_eligible_order": True,
        "eligible_orders": [_order_json(ORDER_A_ID, GROUP_A)],
    }
    order_doc = _order_doc(ORDER_A_ID, GROUP_A)
    mock_find_one.return_value = order_doc

    order_instance = MagicMock()
    order_instance.toJson.return_value = {"_id": ORDER_A_ID, "status": OrderStatus.WAITING_FOR_COLLECTION.value}
    mock_order_cls.return_value = order_instance
    mock_edit.return_value = order_doc

    result = svc.link_authenticated_delivery_person(TOKEN, USER_UID)

    assert len(result["linked_orders"]) == 1
    mock_edit.assert_called_once()
    order_instance.toJson.assert_called()


@patch("app.services.DeliveryService.get_invite_eligibility")
def test_link_authenticated_delivery_person_rejects_ineligible_user(mock_eligibility):
    mock_eligibility.return_value = {
        "has_any_eligible_order": False,
        "eligible_orders": [],
    }

    with pytest.raises(HTTPException) as exc:
        svc.link_authenticated_delivery_person(TOKEN, USER_UID)

    assert exc.value.status_code == 403


@patch("app.services.DeliveryService.Order")
@patch("app.services.DeliveryService.orderRepository.edit")
@patch("app.services.DeliveryService.orderRepository.find_one")
@patch("app.services.DeliveryService.userRolesRepository.find")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_link_only_links_orders_with_matching_role(
    mock_find_profile,
    mock_fetch_orders,
    mock_find_roles,
    mock_find_one,
    mock_edit,
    mock_order_cls,
):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = [
        _order_json(ORDER_A_ID, GROUP_A),
        _order_json(ORDER_B_ID, GROUP_B),
    ]

    def role_side_effect(query):
        if query.get("group") == GROUP_A:
            return [MagicMock()]
        return []

    mock_find_roles.side_effect = role_side_effect

    order_doc_a = _order_doc(ORDER_A_ID, GROUP_A)
    mock_find_one.return_value = order_doc_a

    order_instance = MagicMock()
    order_instance.toJson.return_value = {"_id": ORDER_A_ID, "status": OrderStatus.WAITING_FOR_COLLECTION.value}
    mock_order_cls.return_value = order_instance
    mock_edit.return_value = order_doc_a

    result = svc.link_authenticated_delivery_person(TOKEN, USER_UID)

    assert len(result["linked_orders"]) == 1
    mock_edit.assert_called_once()


@patch("app.services.DeliveryService.guestProfileRepository.insert")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_phone")
def test_build_delivery_assignment_creates_profile_for_supplied_guest_token(
    mock_find_by_phone,
    mock_find_by_token,
    mock_insert,
):
    mock_find_by_token.return_value = None
    mock_find_by_phone.return_value = None

    assignment = svc.build_delivery_assignment(
        assignment_type="guest",
        user_id=None,
        guest_name="Juan",
        guest_phone="+5215512345678",
        group_id=GROUP_A,
        guest_token=TOKEN,
    )

    assert assignment.guest_token == TOKEN
    mock_insert.assert_called_once()
    inserted = mock_insert.call_args[0][0]
    assert inserted["token"] == TOKEN
    assert inserted["name"] == "Juan"
    assert inserted["phone"] == "+5215512345678"


@patch("app.services.DeliveryService._ensure_guest_profile")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_resolve_active_guest_profile_backfills_from_orders(
    mock_find_by_token,
    mock_fetch_orders,
    mock_ensure_profile,
):
    mock_find_by_token.side_effect = [
        None,
        {
            "token": TOKEN,
            "name": "Juan",
            "phone": "+5215512345678",
            "status": GuestDeliveryProfileStatus.ACTIVE,
        },
    ]
    mock_fetch_orders.return_value = [
        {
            "_id": ORDER_A_ID,
            "delivery_assignment": {
                "guest_token": TOKEN,
                "guest_name": "Juan",
                "guest_phone": "+5215512345678",
            },
        }
    ]

    profile = svc._resolve_active_guest_profile(TOKEN)

    mock_ensure_profile.assert_called_once_with(TOKEN, "Juan", "+5215512345678")
    assert profile["token"] == TOKEN


@patch("app.services.DeliveryService._resolve_active_guest_profile")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
def test_get_invite_preview_uses_resolved_profile(
    mock_fetch_orders,
    mock_resolve_profile,
):
    mock_resolve_profile.return_value = {
        "name": "Juan",
        "phone": "+5215512345678",
    }
    mock_fetch_orders.return_value = [_order_json(ORDER_A_ID, GROUP_A)]

    result = svc.get_invite_preview(TOKEN)

    assert result["guest_name"] == "Juan"
    assert result["orders_count"] == 1
    mock_resolve_profile.assert_called_once_with(TOKEN)


@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_guest_order_by_id_returns_matching_order(mock_find_profile, mock_fetch_orders):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = [_order_json(ORDER_A_ID, GROUP_A)]

    result = svc.get_guest_order_by_id(TOKEN, ORDER_A_ID)

    assert result["_id"] == ORDER_A_ID
    mock_fetch_orders.assert_called_once()
    filters = mock_fetch_orders.call_args[0][0]
    assert filters["delivery_assignment.guest_token"] == TOKEN
    assert "$or" in filters


@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_guest_order_by_id_not_found(mock_find_profile, mock_fetch_orders):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = []

    with pytest.raises(HTTPException) as exc:
        svc.get_guest_order_by_id(TOKEN, "missing-order")

    assert exc.value.status_code == 404


@patch("app.services.DeliveryService.guestProfileRepository.insert")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_phone")
def test_build_delivery_assignment_creates_profile_for_supplied_guest_token(
    mock_find_by_phone,
    mock_find_by_token,
    mock_insert,
):
    mock_find_by_token.return_value = None
    mock_find_by_phone.return_value = None

    assignment = svc.build_delivery_assignment(
        assignment_type="guest",
        user_id=None,
        guest_name="Juan",
        guest_phone="+5215512345678",
        group_id=GROUP_A,
        guest_token=TOKEN,
    )

    assert assignment.guest_token == TOKEN
    mock_insert.assert_called_once()
    inserted = mock_insert.call_args[0][0]
    assert inserted["token"] == TOKEN
    assert inserted["name"] == "Juan"
    assert inserted["phone"] == "+5215512345678"


@patch("app.services.DeliveryService._ensure_guest_profile")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_resolve_active_guest_profile_backfills_from_orders(
    mock_find_by_token,
    mock_fetch_orders,
    mock_ensure_profile,
):
    mock_find_by_token.side_effect = [
        None,
        {
            "token": TOKEN,
            "name": "Juan",
            "phone": "+5215512345678",
            "status": GuestDeliveryProfileStatus.ACTIVE,
        },
    ]
    mock_fetch_orders.return_value = [
        {
            "_id": ORDER_A_ID,
            "delivery_assignment": {
                "guest_token": TOKEN,
                "guest_name": "Juan",
                "guest_phone": "+5215512345678",
            },
        }
    ]

    profile = svc._resolve_active_guest_profile(TOKEN)

    mock_ensure_profile.assert_called_once_with(TOKEN, "Juan", "+5215512345678")
    assert profile["token"] == TOKEN


@patch("app.services.DeliveryService._resolve_active_guest_profile")
@patch("app.services.DeliveryService._fetch_orders_for_delivery")
def test_get_invite_preview_uses_resolved_profile(
    mock_fetch_orders,
    mock_resolve_profile,
):
    mock_resolve_profile.return_value = {
        "name": "Juan",
        "phone": "+5215512345678",
    }
    mock_fetch_orders.return_value = [_order_json(ORDER_A_ID, GROUP_A)]

    result = svc.get_invite_preview(TOKEN)

    assert result["guest_name"] == "Juan"
    assert result["orders_count"] == 1
    mock_resolve_profile.assert_called_once_with(TOKEN)


@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_guest_order_by_id_returns_matching_order(mock_find_profile, mock_fetch_orders):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = [_order_json(ORDER_A_ID, GROUP_A)]

    result = svc.get_guest_order_by_id(TOKEN, ORDER_A_ID)

    assert result["_id"] == ORDER_A_ID
    mock_fetch_orders.assert_called_once()
    filters = mock_fetch_orders.call_args[0][0]
    assert filters["delivery_assignment.guest_token"] == TOKEN
    assert "$or" in filters


@patch("app.services.DeliveryService._fetch_orders_for_delivery")
@patch("app.services.DeliveryService.guestProfileRepository.find_by_token")
def test_get_guest_order_by_id_not_found(mock_find_profile, mock_fetch_orders):
    mock_find_profile.return_value = _active_profile()
    mock_fetch_orders.return_value = []

    with pytest.raises(HTTPException) as exc:
        svc.get_guest_order_by_id(TOKEN, "missing-order")

    assert exc.value.status_code == 404
