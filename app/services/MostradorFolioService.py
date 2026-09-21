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


def _dispatch_notifications(result: dict) -> dict:
    from app.services import notification_fanout

    notification_fanout.persist_notification_dict(result.get("notification"))
    notification_fanout.persist_notification_dicts(result.get("notifications"))
    return result


def _generate_folio_code() -> str:
    """Short human code used by 'Capturar Folio'."""
    return uuid4().hex[-6:].upper()


def _hydrate(doc: dict) -> dict:
    enriched = dict(doc)
    enriched["origin_group"] = _group_public_info(doc.get("origin_group_id"))
    return MostradorFolio(**enriched).toJson()


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


def _normalize_phone_e164(phone: str) -> str:
    """Normalize a phone string to E.164 (+52 for 10-digit MX numbers)."""
    raw = (phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+") and digits:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+52{digits}"
    if digits:
        return f"+{digits}"
    return raw


def _phone_lookup_variants(phone: str) -> List[str]:
    """Build phone variants stored on folio.customer.phone for lookup."""
    e164 = _normalize_phone_e164(phone)
    digits = "".join(ch for ch in e164 if ch.isdigit())
    variants = []
    for candidate in (e164, phone.strip(), f"+{digits}" if digits else None):
        if candidate and candidate not in variants:
            variants.append(candidate)
    if len(digits) >= 10:
        last10 = digits[-10:]
        for candidate in (last10, f"+52{last10}"):
            if candidate not in variants:
                variants.append(candidate)
    return variants


def _folio_piece_preview(doc: dict, max_names: int = 2) -> str:
    discarded = {"agotada", "no_manejo"}
    pieces = doc.get("pieces") or []
    active = [p for p in pieces if p.get("status") not in discarded]
    pool = active if active else pieces
    names = [
        (p.get("name") or p.get("tipoParteDescripcion") or "").strip()
        for p in pool[:max_names]
    ]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(pool) > max_names:
        return f"{', '.join(names)}…"
    return ", ".join(names)


def _folio_guest_summary(doc: dict) -> dict:
    """Lightweight folio card for guest list screens (no full piece payloads)."""
    vehicle = doc.get("vehicle") or {}
    vehicle_label = " ".join(
        str(part).strip()
        for part in (vehicle.get("year"), vehicle.get("maker"), vehicle.get("model"))
        if part
    ) or "Sin vehículo"
    customer = doc.get("customer") or {}
    updated_at = doc.get("updated_at")
    return {
        "share_token": doc.get("share_token"),
        "folio_code": doc.get("folio_code"),
        "status": doc.get("status"),
        "vehicle_label": vehicle_label,
        "piece_preview": _folio_piece_preview(doc),
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "customer_name": customer.get("name"),
    }


def list_by_verified_phone(phone: str, limit: int = 25) -> List[dict]:
    """Return guest folio summaries for a Firebase-verified phone number."""
    if not phone or not str(phone).strip():
        return []
    seen_tokens = set()
    summaries: List[dict] = []
    for variant in _phone_lookup_variants(phone):
        docs = folioRepository.find_by_customer_phone(variant, limit=limit)
        for doc in docs:
            token = doc.get("share_token")
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            summaries.append(_folio_guest_summary(doc))
        if len(summaries) >= limit:
            break
    summaries.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return summaries[:limit]


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
    _ensure_mostrador_orders_materialized(folio_id, swallow_errors=True)
    doc = folioRepository.find_by_id(folio_id) or doc
    return _hydrate(doc)


def get_by_share_token(share_token: str) -> dict:
    doc = folioRepository.find_by_share_token(share_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    folio_id = str(doc["_id"])
    _ensure_mostrador_orders_materialized(folio_id, swallow_errors=True)
    doc = folioRepository.find_by_id(folio_id) or doc
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
    _reject_new_pieces_when_ordered(doc, pieces)
    _reject_ordered_piece_option_changes(doc, pieces)
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
    if "pieces" in patch:
        _reject_new_pieces_when_ordered(doc, patch["pieces"])
        _reject_ordered_piece_option_changes(doc, patch["pieces"])
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


def _scope_options_for_shop(folio_doc: dict, shop_key: str) -> dict:
    """A participant shop only ever sees ITS OWN options — never other shops' bids."""
    pieces = []
    for p in (folio_doc.get("pieces") or []):
        pieces.append({
            **p,
            "options": [
                o for o in (p.get("options") or [])
                if o.get("source_shop_id") == shop_key
            ],
        })
    return {**folio_doc, "pieces": pieces}


def _offer_to_mostrador_option(offer: dict, fallback_group_id: str) -> dict:
    """Map a PartRequest Offer document into a folio MostradorOption shape."""
    group_info = offer.get("group_info") or {}
    shop_name = group_info.get("name") if isinstance(group_info, dict) else None
    group_id = str(offer.get("group_id") or fallback_group_id or "")
    brand = (offer.get("brand") or "").strip()
    price = offer.get("price")
    return {
        "brand": offer.get("brand"),
        "code": offer.get("code"),
        "price": price,
        "guarantee": offer.get("guarantee"),
        "unit_of_measure": offer.get("unit_of_measure") or "Pieza",
        "photos": offer.get("photos") or [],
        "note": offer.get("internalComments") or offer.get("publicComments"),
        "ready": bool(brand and price is not None),
        "availability_status": "",
        "source_shop_id": group_id,
        "source_shop_name": shop_name,
        "captured_by_buyer": False,
        "source_confirmation": None,
    }


def _merge_part_request_offers_into_folio(doc: dict, shop_group_id: str) -> dict:
    """Project seller PartRequest offers back into folio options for assist/capture reads."""
    if not shop_group_id or not _assignment_context(doc):
        return doc

    from app.repositories import PartRequestRepository as partRequestRepository
    from app.repositories import OfferRepository as offerRepository
    from app.schemas.Offer import OfferStatus

    folio_id_str = str(doc.get("_id") or "")
    if not folio_id_str:
        return doc

    active_statuses = [
        OfferStatus.created.value,
        OfferStatus.selected.value,
        OfferStatus.pending_approval.value,
        OfferStatus.workshop_approval_pending.value,
        OfferStatus.pending_changes.value,
    ]

    prs = list(partRequestRepository.find(
        {"mostrador_folio_id": folio_id_str, "isActive": True}, {}
    ))
    pr_by_piece = {
        str(pr.get("mostrador_piece_id")): str(pr["_id"])
        for pr in prs
        if pr.get("mostrador_piece_id")
    }

    pieces: List[dict] = []
    for piece in doc.get("pieces") or []:
        piece_id = piece.get("piece_id")
        if not piece_id or piece.get("status") in _DISCARDED_PIECE_STATUSES:
            pieces.append(piece)
            continue

        pr_id = pr_by_piece.get(str(piece_id))
        if not pr_id:
            pieces.append(piece)
            continue

        options = list(piece.get("options") or [])
        option_by_key = {
            _option_match_key(opt, shop_group_id): idx
            for idx, opt in enumerate(options)
        }

        offers = list(offerRepository.find({
            "request_id": pr_id,
            "group_id": str(shop_group_id),
            "status": {"$in": active_statuses},
        }, {}))

        for offer in offers:
            opt = _offer_to_mostrador_option(offer, shop_group_id)
            if not opt.get("brand") or opt.get("price") is None:
                continue
            key = _option_match_key(opt, shop_group_id)
            if key in option_by_key:
                idx = option_by_key[key]
                options[idx] = {**options[idx], **opt}
            else:
                option_by_key[key] = len(options)
                options.append(opt)

        pieces.append({**piece, "options": options})

    return {**doc, "pieces": pieces}


def _participant_shop_entry(doc: dict, group_id: str) -> Optional[dict]:
    return next(
        (
            s for s in (doc.get("participant_shops") or [])
            if s.get("eassymo") and str(s.get("group_id") or "") == str(group_id)
        ),
        None,
    )


def _require_participant_or_origin(doc: dict, group_id: str) -> dict:
    """Return participant shop entry, or allow origin seller group (full access)."""
    if str(doc.get("origin_group_id") or "") == str(group_id):
        return {}
    shop = _participant_shop_entry(doc, group_id)
    if not shop:
        raise HTTPException(status_code=403, detail="Group is not a participant on this folio")
    return shop


def get_tube(tube_token: str) -> dict:
    """Temp-shop restricted view: only pieces the tube is allowed to quote."""
    doc = folioRepository.find_by_tube_token(tube_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Tube not found")
    shop_entry = next(
        (s for s in (doc.get("participant_shops") or []) if s.get("tube_token") == tube_token),
        None,
    )
    scoped = _filter_pieces_for_visibility(doc, tube_token)
    scoped = _scope_options_for_shop(scoped, tube_token)
    hydrated = _hydrate(scoped)
    if shop_entry:
        hydrated["tube_shop"] = {
            "tube_token": tube_token,
            "name": shop_entry.get("name") or "Tienda invitada",
        }
        hydrated["participant_shops"] = [shop_entry]
    else:
        hydrated["participant_shops"] = []
    return hydrated


def require_tube_token(tube_token: str) -> dict:
    """Validate tube token and return the matching participant shop entry."""
    doc = folioRepository.find_by_tube_token(tube_token)
    if not doc:
        raise HTTPException(status_code=404, detail="Tube not found")
    shop = next(
        (s for s in (doc.get("participant_shops") or []) if s.get("tube_token") == tube_token),
        None,
    )
    if not shop:
        raise HTTPException(status_code=404, detail="Tube shop not found")
    return shop


def get_for_group(folio_id: str, group_id: str) -> dict:
    """Invited Eassymo group view: visibility-scoped pieces + own options only."""
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    origin = str(doc.get("origin_group_id") or "")
    if origin == str(group_id):
        merged = _merge_part_request_offers_into_folio(doc, group_id)
        scoped = _scope_options_for_shop(merged, group_id)
        return _hydrate(scoped)

    shop = _participant_shop_entry(doc, group_id)
    if not shop:
        raise HTTPException(status_code=403, detail="Group is not a participant on this folio")

    scoped = _filter_pieces_for_visibility(doc, group_id)
    merged = _merge_part_request_offers_into_folio(scoped, group_id)
    scoped = _scope_options_for_shop(merged, group_id)
    return _hydrate(scoped)


def get_redirect_info(folio_id: str) -> dict:
    """Public: minimal routing fields for a folio (no pieces/pricing/customer)."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    share_token = doc.get("share_token")
    if not share_token:
        share_token = uuid4().hex
        folioRepository.edit(folio_id, {"share_token": share_token, "updated_at": _now()})

    status = doc.get("status")
    if hasattr(status, "value"):
        status = status.value

    return {
        "origin_group_id": doc.get("origin_group_id"),
        "share_token": share_token,
        "status": status,
        "folio_code": doc.get("folio_code"),
    }


def claim_owner(
    folio_id: str,
    uid: str,
    group_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    """Claim an unclaimed folio for the authenticated user's selected group."""
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    customer = doc.get("customer") or {}
    existing_uid = customer.get("user_uid")
    existing_group_id = customer.get("group_id")

    if _is_claimed(doc):
        if existing_uid and str(existing_uid) == str(uid):
            return {
                "folio": _hydrate(doc),
                "claimed": False,
                "group_id": existing_group_id,
            }
        if existing_group_id and str(existing_group_id) == str(group_id):
            return {
                "folio": _hydrate(doc),
                "claimed": False,
                "group_id": existing_group_id,
            }
        raise HTTPException(status_code=409, detail="El folio ya tiene dueño")

    result = _link_folio_to_customer(
        folio_id,
        doc,
        uid,
        name,
        phone,
        str(group_id),
    )
    return {
        **result,
        "claimed": True,
    }


def claim_guest(folio_id: str, guest_device_id: str) -> dict:
    """Claim an unclaimed folio for an anonymous guest (device-scoped, no account)."""
    if not guest_device_id:
        raise HTTPException(status_code=400, detail="guest_device_id is required")

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    customer = doc.get("customer") or {}
    existing_uid = customer.get("user_uid")

    if _is_claimed(doc):
        if existing_uid and str(existing_uid) == str(guest_device_id):
            return {
                "folio": _hydrate(doc),
                "claimed": False,
            }
        raise HTTPException(status_code=409, detail="El folio ya tiene dueño")

    guest_customer = {
        "type": "guest",
        "name": None,
        "phone": None,
        "user_uid": str(guest_device_id),
        "group_id": None,
    }
    updated = folioRepository.edit(
        folio_id,
        {"customer": guest_customer, "updated_at": _now()},
    )
    refreshed = folioRepository.find_by_id(folio_id)
    return {
        "folio": _hydrate(refreshed or updated),
        "claimed": True,
    }


def submit_group_options(
    folio_id: str,
    piece_id: str,
    options: List[dict],
    group_id: str,
) -> dict:
    """Origin or invited Eassymo group submits options (own bids only)."""
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_piece_options_editable(doc, piece_id)

    is_origin = str(doc.get("origin_group_id") or "") == str(group_id)
    shop = _participant_shop_entry(doc, group_id)
    if not is_origin and not shop:
        raise HTTPException(status_code=403, detail="Group is not a participant on this folio")

    if not is_origin:
        visibility = (doc.get("visibility") or {}).get(group_id)
        if visibility is not None and piece_id not in visibility:
            raise HTTPException(status_code=403, detail="Piece is not visible to this group")

    shop_name = (shop.get("name") if shop else None) or _group_name(group_id)
    return _merge_piece_options(
        doc,
        folio_id,
        piece_id,
        options,
        shop_id=group_id,
        shop_name=shop_name,
        captured_by_buyer=False,
        log_activity=True,
    )


def confirm_guest_option(
    folio_id: str,
    piece_id: str,
    option_index: int,
    group_id: str,
) -> dict:
    """A participant shop confirms a guest-captured option as its official bid."""
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_piece_options_editable(doc, piece_id)

    shop = _require_participant_or_origin(doc, group_id)
    shop_name = shop.get("name") if shop else _group_name(group_id)

    is_origin = str(doc.get("origin_group_id") or "") == str(group_id)
    visibility = (doc.get("visibility") or {}).get(group_id)
    if not is_origin and visibility is not None and piece_id not in visibility:
        raise HTTPException(status_code=403, detail="Piece is not visible to this group")

    target = next((p for p in (doc.get("pieces") or []) if p.get("piece_id") == piece_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Piece not found")

    options = list(target.get("options") or [])
    if option_index < 0 or option_index >= len(options):
        raise HTTPException(status_code=404, detail="Option not found")

    opt = options[option_index]
    if not opt.get("captured_by_buyer"):
        raise HTTPException(status_code=400, detail="Option was not captured by buyer")
    if opt.get("source_confirmation") == "confirmed":
        raise HTTPException(status_code=400, detail="Option already confirmed")

    options[option_index] = {
        **opt,
        "source_shop_id": group_id,
        "source_shop_name": shop_name,
        "captured_by_buyer": False,
        "source_confirmation": "confirmed",
        "ready": _option_is_ready(opt),
    }

    merged_piece = {**target, "options": options}
    new_status = _recompute_piece_status(merged_piece)
    from app.schemas.MostradorFolio import MostradorPiece
    normalized = MostradorPiece(**{**merged_piece, "status": new_status}).model_dump()

    updated = folioRepository.set_piece_options(
        folio_id, piece_id, normalized["options"], new_status, _now())
    if not updated:
        raise HTTPException(status_code=500, detail="Could not confirm option")
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


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


def _merge_piece_options(
    doc: dict,
    folio_id: str,
    piece_id: str,
    options: List[dict],
    shop_id: Optional[str],
    shop_name: Optional[str],
    captured_by_buyer: bool = False,
    *,
    log_activity: bool = True,
) -> dict:
    """Merge options for one shop onto a piece; preserve other shops' options."""
    target = next((p for p in (doc.get("pieces") or []) if p.get("piece_id") == piece_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Piece not found")

    others = [o for o in (target.get("options") or []) if o.get("source_shop_id") != shop_id]
    existing_keys = {_option_match_key(o, shop_id or "") for o in others}
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
        key = _option_match_key(tagged, shop_id or "")
        if key in existing_keys:
            continue
        existing_keys.add(key)
        incoming.append(tagged)

    merged_options = others + incoming
    merged_piece = {**target, "options": merged_options}
    new_status = _recompute_piece_status(merged_piece)

    from app.schemas.MostradorFolio import MostradorPiece
    normalized = MostradorPiece(**{**merged_piece, "status": new_status}).model_dump()

    updated = folioRepository.set_piece_options(
        folio_id, piece_id, normalized["options"], new_status, _now())
    if not updated:
        raise HTTPException(status_code=500, detail="Could not update piece options")
    if log_activity:
        piece_label = _piece_display_name(target)
        shop_label = shop_name or "Una tienda"
        _append_activity_log(
            folio_id,
            "shop_option_added",
            f"{shop_label} agregó una opción para {piece_label}",
            piece_id=piece_id,
            shop_name=shop_name,
        )
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


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
    _require_piece_options_editable(doc, piece_id)

    return _merge_piece_options(
        doc,
        folio_id,
        piece_id,
        options,
        shop_id,
        shop_name,
        captured_by_buyer,
        log_activity=True,
    )


def add_piece_by_shop(folio_id: str, group_id: str, piece_data: dict) -> dict:
    """Origin or invited shop appends a piece while bidding on a shared folio."""
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_capture_editable_after_order(doc)

    shop = _require_participant_or_origin(doc, group_id)
    is_origin = str(doc.get("origin_group_id") or "") == str(group_id)
    shop_name = (shop.get("name") if shop else None) or _group_name(group_id)

    name = (piece_data.get("name") or piece_data.get("tipoParteDescripcion") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    from app.schemas.MostradorFolio import MostradorPiece
    tipo_parte_id = piece_data.get("tipoParteId")
    if tipo_parte_id is not None and tipo_parte_id != "":
        tipo_parte_id = str(tipo_parte_id)

    piece_id = uuid4().hex
    new_piece = MostradorPiece(
        piece_id=piece_id,
        name=name,
        tipoParteDescripcion=name,
        tipoParteId=tipo_parte_id,
        categoriaId=piece_data.get("categoriaId"),
        subCategoriaId=piece_data.get("subCategoriaId"),
        qty=int(piece_data.get("qty") or 1),
        unitOfMeasure=piece_data.get("unitOfMeasure") or "Pieza",
        position=piece_data.get("position") or "No aplica",
        note=bool(piece_data.get("note", False)),
        sample=bool(piece_data.get("sample", False)),
        status="pendiente",
        options=[],
        added_by_shop_id=group_id,
        added_by_shop_name=shop_name,
    )
    pieces = list(doc.get("pieces") or [])
    pieces.insert(0, new_piece.model_dump())
    folioRepository.set_pieces(folio_id, pieces, _now())

    if not is_origin:
        visibility = dict(doc.get("visibility") or {})
        allowed = list(visibility.get(group_id) or [])
        if group_id in visibility and piece_id not in allowed:
            allowed.append(piece_id)
            visibility[group_id] = allowed
            folioRepository.edit(folio_id, {"visibility": visibility, "updated_at": _now()})

    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def add_piece_by_guest(folio_id: str, piece_data: dict) -> dict:
    """Guest appends a free-text piece to a shared folio."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_capture_editable_after_order(doc)

    name = (piece_data.get("name") or piece_data.get("tipoParteDescripcion") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    from app.schemas.MostradorFolio import MostradorPiece
    tipo_parte_id = piece_data.get("tipoParteId")
    if tipo_parte_id is not None and tipo_parte_id != "":
        tipo_parte_id = str(tipo_parte_id)

    new_piece = MostradorPiece(
        piece_id=uuid4().hex,
        name=name,
        tipoParteDescripcion=name,
        tipoParteId=tipo_parte_id,
        categoriaId=piece_data.get("categoriaId"),
        subCategoriaId=piece_data.get("subCategoriaId"),
        qty=int(piece_data.get("qty") or 1),
        unitOfMeasure=piece_data.get("unitOfMeasure") or "Pieza",
        position=piece_data.get("position") or "No aplica",
        note=bool(piece_data.get("note", False)),
        sample=bool(piece_data.get("sample", False)),
        status="pendiente",
        options=[],
        added_by_guest=True,
    )
    pieces = list(doc.get("pieces") or [])
    pieces.insert(0, new_piece.model_dump())
    folioRepository.set_pieces(folio_id, pieces, _now())
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def remove_guest_piece(folio_id: str, piece_id: str) -> dict:
    """Guest removes a piece they added, only before it is ordered."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_capture_editable_after_order(doc)

    target = next((p for p in (doc.get("pieces") or []) if p.get("piece_id") == piece_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Piece not found")
    if not target.get("added_by_guest"):
        raise HTTPException(status_code=403, detail="Solo puedes quitar piezas que agregaste")
    if target.get("order"):
        raise HTTPException(status_code=403, detail="No se puede quitar una pieza ya ordenada")

    pieces = [p for p in (doc.get("pieces") or []) if p.get("piece_id") != piece_id]
    folioRepository.set_pieces(folio_id, pieces, _now())
    sync_assigned_folio(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed)


def submit_guest_piece_options(
    folio_id: str,
    piece_id: str,
    options: List[dict],
    shop_id: Optional[str] = None,
    shop_name: Optional[str] = None,
) -> dict:
    """Guest manually captures options on a piece (buyer-proxy quote)."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_piece_options_editable(doc, piece_id)

    return _merge_piece_options(
        doc,
        folio_id,
        piece_id,
        options,
        shop_id=shop_id or "guest",
        shop_name=shop_name,
        captured_by_buyer=True,
        log_activity=False,
    )


def invite_shop(
    folio_id: str,
    group_id: Optional[str],
    name: Optional[str],
    eassymo: bool,
    visible_piece_ids: Optional[List[str]],
    *,
    client_origin: Optional[str] = None,
    captured_by_buyer: bool = False,
) -> dict:
    """Add a participant shop. Temp shops (no account) get a tube_token + visibility scope."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")
    _require_capture_editable_after_order(doc)

    tube_token = None if eassymo else uuid4().hex
    shop = {
        "group_id": group_id,
        "name": name,
        "eassymo": eassymo,
        "tube_token": tube_token,
        "captured_by_buyer": captured_by_buyer or None,
    }

    updated = folioRepository.push_participant_shop(folio_id, shop, visible_piece_ids, _now())

    # apply visibility scope keyed by tube_token (temp shop) or group_id (eassymo shop)
    if visible_piece_ids is not None:
        visibility = dict(updated.get("visibility") or {})
        key = tube_token or group_id
        if key:
            visibility[key] = visible_piece_ids
            updated = folioRepository.edit(folio_id, {"visibility": visibility, "updated_at": _now()})

    share_meta: Dict[str, Any] = {}
    if tube_token:
        share_path = f"/pos/tube/{tube_token}"
        base_url = _resolve_client_base_url(client_origin)
        absolute = f"{base_url}{share_path}" if base_url else share_path
        wa_text = f"Te compartieron piezas para cotizar en Eassymo: {absolute}"
        share_meta = _build_share_urls(share_path, wa_text, client_origin=client_origin)
        share_meta["tube_token"] = tube_token
    elif eassymo and group_id:
        share_meta = {"group_id": group_id, "eassymo": True}

    notification = None
    if eassymo and group_id:
        from app.repositories import GroupRepository as groupRepository
        from app.factories import NotificationsCreator

        group_doc = groupRepository.find_by_id(group_id)
        if group_doc:
            buyer_uid = _resolve_buyer_uid_for_group(group_doc)
            if buyer_uid:
                inviter_name = (doc.get("customer") or {}).get("name") or "Un cliente"
                piece_count = len(visible_piece_ids or [])
                navigate_to_url = f"/pos/mostrador-invite/{folio_id}"
                notif = NotificationsCreator.create_mostrador_shop_invited_notification(
                    inviter_name=inviter_name,
                    piece_count=piece_count,
                    owner=buyer_uid,
                    owner_group=str(group_id),
                    navigate_to_url=navigate_to_url,
                    meta_data={
                        "folioId": folio_id,
                        "groupId": str(group_id),
                        "visiblePieceIds": visible_piece_ids or [],
                    },
                )
                notif_dict = notif.model_dump()
                if hasattr(notif_dict.get("type"), "value"):
                    notif_dict["type"] = notif_dict["type"].value
                notification = notif_dict

    return _dispatch_notifications({
        "folio": _hydrate(updated),
        **share_meta,
        "notification": notification,
    })


def _group_name(group_id: Optional[str]) -> str:
    info = _group_public_info(group_id)
    return info.get("name") or "La tienda"


def _group_public_info(group_id: Optional[str]) -> Optional[dict]:
    if not group_id:
        return None
    try:
        from app.repositories import GroupRepository as groupRepository
        doc = groupRepository.find_by_id(group_id)
        if not doc:
            return None
        logo = (
            doc.get("logo_url")
            or doc.get("logoUrl")
            or doc.get("profileImage")
            or doc.get("photo")
        )
        phone = doc.get("phone") or doc.get("whatsAppNumber")
        return {
            "name": doc.get("name"),
            "logo_url": str(logo) if logo else None,
            "address": doc.get("address"),
            "phone": phone,
            "whatsapp": doc.get("whatsAppNumber") or phone,
        }
    except Exception:
        return None


def _resolve_client_base_url(client_origin: Optional[str] = None) -> str:
    import os
    from urllib.parse import urlparse

    env_base = (os.getenv("CLIENT_BASE_URL") or "").rstrip("/")
    if env_base:
        return env_base
    origin = (client_origin or "").strip().rstrip("/")
    if origin and origin.startswith(("http://", "https://")):
        return origin
    if origin:
        parsed = urlparse(origin if "://" in origin else f"https://{origin}")
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return ""


def _client_origin_from_request(request) -> Optional[str]:
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    origin = headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = headers.get("referer")
    if referer:
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _build_share_urls(
    share_path: str,
    wa_text: str,
    whatsapp_phone: Optional[str] = None,
    *,
    client_origin: Optional[str] = None,
) -> dict:
    from urllib.parse import quote

    base_url = _resolve_client_base_url(client_origin)
    share_url = f"{base_url}{share_path}" if base_url else share_path
    whatsapp_url = None
    if whatsapp_phone:
        digits = "".join(ch for ch in str(whatsapp_phone) if ch.isdigit())
        if digits:
            whatsapp_url = f"https://wa.me/{digits}?text={quote(wa_text)}"
    return {
        "share_path": share_path,
        "share_url": share_url,
        "whatsapp_url": whatsapp_url,
    }


def _append_activity_log(
    folio_id: str,
    entry_type: str,
    message: str,
    *,
    piece_id: Optional[str] = None,
    shop_name: Optional[str] = None,
) -> None:
    entry = {
        "id": uuid4().hex,
        "type": entry_type,
        "message": message,
        "piece_id": piece_id,
        "shop_name": shop_name,
        "created_at": _now(),
        "migrated": False,
    }
    folioRepository.push_activity_log(folio_id, entry, _now())


def _migrate_guest_notifications(folio_id: str, uid: str, group_id: str) -> List[dict]:
    """Build notification descriptors for unmigrated activity_log entries."""
    from app.factories import NotificationsCreator

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        return []
    notifications: List[dict] = []
    migrated_ids: List[str] = []
    for entry in (doc.get("activity_log") or []):
        if entry.get("migrated"):
            continue
        entry_id = entry.get("id")
        if not entry_id:
            continue
        notif = NotificationsCreator.create_mostrador_option_added_notification(
            message=entry.get("message") or "Nueva actividad en tu lista de mostrador",
            owner=uid,
            owner_group=group_id,
            navigate_to_url="/folio",
            meta_data={"folioId": folio_id, "pieceId": entry.get("piece_id")},
        )
        nd = notif.model_dump()
        if hasattr(nd.get("type"), "value"):
            nd["type"] = nd["type"].value
        notifications.append(nd)
        migrated_ids.append(entry_id)
    if migrated_ids:
        folioRepository.mark_activity_entries_migrated(folio_id, migrated_ids, _now())
    return notifications


# Group types mirror eassymo-2.0-client TypeOfGroup: BUYER=1, SELLER=2
_GROUP_TYPE_BUYER = 1
_GROUP_TYPE_SELLER = 2


def _resolve_user_group_by_type(user_doc: dict, group_type: int) -> Optional[dict]:
    from app.repositories import GroupRepository as groupRepository
    for gid in (user_doc.get("groups") or []):
        try:
            g = groupRepository.find_by_id(str(gid))
        except Exception:
            g = None
        if g and int(g.get("type") or -1) == int(group_type):
            return g
    return None


def _guest_provision_email(uid: str) -> str:
    """Synthetic email for phone-only guest signups (must pass EmailStr validation)."""
    local = "".join(c for c in (uid or "user") if c.isalnum()).lower() or "user"
    return f"{local}@guest.eassymo.mx"


def _ensure_platform_user(
    uid: str,
    name: Optional[str],
    phone: Optional[str],
) -> dict:
    """Ensure Mongo user exists (upsert). Group creation is deferred to shop-creator-v3."""
    from app.services import UserService as userService
    from app.schemas.Users import UserSchema
    from app.repositories import UserRepository as userRepository

    userService.create_user(UserSchema(
        uid=uid,
        name=name or "",
        phone=phone or "",
        email=_guest_provision_email(uid),
    ))
    return userRepository.find_one({"uid": uid}) or {}


def _resolve_existing_group_id(uid: str, group_type: int) -> Optional[str]:
    from app.repositories import UserRepository as userRepository
    fresh_user = userRepository.find_one({"uid": uid}) or {}
    existing = _resolve_user_group_by_type(fresh_user, group_type)
    if existing:
        return str(existing["_id"])
    return None


def _link_folio_to_customer(
    folio_id: str,
    doc: dict,
    uid: str,
    name: Optional[str],
    phone: Optional[str],
    group_id: str,
) -> dict:
    """Full buyer folio assignment: customer record, orders, sync, materialize, notifications."""
    customer = {
        "type": "eassymo",
        "name": name,
        "phone": phone,
        "user_uid": uid,
        "group_id": group_id,
    }
    updated = folioRepository.edit(folio_id, {"customer": customer, "updated_at": _now()})
    _propagate_customer_to_orders(doc.get("order_ids") or [], customer)
    sync_assigned_folio(folio_id)
    _ensure_mostrador_orders_materialized(folio_id)
    notifications = _migrate_guest_notifications(folio_id, uid, group_id)
    refreshed = folioRepository.find_by_id(folio_id)
    from app.services import UserService as userService
    return _dispatch_notifications({
        "folio": _hydrate(refreshed or updated),
        "group_id": group_id,
        "needs_group": False,
        "user": userService.get_user_with_groups(uid),
        "notifications": notifications,
    })


def finish_claim(
    folio_id: str,
    uid: str,
    group_id: str,
    account_kind: str,
) -> dict:
    """Complete folio claim after shop-creator-v3 creates the group."""
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    from app.repositories import UserRepository as userRepository
    from app.services import UserService as userService
    user_doc = userRepository.find_one({"uid": uid}) or {}
    name = user_doc.get("name")
    phone = user_doc.get("phone")

    if account_kind == "buyer":
        _require_not_claimed_by_other(doc, uid, group_id, allow_guest_reassign=True)
        return _link_folio_to_customer(folio_id, doc, uid, name, phone, group_id)

    notifications = _migrate_guest_notifications(folio_id, uid, group_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _dispatch_notifications({
        "folio": _hydrate(refreshed or doc),
        "group_id": group_id,
        "needs_group": False,
        "user": userService.get_user_with_groups(uid),
        "notifications": notifications,
    })


def share(
    folio_id: str,
    customer: Optional[dict],
    channel: str = "whatsapp",
    whatsapp_phone: Optional[str] = None,
    *,
    client_origin: Optional[str] = None,
) -> dict:
    """
    Mark a folio as shared with the customer. Persists customer info, ensures a share_token,
    and returns share links + an in-app notification descriptor (dispatched client-side,
    matching the app's existing notification pattern) when the customer is an existing user.
    """
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
    base_url = _resolve_client_base_url(client_origin)
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

    return _dispatch_notifications({
        "folio": _hydrate(updated),
        "share_token": share_token,
        "share_path": share_path,
        "share_url": share_url,
        "whatsapp_url": whatsapp_url,
        "notification": notification,
    })


def order_piece(
    folio_id: str,
    piece_id: str,
    option_index: int,
    delivery_mode: str = "tienda",
    delivery_address: Optional[dict] = None,
    delivery_contact: Optional[dict] = None,
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

    mode = delivery_mode or "tienda"
    if mode == "domicilio":
        if not delivery_address or not (delivery_address.get("address") or "").strip():
            raise HTTPException(status_code=400, detail="delivery_address is required for domicilio")
        contact_name = (delivery_contact or {}).get("name") or ""
        contact_phone = (delivery_contact or {}).get("phone") or ""
        if not str(contact_name).strip() or not str(contact_phone).strip():
            raise HTTPException(status_code=400, detail="delivery_contact is required for domicilio")

    order = {
        "option_index": option_index,
        "delivery_mode": mode,
        "shop_id": chosen.get("source_shop_id"),
        "shop_name": chosen.get("source_shop_name"),
        "status": "ordenada",
        "ordered_at": _now(),
        "order_doc_id": None,
    }
    if mode == "domicilio":
        order["delivery_address"] = delivery_address
        order["delivery_contact"] = delivery_contact
    from app.schemas.MostradorFolio import MostradorPieceOrder
    normalized = MostradorPieceOrder(**order).model_dump()
    updated = folioRepository.set_piece_order(folio_id, piece_id, normalized, _now())
    sync_assigned_folio(folio_id)
    if not chosen.get("captured_by_buyer"):
        _ensure_mostrador_orders_materialized(folio_id)
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
    """Return the user's first buyer taller group (type=1), if any."""
    return _resolve_user_group_by_type(user_doc, _GROUP_TYPE_BUYER)


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
    sync_assigned_folio(folio_id)
    _ensure_mostrador_orders_materialized(folio_id)
    refreshed = folioRepository.find_by_id(folio_id)
    return _hydrate(refreshed or updated)


def claim_account(
    folio_id: str,
    uid: str,
    name: Optional[str],
    phone: Optional[str],
    group_name: Optional[str],
) -> dict:
    """
    Provision a real Eassymo buyer (taller) for a folio and reassign folio data.
    Firebase user is created client-side (OTP).
    When the user has no buyer group yet, defers group creation to shop-creator-v3.
    """
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required to create an account")

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    _ensure_platform_user(uid, name, phone)
    group_id = _resolve_existing_group_id(uid, _GROUP_TYPE_BUYER)

    from app.services import UserService as userService

    if group_id:
        _require_not_claimed_by_other(doc, uid, group_id, allow_guest_reassign=True)
        return _link_folio_to_customer(
            folio_id, doc, uid, name or group_name, phone, group_id
        )

    if _is_claimed(doc):
        customer = doc.get("customer") or {}
        if customer.get("type") != "guest":
            if customer.get("user_uid") and str(customer.get("user_uid")) != str(uid):
                raise HTTPException(status_code=409, detail="El folio ya tiene dueño")

    customer = {
        "type": "eassymo",
        "name": name or group_name,
        "phone": phone,
        "user_uid": uid,
        "group_id": None,
    }
    updated = folioRepository.edit(folio_id, {"customer": customer, "updated_at": _now()})
    refreshed = folioRepository.find_by_id(folio_id)
    return {
        "folio": _hydrate(refreshed or updated),
        "group_id": None,
        "needs_group": True,
        "user": userService.get_user_with_groups(uid),
        "notifications": [],
    }


def create_taller_account(
    folio_id: str,
    uid: str,
    name: Optional[str],
    phone: Optional[str],
    group_name: Optional[str],
) -> dict:
    """
    Create a seller shop account without reassigning the guest folio.
    When the user has no seller group yet, defers group creation to shop-creator-v3.
    """
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required to create an account")

    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Folio not found")

    _ensure_platform_user(uid, name, phone)
    group_id = _resolve_existing_group_id(uid, _GROUP_TYPE_SELLER)

    from app.services import UserService as userService

    if group_id:
        notifications = _migrate_guest_notifications(folio_id, uid, group_id)
        refreshed = folioRepository.find_by_id(folio_id)
        return _dispatch_notifications({
            "folio": _hydrate(refreshed or doc),
            "group_id": group_id,
            "needs_group": False,
            "user": userService.get_user_with_groups(uid),
            "notifications": notifications,
        })

    refreshed = folioRepository.find_by_id(folio_id)
    return {
        "folio": _hydrate(refreshed or doc),
        "group_id": None,
        "needs_group": True,
        "user": userService.get_user_with_groups(uid),
        "notifications": [],
    }


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


def _is_claimed(doc: dict) -> bool:
    """Folio has an owner (customer uid/group) or was materialized to part requests."""
    customer = doc.get("customer") or {}
    if customer.get("user_uid"):
        return True
    if customer.get("group_id"):
        return True
    return bool(doc.get("part_request_ids"))


def _require_not_claimed_by_other(
    doc: dict,
    uid: str,
    group_id: Optional[str] = None,
    *,
    allow_guest_reassign: bool = False,
) -> None:
    """Raise 409 when the folio is already owned by a different user/group."""
    if not _is_claimed(doc):
        return
    customer = doc.get("customer") or {}
    if allow_guest_reassign and customer.get("type") == "guest":
        return
    existing_uid = customer.get("user_uid")
    existing_group_id = customer.get("group_id")
    if existing_uid and str(existing_uid) == str(uid):
        return
    if group_id and existing_group_id and str(existing_group_id) == str(group_id):
        return
    raise HTTPException(status_code=409, detail="El folio ya tiene dueño")


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


def _has_ordered_pieces(doc: dict) -> bool:
    return any(p.get("order") for p in (doc.get("pieces") or []))


def _reject_new_pieces_when_ordered(doc: dict, pieces: List[dict]) -> None:
    if not _has_ordered_pieces(doc):
        return
    old_ids = {p.get("piece_id") for p in (doc.get("pieces") or []) if p.get("piece_id")}
    new_ids = {p.get("piece_id") for p in pieces if p.get("piece_id")}
    if new_ids - old_ids:
        raise HTTPException(
            status_code=403,
            detail="No se pueden agregar piezas después de crear una orden",
        )


def _piece_has_order(piece: dict) -> bool:
    return bool(piece.get("order"))


def _options_unchanged(old: List[dict], new: List[dict]) -> bool:
    import json

    return json.dumps(old or [], sort_keys=True, default=str) == json.dumps(
        new or [], sort_keys=True, default=str
    )


def _reject_ordered_piece_option_changes(doc: dict, pieces: List[dict]) -> None:
    old_by_id = {
        p.get("piece_id"): p for p in (doc.get("pieces") or []) if p.get("piece_id")
    }
    for updated in pieces:
        piece_id = updated.get("piece_id")
        if not piece_id or piece_id not in old_by_id:
            continue
        old = old_by_id[piece_id]
        if not _piece_has_order(old):
            continue
        if not _options_unchanged(old.get("options") or [], updated.get("options") or []):
            raise HTTPException(
                status_code=403,
                detail="No se pueden modificar opciones de una pieza ya ordenada",
            )


def _require_piece_options_editable(doc: dict, piece_id: str) -> None:
    target = next(
        (p for p in (doc.get("pieces") or []) if p.get("piece_id") == piece_id),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Piece not found")
    if _piece_has_order(target):
        raise HTTPException(
            status_code=403,
            detail="No se pueden modificar opciones de una pieza ya ordenada",
        )


def _require_capture_editable_after_order(doc: dict) -> None:
    if _has_ordered_pieces(doc):
        raise HTTPException(
            status_code=403,
            detail="No se pueden modificar el folio después de crear una orden",
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


def _vehicle_information_schema(raw) -> Optional["GroupVehicle"]:
    """Coerce Mongo dict or GroupVehicle into PartRequest.vehicleInformation."""
    if not raw:
        return None
    from app.schemas.GroupVehicle import GroupVehicle

    if isinstance(raw, GroupVehicle):
        return raw
    if isinstance(raw, dict):
        return GroupVehicle(**raw)
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
    offer_embed["origin"] = "mostrador"
    offer_embed["mostrador_folio_id"] = folio_id
    offer_embed["mostrador_piece_id"] = piece_id
    order_doc["offer"] = offer_embed
    order_doc["origin"] = order_doc.get("origin") or "mostrador"
    order_doc["mostrador_folio_id"] = order_doc.get("mostrador_folio_id") or folio_id
    order = Order(**order_doc)
    order_data = order.toJson()
    order_data.pop("_id", None)
    orderRepository.edit(ObjectId(order_doc_id), order_data)


def _ensure_folio_specific_order_uid(folio_id: str, folio: dict) -> tuple[dict, str]:
    """Ensure folio and in-memory doc share one canonical specific_order_uid."""
    uid = folio.get("specific_order_uid")
    if not uid:
        uid = uuid4().hex
        folioRepository.edit(folio_id, {"specific_order_uid": uid, "updated_at": _now()})
        folio = {**folio, "specific_order_uid": uid}
    return folio, uid


def _sync_part_request_specific_order_uid(folio_id: str, specific_order_uid: str) -> None:
    """Align all materialized PartRequests with the folio batch uid."""
    from app.repositories import PartRequestRepository as partRequestRepository

    if not specific_order_uid:
        return
    now = _now()
    for pr in list(partRequestRepository.find({"mostrador_folio_id": folio_id}, {})):
        if pr.get("specific_order_uid") == specific_order_uid:
            continue
        partRequestRepository.edit_part_request(str(pr["_id"]), {
            "specific_order_uid": specific_order_uid,
            "updatedAt": now,
        })


def _domicilio_delivery_fields(order_info: dict) -> dict:
    if (order_info.get("delivery_mode") or "tienda") != "domicilio":
        return {}
    fields = {}
    if order_info.get("delivery_address"):
        fields["delivery_address"] = order_info.get("delivery_address")
    if order_info.get("delivery_contact"):
        fields["delivery_contact"] = order_info.get("delivery_contact")
    return fields


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
            "specific_order_uid": specific_order_uid,
            "isActive": True,
            "updatedAt": now,
            "mostrador_delivery_mode": order_info.get("delivery_mode") or "tienda",
            **_domicilio_delivery_fields(order_info),
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
        "mostrador_delivery_mode": order_info.get("delivery_mode") or "tienda",
        "createdAt": now,
        "updatedAt": now,
        **_domicilio_delivery_fields(order_info),
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

    doc, specific_order_uid = _ensure_folio_specific_order_uid(folio_id, doc)
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
    _sync_part_request_specific_order_uid(folio_id_str, specific_order_uid)
    _ensure_mostrador_orders_materialized(folio_id)


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
    doc, specific_order_uid = _ensure_folio_specific_order_uid(folio_id, doc)
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
    _ensure_mostrador_orders_materialized(folio_id_str)
    sync_assigned_folio(folio_id_str)
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

    return _dispatch_notifications({"folio": _hydrate(refreshed), "part_request_ids": pr_ids, "notification": notification})


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
    customer_group_id = customer.get("group_id") or ""
    customer_uid = customer.get("user_uid") or folio.get("creator_user")
    unit = option.get("unit_of_measure") or piece.get("unitOfMeasure") or "Pieza"

    vehicle = folio.get("vehicle") or {}
    part = _folio_part_payload(piece, unit)
    vehicle_information = _vehicle_information_schema(_load_vehicle_information(vehicle))

    request_id = f"mostrador:{folio_id}:{piece.get('piece_id')}"
    from app.repositories import PartRequestRepository as partRequestRepository
    existing_prs = list(partRequestRepository.find(
        {"mostrador_folio_id": folio_id, "mostrador_piece_id": piece.get("piece_id")}, {}
    ))
    if existing_prs:
        pr_doc = existing_prs[0]
        request_id = str(pr_doc["_id"])
        if not vehicle_information:
            vehicle_information = _vehicle_information_schema(pr_doc.get("vehicleInformation"))

    offer = Offer(
        request_id=request_id,
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
        origin="mostrador",
        mostrador_folio_id=folio_id,
        mostrador_piece_id=piece.get("piece_id"),
    )

    part_request = PartRequest(
        creatorGroup=str(customer_group_id) if customer_group_id else "",
        creatorUser=customer_uid or "",
        vehicleId=str(vehicle.get("group_vehicle_id") or ""),
        subscribedSellers=[str(seller_group_id)] if seller_group_id else [],
        part=part,
        partList=[],
        specific_order_uid=specific_order_uid,
        fulfillment_type=FulfillmentType.pickup,
        origin="mostrador",
        mostrador_folio_id=folio_id,
        mostrador_piece_id=piece.get("piece_id"),
        mostrador_delivery_mode=order_info.get("delivery_mode") or "tienda",
        delivery_address=order_info.get("delivery_address"),
        delivery_contact=order_info.get("delivery_contact"),
        vehicleInformation=vehicle_information,
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


def _piece_has_seller_order_pending_materialization(piece: dict) -> bool:
    order = piece.get("order")
    if not order or order.get("order_doc_id"):
        return False
    option_index = order.get("option_index")
    options = piece.get("options") or []
    if option_index is None or option_index < 0 or option_index >= len(options):
        return False
    return not options[option_index].get("captured_by_buyer")


def _ensure_mostrador_orders_materialized(folio_id: str, *, swallow_errors: bool = False) -> None:
    """Create in-person Order docs for embedded piece orders (buyer optional until assign)."""
    doc = folioRepository.find_by_id(folio_id)
    if not doc:
        return
    has_unmaterialized = any(
        _piece_has_seller_order_pending_materialization(p)
        for p in (doc.get("pieces") or [])
    )
    if not has_unmaterialized:
        return
    try:
        confirm(folio_id, allow_when_assigned=True)
    except HTTPException:
        if swallow_errors:
            return
        raise
    except Exception:
        if swallow_errors:
            import logging
            logging.exception(
                "Failed to materialize mostrador orders for folio %s", folio_id)
            return
        raise


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

    seller_pending = [
        p for p in ordered_pieces
        if _piece_has_seller_order_pending_materialization(p)
    ]
    if not seller_pending:
        return {
            "folio": _hydrate(doc),
            "order_ids": [],
            "specific_order_uid": doc.get("specific_order_uid") or "",
            "notifications": [],
        }

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
        option_index = piece["order"].get("option_index")
        piece_options = piece.get("options") or []
        if (
            option_index is not None
            and 0 <= option_index < len(piece_options)
            and piece_options[option_index].get("captured_by_buyer")
        ):
            continue  # buyer walk-in capture — no seller order doc
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

    return _dispatch_notifications({
        "folio": _hydrate(updated),
        "order_ids": created_ids,
        "specific_order_uid": specific_order_uid,
        "notifications": notifications,
    })


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
