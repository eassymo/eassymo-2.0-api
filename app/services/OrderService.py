from app.repositories import OrderRepository as orderRepository
from app.repositories import GroupRepository as groupRepository
from fastapi import HTTPException
from app.schemas.Order import Order, OrderStatus
from app.schemas.PartRequest import FulfillmentType
from app.schemas.Groups import GroupSchema
from bson import ObjectId
from datetime import datetime, timezone

from typing import Dict, Any, List, Optional
import logging

DELIVERY_PROOF_MAX_RECIPIENT_NAME_LEN = 200

logger = logging.getLogger(__name__)

# A rider is told about a new time only while the order is still on its way.
_DELIVERY_TIME_ALERT_STATUSES = {"WAITING_FOR_COLLECTION", "READY_TO_BE_DISPATCHED", "DISPATCHED"}


def _same_rider(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    if not a or not b or a.get("type") != b.get("type"):
        return False
    key = "guest_token" if a.get("type") == "guest" else "user_id"
    return bool(a.get(key)) and a.get(key) == b.get(key)


def _send_delivery_alert(name: str, order_id: Any, **kwargs) -> None:
    """Delivery alerts never fail the order operation (no tokens or phones in the log)."""
    from app.services import notification_fanout

    try:
        getattr(notification_fanout, name)(**kwargs)
    except Exception as exc:
        logger.warning("delivery alert %s failed for order %s: %s", name, order_id, type(exc).__name__)


def _is_mostrador_checkout_handoff(order: Order) -> bool:
    """Mostrador in-person handoff (tienda/pickup) doesn't need signed proof; domicilio does."""
    is_mostrador = order.origin == "mostrador" or bool(order.mostrador_folio_id)
    if not is_mostrador:
        return False
    mode = (order.part_request.mostrador_delivery_mode if order.part_request else None) or "tienda"
    return mode != "domicilio"


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

    if new_enum == OrderStatus.CANCELED:
        raise HTTPException(status_code=400, detail="Para cancelar usa No puedo surtir esta orden.")

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

    if new_enum == OrderStatus.IN_PERSON_READY_FOR_PICKUP:
        if current != OrderStatus.IN_PERSON_PENDING:
            raise HTTPException(
                status_code=400,
                detail="Can only transition to IN_PERSON_READY_FOR_PICKUP from IN_PERSON_PENDING",
            )
        seller_group_id = order.offer.group_id if order.offer else None
        if not requesting_user_uid or not _user_uid_in_group(
            requesting_user_uid, seller_group_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Only a member of the selling group can mark the order ready for pickup",
            )
        return

    if new_enum == OrderStatus.IN_PERSON_COMPLETED:
        if current == OrderStatus.IN_PERSON_READY_FOR_PICKUP:
            buyer_group_id = order.group
            seller_group_id = order.offer.group_id if order.offer else None
            if not requesting_user_uid or not (
                _user_uid_in_group(requesting_user_uid, buyer_group_id)
                or _user_uid_in_group(requesting_user_uid, seller_group_id)
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Only a buyer or seller group member can confirm in-person pickup",
                )
            return
        if current == OrderStatus.IN_PERSON_PENDING:
            seller_group_id = order.offer.group_id if order.offer else None
            if not requesting_user_uid or not _user_uid_in_group(
                requesting_user_uid, seller_group_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Only a member of the selling group can complete in-person delivery",
                )
            return
        raise HTTPException(
            status_code=400,
            detail="Can only transition to IN_PERSON_COMPLETED from IN_PERSON_READY_FOR_PICKUP or IN_PERSON_PENDING",
        )

    if new_enum == OrderStatus.IN_PERSON_CANCELED:
        if current not in (
            OrderStatus.IN_PERSON_PENDING,
            OrderStatus.IN_PERSON_READY_FOR_PICKUP,
        ):
            raise HTTPException(
                status_code=400,
                detail="Can only cancel in-person orders that are pending or ready for pickup",
            )
        seller_group_id = order.offer.group_id if order.offer else None
        if not requesting_user_uid or not _user_uid_in_group(
            requesting_user_uid, seller_group_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Only a member of the selling group can cancel an in-person order",
            )
        return


def _with_store_code(order_json: Dict[str, Any], order_doc: Dict[str, Any], requesting_user_uid: Optional[str], membership=None) -> Dict[str, Any]:
    """Adds pickup_code for a member of the selling group while the order waits for collection."""
    from app.services import PickupCodeService

    code = PickupCodeService.get_code_for_store(order_doc, requesting_user_uid, membership)
    return {**order_json, "pickup_code": code} if code else order_json


def find(order_id: str, group_id: str | None, current_role: str, search_argument: str | None,
         requesting_user_uid: Optional[str] = None):
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
        membership: Dict[str, bool] = {}

        for order_data in orders:
            order_json = Order(**order_data).toJson()
            offer_group = GroupSchema(**(order_data.get("offer_group") or {}))
            request_group = GroupSchema(**(order_data.get("request_group") or {}))
            order_json = {**order_json, "offer_group": offer_group.toJson(),
                          "request_group": request_group.toJson()}
            # The store's pickup code only goes in the seller view, and only to members of the
            # selling group (checked per order, never trusting the query parameters alone).
            if current_role == "2":
                order_json = _with_store_code(order_json, order_data, requesting_user_uid, membership)

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


def find_by_id(id: str, requesting_user_uid: Optional[str] = None):
    try:
        id = ObjectId(id)
        order_obj = list(orderRepository.find_by_id(id))[0]

        if order_obj is None:
            return {}

        order = Order(**order_obj)

        offer_group = GroupSchema(**(order_obj.get("offer_group") or {}))
        request_group = GroupSchema(**(order_obj.get("request_group") or {}))

        result = {**order.toJson(), "offer_group": offer_group.toJson(), "request_group": request_group.toJson()}
        return _with_store_code(result, order_obj, requesting_user_uid)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching order by id {e}')


def change_order_status(
    order_id: str,
    new_status: str,
    delivery_notes_buyer: str | None,
    delivery_notes_seller: str | None,
    packaged_notes_seller: str | None,
    delivery_pictures_buyer: List[str] | None = None,
    delivery_pictures_seller: List[str] | None = None,
    packaged_pictures_seller: List[str] | None = None,
    delivery_customer_signature_url: str | None = None,
    delivery_received_by_name: str | None = None,
    to_be_delivered_time: str | None = None,
    is_delayed: Optional[bool] = None,
    requesting_user_uid: Optional[str] = None,
    enforce_delivery_completion_proof: bool = False,
):
    try:
        from dateutil import parser as date_parser

        order_id = ObjectId(order_id)
        order: Order
        order_found = list(orderRepository.find_by_id(order_id))

        # Evidence is only written when the caller sends it (None = not sent): a status change
        # must never erase notes or photos left earlier by the store, the rider or the buyer.
        evidence = {
            "delivery_notes_buyer": delivery_notes_buyer,
            "delivery_pictures_buyer": delivery_pictures_buyer,
            "delivery_notes_seller": delivery_notes_seller,
            "delivery_pictures_seller": delivery_pictures_seller,
            "delivery_customer_signature_url": delivery_customer_signature_url,
            "delivery_received_by_name": delivery_received_by_name,
            "packaged_notes_seller": packaged_notes_seller,
            "packaged_pictures_seller": packaged_pictures_seller,
        }
        order_found = {**order_found[0], **{k: v for k, v in evidence.items() if v is not None}}

        if order_found != None:
            order = Order(**order_found)

        if to_be_delivered_time is not None:
            parsed_time = date_parser.parse(to_be_delivered_time)
            order.to_be_delivered_time = parsed_time
            if is_delayed:
                order.current_deliver_promise_delayed = True

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

        if (
            OrderStatus[new_status] == OrderStatus.IN_PERSON_COMPLETED
            and current in (
                OrderStatus.IN_PERSON_READY_FOR_PICKUP,
                OrderStatus.IN_PERSON_PENDING,
            )
            and not _is_mostrador_checkout_handoff(order)
        ):
            _assert_dispatched_to_received_has_proof(order)

        order.change_status(new_status)

        # Marked ready with a rider already assigned (pre-assignment): straight to waiting for
        # collection, and the rider is told they can go.
        became_ready_for_rider = False
        if OrderStatus[new_status] == OrderStatus.READY_TO_BE_DISPATCHED:
            order.ready_at = datetime.now(timezone.utc)
            if order.delivery_assignment and not _order_is_pickup_fulfillment(order):
                order.change_status(OrderStatus.WAITING_FOR_COLLECTION.name)
                became_ready_for_rider = True

        order_data = order.toJson()

        order_data.pop("_id")

        edited_order = orderRepository.edit(order_id, order_data)

        result = Order(**edited_order).toJson()

        from app.services import notification_fanout

        notification_fanout.fanout_order_status_change(order=result, new_status=new_status)

        if became_ready_for_rider:
            _send_delivery_alert("fanout_delivery_ready", order_id, order=result)

        if is_delayed:
            notification_fanout.fanout_order_delayed(order=result)

        if OrderStatus[new_status] == OrderStatus.CANCELED and result.get("delivery_assignment"):
            _send_delivery_alert("fanout_delivery_canceled", order_id, order=result)

        return result

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
    Assigns a delivery person (account or guest) to an order. Allowed while it is being prepared
    (the status stays CONFIRMED and the rider is told it is not ready yet) or once it is ready or
    waiting for collection (the status becomes WAITING_FOR_COLLECTION for every rider type). The
    pickup code is created, or replaced when the rider changes. No "enviado" notice goes to the
    buyer here: that happens when the rider confirms the pickup.
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
        previous_assignment = order.delivery_assignment.toJson() if order.delivery_assignment else None

        if order.part_request and order.part_request.fulfillment_type == FulfillmentType.pickup:
            raise HTTPException(
                status_code=400,
                detail="Delivery assignment is not available for pickup orders",
            )

        _assignable_statuses = {
            OrderStatus.CONFIRMED,
            OrderStatus.READY_TO_BE_DISPATCHED,
            OrderStatus.WAITING_FOR_COLLECTION,
        }
        if order.status not in _assignable_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Order must be in CONFIRMED, READY_TO_BE_DISPATCHED or WAITING_FOR_COLLECTION status to assign delivery (current: {order.status.value})"
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

        if assignment_type == "guest" and guest_phone and guest_name and assignment.guest_token:
            invite_url = f"https://eassymo.mx/delivery-invite/{assignment.guest_token}"
            WhatsappService().send_delivery_invite(
                guest_phone=guest_phone,
                guest_name=guest_name,
                invite_url=invite_url,
            )

        order.delivery_assignment = assignment

        preparing = order.status == OrderStatus.CONFIRMED
        if not preparing and order.status != OrderStatus.WAITING_FOR_COLLECTION:
            order.change_status(OrderStatus.WAITING_FOR_COLLECTION.name)

        # The code first: if saving the order fails, a leftover code is harmless; the reverse would leave
        # an assigned order that silently falls back to the old no-code pickup.
        from app.services import PickupCodeService

        PickupCodeService.reset_code(str(oid))

        order_data = order.toJson()
        order_data.pop("_id", None)

        updated_doc = orderRepository.edit(oid, order_data)
        result = Order(**updated_doc).toJson()

        new_assignment = result.get("delivery_assignment")
        if not _same_rider(previous_assignment, new_assignment):
            _send_delivery_alert("fanout_delivery_assigned", oid, order=result, preparing=preparing)
            if previous_assignment:
                _send_delivery_alert(
                    "fanout_delivery_reassigned", oid, order=result, previous_assignment=previous_assignment,
                )

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
            previous_time = order.to_be_delivered_time
            order.change_delivery_time(
                new_delivery_time, current_deliver_promise_delayed=is_delayed)
            order_data = order.toJson()

            order_data.pop("_id")

            edited_order = orderRepository.edit(order_id, order_data)

            result = Order(**edited_order).toJson()

            if is_delayed:
                from app.services import notification_fanout

                notification_fanout.fanout_order_delayed(order=result)

            if result.get("delivery_assignment") and result.get("status") in _DELIVERY_TIME_ALERT_STATUSES:
                _send_delivery_alert(
                    "fanout_delivery_time_changed", order_id, order=result, previous_time=previous_time,
                )

            return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while changing order delivery time {e}')
