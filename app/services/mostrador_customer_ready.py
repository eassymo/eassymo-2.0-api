"""When a seller folio may be shown to the customer, and what changed after that."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _assigned(doc: dict) -> bool:
    customer = doc.get("customer") or {}
    if customer.get("group_id"):
        return True
    return bool(doc.get("part_request_ids"))


def customer_can_view(doc: dict) -> bool:
    """Legacy shared folios stay visible. New drafts stay hidden until the seller marks them."""
    if doc.get("customer_ready") is True:
        return True
    status = str(doc.get("status") or "")
    if status in {"shared", "confirmed", "closed"}:
        return True
    return _assigned(doc)


def customer_view_only(doc: dict) -> bool:
    """Ready to look at, but not yet in the order flow (Compartir / assignment).

    A WhatsApp draft is never view-only: once the seller shows it, the customer
    claims it and orders like with a shared POS list.
    """
    if doc.get("customer_ready") is not True:
        return False
    if str(doc.get("source") or "") == "whatsapp":
        return False
    if str(doc.get("status") or "") in {"shared", "confirmed", "closed"}:
        return False
    return not _assigned(doc)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _piece_label(piece: dict) -> str:
    return _text(piece.get("name") or piece.get("tipoParteDescripcion")) or "Pieza"


def _option_summary(options: Optional[list]) -> str:
    parts: List[str] = []
    for option in options or []:
        brand = _text(option.get("brand"))
        price = option.get("price")
        if brand and price is not None:
            parts.append(f"{brand} ${price}")
        elif brand:
            parts.append(brand)
        elif price is not None:
            parts.append(f"${price}")
    return ", ".join(parts)


def _piece_changes(old: dict, new: dict) -> List[dict]:
    label = _piece_label(new)
    changes: List[dict] = []
    fields = (
        ("name", "Nombre"),
        ("qty", "Cantidad"),
        ("unitOfMeasure", "Unidad"),
        ("position", "Posición"),
    )
    for key, title in fields:
        before = _text(old.get(key))
        after = _text(new.get(key))
        if before != after:
            changes.append({
                "label": label,
                "detail": f"{title}: {before or '—'} → {after or '—'}",
            })
    before_options = _option_summary(old.get("options"))
    after_options = _option_summary(new.get("options"))
    if before_options != after_options:
        changes.append({
            "label": label,
            "detail": f"Opciones: {before_options or 'sin opciones'} → {after_options or 'sin opciones'}",
        })
    return changes


def _vehicle_changes(before: Optional[dict], after: Optional[dict]) -> List[dict]:
    before = before or {}
    after = after or {}
    changes: List[dict] = []
    fields = (
        ("year", "Año"),
        ("maker", "Marca"),
        ("model", "Modelo"),
        ("engine", "Motor"),
    )
    for key, title in fields:
        old = _text(before.get(key))
        new = _text(after.get(key))
        if old != new:
            changes.append({
                "label": "Vehículo",
                "detail": f"{title}: {old or '—'} → {new or '—'}",
            })
    return changes


def diff_since_ready(
    before_pieces: List[dict],
    after_pieces: List[dict],
    before_vehicle: Optional[dict],
    after_vehicle: Optional[dict],
) -> List[dict]:
    changes: List[dict] = []
    before_by_id = {piece.get("piece_id"): piece for piece in before_pieces}
    after_by_id = {piece.get("piece_id"): piece for piece in after_pieces}
    for piece_id, piece in after_by_id.items():
        previous = before_by_id.get(piece_id)
        if previous is None:
            changes.append({"label": _piece_label(piece), "detail": "Pieza agregada"})
            continue
        changes.extend(_piece_changes(previous, piece))
    for piece_id, previous in before_by_id.items():
        if piece_id not in after_by_id:
            changes.append({"label": _piece_label(previous), "detail": "Pieza eliminada"})
    changes.extend(_vehicle_changes(before_vehicle, after_vehicle))
    return changes


def edition_update(
    doc: dict,
    pieces: List[dict],
    vehicle: Optional[dict],
    *,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Append one edition when the seller changes a list the customer can already see."""
    if doc.get("customer_ready") is not True:
        return None
    baseline = doc.get("customer_visible_baseline") or {}
    changes = diff_since_ready(
        baseline.get("pieces") or [],
        pieces,
        baseline.get("vehicle"),
        vehicle,
    )
    if not changes:
        return None
    stamped = (now or datetime.now(timezone.utc)).isoformat()
    editions = list(doc.get("customer_editions") or [])
    editions.append({"at": stamped, "changes": changes})
    return {
        "customer_editions": editions,
        "customer_visible_baseline": {"pieces": pieces, "vehicle": vehicle},
    }
