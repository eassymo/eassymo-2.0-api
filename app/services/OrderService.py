from app.repositories import OrderRepository as orderRepository
from fastapi import HTTPException
from app.schemas.Order import Order, OrderStatus
from app.schemas.Groups import GroupSchema
from bson import ObjectId
from datetime import datetime

from typing import Dict, Any, List, Optional


def find(order_id: str, group_id: str | None, current_role: str, search_argument: str | None):
    if group_id == None:
        raise HTTPException(status_code=400, detail="Group id is required")
    try:
        filters = {}
        response_obj = {
            "orders": [],
            "sales": []
        }

        filters = _build_order_filters(
            current_role, order_id, group_id, search_argument)

        orders = list(orderRepository.find(filters))

        order_list = []

        for order_data in orders:
            order_json = Order(**order_data).toJson()
            offer_group = GroupSchema(**order_data["offer_group"])
            request_group = GroupSchema(**order_data["request_group"])
            order_json = {**order_json, "offer_group": offer_group.toJson(),
                          "request_group": request_group.toJson()}

            order_list.append(order_json)

        response_obj = {
            "orders": order_list if current_role == "1" else [],
            "sales": order_list if current_role == "2" else []
        }

        return response_obj
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching orders {e}')


def _build_order_filters(current_role: str, order_id: str | None, group_id: str | None, search_argument: str | None) -> Dict[str, Any]:

    filters = {}

    if (order_id != None and len(order_id) > 0):
        order_id = ObjectId(order_id)
        filters["_id"] = order_id

    if (current_role != None and current_role == "1"):
        filters["group"] = group_id

    if (current_role != None and current_role == "2"):
        filters["offer.group_id"] = group_id

    if (search_argument != None):
        filters["$text"] = {
            "$search": search_argument
        }

    return filters


def find_by_id(id: str):
    try:
        id = ObjectId(id)
        order_obj = list(orderRepository.find_by_id(id))[0]

        if order_obj is None:
            return {}

        order = Order(**order_obj)

        offer_group = GroupSchema(**order_obj["offer_group"])
        request_group = GroupSchema(**order_obj["request_group"])

        return {**order.toJson(), "offer_group": offer_group.toJson(), "request_group": request_group.toJson()}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching order by id {e}')


def change_order_status(
    order_id: str,
    new_status: str,
    delivery_notes_buyer: str | None,
    delivery_notes_seller: str | None,
    packaged_notes_seller: str | None,
    delivery_pictures_buyer: List[str] | None = [],
    delivery_pictures_seller: List[str] | None = [],
    packaged_pictures_seller: List[str] | None = [],
):
    try:
        order_id = ObjectId(order_id)
        order: Order
        order_found = list(orderRepository.find_by_id(order_id))

        order_found = {
            **order_found[0],
            "delivery_notes_buyer": delivery_notes_buyer,
            "delivery_pictures_buyer": delivery_pictures_buyer,
            "delivery_notes_seller": delivery_notes_seller,
            "delivery_pictures_seller": delivery_pictures_seller,
            "packaged_notes_seller": packaged_notes_seller,
            "packaged_pictures_seller": packaged_pictures_seller
        }

        if order_found != None:
            order = Order(**order_found)

        order.change_status(new_status)

        order_data = order.toJson()

        order_data.pop("_id")

        edited_order = orderRepository.edit(order_id, order_data)

        return Order(**edited_order).toJson()

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while changing order status {e}')


def assign_delivery(
    order_id: str,
    assignment_type: str,
    requesting_user_uid: str,
    user_id: Optional[str] = None,
    guest_name: Optional[str] = None,
    guest_phone: Optional[str] = None,
    guest_token: Optional[str] = None,
) -> dict:
    """
    Assigns a delivery person to an order and advances its status to DISPATCHED.
    Raises HTTPException on any validation failure.
    """
    from app.services import DeliveryService
    from app.services.WhatsappService import WhatsappService

    try:
        oid = ObjectId(order_id)
        order_docs = list(orderRepository.find_by_id(oid))

        if not order_docs:
            raise HTTPException(status_code=404, detail="Order not found")

        order_doc = order_docs[0]
        order = Order(**order_doc)

        _assignable_statuses = {OrderStatus.READY_TO_BE_DISPATCHED, OrderStatus.WAITING_FOR_COLLECTION}
        if order.status not in _assignable_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Order must be in READY_TO_BE_DISPATCHED or WAITING_FOR_COLLECTION status to assign delivery (current: {order.status.value})"
            )

        offer_group_id = order_doc.get("offer", {}).get("group_id") or (
            order_doc.get("offer_group") or {}
        ).get("_id")

        if not offer_group_id:
            raise HTTPException(status_code=500, detail="Could not determine the selling group for this order")

        offer_group_id = str(offer_group_id)

        DeliveryService._assert_user_in_group(requesting_user_uid, offer_group_id)

        assignment = DeliveryService.build_delivery_assignment(
            assignment_type=assignment_type,
            user_id=user_id,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_token=guest_token,
            group_id=offer_group_id,
        )

        order.delivery_assignment = assignment

        if assignment_type == "guest":
            new_status = OrderStatus.WAITING_FOR_COLLECTION.name
        else:
            new_status = OrderStatus.DISPATCHED.name

        order.change_status(new_status)

        order_data = order.toJson()
        order_data.pop("_id", None)

        updated_doc = orderRepository.edit(oid, order_data)
        result = Order(**updated_doc).toJson()

        if assignment_type == "guest" and guest_phone and guest_name and assignment.guest_token:
            invite_url = f"https://eassymo.mx/delivery-invite/{assignment.guest_token}"
            try:
                WhatsappService().send_delivery_invite(
                    guest_phone=guest_phone,
                    guest_name=guest_name,
                    invite_url=invite_url,
                )
            except Exception:
                pass

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while assigning delivery: {e}")


def change_delivery_time(order_id: str | ObjectId, new_delivery_time: datetime, is_delayed: bool):
    try:
        order_id = ObjectId(order_id)
        orders = list(orderRepository.find_by_id(order_id))
        if len(orders) > 0:
            order = Order(**orders[0])
            order.change_delivery_time(
                new_delivery_time, current_deliver_promise_delayed=is_delayed)
            order_data = order.toJson()

            order_data.pop("_id")

            edited_order = orderRepository.edit(order_id, order_data)

            return Order(**edited_order).toJson()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while changing order delivery time {e}')
