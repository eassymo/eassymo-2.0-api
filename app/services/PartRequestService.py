from app.repositories import PartRequestRepository as partRequestRepository
from app.schemas.PartRequest import (
    PartRequest,
    PartRequestEdit,
    PartRequestStatus,
    PartRequestGroupedByDate,
    FulfillmentType,
    validate_delivery_fulfillment,
)
from app.schemas.Offer import OfferStatus
from app.repositories import GroupCarRepository as groupCarRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import OfferRepository as offerRepository
from app.repositories import RequestStatusByGroupRepository as requestStatusByGroupRepository
from app.repositories import ListsRepository as listRepository
from app.repositories import CommissionerInviteRepository as commissionerInviteRepository
from app.schemas.Groups import GroupType, GroupSchema
from app.schemas.Offer import Offer
from fastapi import HTTPException, Request, status
from uuid import uuid4
from bson import ObjectId
from typing import List, Any, Dict, Optional
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app.services import GroupService as groupService
from app.utils.notification_routes import seller_offer_creator_path
from app.factories.NotificationsCreator import (
    create_part_request_notification,
)
from app.utils.notifications import send_notification
from app.services import ListsService as listService
from app.services import ArmadoraCompatibilityService
from app.services import SistemasCompatibilityService
from app.services import SellerReachService as sellerReachService

import math
import pymongo

from app.services import RouteService


def _empty_commissioner_connections() -> Dict[str, Any]:
    """Shape expected by insert() after __find_commissioner_group_connections; never return a bare []."""
    return {
        "commissioner_groups_from_lists": [],
        "users_from_groups": [],
    }


def _default_fulfillment_type_on_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc.get("fulfillment_type"):
        return {**doc, "fulfillment_type": FulfillmentType.delivery.value}
    return doc


def _normalize_subscribed_seller_ids(raw: Optional[List[Any]]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in raw or []:
        if item is None:
            continue
        if isinstance(item, str):
            sid = item.strip()
        elif isinstance(item, ObjectId):
            sid = str(item).strip()
        elif isinstance(item, dict):
            oid = item.get("$oid") or item.get("_id")
            if isinstance(oid, dict) and "$oid" in oid:
                sid = str(oid["$oid"]).strip()
            else:
                sid = str(oid or item.get("groupId") or item.get("id") or "").strip()
        else:
            sid = str(getattr(item, "_id", None) or getattr(item, "id", None) or item).strip()
        if sid and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def expand_subscribed_sellers_with_accepted_comisionados(
    subscribed_sellers: Optional[List[Any]],
    creator_group_id: Optional[str] = None,
) -> List[str]:
    """One hop: add invited_group_id for ACCEPTED invites of every commissioner in subscribed_sellers."""
    normalized = _normalize_subscribed_seller_ids(subscribed_sellers)
    if not normalized:
        return []
    docs = list(
        groupRepository.find_many_by_string_ids(
            normalized, {"is_commissioner": 1}
        )
    )
    commissioner_ids: List[str] = []
    for doc in docs:
        if doc.get("is_commissioner") is True:
            commissioner_ids.append(str(doc["_id"]))
    invited = commissionerInviteRepository.find_accepted_invited_group_ids_for_commissioners(
        commissioner_ids
    )
    creator = str(creator_group_id).strip() if creator_group_id else ""
    merged: List[str] = []
    merged_set: set[str] = set()
    for gid in normalized:
        if gid not in merged_set:
            merged_set.add(gid)
            merged.append(gid)
    for gid in invited:
        if creator and gid == creator:
            continue
        if gid not in merged_set:
            merged_set.add(gid)
            merged.append(gid)
    return merged


def _vehicle_maker_from_information(vehicle_information: Any) -> Optional[str]:
    if vehicle_information is None:
        return None
    if isinstance(vehicle_information, dict):
        maker = vehicle_information.get("maker")
    else:
        maker = getattr(vehicle_information, "maker", None)
    if maker is None:
        return None
    maker_str = str(maker).strip()
    return maker_str or None


def _now() -> datetime:
    return datetime.now(ZoneInfo('UTC'))


def _commissioner_reach(creator_group: str, commissioner_group: Optional[str]) -> tuple[List[str], List[Any]]:
    """Stores near the buyer from the commissioner's lists (added to every part) and their users (for notifications)."""
    if commissioner_group is None:
        return [], []
    connections = __find_commissioner_group_connections(
        creator_group_id=creator_group,
        commissioner_group_id=commissioner_group
    )
    store_ids = [group.id for group in connections["commissioner_groups_from_lists"]]
    return store_ids, connections["users_from_groups"]


def _part_audiences(
    creator_group: str,
    vehicle_maker: Optional[str],
    part_list: List[Any],
    base_sellers_for,
    subscribed_followers: Optional[List[str]],
    commissioner_store_ids: List[str],
) -> List[dict]:
    """Per part: base sellers + commissioner stores, accepted-comisionado expansion, then compatibility."""
    expanded_by_base: Dict[tuple, List[str]] = {}
    parts: List[dict] = []
    for index, car_part in enumerate(part_list):
        base = list(base_sellers_for(index) or [])
        key = tuple(base)
        if key not in expanded_by_base:
            sellers = list(base)
            for store_id in commissioner_store_ids:
                if store_id not in sellers:
                    sellers.append(store_id)
            expanded_by_base[key] = expand_subscribed_sellers_with_accepted_comisionados(sellers, creator_group)
        subscribed, non_compatible = __resolve_subscribed_and_non_compatible(
            expanded_by_base[key],
            vehicle_maker,
            car_part,
        )
        parts.append({
            "index": index,
            "subscribed": subscribed,
            "non_compatible": non_compatible,
            "audience": sellerReachService.audience(subscribed, subscribed_followers),
        })
    return parts


def compute_part_audiences(
    creator_group: str,
    vehicle_id: str,
    part_list: List[Any],
    subscribed_sellers: List[str],
    subscribed_followers: List[str],
    commissioner_group: Optional[str],
) -> List[dict]:
    """The sellers each part would reach, exactly as insert() resolves them. Reads only."""
    vehicle_maker = _vehicle_maker_from_information(groupCarRepository.find_by_id(vehicle_id))
    commissioner_store_ids, _ = _commissioner_reach(creator_group, commissioner_group)
    return _part_audiences(
        creator_group, vehicle_maker, part_list or [], lambda _index: subscribed_sellers,
        subscribed_followers, commissioner_store_ids,
    )


def _validate_reach_plan(part_request: PartRequest) -> None:
    plan = part_request.reach_plan
    if plan is None:
        return
    selected = set(part_request.subscribedSellers or [])
    outside = [seller for seller in plan.capped_sellers if seller not in selected]
    if outside:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"reach_plan.capped_sellers must be among subscribedSellers: {outside}",
        )
    part_count = len(part_request.partList or [])
    if any(index < 0 or index >= part_count for index in plan.wide_part_indexes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reach_plan.wide_part_indexes out of range",
        )


def _roll_back_insert(creator_group: str, reserved: List[tuple], inserted_ids: List[Any]) -> None:
    """Undo a batch that failed before anyone was notified: drop inserted docs, give slots back."""
    try:
        partRequestRepository.delete_by_ids(inserted_ids)
    except Exception as error:
        print(f"Seller reach: failed to roll back part requests {inserted_ids}: {error}")
    for day, request_id in reserved:
        try:
            sellerReachService.release(creator_group, day, request_id)
        except Exception as error:
            print(f"Seller reach: failed to release slot {request_id} ({day}): {error}")


def insert(part_request: PartRequest, user_token: str = None):
    reserved: List[tuple] = []  # (day, request_id) of slots this call reserved
    inserted_ids = []
    committed = False
    try:
        try:
            validate_delivery_fulfillment(
                part_request.fulfillment_type,
                part_request.delivery_address,
                part_request.delivery_contact,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        _validate_reach_plan(part_request)

        if part_request.parent_request_uid != None and len(part_request.parent_request_uid) > 0:
            parent_request_uid = part_request.parent_request_uid
        else:
            parent_request_uid = str(uuid4())
        part_req = part_request.dict()
        # Do not persist empty client id; Mongo assigns _id (empty id breaks commissioner/offer matching).
        part_req.pop("id", None)
        part_req.pop("_id", None)
        part_req["fulfillment_type"] = part_request.fulfillment_type.value
        vehicle_information = groupCarRepository.find_by_id(
            part_req["vehicleId"])

        creator_group_data = groupRepository.find_by_id(
            part_request.creatorGroup)

        if creator_group_data != None:
            part_request.group_info = GroupSchema(**creator_group_data)

        commissioner_store_ids, users_from_groups = _commissioner_reach(
            part_request.creatorGroup, part_request.commissioner_group)

        plan = part_request.reach_plan
        wide_indexes = set(plan.wide_part_indexes) if plan is not None else set()
        selected_sellers = list(part_request.subscribedSellers or [])

        def base_sellers_for(index: int) -> List[str]:
            if plan is not None and index not in wide_indexes:
                return plan.capped_sellers
            return selected_sellers

        part_list = list(part_request.partList or [])
        parts = _part_audiences(
            part_request.creatorGroup,
            _vehicle_maker_from_information(vehicle_information),
            part_list,
            base_sellers_for,
            part_request.subscribedFollowers,
            commissioner_store_ids,
        )

        # Decide every part before inserting any; parts the buyer chose as wide take slots first.
        request_ids = [ObjectId() for _ in parts]
        decisions: List[Optional[dict]] = [None] * len(parts)
        now = _now()
        for index in sorted(range(len(parts)), key=lambda i: i not in wide_indexes):
            decision = sellerReachService.decide(
                part_request.creatorGroup, str(request_ids[index]), parts[index]["audience"], 0, None, now)
            decisions[index] = decision
            if decision["tier"] == "wide":
                reserved.append((decision["day"], str(request_ids[index])))

        for index, car_part in enumerate(part_list):
            part_request_payload = {
                **part_req,
                "_id": request_ids[index],
                "part": car_part,
                "vehicleInformation": vehicle_information,
                "parent_request_uid": parent_request_uid,
                "status": part_request.status.value,
                "specific_order_uid": part_request.specific_order_uid,
                "subscribedSellers": parts[index]["subscribed"],
                "nonCompatibleSellers": parts[index]["non_compatible"],
                "reach": decisions[index],
                "createdAt": _now()
            }
            del part_request_payload["partList"]
            part_request_id = partRequestRepository.insert(
                part_request_payload).inserted_id
            inserted_ids.append(part_request_id)
        committed = True

        found_part_requests = list(partRequestRepository.find(
            {"_id": {"$in": inserted_ids}}, {}))

        found_part_requests = [__format_part_request(
            part_request) for part_request in found_part_requests]

        if part_request.commissioner_group != None and user_token:
            for part_part_request in found_part_requests:
                __build_and_send_commissioner_notifications(
                    users_from_groups=users_from_groups,
                    part_request_data=part_part_request,
                    creator_group_id=part_request.creatorGroup,
                    creator_name=part_request.group_info.name,
                    user_token=user_token
                )

        from app.services import notification_fanout

        creator_name = part_request.group_info.name if part_request.group_info else ""
        notification_fanout.fanout_part_request_created(
            part_requests=found_part_requests,
            creator_group_name=creator_name,
            subscribed_sellers=list(part_request.subscribedSellers or []),
            subscribed_followers=list(part_request.subscribedFollowers or []),
            commissioner_group=part_request.commissioner_group,
        )

        return found_part_requests
    except Exception as e:
        if not committed:
            _roll_back_insert(part_request.creatorGroup, reserved, inserted_ids)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=500, detail=f'Error while inserting part request {e}')


def __find_commissioner_group_connections(creator_group_id: str, commissioner_group_id: str) -> Dict[str, Any]:
    # TODO: Encontrar a los grupos del comisionado que esten cercanos a el grupo que esta creando la solicitud
    try:
        creator_group_data = groupRepository.find_by_id(creator_group_id)
        if creator_group_data != None:
            creator_group = GroupSchema(**creator_group_data)

            if creator_group.location is None:
                return _empty_commissioner_connections()

            commissioner_group_lists = list(
                listRepository.find_all_groups_in_user_lists(None, commissioner_group_id))

            all_group_ids = []
            for list_data in commissioner_group_lists:
                if 'all_groups' in list_data:
                    all_group_ids.extend(list_data['all_groups'])

            unique_group_ids = list(set(all_group_ids))

            if not unique_group_ids:
                return _empty_commissioner_connections()

            users_from_groups = groupService.find_users_by_groups_ids_v2(
                unique_group_ids)

            nearby_groups = list(groupRepository.find_within_radius(
                group_ids=unique_group_ids,
                center_location=creator_group.location.dict(),
                radius_meters=500
            ))

            commissioner_groups_from_lists: List[GroupSchema] = []
            for group_data in nearby_groups:
                commissioner_groups_from_lists.append(
                    GroupSchema(**group_data))

            return {
                "commissioner_groups_from_lists": commissioner_groups_from_lists,
                "users_from_groups": users_from_groups
            }
        else:
            return _empty_commissioner_connections()

    except HTTPException as e:
        raise e


def build_and_send_notification(
    user_id: str,
    group_id: str,
    created_part_request_id: str,
    part_name: str,
    store_name: str,
    user_token: str
) -> None:
    try:
        # Handle different user_id formats
        if isinstance(user_id, dict):
            owner_id = user_id.get("_id") or user_id.get(
                "uid") or user_id.get("id")
        else:
            owner_id = user_id

        if not owner_id:
            print(f"⚠️ Warning: Invalid user_id format: {user_id}")
            return

        notification = create_part_request_notification(
            store_name=store_name,
            part_name=part_name,
            owner=owner_id,
            owner_group=group_id,
            navigate_to_url=seller_offer_creator_path(created_part_request_id),
            meta_data={"requestId": created_part_request_id}
        )

        send_notification(notification, user_token)

    except Exception as error:
        print(f"❌ Critical error in notification system: {error}")
        print(
            f"📧 Failed notification - User: {user_id}, Part: {part_name}, Store: {store_name}")
        # Log the error but don't re-raise to avoid breaking part request creation


def __dedupe_group_ids(group_ids: List[str]) -> List[str]:
    unique: List[str] = []
    seen: set[str] = set()
    for group_id in group_ids or []:
        normalized = str(group_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def __resolve_subscribed_and_non_compatible(
    candidate_seller_ids: List[str],
    vehicle_maker: Optional[str],
    car_part: Any,
) -> tuple[List[str], List[Dict[str, str]]]:
    candidates = __dedupe_group_ids(candidate_seller_ids)

    armadora_eval = ArmadoraCompatibilityService.evaluate_bulk(
        candidates, vehicle_maker
    )
    armadora_excluded = {
        item["group_id"]: item["reason"]
        for item in armadora_eval.get("excluded", [])
        if item.get("group_id")
    }

    sistemas_eval = SistemasCompatibilityService.evaluate_bulk_for_car_part(
        armadora_eval.get("compatible", []), car_part
    )
    sistemas_excluded = {
        item["group_id"]: item["reason"]
        for item in sistemas_eval.get("excluded", [])
        if item.get("group_id")
    }

    non_compatible: List[Dict[str, str]] = []
    for group_id in candidates:
        if group_id in armadora_excluded:
            non_compatible.append(
                {"group_id": group_id, "reason": armadora_excluded[group_id]}
            )
        elif group_id in sistemas_excluded:
            non_compatible.append(
                {"group_id": group_id, "reason": sistemas_excluded[group_id]}
            )

    return sistemas_eval.get("compatible", []), non_compatible


def __format_part_request(part_request):
    part_request = PartRequest(**part_request)
    return part_request.toJson()


def find(user_uid: str | None, group_id: str | None, specific_order_uid: str | None, status: str | None):
    try:

        filters: Dict[str, Any] = {}

        if user_uid != None and group_id != None:
            filters = {
                "$or": [
                    {"creatorUser": user_uid},
                    {"subscribedSellers": group_id},
                    {"subscribedFollowers": group_id},
                ]
            }

        if specific_order_uid != None:
            filters = {**filters, "specific_order_uid": specific_order_uid}

        if status != None:
            filters = {**filters, "status": status}

        found_requests = partRequestRepository.find(filters, {})

        found_requests_list = list(found_requests)
        return format_part_requests(found_requests_list)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def find_by_id(id, request: Request | None = None):
    try:
        found_request = list(partRequestRepository.find_by_id(id))
        if found_request is not None and len(found_request) > 0:
            found_request = found_request[0]

        if found_request is not None:
            offers_for_request = list(offerRepository.find(
                {'request_id': str(found_request["_id"])}))
            found_request = {
                **found_request,
                "_id": str(found_request["_id"]),
                "show_ranking": len(offers_for_request) > 1,
                "createdAt": str(found_request["createdAt"]),
                "updatedAt": str(found_request["updatedAt"]),
                "vehicleInformation": {
                    **found_request["vehicleInformation"],
                    "_id": str(found_request["_id"]),
                    "createdAt": str(found_request["createdAt"])
                },
                "group_info": {
                    **found_request["group_info"],
                    "_id": str(found_request["_id"])
                },
            }
            found_request = _default_fulfillment_type_on_dict(found_request)

            found_request["partList"] = __find_sister_part_list(
                found_request["specific_order_uid"])

            if request is not None:
                user_info = request.state._state.get("user") or {}
                logged_in_user = user_info.get("uid")
                creator_group_id = found_request.get("creatorGroup")
                if logged_in_user and creator_group_id:
                    enriched_requests = __attach_offers_to_part_requests(
                        [found_request],
                        creator_group_id,
                        logged_in_user,
                        [],
                        None,
                    )
                    if enriched_requests:
                        found_request = enriched_requests[0]

        return found_request
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def __find_sister_part_list(specific_order_uid: str):
    try:
        sister_requests = list(
            partRequestRepository.find_sister_part_requests(specific_order_uid, status=PartRequestStatus.CREATED.value))

        formatted_sister_requests = []

        for sister_part in sister_requests:
            formatted_sister_requests.append(
                _default_fulfillment_type_on_dict({
                    **sister_part,
                    "_id": str(sister_part["_id"]),
                })
            )

        return formatted_sister_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def format_part_requests(part_requests):
    formatted_requests = []
    for part_request in part_requests:
        formatted_requests.append(
            _default_fulfillment_type_on_dict({
                **part_request,
                "vehicleInformation": {
                    **part_request["vehicleInformation"],
                    "_id": str(part_request["vehicleInformation"]["_id"])
                },
                "_id": str(part_request["_id"])
            })
        )
    return formatted_requests


def find_grouped(
        group_id: str,
        group_role: str,
        creator_group: str,
        vehicle_model: str,
        vehicle_id: str,
        created_at: str,
        search_argument: str,
        page: int = 1,
        limit: int = 10
):
    try:
        filters = __format_grouped_filters(
            group_id,
            group_role,
            creator_group,
            vehicle_model,
            vehicle_id,
            created_at,
            search_argument,
        )

        role = int(group_role)

        if (role == 2):
            filters["status"] = PartRequestStatus.CREATED.value

        skip = (page - 1) * limit

        part_requests = list(
            partRequestRepository.find_grouped(filters, skip, limit))

        if len(part_requests) == 0:
            return {
                "data": part_requests,
                "pagination": {
                    "total": 0,
                    "page": page,
                    "limit": limit,
                    "total_pages": 0
                }
            }

        print(part_requests)

        grouped_by_created_date = {}

        part_requests = [PartRequest(**part_request)
                         for part_request in part_requests]

        print(part_requests)

        found_offers = __find_offers_for_requests(
            part_requests, group_id if role == GroupType.CAR_SHOP.value else None)

        __format_offers_with_found_requests(
            requests=part_requests, offers=found_offers, group_id=group_id)

        for part_request in part_requests:

            date_string = part_request.createdAt.strftime('%Y-%m-%d')

            if grouped_by_created_date.get(date_string) == None:
                grouped_by_created_date[date_string] = [part_request]
            else:
                grouped_by_created_date[date_string].append(part_request)

        grouped_part_requests: List[PartRequestGroupedByDate] = []

        for date_key in grouped_by_created_date:
            grouped_part_requests.append(PartRequestGroupedByDate(
                date=date_key,
                part_requests=grouped_by_created_date[date_key]
            ))

        total_count = partRequestRepository.count_grouped(filters)

        return {
            "data": [grouped_part_request.toJson() for grouped_part_request in grouped_part_requests],
            "pagination": {
                "total": total_count,
                "page": page,
                "limit": limit,
                "total_pages": -(-total_count // limit)
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error finding grouped requests {e}')


def find_unquoted_for_seller(group_id: str, limit: int = 200):
    """
    Every open request the seller can see (same rules as find_grouped for role 2) that the
    seller's group hasn't answered with any offer, "sin stock" included. Newest first, capped
    at `limit`; `total` counts them all so the dashboard headline is the real number.
    """
    filters = __format_grouped_filters(group_id, str(GroupType.CAR_SHOP.value), None, None, None, None, None)
    filters["status"] = PartRequestStatus.CREATED.value
    filters["$and"].append({"creatorGroup": {"$ne": group_id}})

    # Check offers only against the open requests this seller can see, so the exclusion list stays
    # as small as the open backlog instead of every request the store ever answered.
    open_ids = [str(oid) for oid in partRequestRepository.find_open_ids(filters)]
    excluded = []
    for rid in offerRepository.distinct_request_ids_for_group(group_id, open_ids):
        if rid and ObjectId.is_valid(str(rid)):
            excluded.append(ObjectId(str(rid)))

    docs = partRequestRepository.find_unquoted(filters, excluded, limit=limit)
    items = [PartRequest(**doc).toJson() for doc in docs]
    return {"items": items, "total": partRequestRepository.count_unquoted(filters, excluded)}


class LocationMissing(HTTPException):
    """A store has no usable pin, so there is no route to draw."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(status_code=422, detail=code)


def _group_point(group_id: str, code: str) -> Dict[str, float]:
    group = groupRepository.find_by_id(group_id, {"location": 1}) or {}
    coords = (group.get("location") or {}).get("coordinates") or []
    if len(coords) != 2 or not all(isinstance(c, (int, float)) and math.isfinite(c) for c in coords):
        raise LocationMissing(code)
    lng, lat = coords
    if (lng == 0 and lat == 0) or abs(lat) > 90 or abs(lng) > 180:
        raise LocationMissing(code)
    return {"lat": lat, "lng": lng}


def get_buyer_route(part_request_id: str, seller_group_id: str) -> Dict[str, Any]:
    """Driving route from the seller's store to the request's buyer. Both points come from the
    database, never from the caller. A request the seller can't see answers 404 with no
    location data (closed requests still count as visible)."""
    if not ObjectId.is_valid(part_request_id):
        raise HTTPException(status_code=404, detail="Request not found")
    filters = __format_grouped_filters(seller_group_id, str(GroupType.CAR_SHOP.value), None, None, None, None, None)
    filters["$and"].append({"_id": ObjectId(part_request_id)})
    if not partRequestRepository.find_open_ids(filters):
        raise HTTPException(status_code=404, detail="Request not found")
    request_doc = partRequestRepository.find_one_by_id(part_request_id) or {}
    buyer_group_id = str(request_doc.get("creatorGroup") or "")
    if not ObjectId.is_valid(buyer_group_id):
        raise LocationMissing("buyer_location_missing")
    origin = _group_point(seller_group_id, "seller_location_missing")
    destination = _group_point(buyer_group_id, "buyer_location_missing")
    return RouteService.get_pair_route(origin, destination)


def find_distinct_vehicle_ids_in_requests(
    group_id: Optional[str],
    group_role: Optional[str],
):
    """
    Same filter pipeline as find_grouped (group_id, group_role, optional filters),
    returns sorted distinct vehicleId strings from matching PartRequests.
    """
    filters = __format_grouped_filters(
        group_id,
        group_role
    )

    if group_role is not None and len(str(group_role)) > 0:
        role = int(group_role)
        if role == 2:
            filters["status"] = PartRequestStatus.CREATED.value
    raw_ids = partRequestRepository.distinct_vehicle_ids_grouped(filters)
    seen = set()
    out: List[str] = []
    for vid in raw_ids:
        if vid is None:
            continue
        s = str(vid).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    out.sort()
    return out


def __find_offers_for_requests(requests: List[PartRequest], group_id: str) -> List[Offer]:
    request_ids = [request.id for request in requests]

    offers_found = list(
        offerRepository.find_by_request_ids(request_ids, group_id))

    offers_found = [Offer(**offer) for offer in offers_found]

    return offers_found


def __format_offers_with_found_requests(requests: List[PartRequest], offers: List[Offer], group_id: str):
    for request in requests:
        matching_for_request = [
            offer for offer in offers
            if offer.request_id == request.id
        ]
        request.offers_amount = __count_offers_for_grouped_dashboard(
            matching_for_request, request)

        offers_found = __filter_part_offer_by_request_id(
            offers, request, group_id)
        if len(offers_found) > 0:
            request.offers = offers_found
        else:
            request.offers = []


def __filter_part_offer_by_request_id(offers: List[Offer], request: PartRequest, group_id: str):

    creator_group = request.creatorGroup

    matching_offers = [
        offer for offer in offers
        if offer.request_id == request.id
    ]

    if len(matching_offers) > 0:
        gv = _normalize_group_id_for_offer_filter(group_id)
        cv = _normalize_group_id_for_offer_filter(creator_group)
        if gv == cv:
            has_commissioner = _part_request_has_commissioner(request)
            matching_offers = [
                offer
                for offer in matching_offers
                if (
                    _offer_status_value(offer) != OfferStatus.pending_approval.value
                    or has_commissioner
                    or _offer_posted_via_call_center(offer)
                )
            ]

    return matching_offers


def _part_request_has_commissioner(request: PartRequest) -> bool:
    raw = getattr(request, "commissioner_group", None)
    if raw is None:
        return False
    return len(str(raw).strip()) > 0


def _offer_status_value(offer: Offer) -> str:
    status = offer.status
    return status.value if isinstance(status, OfferStatus) else str(status)


def _normalize_group_id_for_offer_filter(raw) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _group_nested_has_id(group_nested) -> bool:
    """True if nested group/call_center object carries an id (from DB _id)."""
    if group_nested is None:
        return False
    if isinstance(group_nested, dict):
        oid = group_nested.get("_id") or group_nested.get("id")
        return bool(oid is not None and str(oid).strip())
    oid = getattr(group_nested, "id", None)
    if oid is not None:
        return bool(str(oid).strip())
    alt = getattr(group_nested, "_id", None)
    return bool(str(alt or "").strip())


def _offer_posted_via_call_center(offer: Offer) -> bool:
    return _group_nested_has_id(getattr(offer, "call_center_that_posted_offer", None))


def __count_offers_for_grouped_dashboard(offers_for_request: List[Offer], request: PartRequest) -> int:
    """
    Dashboard list badge for GET /partRequest/grouped counts:
    - Created,
    - Pending_Approval when the request has a commissioner or the offer was
      posted via a call center,
    - Workshop_Approval_Pending (awaiting workshop technical validation).
    """
    has_commissioner = _part_request_has_commissioner(request)
    n = 0
    for offer in offers_for_request:
        sv = _offer_status_value(offer)
        if sv == OfferStatus.created.value:
            n += 1
        elif sv == OfferStatus.workshop_approval_pending.value:
            n += 1
        elif sv == OfferStatus.pending_approval.value:
            if has_commissioner or _offer_posted_via_call_center(offer):
                n += 1
    return n


def __format_grouped_filters(
    group_id: str,
    group_role: str,
    creatorGroup: str | None,
    vehicle_model: str | None,
    vehicle_id: str | None,
    created_at: str | None,
    search_argument: str | None,
):

    current_group_role: int

    if group_role != None and len(group_role) > 0:
        current_group_role = int(group_role)

    filters = {
        "$and": [

        ]
    }
    if group_id is not None:
        if current_group_role == GroupType.CAR_SHOP.value:
            filters["$and"].append({
                "$or": [
                    {"subscribedSellers": group_id},
                    {"subscribedFollowers": group_id},
                ]
            })
        if current_group_role == GroupType.PARTS_STORE.value:
            filters["$and"].append({"creatorGroup": group_id})

    if creatorGroup is not None:
        categories_array = creatorGroup.split(',')
        filters["$and"].append(
            {
                "creatorGroup": {"$in": categories_array}
            }
        )

    if vehicle_model is not None:
        vehicle_models_array = vehicle_model.split(',')
        for model in vehicle_models_array:
            model.strip()
        filters["$and"].append(
            {
                "vehicleInformation.model": {"$in": vehicle_models_array}
            }
        )

    if vehicle_id is not None:
        filters["$and"].append(
            {
                "vehicleId": vehicle_id
            }
        )

    if created_at != None:
        created_at_array = created_at.split(',')

        created_at_dates = list(map(lambda created: datetime.strptime(
            created, "%Y-%m-%d %H:%M:%S.%f"), created_at_array))
        filters["$and"].append(
            {
                "createdAt": {"$in": created_at_dates}
            }
        )

    if search_argument != None:
        filters["$or"] = [
            {
                "part.tipoParteDescripcion": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
            {
                "vehicleInformation.maker": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
            {
                "vehicleInformation.model": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
            {
                "vehicleInformation.subModel": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
        ]

    return filters


def search(search_argument: str, category: str, sub_category: str, part_type: str):
    try:
        filters = __format_search_arguments(
            search_argument, category, sub_category, part_type)
        reduced_part_requests = list(
            partRequestRepository.search_reduced(filters))
        __format_reduced_requests(reduced_part_requests)
        return reduced_part_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error finding reduced requests {e}')


def __format_search_arguments(search_argument: str, category: str, sub_category: str, part_type: str):
    applied_filters = {
        "$or": [
            {
                "part.tipoParteDescripcion": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
            {
                "vehicleInformation.maker": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
            {
                "vehicleInformation.model": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
            {
                "vehicleInformation.subModel": {
                    "$regex": search_argument,
                    "$options": "i"
                }
            },
        ],

    }

    if category != None:
        categories_array = category.split(',')
        applied_filters["$and"].append(
            {
                "part.categoria.categoriaDescripcion": {"$in": categories_array}
            }
        )

    if sub_category != None:
        sub_categories_array = sub_category.split(',')
        for category in sub_categories_array:
            category.strip()
        applied_filters["$and"].append(
            {
                "part.subCategoria.subCategoriaDescripcion": {"$in": sub_categories_array}
            }
        )

    if part_type != None:
        part_types_array = part_type.split(',')
        applied_filters["$and"].append(
            {
                "part.tipoParteDescripcion": {"$in": part_types_array}
            }
        )
    return applied_filters


def __format_reduced_requests(part_requests):
    for i, part_request in enumerate(part_requests):
        part_request = _default_fulfillment_type_on_dict(part_request)
        part_request["_id"] = str(part_request["_id"])
        part_request["vehicleInformation"]["_id"] = str(
            part_request["vehicleInformation"]["_id"])
        part_request["createdAt"] = str(part_request["createdAt"])
        part_requests[i] = part_request


def build_filter(prop_name: str):
    try:
        filter_options = list(
            partRequestRepository.build_filter(propName=prop_name))

        if (len(filter_options) == 0):
            return []

        filter_options = list(map(lambda filter_option: {
                              "label": filter_option, "value": filter_option}, filter_options))

        if (prop_name == "creatorGroup"):
            group_ids = list(
                map(lambda group_id: ObjectId(group_id["value"]), filter_options))
            filter_options = __find_groups_and_format(group_ids)

        if (prop_name == "createdAt"):
            filter_options = list(map(lambda filter_option: {
                "label": filter_option["value"].strftime('%d-%m-%Y'), "value": str(filter_option["value"])}, filter_options))

        return filter_options
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error building filter options {e}')


def __find_groups_and_format(group_ids: List[ObjectId]):
    found_groups = list(groupRepository.find_by_id_list(group_ids))
    return list(map(lambda group: {"label": group["name"], "value": str(group["_id"])}, found_groups))


def __sibling_group_match_filter(group_key: str) -> Dict[str, Any]:
    """
    Marketplace batches group by parent_request_uid; POS/mostrador folio pieces
  group by specific_order_uid (parent_request_uid is often empty).
    """
    return {
        "$or": [
            {"parent_request_uid": group_key},
            {"specific_order_uid": group_key},
        ]
    }


def find_sibling_requests_with_offers(
    request: Request,
    parent_request_uid: str,
    offer_owner_group: str,
    status: Optional[str],
    filters_dict: List[Dict[str, Any]]
):
    user_info = request.state._state.get('user')
    logged_in_user = user_info.get("uid")

    from app.config import database

    # Build aggregation pipeline to handle createdAt as both Date and String
    # Step 1: Match sibling batch (marketplace parent_request_uid or POS specific_order_uid)
    match_stage: Dict[str, Any] = __sibling_group_match_filter(parent_request_uid)
    if status != None:
        match_stage["status"] = status

    # Step 2: Convert createdAt to Date for consistent comparison
    pipeline_first = [
        {"$match": match_stage},
        {
            "$addFields": {
                "createdAtDate": {
                    "$cond": {
                        "if": {"$eq": [{"$type": "$createdAt"}, "string"]},
                        "then": {"$dateFromString": {"dateString": "$createdAt"}},
                        "else": "$createdAt"
                    }
                }
            }
        },
        {"$sort": {"createdAtDate": -1}},
        {"$limit": 1}
    ]

    # Get the newest request to calculate time window
    newest_requests = list(database.db["PartRequests"].aggregate(pipeline_first))
    
    if len(newest_requests) == 0:
        return []

    newest_part_request = PartRequest(**newest_requests[0])
    
    # Parse the createdAtDate from aggregation result
    created_at = newest_requests[0].get("createdAtDate")
    if isinstance(created_at, str):
        created_at = date_parser.parse(created_at)
    
    # Normalize to absolute days (start and end of day)
    newest_date_start = created_at.replace(hour=0, minute=0, second=0, microsecond=0)
    newest_date_end = newest_date_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    three_days_before = newest_date_start - timedelta(days=3)

    # Build aggregation pipeline for time window query
    pipeline_time_window = [
        {"$match": match_stage},
        {
            "$addFields": {
                "createdAtDate": {
                    "$cond": {
                        "if": {"$eq": [{"$type": "$createdAt"}, "string"]},
                        "then": {"$dateFromString": {"dateString": "$createdAt"}},
                        "else": "$createdAt"
                    }
                }
            }
        },
        {
            "$match": {
                "createdAtDate": {
                    "$gte": three_days_before,
                    "$lte": newest_date_end
                }
            }
        },
        {"$sort": {"createdAtDate": -1}}
    ]

    sibling_part_requests = list[Any](database.db["PartRequests"].aggregate(pipeline_time_window))

    return __attach_offers_to_part_requests(
        sibling_part_requests,
        newest_part_request.creatorGroup,
        logged_in_user,
        filters_dict,
        status,
        offer_owner_group,
    )


def find_vehicle_requests_with_offers(
    request: Request,
    vehicle_id: str,
    creator_group_id: str,
    offer_owner_group: Optional[str],
    status: Optional[str],
    filters_dict: List[Dict[str, Any]],
    limit: int = 50,
):
    user_info = request.state._state.get('user')
    logged_in_user = user_info.get("uid")

    from app.config import database

    match_stage = {"vehicleId": vehicle_id, "creatorGroup": creator_group_id}
    if status is not None:
        match_stage["status"] = status

    vehicle_part_requests = list(
        database.db["PartRequests"]
        .find(match_stage)
        .sort("createdAt", pymongo.DESCENDING)
        .limit(limit)
    )

    return __attach_offers_to_part_requests(
        vehicle_part_requests,
        creator_group_id,
        logged_in_user,
        filters_dict,
        status,
        offer_owner_group=offer_owner_group,
    )


def __attach_offers_to_part_requests(
    part_request_data_list: List[Any],
    creator_group_id: str,
    logged_in_user: str,
    filters_dict: List[Dict[str, Any]],
    status: Optional[str] = None,
    offer_owner_group: Optional[str] = None,
) -> List[dict]:
    part_requests_with_offers = []
    follower_group_ids = set(
        listService.get_followers_not_in_my_lists(logged_in_user, creator_group_id)
    )

    for part_request_data in part_request_data_list:
        part_request_dict = PartRequest(**part_request_data).toJson()

        offer_filters = {
            "request_id": part_request_dict.get("_id"),
        }

        if status is not None:
            offer_filters["status"] = status
        elif not offer_owner_group:
            # The buyer can't pick an offer the store withdrew (it canceled the order); sellers still see theirs.
            offer_filters["status"] = {"$ne": OfferStatus.no_inventory.value}

        # A seller asking for their own quoting screen gets only their group's offers, never another seller's.
        if offer_owner_group:
            offer_filters["group_id"] = offer_owner_group

        if filters_dict and len(filters_dict) > 0:
            custom_filters = __build_filters_for_sibling_requests(
                filters_dict,
                creator_group_id,
                logged_in_user,
            )
            offer_filters.update(custom_filters)

        part_request_offers = list[Any](offerRepository.find(offer_filters))

        offers = []
        for offer_data in part_request_offers:
            offer_json = Offer(**offer_data).toJson()
            group_info = groupRepository.find_by_id(offer_json["group_id"])
            group = GroupSchema(**group_info)
            offer_json["group_info"] = group.toJson()

            offer_json["createdByFollower"] = str(offer_json.get("group_id")) in follower_group_ids

            offer_json["creatorIsFavoriteAtSomeList"] = __check_if_group_is_favorite(
                group, creator_group_id, logged_in_user)
            offer_json["creatorIsInSomeList"] = (
                not offer_json["creatorIsFavoriteAtSomeList"]
                and __check_if_group_is_in_non_favorite_list(
                    group, creator_group_id, logged_in_user)
            )
            offers.append(offer_json)

        part_request_dict["offers"] = offers
        part_requests_with_offers.append(part_request_dict)

    return part_requests_with_offers


def __build_filters_for_sibling_requests(
    filters_dict: List[Dict[str, Any]], 
    creator_group_id: str, 
    logged_in_user: str
) -> Dict[str, Any]:

    # Collect all group IDs from all applicable filters
    all_group_ids = []

    for filter_item in filters_dict:
        filter_type = filter_item.get("type")
        filter_values = filter_item.get("values", [])
        
        if filter_type == "followers_custom":
            all_group_ids.extend(filter_values)

        elif filter_type == "connected_custom":
            all_group_ids.extend(filter_values)

        elif filter_type == "favorites":
            if filter_values and filter_values[0] == "true":
                all_group_ids.extend(
                    listService.get_groups_in_user_lists(
                        logged_in_user,
                        creator_group_id,
                        favorites_only=True,
                    )
                )

        elif filter_type == "connected":
            if filter_values and filter_values[0] == "true":
                all_group_ids.extend(
                    listService.get_groups_in_user_lists(
                        logged_in_user,
                        creator_group_id,
                        favorites_only=False,
                    )
                )

        elif filter_type == "followers":
            if filter_values and filter_values[0] == "true":
                all_group_ids.extend(
                    listService.get_followers_not_in_my_lists(
                        logged_in_user,
                        creator_group_id,
                    )
                )
    
    # Remove duplicates in case same group appears in multiple filter types
    unique_group_ids = list(set(str(group_id) for group_id in all_group_ids if group_id))

    scoped_filter_types = {
        "favorites",
        "connected",
        "followers",
        "followers_custom",
        "connected_custom",
    }
    has_scoped_filter = any(
        filter_item.get("type") in scoped_filter_types for filter_item in filters_dict
    )

    # If we have group IDs to filter by, return the MongoDB $in filter
    if len(unique_group_ids) > 0:
        return {
            "group_id": {"$in": unique_group_ids}
        }

    if has_scoped_filter:
        return {
            "group_id": {"$in": []}
        }

    # No applicable filters, return empty dict (no additional filtering)
    return {}


def __check_if_group_is_favorite(
    group: GroupSchema,
    creator_group_id: str,
    logged_in_user: str,
) -> bool:
    favorite_lists = list(listRepository.find({
        "is_favorite": True,
        "groups": group.id,
        "group_id": creator_group_id,
        "user_uid": logged_in_user,
    }))

    return len(favorite_lists) > 0


def __check_if_group_is_in_non_favorite_list(
    group: GroupSchema,
    creator_group_id: str,
    logged_in_user: str,
) -> bool:
    non_favorite_lists = list(listRepository.find({
        "is_favorite": False,
        "groups": group.id,
        "group_id": creator_group_id,
        "user_uid": logged_in_user,
    }))

    return len(non_favorite_lists) > 0


def edit_part_request(part_request_data: List[PartRequestEdit]):
    reserved: List[tuple] = []  # (group, day, request_id) of slots this call reserved
    try:
        edited_ids = []
        now = _now()
        planned: List[dict] = []
        # Phase 1: resolve every doc and decide its reach; nothing is written yet.
        for part_request_edit in part_request_data:
            if not part_request_edit.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each edit item must include id",
                )
            found_part_request = list(
                partRequestRepository.find_by_id(part_request_edit.id))
            if len(found_part_request) > 0:

                current_part_request = PartRequest(**found_part_request[0])
                merged = current_part_request.model_copy(deep=True)

                if part_request_edit.fulfillment_type is not None:
                    merged.fulfillment_type = part_request_edit.fulfillment_type
                if part_request_edit.delivery_address is not None:
                    merged.delivery_address = part_request_edit.delivery_address
                if part_request_edit.delivery_contact is not None:
                    merged.delivery_contact = part_request_edit.delivery_contact

                if merged.fulfillment_type == FulfillmentType.pickup:
                    merged.delivery_address = None
                    merged.delivery_contact = None

                try:
                    validate_delivery_fulfillment(
                        merged.fulfillment_type,
                        merged.delivery_address,
                        merged.delivery_contact,
                    )
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

                subs = list(current_part_request.subscribedSellers or [])
                previous_subs = set(subs)
                if part_request_edit.subscribedSellers is not None:
                    subs = list(set(subs + part_request_edit.subscribedSellers))

                subs = expand_subscribed_sellers_with_accepted_comisionados(
                    subs,
                    merged.creatorGroup,
                )

                new_seller_group_ids = sorted(set(subs) - previous_subs)

                vehicle_maker = _vehicle_maker_from_information(
                    current_part_request.vehicleInformation
                )
                subs, non_compatible_sellers = (
                    __resolve_subscribed_and_non_compatible(
                        subs,
                        vehicle_maker,
                        current_part_request.part,
                    )
                )

                reach_doc = current_part_request.reach
                if merged.origin == "mostrador":
                    decision = None
                else:
                    followers = current_part_request.subscribedFollowers
                    new_audience = sellerReachService.audience(subs, followers)
                    # Stored subs are already post-expansion, so they are a comparable baseline when sellers
                    # change; with no seller change nothing was added by the buyer, so there is no growth.
                    previous_audience = (
                        new_audience if part_request_edit.subscribedSellers is None
                        else sellerReachService.audience(list(previous_subs), followers)
                    )
                    current_tier = (reach_doc or {}).get("tier")
                    if reach_doc is None:
                        limits = sellerReachService.limits_for(merged.creatorGroup)
                        if previous_audience >= limits.wide_threshold:
                            current_tier = "wide"  # legacy doc already wide: never limited
                    decision = sellerReachService.decide(
                        merged.creatorGroup,
                        part_request_edit.id,
                        new_audience,
                        previous_audience,
                        current_tier,
                        now,
                    )
                    if decision["tier"] == "wide" and current_tier != "wide":
                        reserved.append((merged.creatorGroup, decision["day"], part_request_edit.id))

                part_request_json = {
                    "part": {
                        **current_part_request.part,
                        "comments": part_request_edit.comment,
                        "amount": part_request_edit.amount
                    },
                    "subscribedSellers": subs,
                    "nonCompatibleSellers": non_compatible_sellers,
                    "fulfillment_type": merged.fulfillment_type.value,
                    "delivery_address": merged.delivery_address.model_dump()
                    if merged.delivery_address is not None else None,
                    "delivery_contact": merged.delivery_contact.model_dump()
                    if merged.delivery_contact is not None else None,
                    "updatedAt": datetime.now(ZoneInfo('UTC')),
                }
                if decision is not None:
                    part_request_json["reach"] = decision
                if new_seller_group_ids:
                    # The monitor's 30-minute wait before widening again restarts from here.
                    part_request_json["last_widened_at"] = now

                planned.append({
                    "edit": part_request_edit,
                    "json": part_request_json,
                    "merged": merged,
                    "new_seller_group_ids": new_seller_group_ids,
                })

        # Phase 2: every doc passed; write. A doc's slot is kept once its write succeeds.
        for item in planned:
            part_request_edit = item["edit"]
            merged = item["merged"]
            new_seller_group_ids = item["new_seller_group_ids"]
            edited_part_request = partRequestRepository.edit_part_request(
                part_request_edit.id, item["json"])
            edited_ids.append(str(edited_part_request["_id"]))
            written_reach = item["json"].get("reach") or {}
            slot = (merged.creatorGroup, written_reach.get("day"), part_request_edit.id)
            if slot in reserved:
                reserved.remove(slot)

            if new_seller_group_ids:
                from app.services import notification_fanout

                creator_group_doc = groupRepository.find_by_id(merged.creatorGroup)
                creator_name = (creator_group_doc or {}).get("name") or ""
                formatted = __format_part_request(edited_part_request)
                notification_fanout.fanout_part_request_to_new_sellers(
                    part_request=formatted,
                    creator_group_name=creator_name,
                    new_seller_group_ids=new_seller_group_ids,
                )

        return edited_ids
    except Exception as e:
        for group_id, day, request_id in reserved:
            try:
                sellerReachService.release(group_id, day, request_id)
            except Exception as release_error:
                print(f"Seller reach: failed to release slot {request_id} ({day}): {release_error}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=500, detail=f'Error while editing part request {e}')


def join_seller_to_part_request(parent_request_id: str | None, new_seller_group_id: str | None):
    reserved: List[tuple] = []  # (group, day, request_id) of slots this call reserved
    try:
        if parent_request_id is None or new_seller_group_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="The request is missing information")

        part_requests_documents = list(partRequestRepository.find(
            {"specific_order_uid": parent_request_id}, None))

        part_requests: List[PartRequest] = []
        if len(part_requests_documents) > 0:
            for part_request_data in part_requests_documents:
                part_requests.append(PartRequest(**part_request_data))
        else:
            raise HTTPException(status_code=status.HTTP_204_NO_CONTENT,
                                detail="The requested part request is not found")

        for part_request in part_requests:
            if part_request.status != PartRequestStatus.CREATED:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail="The part request status does not allow this operation")

        pending = [p for p in part_requests if new_seller_group_id not in (p.subscribedSellers or [])]
        if not pending:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="The current seller already belongs to the request")

        now = _now()
        planned: List[tuple] = []  # (part_request, decision)
        full_ids: List[str] = []
        # Phase 1: decide every part the seller is not in yet; a refusal only skips that part.
        for part_request in pending:
            subs = list(part_request.subscribedSellers or [])
            followers = part_request.subscribedFollowers
            decision = None
            if part_request.origin != "mostrador":
                previous_audience = sellerReachService.audience(subs, followers)
                current_tier = (part_request.reach or {}).get("tier")
                if part_request.reach is None:
                    limits = sellerReachService.limits_for(part_request.creatorGroup)
                    if previous_audience >= limits.wide_threshold:
                        current_tier = "wide"  # legacy doc already wide: never limited
                try:
                    decision = sellerReachService.decide(
                        part_request.creatorGroup,
                        part_request.id,
                        sellerReachService.audience([*subs, new_seller_group_id], followers),
                        previous_audience,
                        current_tier,
                        now,
                    )
                except sellerReachService.SellerReachError:
                    full_ids.append(part_request.id)
                    sellerReachService.repo.write_event(
                        "join_skipped", part_request.creatorGroup, request_id=part_request.id,
                        day=sellerReachService.local_day(now), seller_group_id=new_seller_group_id)
                    continue
                if decision["tier"] == "wide" and current_tier != "wide":
                    reserved.append((part_request.creatorGroup, decision["day"], part_request.id))
            planned.append((part_request, decision))

        if not planned:
            raise sellerReachService.SellerReachError(
                "request_full",
                "Esta solicitud ya está llena.",
                {"full_ids": full_ids, "renews_at": sellerReachService.renews_at(now).isoformat()},
            )

        # Phase 2: write. A slot leaves `reserved` only once its doc is written.
        edited_part_request_ids: List[str] = []
        for part_request, decision in planned:
            part_request.subscribedSellers = [*(part_request.subscribedSellers or []), new_seller_group_id]
            # Only what joining changes. Writing toJson() back stored createdAt/updatedAt as ISO text.
            edit_payload = {"subscribedSellers": part_request.subscribedSellers, "updatedAt": now}
            if decision is not None:
                edit_payload["reach"] = decision
            edited_part_request = partRequestRepository.edit_part_request(
                part_request.id, edit_payload)
            edited_part_request_ids.append(str(edited_part_request["_id"]))
            slot = (part_request.creatorGroup, (decision or {}).get("day"), part_request.id)
            if slot in reserved:
                reserved.remove(slot)

        return {"joined_ids": edited_part_request_ids, "full_ids": full_ids}
    except HTTPException as e:
        for group_id, day, request_id in reserved:
            try:
                sellerReachService.release(group_id, day, request_id)
            except Exception as release_error:
                print(f"Seller reach: failed to release slot {request_id} ({day}): {release_error}")
        if isinstance(e, sellerReachService.SellerReachError):
            raise
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception:
        for group_id, day, request_id in reserved:
            try:
                sellerReachService.release(group_id, day, request_id)
            except Exception as release_error:
                print(f"Seller reach: failed to release slot {request_id} ({day}): {release_error}")
        raise


def __build_and_send_commissioner_notifications(
    users_from_groups: List[str],
    part_request_data: Dict[str, Any],
    creator_group_id: str,
    creator_name: str,
    user_token: str
):
    """
    Build and send notifications to commissioner group users

    Args:
        users_from_groups: List of user IDs from nearby commissioner groups
        part_request_data: The part request data
        creator_group_id: The ID of the group that created the request
        creator_name: The name of the creator group
        user_token: Firebase user ID token for authentication
    """
    if not users_from_groups:
        print("ℹ️ No commissioner users found for notifications")
        return

    notification_errors = []

    for user in users_from_groups:
        try:
            for user_uid in user["users"]:
                build_and_send_notification(
                    user_id=user_uid,
                    group_id=user.get("_id"),
                    created_part_request_id=part_request_data["_id"],
                    part_name=part_request_data["part"]["tipoParteDescripcion"],
                    store_name=creator_name,
                    user_token=user_token
                )
        except Exception as error:
            notification_errors.append(f"group {user}: {error}")

    if notification_errors:
        print(f"⚠️ Some commissioner notifications failed:")
        for error in notification_errors:
            print(f"   - {error}")
    else:
        print(
            f"✅ All commissioner notifications sent successfully ({len(users_from_groups)} users)")


TURN_DAYS_WINDOW = 60
DEFAULT_SELLER_TZ = "America/Mexico_City"


def _seller_zone(tz: Optional[str]) -> str:
    """`tz` when it names a known IANA zone, else the default."""
    if not tz:
        return DEFAULT_SELLER_TZ
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_SELLER_TZ
    return tz


def answered_request_ids(seller_group_id: str, request_ids) -> set:
    """Parts this seller answered: an offer in any status, or a discard in the cotizador."""
    ids = [str(rid) for rid in request_ids]  # Offers store request_id as text; part _ids arrive as ObjectIds
    offered = offerRepository.distinct_request_ids_for_group(seller_group_id, ids)
    discarded = requestStatusByGroupRepository.distinct_request_ids_for_group(seller_group_id, ids)
    return {str(rid) for rid in [*offered, *discarded]}


def find_open_turn_days(seller_group_id: str, tz: Optional[str], now: datetime) -> List[dict]:
    """Days (seller's local calendar, last 60 incl. today) with open turns, newest first.

    `to_quote` counts the day's batches with at least one part of that day still unanswered.
    """
    zone = _seller_zone(tz)
    local_today = now.astimezone(ZoneInfo(zone)).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (local_today - timedelta(days=TURN_DAYS_WINDOW - 1)).astimezone(ZoneInfo("UTC"))

    rows = partRequestRepository.open_turn_days(seller_group_id, since, zone)
    answered = answered_request_ids(seller_group_id, [pid for row in rows for pid in row["part_ids"]])

    days: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        day = days.setdefault(row["day"], {"day": row["day"], "turns": 0, "to_quote": 0})
        day["turns"] += 1
        if any(str(pid) not in answered for pid in row["part_ids"]):
            day["to_quote"] += 1
    return sorted(days.values(), key=lambda d: d["day"], reverse=True)


def find_grouped_by_parent_request_uid(
    creator_group_id: Optional[str],
    seller_group_id: Optional[str],
    status: Optional[str],
    specific_order_uid: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
):
    """Turns for the cotizador: each batch with its buyer, car, arrival and how many parts this seller answered."""
    from app.utils.datetime_utils import serialize_datetime

    try:
        status_enum = PartRequestStatus(status) if status else None

        results = list(partRequestRepository.find_grouped_by_parent_request_uid(
            creator_group_id,
            seller_group_id,
            status_enum,
            specific_order_uid,
            created_from=created_from,
            created_to=created_to,
        ))

        quoted_ids: set = set()
        if seller_group_id:
            all_ids = [pr["_id"] for group in results for pr in group.get("part_requests") or []]
            quoted_ids = answered_request_ids(seller_group_id, all_ids)

        buyer_names: Dict[str, str] = {}
        for group_result in results:
            part_requests = group_result.get("part_requests") or []
            base_request = part_requests[0]
            buyer_id = str(base_request.get("creatorGroup") or "")
            if buyer_id not in buyer_names:
                buyer_names[buyer_id] = ((groupRepository.find_by_id(buyer_id) if buyer_id else None) or {}).get("name") or ""

            vehicle = base_request.get("vehicleInformation") or {}
            car = " ".join(str(vehicle.get(key)) for key in ("maker", "model", "year") if vehicle.get(key))

            group_result["creator_group_id"] = buyer_id
            group_result["creator_group"] = buyer_names[buyer_id]
            group_result["car_data"] = car
            group_result["created_at"] = serialize_datetime(group_result.pop("first_created", None) or base_request.get("createdAt"))
            group_result["part_count"] = len(part_requests)
            group_result["quoted_count"] = sum(1 for pr in part_requests if str(pr.get("_id")) in quoted_ids)
            group_result["part_requests"] = [PartRequest(**pr).toJson() for pr in part_requests]

        return results
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while finding part requests grouped by parent_request_uid: {e}')


REMINDER_AFTER = timedelta(hours=1)


def _created_at_utc(value) -> Optional[datetime]:
    """A part request's createdAt (datetime or ISO string; naive means UTC)."""
    if value is None:
        return None
    try:
        created = value if isinstance(value, datetime) else date_parser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    return created if created.tzinfo else created.replace(tzinfo=ZoneInfo("UTC"))


def send_seller_reminder(part_request_id: str, pending_group_ids: List[str], store_name: str) -> int:
    from app.services import notification_fanout

    part_request_data = partRequestRepository.find_one_by_id(part_request_id)
    if not part_request_data:
        raise HTTPException(status_code=404, detail="Part request not found")

    # Stores get an hour to answer before the buyer can nudge them, after creating the request and after each
    # reminder (the monitor shows the wait).
    now = datetime.now(ZoneInfo("UTC"))
    created = _created_at_utc(part_request_data.get("createdAt"))
    if created and now - created < REMINDER_AFTER:
        raise HTTPException(status_code=409, detail="Podrás enviar un recordatorio una hora después de crear la solicitud.")
    last_reminder = _created_at_utc(part_request_data.get("last_reminder_at"))
    if last_reminder and now - last_reminder < REMINDER_AFTER:
        raise HTTPException(status_code=409, detail="Podrás enviar otro recordatorio una hora después del anterior.")

    formatted = __format_part_request(part_request_data)
    sent = notification_fanout.fanout_part_request_reminder(
        part_request=formatted,
        pending_group_ids=pending_group_ids,
        store_name=store_name,
    )
    partRequestRepository.edit_part_request(part_request_id, {"last_reminder_at": now})
    return sent


def close_part_request(part_request_id: str, uid: str) -> Dict[str, Any]:
    """The buyer closes a request. A reopened one (a store canceled) had a pending 'choose' decision: settle it."""
    from app.services import NotificationService, PickupCodeService

    doc = partRequestRepository.find_one_by_id(part_request_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Part request not found")
    if not PickupCodeService._user_in_group(uid, doc.get("creatorGroup")):
        raise HTTPException(status_code=403, detail="Solo quien creó la solicitud puede cerrarla.")
    partRequestRepository.edit_part_request(
        part_request_id,
        {"isActive": False, "last_cancellation": None, "updatedAt": datetime.now(ZoneInfo("UTC"))},
    )
    try:
        NotificationService.resolve_decisions(f"request:{part_request_id}:choose")
        NotificationService.resolve_decisions_prefix(f"request:{part_request_id}:quote:")
        from app.repositories import OrderRepository
        OrderRepository.clear_request_cancellation(part_request_id, closed=True)
    except Exception:
        pass
    return {"_id": part_request_id, "isActive": False}
