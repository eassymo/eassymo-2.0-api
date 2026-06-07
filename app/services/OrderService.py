from app.repositories import OrderRepository as orderRepository
from app.repositories import GroupRepository as groupRepository
from fastapi import HTTPException
from app.schemas.Order import Order, OrderStatus
from app.schemas.PartRequest import FulfillmentType
from app.schemas.Groups import GroupSchema
from bson import ObjectId
from datetime import datetime

from typing import Dict, Any, List, Optional

DELIVERY_PROOF_MAX_RECIPIENT_NAME_LEN = 200


def _assert_dispatched_to_received_has_proof(order: Order) -> None:
    """Courier/guest completing delivery must submit photo(s), signature image URL, and recipient name."""
    pics = order.delivery_pictures_seller
    if not pics or not isinstance(pics, list) or len(pics) < 1:
        raise HTTPException(
            status_code=400,
            detail="Se requiere al menos una foto de la entrega para marcar como recibida.",
        )
    sig = (order.delivery_customer_signature_url or "").strip()
    if not sig:
        raise HTTPException(
            status_code=400,
            detail="Se requiere la firma de quien recibe para marcar como recibida.",
        )
    name = (order.delivery_received_by_name or "").strip()
    if not name:
        raise HTTPException(
            status_code=400,
            detail="Se requiere el nombre de quien recibe para marcar como recibida.",
        )
    if len(name) > DELIVERY_PROOF_MAX_RECIPIENT_NAME_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"El nombre de quien recibe no puede superar {DELIVERY_PROOF_MAX_RECIPIENT_NAME_LEN} caracteres.",
        )


def _order_is_pickup_fulfillment(order: Order) -> bool:
    try:
        return bool(
            order.part_request
            and order.part_request.fulfillment_type == FulfillmentType.pickup
        )
    except Exception:
        return False


def _user_uid_in_group(user_uid: str, group_id: str | None) -> bool:
    if not user_uid or not group_id:
        return False
    try:
        group_doc = groupRepository.find_users_by_group_id(str(group_id))
    except Exception:
        return False
    if not group_doc or "users" not in group_doc:
        return False
    return user_uid in group_doc.get("users", [])


def _assert_order_status_transition(
    order: Order,
    new_status_name: str,
    requesting_user_uid: Optional[str],
) -> None:
    try:
        new_enum = OrderStatus[new_status_name]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order status: {new_status_name}",
        )

    current = order.status
    if not isinstance(current, OrderStatus):
        current = OrderStatus(current)

    if new_enum == OrderStatus.WAITING_FOR_CUSTOMER_PICKUP:
        if current != OrderStatus.READY_TO_BE_DISPATCHED:
            raise HTTPException(
                status_code=400,
                detail="Can only transition to WAITING_FOR_CUSTOMER_PICKUP from READY_TO_BE_DISPATCHED",
            )
        if not _order_is_pickup_fulfillment(order):
            raise HTTPException(
                status_code=400,
                detail="WAITING_FOR_CUSTOMER_PICKUP is only allowed when the part request fulfillment type is pickup",
            )
        seller_group_id = order.offer.group_id if order.offer else None
        if not requesting_user_uid or not _user_uid_in_group(
            requesting_user_uid, seller_group_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Only a member of the selling group can mark the order ready for customer pickup",
            )
        return

    if new_enum == OrderStatus.RECIEVED and current == OrderStatus.WAITING_FOR_CUSTOMER_PICKUP:
        if not requesting_user_uid or not _user_uid_in_group(
            requesting_user_uid, order.group
        ):
            raise HTTPException(
                status_code=403,
                detail="Only a member of the buyer group can confirm pickup as received",
            )
        return


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
    delivery_customer_signature_url: str | None = None,
    delivery_received_by_name: str | None = None,
    to_be_delivered_time: str | None = None,
    requesting_user_uid: Optional[str] = None,
    enforce_delivery_completion_proof: bool = False,
):
    try:
        from dateutil import parser as date_parser

        order_id = ObjectId(order_id)
        order: Order
        order_found = list(orderRepository.find_by_id(order_id))

        order_found = {
            **order_found[0],
            "delivery_notes_buyer": delivery_notes_buyer,
            "delivery_pictures_buyer": delivery_pictures_buyer or [],
            "delivery_notes_seller": delivery_notes_seller,
            "delivery_pictures_seller": delivery_pictures_seller or [],
            "delivery_customer_signature_url": delivery_customer_signature_url,
            "delivery_received_by_name": delivery_received_by_name,
            "packaged_notes_seller": packaged_notes_seller,
            "packaged_pictures_seller": packaged_pictures_seller,
        }

        if order_found != None:
            order = Order(**order_found)

        if to_be_delivered_time is not None:
            parsed_time = date_parser.parse(to_be_delivered_time)
            order.to_be_delivered_time = parsed_time

        _assert_order_status_transition(order, new_status, requesting_user_uid)

        current = order.status
        if not isinstance(current, OrderStatus):
            current = OrderStatus(current)
        if (
            enforce_delivery_completion_proof
            and OrderStatus[new_status] == OrderStatus.RECIEVED
            and current == OrderStatus.DISPATCHED
        ):
            _assert_dispatched_to_received_has_proof(order)

        order.change_status(new_status)

        order_data = order.toJson()

        order_data.pop("_id")

        edited_order = orderRepository.edit(order_id, order_data)

        return Order(**edited_order).toJson()

    except HTTPException:
        raise
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

        if order.part_request and order.part_request.fulfillment_type == FulfillmentType.pickup:
            raise HTTPException(
                status_code=400,
                detail="Delivery assignment is not available for pickup orders",
            )

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
