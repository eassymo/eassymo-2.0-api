"""Eassymo support's view of delivery issues (Super Admin). Summaries only: no tokens, no codes."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.repositories import OrderRepository as orderRepository

MAX_LIMIT = 100


def _naive_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _row(order: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    last = order.get("last") or (order.get("delivery_failures") or [{}])[-1]
    assignment = order.get("delivery_assignment") or {}
    at = _naive_utc(last.get("at"))
    rider_name = assignment.get("guest_name") if assignment.get("type") == "guest" else assignment.get("user_name")
    return {
        "order_id": str(order.get("_id")),
        "order_code": order.get("order_id"),
        "status": order.get("status"),
        "part": ((order.get("part_request") or {}).get("part") or {}).get("tipoParteDescripcion"),
        "store": (order.get("offer_group") or {}).get("name"),
        "store_phone": (order.get("offer_group") or {}).get("phone"),
        "buyer": (order.get("request_group") or {}).get("name"),
        "rider": {"name": rider_name or "Sin asignar", "phone": assignment.get("guest_phone")},
        "issue_id": last.get("id"),
        "kind": last.get("kind") or "delivery",
        "reason": last.get("reason"),
        "note": last.get("note"),
        "return_requested": bool(last.get("return_requested")),
        "resolution": last.get("resolution"),
        "at": at.isoformat() + "Z" if at else None,
        "age_minutes": int((now - at).total_seconds() // 60) if at else None,
    }


def list_issues(
    status: str = "open", skip: int = 0, limit: int = 50, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Orders whose last failed attempt is open (default, oldest first) or resolved (newest first)."""
    now = _naive_utc(now) or datetime.utcnow()
    skip = max(0, int(skip))
    limit = min(MAX_LIMIT, max(1, int(limit)))
    open_ = status != "resolved"
    # `last` is the order's last failure; failures recorded before issues existed have no id and never show.
    pipeline = [
        {"$match": {"delivery_failures.0": {"$exists": True}}},
        {"$addFields": {"last": {"$arrayElemAt": ["$delivery_failures", -1]}}},
        {"$match": {"last.id": {"$exists": True}, "last.resolution": None if open_ else {"$ne": None}}},
        {"$sort": {"last.at": 1 if open_ else -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    rows = [_row(o, now) for o in orderRepository.aggregate(pipeline)]
    return {"items": rows, "skip": skip, "limit": limit}
