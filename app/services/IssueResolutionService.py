"""Resolving an open delivery issue: store, buyer or Eassymo support, each with their own actions.

An issue is the order's last failed attempt while it has no resolution (see DeliveryFailure.open_issue).
The status of the order only changes for confirm_return and cancel.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import HTTPException

from app.repositories import GroupRepository as groupRepository
from app.repositories import OrderRepository as orderRepository
from app.schemas.DeliveryFailure import open_issue
from app.schemas.Order import Order
from app.services import OrderService, PickupCodeService, notification_fanout

logger = logging.getLogger(__name__)

ACTIONS = ("fix_and_retry", "reschedule", "return_to_store", "confirm_return", "cancel")
ALLOWED_ROLES = {
    "fix_and_retry": {"buyer", "support"},
    "reschedule": {"store", "support"},
    "return_to_store": {"store", "support"},
    "confirm_return": {"store", "support"},
    "cancel": {"store", "support"},
}


def _user_in_group(uid: Optional[str], group_id: Optional[str]) -> bool:
    return PickupCodeService._user_in_group(uid, group_id)


def _role_of(order_doc: Dict[str, Any], uid: str, is_support: bool) -> str:
    if is_support:
        return "support"
    if _user_in_group(uid, (order_doc.get("offer") or {}).get("group_id")):
        return "store"
    if _user_in_group(uid, order_doc.get("group")):
        return "buyer"
    raise HTTPException(status_code=403, detail="Not a party of this order")


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="new_time is not a valid date")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_issue(
    order_id: str,
    action: str,
    uid: str,
    *,
    is_support: bool = False,
    note: Optional[str] = None,
    new_time: Any = None,
    new_rider: Optional[Dict[str, Any]] = None,
    contact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {', '.join(ACTIONS)}")
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    docs = list(orderRepository.find_by_id(oid))
    if not docs:
        raise HTTPException(status_code=404, detail="Order not found")
    doc = docs[0]

    role = _role_of(doc, uid, is_support)
    if role not in ALLOWED_ROLES[action]:
        raise HTTPException(status_code=403, detail=f"A {role} cannot {action}")

    issue = open_issue(doc.get("delivery_failures"))
    if issue is None:
        raise HTTPException(status_code=409, detail="This order has no open issue")

    resolution: Dict[str, Any] = {
        "action": action,
        "by": {"role": role, "uid": uid},
        "note": (note or "").strip() or None,
        "at": datetime.now(timezone.utc),
    }
    status = doc.get("status")

    if action == "fix_and_retry":
        if issue.get("kind") != "delivery":
            raise HTTPException(status_code=409, detail="Only a failed delivery can be fixed and retried")
        fixes = {k: str(v).strip() for k, v in (contact or {}).items()
                 if k in ("address", "phone", "available_from") and v and str(v).strip()}
        if not fixes:
            raise HTTPException(status_code=400, detail="Send at least one of address, phone or available_from")
        sets: Dict[str, Any] = {}
        if "phone" in fixes:
            if not ((doc.get("part_request") or {}).get("delivery_contact") or {}).get("name"):
                raise HTTPException(status_code=409, detail="This order has no delivery contact to correct")
            sets["part_request.delivery_contact.phone"] = fixes["phone"]
        if "address" in fixes:
            sets["part_request.delivery_address.address"] = fixes["address"]
        resolution["contact"] = fixes
        orderRepository.apply_update(oid, set_=sets)

    elif action == "reschedule":
        if new_time is None:
            raise HTTPException(status_code=400, detail="new_time is required")
        when = _parse_time(new_time)
        if new_rider:
            # Validates membership and statuses before anything is resolved.
            OrderService.assign_delivery(order_id=order_id, requesting_user_uid=uid, **new_rider)
            doc = list(orderRepository.find_by_id(oid))[0]
        order = Order(**doc)
        order.change_delivery_time(when, current_deliver_promise_delayed=False)
        order_json = order.toJson()
        orderRepository.apply_update(oid, set_={
            "to_be_delivered_time": order_json["to_be_delivered_time"],
            "updated_at": order_json["updated_at"],
            "current_deliver_promise_delayed": False,
        })

    elif action == "return_to_store":
        if status != "DISPATCHED":
            raise HTTPException(status_code=409, detail="Only a parcel the rider already collected is returned")
        updated = orderRepository.mark_return_requested(oid, issue["id"])
        if updated is None:
            raise HTTPException(status_code=409, detail="This order has no open issue")
        _alert("fanout_issue_resolved", oid, order=Order(**updated).toJson(), action=action, resolution=resolution)
        return Order(**updated).toJson()

    elif action == "confirm_return":
        if not issue.get("return_requested"):
            raise HTTPException(status_code=409, detail="The return was not requested")
        order = Order(**doc)
        order.change_status("READY_TO_BE_DISPATCHED")
        order_json = order.toJson()
        orderRepository.apply_update(
            oid,
            set_={"status": order_json["status"], "status_history": order_json["status_history"],
                  "updated_at": order_json["updated_at"], "ready_at": datetime.now(timezone.utc)},
            unset=["delivery_assignment", "picked_up_at", "picked_up_via", "picked_up_by"],
        )
        PickupCodeService.delete_code(str(oid))

    elif action == "cancel":
        order = Order(**doc)
        order.change_status("CANCELED")
        order_json = order.toJson()
        orderRepository.apply_update(oid, set_={
            "status": order_json["status"], "status_history": order_json["status_history"],
            "updated_at": order_json["updated_at"],
        })
        PickupCodeService.delete_code(str(oid))

    updated = orderRepository.resolve_delivery_failure(oid, issue["id"], resolution)
    if updated is None:
        raise HTTPException(status_code=409, detail="This issue was already resolved")
    result = Order(**updated).toJson()
    if action == "cancel":
        if doc.get("delivery_assignment"):
            # the rider's copy, with picked_up_at intact so the wording says "devuélvela"
            _alert("fanout_delivery_canceled", oid, order={**result, "delivery_assignment": doc["delivery_assignment"]})
    elif action != "confirm_return":
        _alert("fanout_issue_resolved", oid, order=result, action=action, resolution=resolution)
    return result


def _alert(name: str, oid: Any, **kwargs) -> None:
    try:
        getattr(notification_fanout, name)(**kwargs)
    except Exception as exc:
        logger.warning("issue alert %s failed for order %s: %s", name, oid, type(exc).__name__)
