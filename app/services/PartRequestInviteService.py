from app.schemas.RequestInvites import RequestInvite, RequestInviteStatus
from fastapi import HTTPException, status
from app.repositories import PartRequestRepository, PartRequestInviteRepository
from app.repositories import GroupRepository, OfferRepository
from app.schemas.PartRequest import PartRequest, PartRequestStatus
from app.services import PartRequestService as partRequestService
from app.schemas.Groups import GroupSchema
from pymongo.errors import PyMongoError
from bson import ObjectId
from typing import List, Dict, Any


def insert(partRequestInvite: RequestInvite) -> RequestInvite:
    try:
        part_request_data = list(PartRequestRepository.find({
            "specific_order_uid": partRequestInvite.parent_request_id
        }, {}))

        if len(part_request_data) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="part request with that id is not found")

        for part_request in part_request_data:
            part_request_item = PartRequest(**part_request)

            if part_request_item.status.value != PartRequestStatus.CREATED.value:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="cannot create invites for part requests that have a status different that created")

        filters = {
            "parent_request_id": partRequestInvite.parent_request_id,
            "inviter_group": partRequestInvite.inviter_group,
            "inviter_user": partRequestInvite.inviter_user
        }

        if partRequestInvite.invited_group != None:
            filters["invited_group"] = partRequestInvite.invited_group

        if partRequestInvite.census_id != None:
            filters["census_id"] = partRequestInvite.census_id

        existing_invite = list(PartRequestInviteRepository.find(filters))

        if len(existing_invite) > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Cannot create an invite since one already exists")

        part_request_invite_payload = partRequestInvite.toJson()

        part_request_invite_payload.pop('_id')

        inserted_id = PartRequestInviteRepository.insert(
            part_request_invite_payload).inserted_id

        part_request_invite_data = PartRequestInviteRepository.find_by_id(
            inserted_id)

        invite = RequestInvite(**part_request_invite_data)

        if partRequestInvite.invited_group:
            from app.services import notification_fanout

            inviter_group_doc = GroupRepository.find_by_id(partRequestInvite.inviter_group)
            inviter_group_name = (inviter_group_doc or {}).get("name") or ""
            linked = list(PartRequestRepository.find({
                "specific_order_uid": partRequestInvite.parent_request_id
            }, {}))
            linked_fmt = [PartRequest(**raw).toJson() for raw in linked]
            if linked_fmt:
                for group_found in notification_fanout._users_by_group_ids(
                    [str(partRequestInvite.invited_group)],
                ):
                    for user_id in group_found.get("users") or []:
                        notification_fanout.fanout_part_request_invite(
                            invite_id=str(inserted_id),
                            inviter_group_name=inviter_group_name,
                            inviter_user=str(partRequestInvite.inviter_user or ""),
                            owner=str(user_id),
                            owner_group=str(partRequestInvite.invited_group),
                            part_requests=linked_fmt,
                        )

        return invite
    except (HTTPException, PyMongoError) as e:
        raise HTTPException(e)


def update_status(inviter_group: str, invited_group: str, parent_request_id: str, status: str):
    try:

        part_requests_modified: List[Dict[str, Any]] = []

        part_request_invites_data = list(PartRequestInviteRepository.find({
            "inviter_group": inviter_group,
            "invited_group": invited_group,
            "parent_request_id": parent_request_id
        }))

        for part_request_invite_item in part_request_invites_data:
            part_request_invite: RequestInvite = RequestInvite(
                **part_request_invite_item)
            part_request_invite.change_status(status)

            part_request_json = part_request_invite.toJson()

            part_request_id = ObjectId(part_request_json["_id"])

            part_request_json.pop('_id')

            modified_part_request_invite = PartRequestInviteRepository.find_one_and_update(
                part_request_id, part_request_json)

            modified_invite = RequestInvite(**modified_part_request_invite)

            part_requests_modified.append(modified_invite.toJson())

        return part_requests_modified
    except (HTTPException) as e:
        raise HTTPException(e)


def find_by_id(part_request_invite_id: str) -> RequestInvite:
    try:
        part_request_invite_id = ObjectId(part_request_invite_id)
        part_request_invite_data = PartRequestInviteRepository.find_by_id(
            part_request_invite_id)

        if part_request_invite_data != None:
            part_request_invite = RequestInvite(**part_request_invite_data)
            return part_request_invite

        return None
    except (HTTPException) as e:
        raise HTTPException(e)


def find_and_link_census_invites_with_created_group(
    census_id: str,
    new_group_id: str
) -> List[Dict[str, Any]]:
    try:

        filters = {
            "status": RequestInviteStatus.CREATED.value
        }

        if census_id != None:
            filters["census_id"] = census_id

        invites_found = list(PartRequestInviteRepository.find(filters))

        part_requests_invites_modified: List[Dict[Any, str]] = []
        for invite_item in invites_found:
            part_request_invite = RequestInvite(**invite_item)

            group_info = GroupRepository.find_by_id(
                part_request_invite.inviter_group)

            group = GroupSchema(**group_info)

            part_request_invite.inviter_group_name = group.name

            part_request_invite.invited_group = new_group_id

            part_requests_linked_to_invite = partRequestService.find(
                None, None, part_request_invite.parent_request_id)
            
            part_requests_linked_to_invite = format_part_requests(part_requests_linked_to_invite)

            payload = part_request_invite.toJson()

            payload.pop("_id")

            part_request_invite_modified = PartRequestInviteRepository.find_one_and_update(
                ObjectId(part_request_invite.id), payload)

            part_request_invite_modified["linked_part_requests"] = part_requests_linked_to_invite

            part_requests_invites_modified.append(RequestInvite(
                **part_request_invite_modified).toJson())

        from app.services import notification_fanout

        for invite_json in part_requests_invites_modified:
            invite_id = str(invite_json.get("_id") or invite_json.get("id") or "")
            inviter_group_name = invite_json.get("inviter_group_name") or ""
            inviter_user = invite_json.get("inviter_user") or ""
            invited_group = invite_json.get("invited_group") or ""
            linked_part_requests = invite_json.get("linked_part_requests") or []
            if not (linked_part_requests and invited_group):
                continue
            for group_found in notification_fanout._users_by_group_ids([invited_group]):
                for user_id in group_found.get("users") or []:
                    notification_fanout.fanout_part_request_invite(
                        invite_id=invite_id,
                        inviter_group_name=inviter_group_name,
                        inviter_user=inviter_user,
                        owner=str(user_id),
                        owner_group=invited_group,
                        part_requests=linked_part_requests,
                    )

        return part_requests_invites_modified

    except (PyMongoError, Exception) as e:
        raise Exception(e)


def format_part_requests(part_requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_part_requests = []
    for part_request_dict in part_requests:
        part_request = PartRequest(**part_request_dict)
        formatted_part_requests.append(part_request.toJson())

    return formatted_part_requests

def find_pending_for_group(group_id: str) -> List[Dict[str, Any]]:
    """Open invites for `group_id` the seller has not yet joined, newest first."""
    if not group_id:
        return []
    invites = list(PartRequestInviteRepository.find({
        "invited_group": group_id,
        "status": RequestInviteStatus.CREATED.value
    }))
    invites.sort(key=lambda invite: str(invite.get("created_at") or ""), reverse=True)

    # Batched: one query per collection however many invites there are.
    parent_ids = list({invite.get("parent_request_id") for invite in invites if invite.get("parent_request_id")})
    part_requests_by_parent: Dict[Any, List[Dict[str, Any]]] = {}
    if parent_ids:
        for part_request in PartRequestRepository.find({"specific_order_uid": {"$in": parent_ids}}, {}):
            part_requests_by_parent.setdefault(part_request.get("specific_order_uid"), []).append(part_request)

    all_request_ids = [str(pr["_id"]) for prs in part_requests_by_parent.values() for pr in prs]
    offers_by_request: Dict[str, List[Dict[str, Any]]] = {}
    if all_request_ids:
        for offer in OfferRepository.find({"request_id": {"$in": all_request_ids}}):
            offers_by_request.setdefault(str(offer.get("request_id")), []).append(offer)

    inviter_names = _inviter_names([invite for invite in invites if not invite.get("inviter_group_name")])

    pending: List[Dict[str, Any]] = []
    for invite in invites:
        part_requests = part_requests_by_parent.get(invite.get("parent_request_id"), [])
        offers = [offer for pr in part_requests for offer in offers_by_request.get(str(pr["_id"]), [])]

        view = _pending_invite_view(invite, part_requests, offers, group_id, inviter_names)
        if view is not None:
            pending.append(view)

    return pending


def _inviter_names(invites: List[Dict[str, Any]]) -> Dict[str, str]:
    """Names of the inviter groups of `invites` (those lacking a stored name), in a single query."""
    oids = []
    for invite in invites:
        try:
            oids.append(ObjectId(str(invite.get("inviter_group"))))
        except Exception:
            continue
    if not oids:
        return {}
    groups = GroupRepository.find({"_id": {"$in": list(set(oids))}}, {"name": 1})
    return {str(group["_id"]): group.get("name") for group in groups}


def _pending_invite_view(invite: Dict[str, Any], part_requests: List[Dict[str, Any]],
                         offers: List[Dict[str, Any]], group_id: str = None,
                         inviter_names: Dict[str, str] = None) -> Dict[str, Any] | None:
    if not part_requests:
        return None

    for part_request in part_requests:
        if (part_request.get("status") != PartRequestStatus.CREATED.value
                or part_request.get("isActive") is False
                or (group_id is not None and group_id in (part_request.get("subscribedSellers") or []))):
            return None

    first = part_requests[0]
    vehicle = first.get("vehicleInformation") or {}

    inviter_group_name = invite.get("inviter_group_name")
    if not inviter_group_name:
        inviter_group_name = (inviter_names or {}).get(str(invite.get("inviter_group")))

    parts = []
    for part_request in part_requests:
        part = part_request.get("part") or {}
        parts.append({
            "part_request_id": str(part_request["_id"]),
            "name": part.get("tipoParteDescripcion"),
            "amount": part.get("amount"),
            "unit": part.get("unitOfMeasure"),
            "position": part.get("position"),
        })

    created_at = invite.get("created_at")
    return {
        "id": str(invite["_id"]),
        "parent_request_id": invite.get("parent_request_id"),
        "inviter_group": invite.get("inviter_group"),
        "inviter_group_name": inviter_group_name,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "fulfillment_type": first.get("fulfillment_type"),
        "vehicle": {
            "maker": vehicle.get("maker"),
            "model": vehicle.get("model"),
            "year": vehicle.get("year"),
            "sub_model": vehicle.get("subModel"),
            "engine": vehicle.get("engine"),
        },
        "parts": parts,
        "invited_shops": len(first.get("subscribedSellers") or []),
        "quoted_shops": len({str(offer.get("group_id")) for offer in offers if offer.get("group_id")}),
    }
