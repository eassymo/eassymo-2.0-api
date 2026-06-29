from app.repositories import MostradorFolioRepository as folioRepository
from app.schemas.MostradorFolio import MostradorFolio, FolioStatus, FolioSource
from fastapi import HTTPException
from bson import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from typing import Any, Dict, List, Optional


def _now():
    return datetime.now(ZoneInfo('UTC'))


def _generate_folio_code() -> str:
    """Short human code used by 'Capturar Folio'."""
    return uuid4().hex[-6:].upper()


def _hydrate(doc: dict) -> dict:
    return MostradorFolio(**doc).toJson()


def create(payload: dict, creator_uid: Optional[str], group_id: Optional[str]) -> dict:
    """Seller opens a new folio (Solicitud + -> Nueva)."""
    try:
        folio = MostradorFolio(**payload)
        folio.creator_user = creator_uid
        folio.origin_group_id = folio.origin_group_id or group_id
        folio.folio_code = _generate_folio_code()
        folio.share_token = uuid4().hex
        folio.status = folio.status or FolioStatus.DRAFT
        folio.source = folio.source or FolioSource.COUNTER
        folio.created_at = _now()
        folio.updated_at = _now()

        data = folio.toJson()
        data.pop("_id", None)

        result = folioRepository.insert(data)
        created = folioRepository.find_by_id(str(result.inserted_id))
        return _hydrate(created)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while creating folio {e}")


def list_for_group(group_id: Optional[str]) -> List[dict]:
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    try:
        filters = {
            "$or": [
                {"origin_group_id": group_id},
                {"participant_shops.group_id": group_id},
            ]
        }
        return [_hydrate(d) for d in folioRepository.find(filters)]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while listing folios {e}")


def list_orphans(group_id: Optional[str], limit: int = 20) -> List[dict]:
    """POS folios created at this seller's counter with no linked Eassymo customer."""
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    try:
        docs = folioRepository.find_orphans(group_id, limit=limit)
        return [_hydrate(d) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while listing orphan folios {e}")


def _propagate_customer_to_orders(order_ids: List[str], customer: dict) -> None:
    """Reassign existing Order docs to the linked buyer group after customer link."""
    from app.repositories import OrderRepository as orderRepository
    from app.schemas.Order import Order

    customer_group_id = customer.get("group_id")
    if not customer_group_id:
        return

    customer_uid = customer.get("user_uid")
    for order_id in order_ids or []:
        try:
            order_doc = orderRepository.find_one({"_id": ObjectId(order_id)})
            if not order_doc:
                continue
            order_doc = dict(order_doc)
            order_doc["group"] = str(customer_group_id)
            if customer_uid:
                order_doc["creator_user"] = customer_uid
            part_request = order_doc.get("part_request")
            if isinstance(part_request, dict):
                part_request = {**part_request, "creatorGroup": str(customer_group_id)}
                if customer_uid:
                    part_request["creatorUser"] = customer_uid
                order_doc["part_request"] = part_request
            order = Order(**order_doc)
            order_data = order.toJson()
            order_data.pop("_id", None)
            orderRepository.edit(ObjectId(order_id), order_data)
        except Exception:
            continue


def get(folio_id: str) -> dict:
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    return _hydrate(doc)


def get_by_share_token(share_token: str) -> dict:
    doc = folioRepository.find_by_share_token(share_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    return _hydrate(doc)


def folio_id_by_share_token(share_token: str) -> str:
    doc = folioRepository.find_by_share_token(share_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    return str(doc["_id"])


def folio_and_shop_by_tube_token(tube_token: str):
    """Resolve (folio_id, shop) for a temp-shop tube token."""
    doc = folioRepository.find_by_tube_token(tube_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Tube not found")
    shop = next(
        (s for s in (doc.get("participant_shops") or []) if s.get("tube_token") == tube_token),
        None,
    )
    return str(doc["_id"]), shop, doc


def update_pieces(folio_id: str, pieces: List[dict]) -> dict:
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_seller_folio_editable(doc)
    # validate through schema by round-tripping the whole doc
    merged = {**doc, "pieces": pieces, "updated_at": _now()}
    validated = MostradorFolio(**merged)
    normalized = [p.model_dump() for p in validated.pieces]
    updated = folioRepository.set_pieces(folio_id, normalized, _now())
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def update(folio_id: str, patch: Dict[str, Any]) -> dict:
    """Generic patch of top-level folio fields (vehicle, customer, status, source)."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    if any(k in patch for k in ("pieces", "vehicle")):
        _require_seller_folio_editable(doc)
    allowed = {"vehicle", "customer", "status", "source", "pieces", "participant_shops", "visibility", "part_request_ids", "assignment_with_options"}
    merged = {**doc}
    for key, value in patch.items():
        if key in allowed:
            merged[key] = value
    merged["updated_at"] = _now()
    validated = MostradorFolio(**merged)
    data = validated.toJson()
    data.pop("_id", None)
    updated = folioRepository.edit(folio_id, data)
    return _hydrate(updated)


def _filter_pieces_for_visibility(folio_doc: dict, key: str) -> dict:
    """Return a copy of the folio exposing only pieces allowed for a given visibility key."""
    visibility = folio_doc.get("visibility") or {}
    allowed_ids = visibility.get(key)
    if allowed_ids is None:
        return folio_doc
    pieces = [p for p in (folio_doc.get("pieces") or []) if p.get("piece_id") in allowed_ids]
    return {**folio_doc, "pieces": pieces}


def get_tube(tube_token: str) -> dict:
    """Temp-shop restricted view: only pieces the tube is allowed to quote."""
    doc = folioRepository.find_by_tube_token(tube_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Tube not found")
    scoped = _filter_pieces_for_visibility(doc, tube_token)
    return _hydrate(scoped)


def _option_is_ready(option: dict) -> bool:
    brand = (option.get("brand") or "").strip()
    price = option.get("price")
    return bool(brand) and price is not None and price != ""


def _recompute_piece_status(piece: dict) -> str:
    options = piece.get("options") or []
    if any(o.get("availability_status") == "no_manejo" for o in options) and not any(_option_is_ready(o) for o in options):
        return "no_manejo"
    if any(o.get("availability_status") == "agotada" for o in options) and not any(_option_is_ready(o) for o in options):
        return "agotada"
    if any(_option_is_ready(o) for o in options):
        return "cotizada"
    if options:
        return "cotizando"
    return "pendiente"


def submit_shop_options(
    folio_id: str,
    piece_id: str,
    options: List[dict],
    shop_id: Optional[str],
    shop_name: Optional[str],
    captured_by_buyer: bool = False,
) -> dict:
    """
    Offer Creator: a shop (or buyer-proxy) sets ITS options on a piece. Other shops'
    options on the same piece are preserved (merge by source_shop_id).
    """
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_seller_folio_editable(doc)

    target = next((p for p in (doc.get("pieces") or []) if p.get("piece_id") == piece_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Piece not found")

    # keep options from other shops; drop this shop's previous options
    others = [o for o in (target.get("options") or []) if o.get("source_shop_id") != shop_id]
    incoming = []
    for opt in options:
        tagged = {
            **opt,
            "source_shop_id": shop_id,
            "source_shop_name": shop_name,
            "ready": _option_is_ready(opt),
            "captured_by_buyer": captured_by_buyer,
        }
        if captured_by_buyer and not tagged.get("source_confirmation"):
            tagged["source_confirmation"] = "not_confirmed_by_shop"
        incoming.append(tagged)

    merged_options = others + incoming
    merged_piece = {**target, "options": merged_options}
    new_status = _recompute_piece_status(merged_piece)

    # validate through schema (single piece)
    from app.schemas.MostradorFolio import MostradorPiece
    normalized = MostradorPiece(**{**merged_piece, "status": new_status}).model_dump()

    updated = folioRepository.set_piece_options(
        folio_id, piece_id, normalized["options"], new_status, _now())
    if not updated:
        raise HTTPException(status_code=500, detail="Could not update piece options")
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def invite_shop(
    folio_id: str,
    group_id: Optional[str],
    name: Optional[str],
    eassymo: bool,
    visible_piece_ids: Optional[List[str]],
) -> dict:
    """Add a participant shop. Temp shops (no account) get a tube_token + visibility scope."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_seller_folio_editable(doc)

    tube_token = None if eassymo else uuid4().hex
    shop = {
        "group_id": group_id,
        "name": name,
        "eassymo": eassymo,
        "tube_token": tube_token,
    }

    updated = folioRepository.push_participant_shop(folio_id, shop, visible_piece_ids, _now())

    # apply visibility scope keyed by tube_token (temp shop) or group_id (eassymo shop)
    if visible_piece_ids is not None:
        visibility = dict(updated.get("visibility") or {})
        key = tube_token or group_id
        if key:
            visibility[key] = visible_piece_ids
            updated = folioRepository.edit(folio_id, {"visibility": visibility, "updated_at": _now()})

    return _hydrate(updated)


def _group_name(group_id: Optional[str]) -> str:
    if not group_id:
        return "La tienda"
    try:
        from app.repositories import GroupRepository as groupRepository
        doc = groupRepository.find_by_id(group_id, {"name": 1})
        if doc and doc.get("name"):
            return doc["name"]
    except Exception:
        pass
    return "La tienda"


def share(
    folio_id: str,
    customer: Optional[dict],
    channel: str = "whatsapp",
    whatsapp_phone: Optional[str] = None,
) -> dict:
    """
    Mark a folio as shared with the customer. Persists customer info, ensures a share_token,
    and returns share links + an in-app notification descriptor (dispatched client-side,
    matching the app's existing notification pattern) when the customer is an existing user.
    """
    import os
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    share_token = doc.get("share_token") or uuid4().hex
    patch: Dict[str, Any] = {
        "share_token": share_token,
        "status": FolioStatus.SHARED.value,
        "updated_at": _now(),
    }
    existing_customer = doc.get("customer") or {}
    existing_group_id = existing_customer.get("group_id")
    if customer and not existing_group_id:
        patch["customer"] = customer
    elif customer and existing_group_id:
        # Re-share link for end customer without breaking buyer business assignment.
        patch["customer"] = existing_customer

    updated = folioRepository.edit(folio_id, patch)

    share_path = f"/folio/{share_token}"
    base_url = (os.getenv("CLIENT_BASE_URL") or "").rstrip("/")
    share_url = f"{base_url}{share_path}" if base_url else share_path

    store_name = _group_name(doc.get("origin_group_id"))
    wa_text = f"{store_name} te compartió tu cotización en Eassymo: {share_url}"
    whatsapp_url = None
    phone = (
        whatsapp_phone
        or (customer or {}).get("phone")
        or existing_customer.get("phone")
    )
    if phone:
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        from urllib.parse import quote
        whatsapp_url = f"https://wa.me/{digits}?text={quote(wa_text)}"

    notification = None
    cust = customer or existing_customer or {}
    if cust.get("type") == "eassymo" and cust.get("user_uid") and cust.get("group_id"):
        from app.factories import NotificationsCreator
        notif = NotificationsCreator.create_mostrador_folio_shared_notification(
            store_name=store_name,
            owner=cust["user_uid"],
            owner_group=cust["group_id"],
            navigate_to_url=share_path,
            meta_data={"folioId": folio_id, "shareToken": share_token},
        )
        notif_dict = notif.model_dump()
        if hasattr(notif_dict.get("type"), "value"):
            notif_dict["type"] = notif_dict["type"].value
        notification = notif_dict

    return {
        "folio": _hydrate(updated),
        "share_token": share_token,
        "share_path": share_path,
        "share_url": share_url,
        "whatsapp_url": whatsapp_url,
        "notification": notification,
    }


def order_piece(
    folio_id: str,
    piece_id: str,
    option_index: int,
    delivery_mode: str = "tienda",
    *,
    allow_when_assigned: bool = False,
) -> dict:
    """Buyer/seller orders a piece by choosing one of its options (embedded order)."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    if not allow_when_assigned:
        _require_seller_folio_editable(doc)
    target = next((p for p in (doc.get("pieces") or []) if p.get("piece_id") == piece_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Piece not found")
    options = target.get("options") or []
    if option_index < 0 or option_index >= len(options):
        raise HTTPException(status_code=400, detail="Invalid option_index")
    chosen = options[option_index]
    if not _option_is_ready(chosen):
        raise HTTPException(status_code=400, detail="Option is not orderable (missing brand/price)")

    order = {
        "option_index": option_index,
        "delivery_mode": delivery_mode or "tienda",
        "shop_id": chosen.get("source_shop_id"),
        "shop_name": chosen.get("source_shop_name"),
        "status": "ordenada",
        "ordered_at": _now(),
        "order_doc_id": None,
    }
    from app.schemas.MostradorFolio import MostradorPieceOrder
    normalized = MostradorPieceOrder(**order).model_dump()
    updated = folioRepository.set_piece_order(folio_id, piece_id, normalized, _now())
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def unorder_piece(
    folio_id: str,
    piece_id: str,
    *,
    allow_when_assigned: bool = False,
) -> dict:
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    if not allow_when_assigned:
        _require_seller_folio_editable(doc)
    updated = folioRepository.set_piece_order(folio_id, piece_id, None, _now())
    if not updated:
        raise HTTPException(status_code=404, detail="Piece not found")
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def _resolve_taller_group_for_user(user_doc: dict) -> Optional[dict]:
    """Return the user's first taller (buyer, type=2) group, if any."""
    from app.repositories import GroupRepository as groupRepository
    group_ids = user_doc.get("groups") or []
    for gid in group_ids:
        try:
            g = groupRepository.find_by_id(str(gid))
        except Exception:
            g = None
        if g and g.get("type") == 2:
            return g
    return None


def link_existing_customer(folio_id: str, phone: str) -> dict:
    """Seller links an existing Eassymo customer by phone; attaches their taller group."""
    from app.repositories import UserRepository as userRepository
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")

    user = userRepository.find_by_phone(phone)
    if not user:
        raise HTTPException(status_code=404, detail="No Eassymo customer found with that phone")

    taller = _resolve_taller_group_for_user(user)
    customer = {
        "type": "eassymo",
        "name": user.get("name"),
        "phone": phone,
        "user_uid": user.get("uid"),
        "group_id": str(taller["_id"]) if taller else None,
    }
    updated = folioRepository.edit(folio_id, {"customer": customer, "updated_at": _now()})
    _propagate_customer_to_orders(doc.get("order_ids") or [], customer)
    return _hydrate(updated)


def claim_account(
    folio_id: str,
    uid: str,
    name: Optional[str],
    phone: Optional[str],
    group_name: Optional[str],
) -> dict:
    """
    Provision a real Eassymo customer (taller buyer) for a folio.
    The Firebase user is created client-side (OTP). Here we ensure the User doc + a
    taller (type=2) Group exist, link them, and attach the customer to the folio.
    Works for self-serve (customer signed in) and seller-initiated (seller passes the
    customer's freshly-created uid).
    """
    from app.repositories import UserRepository as userRepository
    from app.repositories import GroupRepository as groupRepository
    from app.repositories import UserRolesRepository
    from app.schemas.UserRoles import UserRoles as UserRolesSchema

    if not uid:
        raise HTTPException(status_code=400, detail="uid is required to create an account")

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    # ensure user doc
    user = userRepository.find_one({"uid": uid})
    if not user:
        userRepository.insert_user({
            "uid": uid,
            "name": name,
            "phone": phone,
            "email": "",
            "roles": [],
            "groups": [],
        })

    # ensure a taller (buyer) group
    taller = None
    fresh_user = userRepository.find_one({"uid": uid}) or {}
    taller = _resolve_taller_group_for_user(fresh_user)
    if not taller:
        group_payload = {
            "name": group_name or (name and f"Taller {name}") or "Mi taller",
            "type": 2,
            "country": "Mexico",
            "isActive": True,
            "owner": uid,
            "users": [uid],
        }
        result = groupRepository.insert(group_payload)
        group_id = str(result.inserted_id)
        userRepository.add_user_group(uid, group_id)
        try:
            UserRolesRepository.insert(UserRolesSchema(
                user_uid=uid, role="212", group=group_id, active=True))
        except Exception:
            pass
        taller = groupRepository.find_by_id(group_id)

    group_id = str(taller["_id"]) if taller else None
    customer = {
        "type": "eassymo",
        "name": name or (taller or {}).get("name"),
        "phone": phone,
        "user_uid": uid,
        "group_id": group_id,
    }
    updated = folioRepository.edit(folio_id, {"customer": customer, "updated_at": _now()})
    _propagate_customer_to_orders(doc.get("order_ids") or [], customer)
    return {"folio": _hydrate(updated), "group_id": group_id}


def _piece_display_name(piece: dict) -> str:
    return (
        piece.get("tipoParteDescripcion")
        or piece.get("name")
        or "Pieza"
    )


def _folio_part_payload(piece: dict, unit: Optional[str] = None) -> dict:
    u = unit or piece.get("unitOfMeasure") or "Pieza"
    return {
        "tipoParteId": piece.get("tipoParteId"),
        "tipoParteDescripcion": _piece_display_name(piece),
        "categoriaId": piece.get("categoriaId"),
        "subCategoriaId": piece.get("subCategoriaId"),
        "quantity": piece.get("qty", 1),
        "unitOfMeasure": u,
        "position": piece.get("position"),
        "comments": piece.get("comments"),
    }


def _seller_group_for_piece(folio: dict, piece: dict) -> Optional[str]:
    order_info = piece.get("order") or {}
    options = piece.get("options") or []
    option_index = order_info.get("option_index")
    if option_index is not None and 0 <= option_index < len(options):
        sid = options[option_index].get("source_shop_id")
        if sid:
            return str(sid)
    for opt in options:
        if opt.get("ready") and opt.get("source_shop_id"):
            return str(opt["source_shop_id"])
    origin = folio.get("origin_group_id")
    return str(origin) if origin else None


def _resolve_buyer_uid_for_group(group: dict) -> Optional[str]:
    owner = group.get("owner")
    if owner:
        return str(owner)
    users = group.get("users") or []
    return str(users[0]) if users else None


_DISCARDED_PIECE_STATUSES = {"agotada", "no_manejo"}


def _materializable_pieces(folio: dict) -> List[dict]:
    pieces = folio.get("pieces") or []
    return [p for p in pieces if p.get("piece_id") and p.get("status") not in _DISCARDED_PIECE_STATUSES]


def _assignment_context(doc: dict) -> Optional[tuple]:
    customer = doc.get("customer") or {}
    group_id = customer.get("group_id")
    buyer_uid = customer.get("user_uid")
    if not group_id or not buyer_uid:
        return None
    return str(group_id), str(buyer_uid)


def _is_assigned_to_buyer(doc: dict) -> bool:
    customer = doc.get("customer") or {}
    if customer.get("group_id"):
        return True
    return bool(doc.get("part_request_ids"))


def _require_seller_folio_editable(doc: dict) -> None:
    if _is_assigned_to_buyer(doc):
        raise HTTPException(
            status_code=403,
            detail="Este folio ya fue asignado a un comprador y ya no puede editarse desde mostrador",
        )


def _offer_match_key(brand: Optional[str], code: Optional[str], group_id: Optional[str]) -> tuple:
    return (
        (brand or "").strip().lower(),
        (code or "").strip().lower(),
        str(group_id or ""),
    )


def _option_match_key(option: dict, fallback_group: str = "") -> tuple:
    return _offer_match_key(
        option.get("brand"),
        option.get("code"),
        option.get("source_shop_id") or fallback_group,
    )


def _load_vehicle_information(vehicle: dict):
    from app.repositories import GroupCarRepository as groupCarRepository

    vehicle_id = str(vehicle.get("group_vehicle_id") or "")
    if not vehicle_id:
        return None
    try:
        return groupCarRepository.find_by_id(vehicle_id)
    except Exception:
        return None


def _relink_order_for_piece(
    order_doc_id: str,
    pr_id: str,
    buyer_group_id: str,
    buyer_uid: str,
    folio_id: str,
    piece_id: str,
) -> None:
    from app.repositories import OrderRepository as orderRepository
    from app.schemas.Order import Order

    order_doc = orderRepository.find_one({"_id": ObjectId(order_doc_id)})
    if not order_doc:
        return
    order_doc = dict(order_doc)
    order_doc["group"] = str(buyer_group_id)
    order_doc["creator_user"] = buyer_uid
    pr_embed = dict(order_doc.get("part_request") or {})
    pr_embed["creatorGroup"] = str(buyer_group_id)
    pr_embed["creatorUser"] = buyer_uid
    pr_embed["_id"] = pr_id
    pr_embed["id"] = pr_id
    pr_embed["origin"] = "mostrador"
    pr_embed["mostrador_folio_id"] = folio_id
    pr_embed["mostrador_piece_id"] = piece_id
    order_doc["part_request"] = pr_embed
    offer_embed = dict(order_doc.get("offer") or {})
    offer_embed["request_id"] = pr_id
    order_doc["offer"] = offer_embed
    order = Order(**order_doc)
    order_data = order.toJson()
    order_data.pop("_id", None)
    orderRepository.edit(ObjectId(order_doc_id), order_data)


def _ensure_part_request_for_piece(
    folio: dict,
    piece: dict,
    buyer_group_id: str,
    buyer_uid: str,
    folio_id: str,
) -> str:
    from app.repositories import PartRequestRepository as partRequestRepository
    from app.schemas.PartRequest import PartRequestStatus, FulfillmentType

    piece_id = piece.get("piece_id")
    existing = list(partRequestRepository.find(
        {"mostrador_folio_id": folio_id, "mostrador_piece_id": piece_id}, {}
    ))
    seller_group_id = _seller_group_for_piece(folio, piece)
    unit = piece.get("unitOfMeasure") or "Pieza"
    specific_order_uid = folio.get("specific_order_uid") or uuid4().hex
    vehicle = folio.get("vehicle") or {}
    vehicle_id = str(vehicle.get("group_vehicle_id") or "")
    order_info = piece.get("order") or {}
    is_ordered = bool(order_info.get("order_doc_id") or order_info.get("option_index") is not None)
    pr_status = (
        PartRequestStatus.OFFER_SELECTED.value
        if is_ordered and order_info.get("order_doc_id")
        else PartRequestStatus.CREATED.value
    )
    part_payload = _folio_part_payload(piece, unit)
    subscribed = [seller_group_id] if seller_group_id else []
    now = _now()

    if existing:
        pr_id = str(existing[0]["_id"])
        patch = {
            "part": part_payload,
            "subscribedSellers": subscribed,
            "status": pr_status,
            "isActive": True,
            "updatedAt": now,
        }
        partRequestRepository.edit_part_request(pr_id, patch)
        return pr_id

    pr_payload = {
        "creatorGroup": str(buyer_group_id),
        "creatorUser": buyer_uid,
        "vehicleId": vehicle_id,
        "part": part_payload,
        "partList": [],
        "parent_request_uid": "",
        "status": pr_status,
        "specific_order_uid": specific_order_uid,
        "subscribedSellers": subscribed,
        "isActive": True,
        "fulfillment_type": FulfillmentType.pickup.value,
        "origin": "mostrador",
        "mostrador_folio_id": folio_id,
        "mostrador_piece_id": piece_id,
        "createdAt": now,
        "updatedAt": now,
    }
    vehicle_information = _load_vehicle_information(vehicle)
    if vehicle_information:
        pr_payload["vehicleInformation"] = vehicle_information

    result = partRequestRepository.insert(pr_payload)
    return str(result.inserted_id)


def _sync_offers_for_piece(
    pr_id: str,
    folio: dict,
    piece: dict,
    seller_uid: str,
    folio_id: str,
) -> None:
    from app.repositories import PartRequestRepository as partRequestRepository
    from app.repositories import OfferRepository as offerRepository
    from app.schemas.PartRequest import PartRequestStatus
    from app.schemas.Offer import Offer, OfferStatus

    piece_id = piece.get("piece_id")
    seller_group_id = _seller_group_for_piece(folio, piece) or ""
    unit = piece.get("unitOfMeasure") or "Pieza"
    order_info = piece.get("order") or {}
    ordered_option_index = order_info.get("option_index")
    is_ordered = ordered_option_index is not None

    existing_offers = list(offerRepository.find({
        "request_id": pr_id,
        "origin": "mostrador",
        "mostrador_piece_id": piece_id,
    }, {}))

    protected_keys: set = set()
    protected_ids: List[str] = []
    for offer in existing_offers:
        status = offer.get("status")
        status_val = status.value if hasattr(status, "value") else status
        if status_val == OfferStatus.selected.value:
            protected_keys.add(_offer_match_key(
                offer.get("brand"), offer.get("code"), offer.get("group_id")))
            protected_ids.append(str(offer["_id"]))

    delete_filter = {
        "request_id": pr_id,
        "origin": "mostrador",
        "mostrador_piece_id": piece_id,
    }
    if protected_ids:
        delete_filter["_id"] = {"$nin": [ObjectId(oid) for oid in protected_ids]}
    offerRepository.delete_many(delete_filter)

    has_selected = len(protected_ids) > 0
    options = piece.get("options") or []
    for idx, option in enumerate(options):
        if not option.get("ready"):
            continue
        opt_seller = str(option.get("source_shop_id") or seller_group_id or "")
        key = _option_match_key(option, seller_group_id)
        if key in protected_keys:
            continue
        offer_status = OfferStatus.selected.value if (
            is_ordered and idx == ordered_option_index
        ) else OfferStatus.created.value
        if offer_status == OfferStatus.selected.value:
            has_selected = True
        offer = Offer(
            request_id=pr_id,
            user_uid=seller_uid,
            group_id=opt_seller,
            brand=option.get("brand"),
            guarantee=option.get("guarantee"),
            price=option.get("price"),
            unit_of_measure=option.get("unit_of_measure") or unit,
            code=option.get("code"),
            photos=option.get("photos") or [],
            internalComments=option.get("note"),
            publicComments=option.get("note"),
            status=offer_status,
            origin="mostrador",
            mostrador_folio_id=folio_id,
            mostrador_piece_id=piece_id,
        )
        offer_data = offer.toJson()
        offer_data.pop("_id", None)
        offerRepository.insert(offer_data)

    pr_status = (
        PartRequestStatus.OFFER_SELECTED.value
        if has_selected or (is_ordered and order_info.get("order_doc_id"))
        else PartRequestStatus.CREATED.value
    )
    partRequestRepository.edit_part_request(pr_id, {
        "status": pr_status,
        "updatedAt": _now(),
    })


def _deactivate_piece_projection(
    folio_id: str,
    piece_id: str,
    piece: Optional[dict] = None,
) -> None:
    from app.repositories import PartRequestRepository as partRequestRepository
    from app.repositories import OfferRepository as offerRepository
    from app.schemas.Offer import OfferStatus

    existing = list(partRequestRepository.find(
        {"mostrador_folio_id": folio_id, "mostrador_piece_id": piece_id}, {}
    ))
    if not existing:
        return
    pr = existing[0]
    pr_id = str(pr["_id"])
    order_info = (piece or {}).get("order") or {}
    if order_info.get("order_doc_id"):
        return

    offers = list(offerRepository.find({
        "request_id": pr_id,
        "origin": "mostrador",
        "mostrador_piece_id": piece_id,
    }, {}))
    for offer in offers:
        status = offer.get("status")
        status_val = status.value if hasattr(status, "value") else status
        if status_val == OfferStatus.selected.value:
            return

    offerRepository.delete_many({
        "request_id": pr_id,
        "origin": "mostrador",
        "mostrador_piece_id": piece_id,
    })
    partRequestRepository.edit_part_request(pr_id, {"isActive": False, "updatedAt": _now()})


def sync_assigned_folio(folio_id: str) -> None:
    """Project folio pieces/options to buyer PartRequests + Offers when assigned."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        return
    ctx = _assignment_context(doc)
    if not ctx:
        return

    buyer_group_id, buyer_uid = ctx
    folio_id_str = str(doc["_id"])
    seller_uid = doc.get("creator_user") or ""
    pr_ids: List[str] = []
    current_piece_ids: set = set()

    for piece in doc.get("pieces") or []:
        piece_id = piece.get("piece_id")
        if not piece_id:
            continue
        current_piece_ids.add(piece_id)

        if piece.get("status") in _DISCARDED_PIECE_STATUSES:
            _deactivate_piece_projection(folio_id_str, piece_id, piece)
            continue

        pr_id = _ensure_part_request_for_piece(
            doc, piece, buyer_group_id, buyer_uid, folio_id_str)
        pr_ids.append(pr_id)
        _sync_offers_for_piece(pr_id, doc, piece, seller_uid, folio_id_str)

        order_doc_id = (piece.get("order") or {}).get("order_doc_id")
        if order_doc_id:
            _relink_order_for_piece(
                order_doc_id, pr_id, buyer_group_id, buyer_uid, folio_id_str, piece_id)

    from app.repositories import PartRequestRepository as partRequestRepository

    orphaned = list(partRequestRepository.find(
        {"mostrador_folio_id": folio_id_str, "isActive": True}, {}
    ))
    for pr in orphaned:
        pid = pr.get("mostrador_piece_id")
        if pid and pid not in current_piece_ids:
            _deactivate_piece_projection(folio_id_str, pid)

    all_prs = list(partRequestRepository.find({"mostrador_folio_id": folio_id_str}, {}))
    active_pr_ids = [str(p["_id"]) for p in all_prs if p.get("isActive", True)]
    folioRepository.edit(folio_id, {
        "part_request_ids": active_pr_ids,
        "updated_at": _now(),
    })


def _materialize_part_requests_for_folio(
    folio: dict,
    buyer_group_id: str,
    buyer_uid: str,
    with_options: bool,
    folio_id: str,
) -> List[str]:
    """Assignment-time projection: ensure PRs; optionally push initial offers snapshot."""
    created_ids: List[str] = []
    seller_uid = folio.get("creator_user") or ""

    for piece in _materializable_pieces(folio):
        piece_id = piece.get("piece_id")
        pr_id = _ensure_part_request_for_piece(
            folio, piece, buyer_group_id, buyer_uid, folio_id)
        created_ids.append(pr_id)

        if with_options:
            _sync_offers_for_piece(pr_id, folio, piece, seller_uid, folio_id)

        order_doc_id = (piece.get("order") or {}).get("order_doc_id")
        if order_doc_id:
            _relink_order_for_piece(
                order_doc_id, pr_id, buyer_group_id, buyer_uid, folio_id, piece_id)

    return created_ids


def assign_to_group(folio_id: str, group_id: str, with_options: bool = True) -> dict:
    """Assign a POS folio to a buyer business group and materialize PartRequests."""
    from app.repositories import GroupRepository as groupRepository

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")

    if not _materializable_pieces(doc):
        raise HTTPException(
            status_code=400,
            detail="Agrega al menos una pieza antes de asignar",
        )

    existing_customer = doc.get("customer") or {}
    existing_group_id = existing_customer.get("group_id")
    existing_pr_ids = doc.get("part_request_ids") or []
    was_already_assigned = bool(existing_group_id)
    if existing_group_id and str(existing_group_id) != str(group_id):
        raise HTTPException(
            status_code=409,
            detail="El folio ya fue asignado a un comprador",
        )
    if not existing_group_id and existing_pr_ids:
        raise HTTPException(
            status_code=409,
            detail="El folio ya fue asignado a un comprador",
        )

    group = groupRepository.find_by_id(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    buyer_uid = _resolve_buyer_uid_for_group(group)
    if not buyer_uid:
        raise HTTPException(status_code=400, detail="Could not resolve a user for the target group")

    folio_id_str = str(doc["_id"])
    pr_ids = _materialize_part_requests_for_folio(
        doc, group_id, buyer_uid, with_options, folio_id_str)

    customer = {
        "type": "eassymo",
        "name": group.get("name"),
        "phone": group.get("phone") or group.get("whatsAppNumber"),
        "user_uid": buyer_uid,
        "group_id": group_id,
    }
    _propagate_customer_to_orders(doc.get("order_ids") or [], customer)

    merged_pr_ids = list({*(doc.get("part_request_ids") or []), *pr_ids})
    specific_order_uid = doc.get("specific_order_uid") or uuid4().hex
    new_status = doc.get("status")
    if new_status not in (FolioStatus.CONFIRMED.value, FolioStatus.CLOSED.value):
        new_status = FolioStatus.SHARED.value

    updated = folioRepository.edit(folio_id, {
        "customer": customer,
        "status": new_status,
        "part_request_ids": merged_pr_ids,
        "specific_order_uid": specific_order_uid,
        "assignment_with_options": with_options,
        "updated_at": _now(),
    })
    refreshed = folioRepository.find_by_id(folio_id)
    notification = None
    if buyer_uid and not was_already_assigned:
        from app.factories import NotificationsCreator

        store_name = _group_name(doc.get("origin_group_id"))
        piece_count = len(_materializable_pieces(refreshed or doc))
        first_pr_id = merged_pr_ids[0] if merged_pr_ids else None
        navigate_to_url = (
            f"/dynamic-offer-selector/{specific_order_uid}"
            if specific_order_uid
            else "/dashboard-v2"
        )
        notif = NotificationsCreator.create_mostrador_folio_assigned_notification(
            store_name=store_name,
            piece_count=piece_count,
            owner=buyer_uid,
            owner_group=str(group_id),
            navigate_to_url=navigate_to_url,
            meta_data={
                "folioId": folio_id_str,
                "requestId": first_pr_id,
                "partRequestIds": merged_pr_ids,
                "parentRequestUid": specific_order_uid,
                "originGroupId": str(doc.get("origin_group_id") or ""),
            },
        )
        notif_dict = notif.model_dump()
        if hasattr(notif_dict.get("type"), "value"):
            notif_dict["type"] = notif_dict["type"].value
        notification = notif_dict

    return {"folio": _hydrate(refreshed), "part_request_ids": pr_ids, "notification": notification}


def _build_order_for_piece(folio: dict, piece: dict, specific_order_uid: str, folio_id: str):
    """Build an embed-only Order (Offer + PartRequest) for one confirmed piece."""
    from app.schemas.Order import Order, OrderStatus, StatusChange
    from app.schemas.Offer import Offer, OfferStatus
    from app.schemas.PartRequest import PartRequest, FulfillmentType

    order_info = piece.get("order") or {}
    options = piece.get("options") or []
    option_index = order_info.get("option_index")
    if option_index is None or option_index < 0 or option_index >= len(options):
        return None
    option = options[option_index]

    seller_group_id = option.get("source_shop_id") or folio.get("origin_group_id")
    customer = folio.get("customer") or {}
    customer_group_id = customer.get("group_id") or folio.get("origin_group_id")
    customer_uid = customer.get("user_uid") or folio.get("creator_user")
    unit = option.get("unit_of_measure") or piece.get("unitOfMeasure") or "Pieza"

    offer = Offer(
        request_id=f"mostrador:{folio_id}:{piece.get('piece_id')}",
        user_uid=folio.get("creator_user") or "",
        group_id=str(seller_group_id) if seller_group_id else "",
        brand=option.get("brand"),
        guarantee=option.get("guarantee"),
        price=option.get("price"),
        unit_of_measure=unit,
        code=option.get("code"),
        photos=option.get("photos") or [],
        internalComments=option.get("note"),
        publicComments=option.get("note"),
        status=OfferStatus.selected.value,
    )

    vehicle = folio.get("vehicle") or {}
    part = _folio_part_payload(piece, unit)

    part_request = PartRequest(
        creatorGroup=str(customer_group_id) if customer_group_id else "",
        creatorUser=customer_uid or "",
        vehicleId=str(vehicle.get("group_vehicle_id") or ""),
        subscribedSellers=[str(seller_group_id)] if seller_group_id else [],
        part=part,
        partList=[],
        specific_order_uid=specific_order_uid,
        fulfillment_type=FulfillmentType.pickup,
    )

    order = Order(
        offer=offer,
        part_request=part_request,
        status=OrderStatus.IN_PERSON_PENDING,
        status_history=[StatusChange(
            status=OrderStatus.IN_PERSON_PENDING, timestamp=_now())],
        creator_user=folio.get("creator_user") or "",
        group=str(customer_group_id) if customer_group_id else str(seller_group_id or ""),
        origin="mostrador",
        mostrador_folio_id=folio_id,
    )
    return order


def confirm(folio_id: str, *, allow_when_assigned: bool = False) -> dict:
    """
    Turn confirmed (ordered) pieces into real in-person Orders. One Order per ordered
    piece, all grouped by a shared specific_order_uid + the folio id. Embed-only:
    no separate Offers/PartRequests documents are inserted.
    """
    from app.repositories import OrderRepository as orderRepository
    from app.schemas.Order import Order

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    if not allow_when_assigned:
        _require_seller_folio_editable(doc)

    ordered_pieces = [p for p in (doc.get("pieces") or []) if p.get("order")]
    if not ordered_pieces:
        raise HTTPException(status_code=400, detail="No ordered pieces to confirm")

    specific_order_uid = doc.get("specific_order_uid") or uuid4().hex
    created_ids: List[str] = []
    pieces = [dict(p) for p in (doc.get("pieces") or [])]
    notifications: List[dict] = []
    store_name = _group_name(doc.get("origin_group_id"))

    for piece in pieces:
        if not piece.get("order"):
            continue
        if piece["order"].get("order_doc_id"):
            continue  # already created
        order = _build_order_for_piece(doc, piece, specific_order_uid, folio_id)
        if order is None:
            continue
        order_data = order.toJson()
        order_data.pop("_id", None)
        result = orderRepository.insert(order_data)
        order_doc_id = str(result.inserted_id)
        created_ids.append(order_doc_id)
        piece["order"] = {**piece["order"], "order_doc_id": order_doc_id, "status": "confirmada"}

        customer = doc.get("customer") or {}
        if customer.get("type") == "eassymo" and customer.get("user_uid") and customer.get("group_id"):
            from app.factories import NotificationsCreator
            notif = NotificationsCreator.create_mostrador_order_created_notification(
                store_name=store_name,
                part_name=_piece_display_name(piece),
                order_id=order.order_id,
                owner=customer["user_uid"],
                owner_group=customer["group_id"],
                navigate_to_url="/order-management-v2",
                meta_data={"orderId": order_doc_id, "folioId": folio_id},
            )
            nd = notif.model_dump()
            if hasattr(nd.get("type"), "value"):
                nd["type"] = nd["type"].value
            notifications.append(nd)

    updated = folioRepository.edit(folio_id, {
        "pieces": pieces,
        "status": FolioStatus.CONFIRMED.value,
        "specific_order_uid": specific_order_uid,
        "order_ids": (doc.get("order_ids") or []) + created_ids,
        "updated_at": _now(),
    })

    return {
        "folio": _hydrate(updated),
        "order_ids": created_ids,
        "specific_order_uid": specific_order_uid,
        "notifications": notifications,
    }


def complete_in_person_delivery(folio_id: str) -> dict:
    """
    Mark all ordered pieces on a folio as delivered (entregada).
    Confirms the folio first when real Order docs have not been created yet.
    """
    from app.repositories import OrderRepository as orderRepository
    from app.schemas.Order import Order, OrderStatus

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_seller_folio_editable(doc)

    ordered = [p for p in (doc.get("pieces") or []) if p.get("order")]
    if not ordered:
        raise HTTPException(status_code=400, detail="No ordered pieces to deliver")

    if doc.get("status") != FolioStatus.CONFIRMED.value:
        confirm(folio_id)
        doc = folioRepository.find_by_id(folio_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Folio not found")

    pieces = [dict(p) for p in (doc.get("pieces") or [])]
    delivered_count = 0
    for piece in pieces:
        order_embed = piece.get("order")
        if not order_embed or order_embed.get("status") == "entregada":
            continue
        order_doc_id = order_embed.get("order_doc_id")
        if order_doc_id:
            order_doc = orderRepository.find_one({"_id": ObjectId(order_doc_id)})
            if order_doc:
                order = Order(**order_doc)
                order.change_status(OrderStatus.IN_PERSON_COMPLETED.name)
                order_data = order.toJson()
                order_data.pop("_id", None)
                orderRepository.edit(ObjectId(order_doc_id), order_data)
        piece["order"] = {**order_embed, "status": "entregada"}
        delivered_count += 1

    if delivered_count == 0:
        raise HTTPException(status_code=400, detail="All ordered pieces are already delivered")

    updated = folioRepository.edit(folio_id, {"pieces": pieces, "updated_at": _now()})
    return {"folio": _hydrate(updated), "delivered_count": delivered_count}


def confirm_pickup(
    order_id: str,
    signature_url: Optional[str],
    received_by_name: Optional[str],
    pictures: Optional[List[str]] = None,
) -> dict:
    """In-person pickup completion. Reuses the delivery-proof fields (signature + received-by)."""
    from app.repositories import OrderRepository as orderRepository
    from app.schemas.Order import Order, OrderStatus

    if not (signature_url or "").strip():
        raise HTTPException(status_code=400, detail="Se requiere la firma de quien recibe.")
    if not (received_by_name or "").strip():
        raise HTTPException(status_code=400, detail="Se requiere el nombre de quien recibe.")

    order_doc = orderRepository.find_one({"_id": ObjectId(order_id)})
    if not order_doc:
        raise HTTPException(status_code=404, detail="Order not found")

    order_doc = {
        **order_doc,
        "delivery_customer_signature_url": signature_url,
        "delivery_received_by_name": received_by_name,
        "delivery_pictures_seller": pictures or order_doc.get("delivery_pictures_seller") or [],
    }
    order = Order(**order_doc)
    order.change_status(OrderStatus.IN_PERSON_COMPLETED.name)
    order_data = order.toJson()
    order_data.pop("_id", None)
    edited = orderRepository.edit(ObjectId(order_id), order_data)

    # reflect completion on the folio piece order (best-effort)
    folio_id = order_doc.get("mostrador_folio_id")
    if folio_id:
        folio = folioRepository.find_by_id(folio_id)
        if folio:
            pieces = [dict(p) for p in (folio.get("pieces") or [])]
            for piece in pieces:
                if (piece.get("order") or {}).get("order_doc_id") == order_id:
                    piece["order"] = {**piece["order"], "status": "entregada"}
            folioRepository.edit(folio_id, {"pieces": pieces, "updated_at": _now()})

    return Order(**edited).toJson()


def _normalize_part_to_piece(part: dict, index: int) -> dict:
    """Map a marketplace/cart part entry into a MostradorPiece-shaped dict."""
    part = part or {}
    return {
        "piece_id": str(part.get("id") or part.get("_id") or f"imp-{index}-{uuid4().hex[:6]}"),
        "tipoParteId": str(part["tipoParteId"]) if part.get("tipoParteId") is not None else None,
        "tipoParteDescripcion": part.get("tipoParteDescripcion") or part.get("name"),
        "categoriaId": part.get("categoriaId"),
        "subCategoriaId": part.get("subCategoriaId"),
        "name": part.get("tipoParteDescripcion") or part.get("name"),
        "qty": part.get("quantity") or part.get("qty") or 1,
        "unitOfMeasure": part.get("unitOfMeasure") or "Pieza",
        "position": part.get("position") or "No aplica",
        "comments": part.get("comments") or part.get("comment"),
        "status": "pendiente",
        "options": [],
        "order": None,
    }


def _normalize_vehicle(vehicle_info: Optional[dict]) -> Optional[dict]:
    if not vehicle_info:
        return None
    return {
        "year": str(vehicle_info.get("year")) if vehicle_info.get("year") is not None else None,
        "maker": vehicle_info.get("maker") or vehicle_info.get("brand"),
        "model": vehicle_info.get("model"),
        "version": vehicle_info.get("version") or vehicle_info.get("trim") or vehicle_info.get("subModel"),
        "engine": vehicle_info.get("engine"),
        "vin": vehicle_info.get("vin"),
        "licensePlate": vehicle_info.get("licensePlate") or vehicle_info.get("license_plate"),
        "serviceOrder": vehicle_info.get("serviceOrder") or vehicle_info.get("service_order"),
        "group_vehicle_id": str(vehicle_info.get("_id")) if vehicle_info.get("_id") else None,
    }


def _part_request_to_import(pr_doc: dict) -> dict:
    parts = pr_doc.get("partList") or []
    if not parts and pr_doc.get("part"):
        parts = [pr_doc.get("part")]
    pieces = [_normalize_part_to_piece(p, i) for i, p in enumerate(parts)]
    return {
        "vehicle": _normalize_vehicle(pr_doc.get("vehicleInformation")),
        "pieces": pieces,
        "source_part_request_id": str(pr_doc.get("_id")),
        "specific_order_uid": pr_doc.get("specific_order_uid"),
    }


def resolve_import(code: str) -> dict:
    """
    'Existente' import resolver. Detects what a folio code / QR payload refers to and
    returns a normalized envelope { type, data }: a Mostrador folio, a buyer
    pending_cart, or a marketplace PartRequest (single or grouped by specific_order_uid).
    """
    from app.repositories import PartRequestRepository as partRequestRepository
    from app.repositories import PendingCartRepository as pendingCartRepository

    if not code:
        raise HTTPException(status_code=400, detail="code is required")
    code = code.strip()

    # 1) Mostrador folio (short human code, then share token)
    doc = folioRepository.find_by_folio_code(code) or folioRepository.find_by_folio_code(code.upper())
    if doc:
        return {"type": "mostrador_folio", "data": _hydrate(doc)}
    doc = folioRepository.find_by_share_token(code)
    if doc:
        return {"type": "mostrador_folio", "data": _hydrate(doc)}

    # 2) By ObjectId: a marketplace PartRequest or a buyer pending_cart
    is_object_id = len(code) == 24
    if is_object_id:
        pr = partRequestRepository.find_by_id(code)
        if pr:
            return {"type": "part_request", "data": _part_request_to_import(pr)}
        cart = pendingCartRepository.find_by_id(code)
        if cart:
            pieces = [_normalize_part_to_piece(p, i) for i, p in enumerate(cart.get("part_list") or [])]
            return {"type": "pending_cart", "data": {
                "vehicle": None,
                "vehicle_id": cart.get("vehicle_id"),
                "pieces": pieces,
            }}

    # 3) A group of marketplace requests sharing a specific_order_uid
    grouped = list(partRequestRepository.find_by_specific_order_uid(code))
    if grouped:
        pieces: List[dict] = []
        vehicle = None
        for i, pr in enumerate(grouped):
            imported = _part_request_to_import(pr)
            vehicle = vehicle or imported.get("vehicle")
            pieces.extend(imported["pieces"])
        return {"type": "part_request_group", "data": {
            "vehicle": vehicle,
            "pieces": pieces,
            "specific_order_uid": code,
        }}

    raise HTTPException(status_code=404, detail="No request found for that code")
