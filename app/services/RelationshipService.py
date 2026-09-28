from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.factories.NotificationsCreator import create_relationship_review_reminder
from app.repositories import GroupRepository as groupRepository
from app.repositories import OfferRepository as offerRepository
from app.repositories import OrderRepository as orderRepository
from app.repositories import RelationshipRepository as relationshipRepository
from app.repositories import UserRepository as userRepository
from app.schemas.Order import OrderStatus
from app.schemas.Relationship import (
    RelationshipAnswer,
    RelationshipDirection,
    ReminderCadence,
    SaveReminderPrefsRequest,
    SubmitPerceptionRequest,
)
from app.services import NotificationService as notificationService

MEXICO_TZ = ZoneInfo("America/Mexico_City")
COMPLETED_STATUSES = {
    OrderStatus.RECIEVED.value,
    OrderStatus.IN_PERSON_COMPLETED.value,
}
CANCELED_STATUSES = {
    OrderStatus.CANCELED.value,
    OrderStatus.IN_PERSON_CANCELED.value,
}
PRINCIPAL_DAYS = 90
ACTIVITY_DAYS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_valid_object_id(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null", "undefined"}:
        return False
    try:
        ObjectId(normalized)
        return True
    except InvalidId:
        return False


def _normalize_group_id(group_id: Optional[Any]) -> Optional[str]:
    if not _is_valid_object_id(group_id):
        return None
    return str(ObjectId(str(group_id).strip()))


def _lookup_id_variants(value: Optional[Any]) -> List[Any]:
    if value is None:
        return []
    normalized = str(value).strip()
    if not normalized:
        return []
    variants: List[Any] = [normalized]
    try:
        oid = ObjectId(normalized)
        if oid not in variants:
            variants.append(oid)
    except InvalidId:
        pass
    return variants


def _group_field_filter(field: str, group_id: Optional[str]) -> Dict[str, Any]:
    variants = _lookup_id_variants(group_id)
    if not variants:
        return {}
    if len(variants) == 1:
        return {field: variants[0]}
    return {field: {"$in": variants}}


def _parse_datetime_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        text = value.strip().replace(" ", "T")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _order_status_value(order_doc: dict) -> str:
    status_val = order_doc.get("status")
    if hasattr(status_val, "value"):
        return status_val.value
    return str(status_val or "")


def _get_order_participants(order_doc: dict) -> Tuple[Optional[str], Optional[str]]:
    offer = order_doc.get("offer") or {}
    part_request = order_doc.get("part_request") or {}
    buyer_group_id = _normalize_group_id(order_doc.get("group"))
    if not buyer_group_id and isinstance(part_request, dict):
        buyer_group_id = _normalize_group_id(part_request.get("creatorGroup"))
    seller_group_id = _normalize_group_id(offer.get("group_id")) if isinstance(offer, dict) else None
    return buyer_group_id, seller_group_id


def _status_history_at(order_doc: dict, statuses: set[str]) -> Optional[datetime]:
    found: Optional[datetime] = None
    for change in order_doc.get("status_history") or []:
        status_val = change.get("status")
        if hasattr(status_val, "value"):
            status_val = status_val.value
        if status_val in statuses:
            ts = _parse_datetime_value(change.get("timestamp"))
            if ts and (found is None or ts > found):
                found = ts
    return found


def _order_completed_at(order_doc: dict) -> Optional[datetime]:
    completed_at = _status_history_at(order_doc, COMPLETED_STATUSES)
    if completed_at:
        return completed_at
    if _order_status_value(order_doc) in COMPLETED_STATUSES:
        return _parse_datetime_value(order_doc.get("updated_at"))
    return None


def _group_display(group_id: str) -> Dict[str, str]:
    doc = None
    try:
        doc = groupRepository.find_by_id(group_id)
    except Exception:
        doc = None
    name = (doc or {}).get("name") or "Grupo"
    initials = "".join(part[0] for part in str(name).split()[:2]).upper() or "?"
    return {"id": group_id, "name": str(name), "initials": initials[:2]}


def _direction_roles(
    reviewer_group_id: str, order_doc: dict
) -> Optional[RelationshipDirection]:
    buyer_id, seller_id = _get_order_participants(order_doc)
    if not buyer_id or not seller_id or buyer_id == seller_id:
        return None
    if reviewer_group_id == buyer_id:
        return RelationshipDirection.COMPRANDO
    if reviewer_group_id == seller_id:
        return RelationshipDirection.VENDIENDO
    return None


def _counterpart_for(reviewer_group_id: str, order_doc: dict) -> Optional[str]:
    buyer_id, seller_id = _get_order_participants(order_doc)
    if reviewer_group_id == buyer_id:
        return seller_id
    if reviewer_group_id == seller_id:
        return buyer_id
    return None


def _iter_reviewer_orders(reviewer_group_id: str) -> List[dict]:
    buyer_orders = list(
        orderRepository.find(_group_field_filter("group", reviewer_group_id))
    )
    seller_orders = list(
        orderRepository.find(_group_field_filter("offer.group_id", reviewer_group_id))
    )
    seen = set()
    merged: List[dict] = []
    for doc in buyer_orders + seller_orders:
        oid = str(doc.get("_id") or "")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        merged.append(doc)
    return merged


def _is_today(value: Optional[datetime]) -> bool:
    if not value:
        return False
    local = value.astimezone(MEXICO_TZ)
    now_local = _now().astimezone(MEXICO_TZ)
    return local.date() == now_local.date()


def _answer_label(answer: Optional[str]) -> Optional[str]:
    mapping = {
        RelationshipAnswer.BIEN.value: "Bien",
        RelationshipAnswer.REGULAR.value: "Regular",
        RelationshipAnswer.PUEDE_MEJORAR.value: "Puede mejorar",
    }
    return mapping.get(answer or "")


def _build_relationship_rows(
    reviewer_group_id: str,
    direction: RelationshipDirection,
) -> Dict[str, Any]:
    latest = {
        str(doc.get("counterpart_group_id")): doc
        for doc in relationshipRepository.find_latest_perceptions(
            reviewer_group_id, direction.value
        )
    }
    aggregates: Dict[str, Dict[str, Any]] = {}
    for order_doc in _iter_reviewer_orders(reviewer_group_id):
        order_direction = _direction_roles(reviewer_group_id, order_doc)
        if order_direction != direction:
            continue
        counterpart_id = _counterpart_for(reviewer_group_id, order_doc)
        if not counterpart_id:
            continue
        status = _order_status_value(order_doc)
        completed_at = _order_completed_at(order_doc)
        bucket = aggregates.setdefault(
            counterpart_id,
            {
                "latest_completed_at": None,
                "has_completed": False,
            },
        )
        if status in COMPLETED_STATUSES and completed_at:
            bucket["has_completed"] = True
            if bucket["latest_completed_at"] is None or completed_at > bucket["latest_completed_at"]:
                bucket["latest_completed_at"] = completed_at

    rows: List[dict] = []
    now = _now()
    principal_cutoff = now - timedelta(days=PRINCIPAL_DAYS)
    for counterpart_id, bucket in aggregates.items():
        if not bucket["has_completed"]:
            continue
        perception = latest.get(counterpart_id)
        answered_at = _parse_datetime_value((perception or {}).get("created_at"))
        latest_completed = bucket["latest_completed_at"]
        due = answered_at is None or (latest_completed is not None and latest_completed > answered_at)
        answer = (perception or {}).get("answer")
        display = _group_display(counterpart_id)
        rows.append(
            {
                "counterpart_group_id": counterpart_id,
                "counterpart_name": display["name"],
                "counterpart_initials": display["initials"],
                "direction": direction.value,
                "due": due,
                "answer": answer,
                "answer_label": _answer_label(answer) if answer and not due else None,
                "reviewed_today": _is_today(answered_at) and not due,
                "latest_completed_at": latest_completed.isoformat() if latest_completed else None,
                "is_principal": bool(latest_completed and latest_completed >= principal_cutoff),
            }
        )

    rows.sort(key=lambda item: item.get("latest_completed_at") or "", reverse=True)
    principales = [row for row in rows if row["is_principal"]]
    otras = [row for row in rows if not row["is_principal"]]
    due_count = sum(1 for row in rows if row["due"])
    return {
        "direction": direction.value,
        "principales": principales,
        "otras": otras,
        "due_count": due_count,
        "has_due": due_count > 0,
    }


def list_relationships(reviewer_group_id: str, direction: RelationshipDirection) -> Dict[str, Any]:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    if not reviewer_group_id:
        raise HTTPException(status_code=400, detail="Invalid group id")
    return _build_relationship_rows(reviewer_group_id, direction)


def group_has_due_direction(reviewer_group_id: str) -> bool:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    if not reviewer_group_id:
        return False
    buying = _build_relationship_rows(reviewer_group_id, RelationshipDirection.COMPRANDO)
    selling = _build_relationship_rows(reviewer_group_id, RelationshipDirection.VENDIENDO)
    return bool(buying["has_due"] or selling["has_due"])


def submit_perception(
    *,
    user_uid: str,
    reviewer_group_id: str,
    payload: SubmitPerceptionRequest,
) -> dict:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    counterpart_id = _normalize_group_id(payload.counterpart_group_id)
    if not reviewer_group_id or not counterpart_id:
        raise HTTPException(status_code=400, detail="Invalid group id")
    if reviewer_group_id == counterpart_id:
        raise HTTPException(status_code=400, detail="Cannot review the same group")

    found_completed = False
    for order_doc in _iter_reviewer_orders(reviewer_group_id):
        if _direction_roles(reviewer_group_id, order_doc) != payload.direction:
            continue
        if _counterpart_for(reviewer_group_id, order_doc) != counterpart_id:
            continue
        if _order_status_value(order_doc) in COMPLETED_STATUSES:
            found_completed = True
            break
    if not found_completed:
        raise HTTPException(
            status_code=400,
            detail="No completed order exists for this relationship",
        )

    now = _now()
    doc = {
        "reviewer_group_id": reviewer_group_id,
        "counterpart_group_id": counterpart_id,
        "direction": payload.direction.value,
        "answer": payload.answer.value,
        "reviewer_user_id": user_uid,
        "created_at": now,
    }
    relationshipRepository.insert_perception(doc)
    return {
        "counterpart_group_id": counterpart_id,
        "direction": payload.direction.value,
        "answer": payload.answer.value,
        "answer_label": _answer_label(payload.answer.value),
        "created_at": now.isoformat(),
    }


def _doc_created_at(doc: Any) -> Optional[datetime]:
    if not isinstance(doc, dict):
        return None
    return _parse_datetime_value(doc.get("createdAt") if doc.get("createdAt") is not None else doc.get("created_at"))


def _selected_offer_response_minutes(order_doc: dict) -> Optional[float]:
    """Minutes from the part request to the seller's offer that became this order."""
    offer = order_doc.get("offer") or {}
    part_request = order_doc.get("part_request") or {}
    if not isinstance(offer, dict) or not isinstance(part_request, dict):
        return None
    _, seller_id = _get_order_participants(order_doc)
    if not seller_id or _normalize_group_id(offer.get("group_id")) != seller_id:
        return None
    return _minutes_between(_doc_created_at(part_request), _doc_created_at(offer))


def _minutes_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if not start or not end or end < start:
        return None
    return (end - start).total_seconds() / 60.0


def _as_of_ten(ratio: Optional[float]) -> Optional[int]:
    if ratio is None:
        return None
    return max(0, min(10, round(ratio * 10)))


def _offer_price(offer: dict) -> Optional[float]:
    price = offer.get("price")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def get_activity(
    reviewer_group_id: str,
    counterpart_group_id: str,
    direction: RelationshipDirection,
) -> dict:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    counterpart_id = _normalize_group_id(counterpart_group_id)
    if not reviewer_group_id or not counterpart_id:
        raise HTTPException(status_code=400, detail="Invalid group id")

    cutoff = _now() - timedelta(days=ACTIVITY_DAYS)
    display = _group_display(counterpart_id)
    perception = relationshipRepository.find_latest_perception(
        reviewer_group_id, counterpart_id, direction.value
    )

    directional_orders: List[dict] = []
    for order_doc in _iter_reviewer_orders(reviewer_group_id):
        if _direction_roles(reviewer_group_id, order_doc) != direction:
            continue
        if _counterpart_for(reviewer_group_id, order_doc) != counterpart_id:
            continue
        directional_orders.append(order_doc)

    recent_orders = []
    for order_doc in directional_orders:
        created = _parse_datetime_value(order_doc.get("created_at")) or _order_completed_at(order_doc)
        if created and created >= cutoff:
            recent_orders.append(order_doc)

    completed = [o for o in recent_orders if _order_status_value(o) in COMPLETED_STATUSES]
    canceled = [o for o in recent_orders if _order_status_value(o) in CANCELED_STATUSES]
    decided = len(completed) + len(canceled)
    resolution_ratio = (len(completed) / decided) if decided else None

    response_minutes: List[float] = []
    responded = 0
    sample = recent_orders[:10] if recent_orders else directional_orders[:10]

    for order_doc in sample:
        minutes = _selected_offer_response_minutes(order_doc)
        if minutes is not None:
            response_minutes.append(minutes)
            responded += 1

    commercial_hits = 0
    commercial_total = 0
    if direction == RelationshipDirection.COMPRANDO:
        request_ids = []
        for order_doc in sample:
            part_request = order_doc.get("part_request") or {}
            rid = part_request.get("_id") or part_request.get("id")
            if rid:
                request_ids.append(str(rid))
        for request_id in request_ids[:10]:
            offers = list(offerRepository.find({"request_id": request_id}))
            prices = [p for p in (_offer_price(o) for o in offers) if p is not None]
            counterpart_prices = [
                p
                for p, o in ((_offer_price(o), o) for o in offers)
                if p is not None and _normalize_group_id(o.get("group_id")) == counterpart_id
            ]
            if not counterpart_prices or not prices:
                continue
            commercial_total += 1
            if min(counterpart_prices) <= min(prices):
                commercial_hits += 1
    else:
        commercial_total = len(sample)
        commercial_hits = len([o for o in sample if _order_status_value(o) in COMPLETED_STATUSES])

    habitual_minutes = int(round(mean(response_minutes))) if response_minutes else None
    return {
        "counterpart_group_id": counterpart_id,
        "counterpart_name": display["name"],
        "counterpart_initials": display["initials"],
        "direction": direction.value,
        "answer": (perception or {}).get("answer"),
        "answer_label": _answer_label((perception or {}).get("answer")),
        "window_days": ACTIVITY_DAYS,
        "respuesta_habitual": {
            "minutes": habitual_minutes,
            "responded": responded,
            "sample": min(10, len(sample)),
        },
        "resolucion": {
            "of_ten": _as_of_ten(resolution_ratio),
            "completed": len(completed),
            "canceled": len(canceled),
        },
        "oferta_comercial": {
            "of_ten": _as_of_ten((commercial_hits / commercial_total) if commercial_total else None),
            "hits": commercial_hits,
            "sample": commercial_total,
        },
    }


def _default_prefs(uid: str) -> dict:
    return {
        "uid": uid,
        "cadence": ReminderCadence.WEEKLY.value,
        "weekday": 4,
        "hour": 17,
        "minute": 0,
        "last_sent_at": None,
    }


def get_reminder_prefs(uid: str) -> dict:
    stored = relationshipRepository.find_prefs_by_uid(uid)
    prefs = _default_prefs(uid)
    if stored:
        prefs.update(
            {
                "cadence": stored.get("cadence") or prefs["cadence"],
                "weekday": int(stored.get("weekday", 4)),
                "hour": int(stored.get("hour", 17)),
                "minute": int(stored.get("minute", 0)),
                "last_sent_at": stored.get("last_sent_at"),
            }
        )
    prefs["summary"] = reminder_summary(prefs)
    last_sent = _parse_datetime_value(prefs.get("last_sent_at"))
    prefs["last_sent_at"] = last_sent.isoformat() if last_sent else None
    return prefs


def save_reminder_prefs(uid: str, payload: SaveReminderPrefsRequest) -> dict:
    now = _now()
    stored = relationshipRepository.upsert_prefs(
        uid,
        {
            "cadence": payload.cadence.value,
            "weekday": payload.weekday,
            "hour": payload.hour,
            "minute": payload.minute,
            "updated_at": now,
        },
    )
    return get_reminder_prefs(uid) if stored else get_reminder_prefs(uid)


def reminder_summary(prefs: dict) -> str:
    cadence = prefs.get("cadence")
    if cadence == ReminderCadence.OFF.value:
        return "Sin recordatorio"
    weekday_names = (
        "Lunes",
        "Martes",
        "Miércoles",
        "Jueves",
        "Viernes",
        "Sábado",
        "Domingo",
    )
    weekday = int(prefs.get("weekday") or 4)
    hour = int(prefs.get("hour") or 17)
    minute = int(prefs.get("minute") or 0)
    suffix = "p.m." if hour >= 12 else "a.m."
    display_hour = hour % 12 or 12
    time_label = f"{display_hour}:{minute:02d} {suffix}"
    if cadence == ReminderCadence.MONTHLY.value:
        return f"Cada mes · {weekday_names[weekday]} · {time_label}"
    return f"Cada semana · {weekday_names[weekday]} · {time_label}"


def _already_sent_in_window(prefs: dict, now: datetime) -> bool:
    last_sent = _parse_datetime_value(prefs.get("last_sent_at"))
    if not last_sent:
        return False
    cadence = prefs.get("cadence")
    if cadence == ReminderCadence.MONTHLY.value:
        return last_sent >= now - timedelta(days=28)
    return last_sent >= now - timedelta(days=6)


def prefs_match_local_slot(prefs: dict, now: Optional[datetime] = None) -> bool:
    if prefs.get("cadence") == ReminderCadence.OFF.value:
        return False
    local = (now or _now()).astimezone(MEXICO_TZ)
    if int(prefs.get("hour") or 17) != local.hour:
        return False
    if prefs.get("cadence") == ReminderCadence.WEEKLY.value:
        return int(prefs.get("weekday") or 4) == local.weekday()
    if prefs.get("cadence") == ReminderCadence.MONTHLY.value:
        return int(prefs.get("weekday") or 4) == local.weekday() and 1 <= local.day <= 7
    return False


def _groups_for_uid(uid: str) -> List[str]:
    ids: List[str] = []
    user_doc = userRepository.find_one({"uid": uid}) or {}
    for gid in user_doc.get("groups") or []:
        normalized = _normalize_group_id(gid)
        if normalized:
            ids.append(normalized)
    for group in groupRepository.find_by_user(uid):
        normalized = _normalize_group_id(group.get("_id"))
        if normalized:
            ids.append(normalized)
    return list(dict.fromkeys(ids))


def send_due_reminders(now: Optional[datetime] = None) -> dict:
    now = now or _now()
    sent = 0
    skipped = 0
    considered = 0
    for prefs in relationshipRepository.find_all_active_prefs():
        considered += 1
        if not prefs_match_local_slot(prefs, now):
            skipped += 1
            continue
        uid = str(prefs.get("uid") or "")
        if not uid:
            skipped += 1
            continue
        due_groups = [gid for gid in _groups_for_uid(uid) if group_has_due_direction(gid)]
        if not due_groups:
            skipped += 1
            continue
        window_days = 28 if prefs.get("cadence") == ReminderCadence.MONTHLY.value else 6
        if not relationshipRepository.claim_send_slot(uid, now, now - timedelta(days=window_days)):
            skipped += 1
            continue
        for group_id in due_groups:
            notification = create_relationship_review_reminder(
                owner=uid,
                owner_group=group_id,
            )
            notificationService.create(notification)
            sent += 1
    return {"considered": considered, "sent": sent, "skipped": skipped}


def ensure_indexes() -> None:
    relationshipRepository.ensure_indexes()
