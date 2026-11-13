"""Messages inbox: every solicitud and order conversation of a group, unread first."""
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.repositories import ConversationRepository as repo
from app.services.ChatService import _message_is_unread_for_user, _user_group_read_key

FILTERS = ("all", "unread", "request", "order", "waiting")

OPEN_REQUEST_STATUSES = {"Created", "Pending"}
CLOSED_ORDER_STATUSES = {"RECIEVED", "CANCELED", "IN_PERSON_COMPLETED", "IN_PERSON_CANCELED"}

ORDER_STATUS_LABELS = {
    "WAITING_FOR_CONFIRMATION": "Por confirmar",
    "CONFIRMED": "Confirmada",
    "READY_TO_BE_DISPATCHED": "Lista para envío",
    "WAITING_FOR_CUSTOMER_PICKUP": "Lista para recoger",
    "WAITING_FOR_COLLECTION": "Lista para recoger",
    "IN_PERSON_READY_FOR_PICKUP": "Lista para recoger",
    "DISPATCHED": "En camino",
    "RECIEVED": "Entregada",
    "IN_PERSON_COMPLETED": "Entregada",
    "CANCELED": "Cancelada",
    "IN_PERSON_CANCELED": "Cancelada",
    "IN_PERSON_PENDING": "En mostrador",
}

ATTACHMENT_PREVIEW = {"image": "Foto", "video": "Video", "file": "Archivo", "link": "Enlace"}


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sort_key(value: Optional[str]) -> float:
    """Parse ISO strings (with or without Z) to a timestamp; unknown dates sort last."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _request_context(request: dict) -> str:
    part = (request.get("part") or {}).get("tipoParteDescripcion")
    vehicle = request.get("vehicleInformation") or {}
    bits = [str(b) for b in (part, vehicle.get("maker"), vehicle.get("model"), vehicle.get("year")) if b]
    return "Solicitud · " + " ".join(bits) if bits else "Solicitud"


def _order_context(order: dict) -> str:
    label = ORDER_STATUS_LABELS.get(str(order.get("status") or ""), "")
    title = f"Orden #{order.get('order_id') or ''}".rstrip()
    return f"{title} · {label}" if label else title


def _request_is_open(request: dict) -> bool:
    return request.get("isActive", True) is not False and request.get("status") in OPEN_REQUEST_STATUSES


def _last_message(messages: List[dict], group_id: str) -> Optional[Dict[str, Any]]:
    if not messages:
        return None
    last = messages[-1]
    kind = str(last.get("type") or "text")
    text = (last.get("content") or "").strip() or ATTACHMENT_PREVIEW.get(kind, "Mensaje")
    return {
        "kind": kind,
        "text": text,
        "at": _iso(last.get("createdAt")),
        "from_me": str(last.get("groupId") or "") == str(group_id),
    }


def _unread_count(messages: List[dict], uid: str, group_id: str) -> int:
    key = _user_group_read_key(uid, group_id)
    return sum(1 for msg in messages if _message_is_unread_for_user(msg, key, group_id))


def _latest_other_group(messages: List[dict], group_id: str) -> Optional[Dict[str, str]]:
    for msg in reversed(messages):
        sender = str(msg.get("groupId") or "")
        if sender and sender != str(group_id):
            name = (msg.get("metaData") or {}).get("groupName") or ""
            return {"group_id": sender, "name": name}
    return None


def _build_items(group_id: str, uid: str) -> List[Dict[str, Any]]:
    gid = str(group_id)
    requests = {str(r["_id"]): r for r in repo.request_docs_for_group(gid)}
    orders = {str(o["_id"]): o for o in repo.order_docs_for_group(gid)}
    chats = repo.chats_for(requests.keys(), orders.keys())

    creator_ids = {str(r.get("creatorGroup")) for r in requests.values() if str(r.get("creatorGroup")) != gid}
    names = repo.group_names(creator_ids) if creator_ids else {}

    items: List[Dict[str, Any]] = []
    requests_with_messages = set()

    for chat in chats:
        messages = chat.get("messages") or []
        request_id = chat.get("requestId")
        order_id = chat.get("orderId")

        if request_id:
            request = requests.get(str(request_id))
            if not request or not messages:
                continue
            requests_with_messages.add(str(request_id))
            creator = str(request.get("creatorGroup") or "")
            if creator == gid:
                counterpart = _latest_other_group(messages, gid)
            else:
                counterpart = {"group_id": creator, "name": names.get(creator, "")}
            context = _request_context(request)
            if counterpart and not counterpart["name"]:
                counterpart = None
            items.append({
                "id": str(chat.get("_id")),
                "kind": "chat",
                "type": "request",
                "entity_id": str(request_id),
                "counterpart": counterpart,
                "context_title": context,
                "status": request.get("status"),
                "is_closed": not _request_is_open(request),
                "last_message": _last_message(messages, gid),
                "unread_count": _unread_count(messages, uid, gid),
                "activity_at": _iso(messages[-1].get("createdAt")),
            })
        elif order_id:
            order = orders.get(str(order_id))
            if not order or not messages:
                continue
            seller = str((order.get("offer") or {}).get("group_id") or "")
            other = order.get("request_group") if seller == gid else order.get("offer_group")
            other = other or {}
            items.append({
                "id": str(chat.get("_id")),
                "kind": "chat",
                "type": "order",
                "entity_id": str(order_id),
                "counterpart": {"group_id": str(other.get("_id") or ""), "name": other.get("name") or ""} if other.get("name") else None,
                "context_title": _order_context(order),
                "status": order.get("status"),
                "is_closed": str(order.get("status") or "") in CLOSED_ORDER_STATUSES,
                "last_message": _last_message(messages, gid),
                "unread_count": _unread_count(messages, uid, gid),
                "activity_at": _iso(messages[-1].get("createdAt")),
            })

    for rid, request in requests.items():
        if rid in requests_with_messages:
            continue
        if str(request.get("creatorGroup") or "") != gid or not _request_is_open(request):
            continue
        items.append({
            "id": f"waiting-{rid}",
            "kind": "waiting_request",
            "type": "request",
            "entity_id": rid,
            "counterpart": None,
            "context_title": _request_context(request),
            "status": request.get("status"),
            "is_closed": False,
            "last_message": None,
            "unread_count": 0,
            "activity_at": _iso(request.get("createdAt")),
        })

    items.sort(key=lambda i: (i["unread_count"] > 0, _sort_key(i["activity_at"]), i["id"]), reverse=True)
    return items


def _matches(item: Dict[str, Any], filter: str, q: str) -> bool:
    if filter == "unread" and item["unread_count"] <= 0:
        return False
    if filter in ("request", "order") and item["type"] != filter:
        return False
    if filter == "waiting" and item["kind"] != "waiting_request":
        return False
    if q:
        haystack = " ".join([
            (item.get("counterpart") or {}).get("name") or "",
            item.get("context_title") or "",
        ])
        return _normalize(q) in _normalize(haystack)
    return True


def list_conversations(
    group_id: str,
    uid: str,
    filter: str = "all",
    q: str = "",
    cursor: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    items = _build_items(group_id, uid)
    unread_conversations = sum(1 for i in items if i["unread_count"] > 0)
    query = (q or "").strip()
    selected = [i for i in items if _matches(i, filter, query)]
    try:
        offset = max(0, int(cursor)) if cursor else 0
    except ValueError:
        offset = 0
    page = selected[offset:offset + limit]
    next_offset = offset + limit
    return {
        "items": page,
        "next_cursor": str(next_offset) if next_offset < len(selected) else None,
        "unread_conversations": unread_conversations,
    }


def unread_summary(group_id: str, uid: str) -> Dict[str, int]:
    items = _build_items(group_id, uid)
    return {"unread_conversations": sum(1 for i in items if i["unread_count"] > 0)}
