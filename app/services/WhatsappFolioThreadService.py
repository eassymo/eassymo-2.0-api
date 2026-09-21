from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.repositories import MostradorFolioRepository as folioRepository
from app.repositories import WhatsappInboundRepository as inbound_repo

_BURST_GAP_SECONDS = 120


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _last4(from_number: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (from_number or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits or None


def _event_from_doc(doc: dict) -> dict:
    num_media = int(doc.get("num_media") or 0)
    direction = doc.get("direction") or "inbound"
    return {
        "id": str(doc.get("_id") or doc.get("message_sid") or ""),
        "direction": direction,
        "kind": doc.get("kind") or ("content" if direction == "inbound" else "bot_ack"),
        "body": doc.get("body") or "",
        "forwarded": bool(doc.get("forwarded")),
        "created_at": doc.get("created_at"),
        "has_media": num_media > 0 or bool(doc.get("media_urls")),
        "media_count": num_media,
        "linked_reaction": doc.get("linked_reaction"),
    }


def _group_into_bursts(messages: List[dict]) -> List[dict]:
    if not messages:
        return []

    by_burst: Dict[str, List[dict]] = {}
    ordered_burst_ids: List[str] = []
    legacy: List[dict] = []

    for doc in messages:
        burst_id = doc.get("burst_id")
        if burst_id:
            key = str(burst_id)
            if key not in by_burst:
                by_burst[key] = []
                ordered_burst_ids.append(key)
            by_burst[key].append(doc)
        else:
            legacy.append(doc)

    bursts: List[dict] = []
    for burst_id in ordered_burst_ids:
        docs = sorted(
            by_burst[burst_id],
            key=lambda item: _parse_dt(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
        events = [_event_from_doc(doc) for doc in docs]
        started_at = events[0]["created_at"] if events else None
        bursts.append(
            {
                "burst_id": burst_id,
                "started_at": started_at,
                "events": events,
            }
        )

    if legacy:
        current: List[dict] = []
        last_dt: Optional[datetime] = None
        for doc in legacy:
            dt = _parse_dt(doc.get("created_at"))
            if (
                current
                and last_dt
                and dt
                and (dt - last_dt).total_seconds() > _BURST_GAP_SECONDS
            ):
                events = [_event_from_doc(item) for item in current]
                bursts.append(
                    {
                        "burst_id": None,
                        "started_at": events[0]["created_at"] if events else None,
                        "events": events,
                    }
                )
                current = []
            current.append(doc)
            if dt:
                last_dt = dt
        if current:
            events = [_event_from_doc(item) for item in current]
            bursts.append(
                {
                    "burst_id": None,
                    "started_at": events[0]["created_at"] if events else None,
                    "events": events,
                }
            )

    return bursts


def _assert_folio_thread_access(doc: dict, group_id: str) -> None:
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")

    origin = str(doc.get("origin_group_id") or "")
    if origin == str(group_id):
        return

    invited = doc.get("invited_shops") or []
    for shop in invited:
        if str(shop.get("shop_id") or shop.get("group_id") or "") == str(group_id):
            return

    raise HTTPException(status_code=403, detail="Group is not a participant on this folio")


def get_whatsapp_thread(folio_id: str, group_id: str) -> dict:
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    source = doc.get("source")
    if hasattr(source, "value"):
        source = source.value
    if source != "whatsapp":
        raise HTTPException(status_code=404, detail="WhatsApp thread not available for this folio")

    _assert_folio_thread_access(doc, group_id)

    messages = inbound_repo.list_by_folio_id(folio_id)
    from_number = next(
        (msg.get("from_number") for msg in messages if msg.get("from_number")),
        None,
    )

    return {
        "from_number_last4": _last4(from_number),
        "bursts": _group_into_bursts(messages),
    }
