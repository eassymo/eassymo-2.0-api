from app.repositories import OfferRepository as offerRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.services import BrandService as brandService
from app.services import GuaranteeService as guaranteeService
from app.services import ListsService as listService
from app.schemas.Offer import Offer
from app.schemas.Brand import Brand
from app.schemas.Guarantee import Guarantee
from app.schemas.PartRequest import PartRequest, PartRequestStatus
from app.schemas.Groups import GroupSchema
from app.schemas.Notification import Notification
from fastapi import HTTPException, Request, status
from uuid import uuid4
from app.schemas.Offer import OfferStatus, OfferType
from app.repositories import OrderRepository as orderRepository
from app.repositories import CallCenterConnectionRepository as callCenterConnectionRepository
from app.schemas.Order import Order, OrderStatus
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Optional, Dict
from app.factories.NotificationsCreator import (
    create_offer_workshop_approval, create_offer_notification)
from app.utils.notification_routes import (
    buyer_offer_notification_meta,
    buyer_offer_review_path,
)
from app.utils.notifications import send_notification

from app.repositories import ListsRepository as listsRepository
from app.repositories import RequestStatusByGroupRepository as requestStatusByGroupRepository


def _group_acts_as_callcenter(group: GroupSchema) -> bool:
    """Call-center offer queries match on call_center_that_posted_offer, not group_id."""
    if group.is_callcenter:
        return True
    return len(callCenterConnectionRepository.find({"callcenter_id": group.id})) > 0


def insert(payload: Offer, user_token: str):
    try:
        if payload.offer_group_uid == None:
            offer_group_uid = str(uuid4())
            payload.offer_group_uid = offer_group_uid

        if payload.status is not None:
            if isinstance(payload.status, str):
                payload.status = OfferStatus[payload.status.lower()]
            elif isinstance(payload.status, OfferStatus):
                pass
            else:
                raise ValueError(
                    f"Invalid status type: {type(payload.status)}")

        if payload.type is not None:
            if isinstance(payload.type, str):
                payload.type = OfferType[payload.type]
            elif isinstance(payload.type, OfferType):
                pass
            else:
                raise ValueError(f"Invalid offer type: {type(payload.status)}")

        brand_payload = Brand(label=payload.brand, user_uid=payload.user_uid)
        brandService.insert(brand_payload)

        guarantee_payload = Guarantee(
            label=payload.guarantee, user_uid=payload.user_uid)
        guaranteeService.insert(guarantee_payload)

        group_info = groupRepository.find_by_id(payload.group_id)

        group: GroupSchema

        if (group_info != None):
            group = GroupSchema(**group_info)
            payload.group_info = group

        payload.createdAt = datetime.now(ZoneInfo('UTC'))

        part_request_data = partRequestRepository.find_one_by_id(
            payload.request_id)

        part_request: PartRequest | None = None

        if part_request_data != None:
            part_request = PartRequest(**part_request_data)

            if part_request.commissioner_group != None:
                payload.status = OfferStatus.workshop_approval_pending

                __send_workshop_notification_for_approval(
                    part_request.creatorGroup, part_request, payload, user_token)

        offer_payload = payload.toJson()

        offer_payload.pop('_id')

        inserted_id = offerRepository.insert(offer_payload).inserted_id

        if part_request is not None:
            from app.services import notification_fanout

            notification_fanout.fanout_offer_after_insert(
                offer_payload=offer_payload,
                part_request=part_request.toJson(),
                offer_id=str(inserted_id),
            )

        return str(inserted_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while creating offer Error: {e}')


def __send_workshop_notification_for_approval(request_creator_id: str,
                                              part_request_data: PartRequest,
                                              offer_data: Offer,
                                              user_token: str
                                              ):

    request_creator_user_list = groupRepository.find_users_by_group_id(
        request_creator_id)

    if request_creator_user_list == None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Cannot find users to notify')

    for user_id in request_creator_user_list.get("users"):
        build_and_send_notification(
            user_id=user_id,
            group_id=request_creator_id,
            part_name=part_request_data.part.get("tipoParteDescripcion"),
            offer_id=offer_data.id,
            part_request_id=part_request_data.id,
            store_name=offer_data.group_info.name,
            user_token=user_token,
            status=OfferStatus.workshop_approval_pending,
            parent_request_uid=part_request_data.parent_request_uid,
        )


def find(filters: Offer):
    try:
        found_offers = offerRepository.find(__format_filters(filters))
        return __format_offers_response(found_offers)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching offer Error: {e}')


def find_by_request_id_and_group(request: Request, part_request_id: str, group_id: str):
    try:

        group_ids = []

        user_info = request.state._state.get('user')

        logged_in_user = user_info.get("uid")

        part_request_data = list(
            partRequestRepository.find_by_id(part_request_id))

        if len(part_request_data) > 0:
            part_request = PartRequest(**part_request_data[0])
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Part Request not found")

        followers = []

        group: GroupSchema

        if group_id != None:
            group_info = groupRepository.find_by_id(group_id)

            followers = listService.get_followers_list(
                logged_in_user, group_id)

            if group_info == None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Group info is not found")

            group = GroupSchema(**group_info)

            group_ids.append(group.id)

        if group_id == part_request.creatorGroup:
            group_ids = []

        acts_as_callcenter = _group_acts_as_callcenter(group)

        found_offers_dicts = list(offerRepository.find_by_request_id_and_group(
            part_request_id, group_ids, acts_as_callcenter))

        if len(found_offers_dicts) == 0:
            return []

        found_offers: List[Dict[str, any]] = [
            Offer(**offer_data).toJson() for offer_data in found_offers_dicts]

        follower_group_ids = {
            str(follower.get('_id')) for follower in followers if follower.get('_id')
        }
        creator_group_id = part_request.creatorGroup

        for offer in found_offers:
            offer_group_id = offer.get('group_id')
            offer['createdByFollower'] = str(offer_group_id) in follower_group_ids

            offer_group_info = groupRepository.find_by_id(offer_group_id)
            if offer_group_info is None:
                offer['creatorIsFavoriteAtSomeList'] = False
                offer['creatorIsInSomeList'] = False
                continue

            offer_group = GroupSchema(**offer_group_info)
            is_favorite = __check_if_group_is_favorite(
                offer_group, creator_group_id, logged_in_user)
            offer['creatorIsFavoriteAtSomeList'] = is_favorite
            offer['creatorIsInSomeList'] = (
                not is_favorite
                and __check_if_group_is_in_non_favorite_list(
                    offer_group, creator_group_id, logged_in_user)
            )

        return found_offers

    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f'Error while getting specific offer {e}')


def __check_if_group_is_favorite(
    group: GroupSchema,
    creator_group_id: str,
    logged_in_user: str,
) -> bool:
    favorite_lists = list(listsRepository.find({
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
    non_favorite_lists = list(listsRepository.find({
        "is_favorite": False,
        "groups": group.id,
        "group_id": creator_group_id,
        "user_uid": logged_in_user,
    }))

    return len(non_favorite_lists) > 0


def __format_filters(payload: Offer):
    offer_filters = {}
    if payload.request_id != None:
        offer_filters["request_id"] = payload.request_id

    return offer_filters


def __format_offers_response(offers):
    formatted_offers = []
    for offer in offers:
        formatted_offers.append({
            **offer,
            "_id": str(offer["_id"])
        })
    return formatted_offers


def build_filters(propName):
    filters = []

    if (propName == "group"):
        group_ids = list(groupRepository.distinct_by_id())
        filters = group_ids

    if (propName == "car"):
        car_list = list(partRequestRepository.distinct_by_vehicle())
        filters = car_list

    return filters


def find_specific(car_models: str, group_ids: str):
    filters = {}
    part_request_ids = []
    if car_models != None:
        car_model_list = car_models.split(",")
        part_requests_found = list(partRequestRepository.find(
            {
                "vehicleInformation.model": {"$in": car_model_list},
            },
            {
                "_id": {"$toString": "$_id"}
            }
        ))
        for part_request_id in part_requests_found:
            part_request_ids.append(part_request_id["_id"])
        filters = {
            **filters,
            "request_id": {"$in": part_request_ids}
        }

    if group_ids != None:
        filters = {
            **filters,
            "group_id": {"$in": part_request_ids}
        }

    offer_list = list(offerRepository.find(filters))
    offer_list = __format_offer_list(offer_list)
    return offer_list


def __format_offer_list(offer_list):
    formatted_offers = []
    for offer in offer_list:
        offer = {
            **offer,
            "_id": str(offer["_id"]),
            "to_be_delivered_time": str(offer["to_be_delivered_time"])
        }
        formatted_offers.append(offer)

    return formatted_offers


def find_request_offers_by_groups(request_id: str):
    part_request_data = partRequestRepository.find_one_by_id(request_id)
    part_request = PartRequest(**part_request_data)
    subscribed_sellers = part_request.subscribedSellers

    seller_dict = list(map(lambda seller_id: {
        "seller_id": seller_id,
        "has_offered": False,
        "no_stock": False,
        "rejected": False,
    }, subscribed_sellers))

    for seller in seller_dict:
        offers = list(offerRepository.find_by_request_id_and_group(
            request_id, [seller["seller_id"]]))

        if len(offers) > 0:
            seller["has_offered"] = True

        request_status = requestStatusByGroupRepository.find_by_group_and_request_id(
            seller["seller_id"], request_id)

        if request_status is not None:
            if request_status.status == OfferStatus.no_inventory:
                seller["no_stock"] = True
            elif request_status.status == OfferStatus.rejected:
                seller["rejected"] = True

    have_offered = []
    have_not_offered = []
    no_stock = []
    rejected = []

    for seller in seller_dict:
        group_data = groupRepository.find_by_id(seller["seller_id"])
        if group_data is None:
            continue

        group_json = GroupSchema(**group_data).toJson()

        if seller["has_offered"]:
            have_offered.append(group_json)
        elif not seller["no_stock"] and not seller["rejected"]:
            have_not_offered.append(group_json)

        if seller["no_stock"]:
            no_stock.append(group_json)
        if seller["rejected"]:
            rejected.append(group_json)

    return {
        "have_offered": have_offered,
        "have_not_offered": have_not_offered,
        "no_stock": no_stock,
        "rejected": rejected,
    }


def edit_offer(offer_uid: str, payload: Offer):
    try:

        offer_json = payload.toJson()
        offer_json.pop("_id")
        edited_offer = offerRepository.edit_offer(offer_uid, offer_json)

        brand_payload = Brand(label=payload.brand, user_uid=payload.user_uid)
        brandService.insert(brand_payload)

        guarantee_payload = Guarantee(
            label=payload.guarantee, user_uid=payload.user_uid)
        guaranteeService.insert(guarantee_payload)

        edited_offer["_id"] = str(edited_offer["_id"])
        return edited_offer
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while editing offer {e}')


def find_offer_by_id(offer_uid: str):
    try:
        offer = offerRepository.find_offer_by_id(offer_uid)
        if offer is not None:
            offer = Offer(**offer)
        offer_json = offer.toJson()
        return offer_json
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching offer {e}')


def _find_existing_order_for_selection(request_id: str) -> dict | None:
    for query in (
        {"part_request._id": request_id},
        {"part_request.id": request_id},
    ):
        existing = orderRepository.find_one(query)
        if existing is not None:
            return existing
    return None


def _selected_offer_response(offer: Offer, order_doc: dict) -> dict:
    offer_json = offer.toJson()
    offer_json.pop("_id", None)
    offer_json["order_id"] = str(order_doc["_id"])
    return offer_json


def change_offer_status(request_id: str, offer_id: str, status: str, user_token: str):
    try:
        part_request: PartRequest = _get_part_request_data(request_id)
        offer: Offer = _get_offer_data(offer_id)
        previous_status = offer.status
        offer_status = OfferStatus[status.lower()]
        order_id: str = ""
        match offer_status:
            case offer_status.created:
                offer.update_status(OfferStatus.created)
            case offer_status.pending_approval:
                if offer.status == OfferStatus.workshop_approval_pending:
                    __create_workshop_approved_for_commissioner_notification(
                        part_request.commissioner_group,
                        part_request,
                        offer,
                        user_token
                    )
                offer.update_status(OfferStatus.pending_approval)
            case offer_status.selected:
                existing_order = _find_existing_order_for_selection(request_id)
                if existing_order is not None:
                    existing_offer_id = existing_order.get("offer", {}).get("_id")
                    if existing_offer_id == offer_id:
                        return _selected_offer_response(offer, existing_order)
                    raise HTTPException(
                        status_code=409,
                        detail="Part request already has a selected offer",
                    )

                if offer.status == OfferStatus.selected:
                    raise HTTPException(
                        status_code=409,
                        detail="Offer already selected",
                    )

                if part_request.status == PartRequestStatus.OFFER_SELECTED:
                    raise HTTPException(
                        status_code=409,
                        detail="Part request already has a selected offer",
                    )

                part_request.update_status(PartRequestStatus.OFFER_SELECTED)
                offer.update_status(OfferStatus.selected)

                order_created_at = datetime.now(ZoneInfo('UTC'))
                order_to_be_delivered_time = None
                if offer.to_be_delivered_time:
                    offer_time = offer.to_be_delivered_time
                    order_to_be_delivered_time = order_created_at.replace(
                        hour=offer_time.hour,
                        minute=offer_time.minute,
                        second=offer_time.second,
                        microsecond=0
                    )

                order = Order(offer=offer, part_request=part_request, status=OrderStatus.WAITING_FOR_CONFIRMATION,
                              creator_user=part_request.creatorUser, group=part_request.creatorGroup, created_at=order_created_at, to_be_delivered_time=order_to_be_delivered_time)
                order_json = order.toJson()
                order_json.pop("_id")
                inserted_order = orderRepository.insert(order_json)
                order_id = str(inserted_order.inserted_id)
                part_request_json = part_request.toJson()
                part_request_json.pop('_id')
                partRequestRepository.edit_part_request(
                    request_id, part_request_json)

        offer_json = offer.toJson()
        offer_json.pop('_id')
        offerRepository.edit_offer(offer_id, offer_json)

        if len(order_id) > 0:
            offer_json["order_id"] = order_id

        from app.services import notification_fanout

        part_request_json = part_request.toJson()
        offer_json_for_notify = offer.toJson()

        if offer_status == OfferStatus.selected and order_id:
            creator_group_doc = groupRepository.find_by_id(str(part_request.creatorGroup))
            buyer_name = (creator_group_doc or {}).get("name") or ""
            notification_fanout.fanout_offer_selected(
                offer=offer_json_for_notify,
                part_request=part_request_json,
                order_id=order_id,
                buyer_store_name=buyer_name,
            )
        elif (
            offer_status == OfferStatus.created
            and previous_status == OfferStatus.pending_approval
            and offer_json_for_notify.get("call_center_that_posted_offer")
        ):
            offer_group_doc = groupRepository.find_by_id(str(offer.group_id))
            approver_name = (offer_group_doc or {}).get("name") or ""
            notification_fanout.fanout_callcenter_offer_approved(
                offer=offer_json_for_notify,
                part_request=part_request_json,
                approver_group_name=approver_name,
            )

        return offer_json

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while changing offer status {e}')


def __create_workshop_approved_for_commissioner_notification(
    commissioner_id: str,
    part_request_data: PartRequest,
    offer_data: Offer,
    user_token: str
):

    commissioner_user_list = groupRepository.find_users_by_group_id(
        commissioner_id)

    if commissioner_user_list == None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Cannot find users to notify')

    for user_id in commissioner_user_list.get("users"):
        build_and_send_notification(
            user_id=user_id,
            group_id=commissioner_id,
            part_name=part_request_data.part.get("tipoParteDescripcion"),
            offer_id=offer_data.id,
            part_request_id=part_request_data.id,
            store_name=offer_data.group_info.name,
            user_token=user_token,
            status=OfferStatus.pending_approval,
            parent_request_uid=part_request_data.parent_request_uid,
        )


def get_ranked_offers(request_id: str):

    found_request = partRequestRepository.find_one_by_id(request_id)

    if found_request == None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f'Part Request with id {request_id} not found')

    part_request: PartRequest = PartRequest(**found_request)

    filters = {"request_id": request_id, "status": {
        "$in": [OfferStatus.created.value, OfferStatus.selected.value]}}

    if part_request.commissioner_group != None:
        filters = {
            **filters,
            "status": {
                "$in": [OfferStatus.created.value, OfferStatus.selected.value, OfferStatus.pending_approval.value]
            }
        }

    found_offers = list(offerRepository.find(filters))

    ids = [offer["_id"] for offer in found_offers]

    ranked_offers = {}

    counter = 1

    offers = list(offerRepository.get_ranked_offers(
        ids,
        [{"status": OfferStatus.pending_approval.value}] if part_request.commissioner_group != None else None)
    )

    for offer_item in offers:
        ranked_offers[str(offer_item["_id"])] = counter
        counter += 1

    return ranked_offers


def _get_part_request_data(request_id: str) -> PartRequest:
    try:
        part_request_data = partRequestRepository.find_one_by_id(request_id)
        if (part_request_data is not None):
            return PartRequest(**part_request_data)
        return None
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching part request {e}')


def _get_offer_data(offer_id: str) -> Offer:
    try:
        offer_data = offerRepository.find_offer_by_id(offer_id)
        if (offer_data is not None):
            return Offer(**offer_data)
        return None
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching part offer {e}')


def _serialize_offer_doc(doc: dict, role: str) -> dict:
    serialized = Offer(**doc).toJson()
    serialized["role"] = role
    if doc.get("part_request"):
        pr = doc["part_request"]
        serialized["part_request_snapshot"] = {
            "_id": str(pr.get("_id", "")),
            "creatorGroup": pr.get("creatorGroup"),
            "status": pr.get("status"),
            "part": pr.get("part"),
            "vehicleInformation": pr.get("vehicleInformation"),
            "createdAt": str(pr.get("createdAt", "")),
        }
    if doc.get("group_info"):
        gi = doc["group_info"]
        serialized["group_info"] = {
            "_id": str(gi.get("_id", "")),
            "name": gi.get("name"),
            "type": gi.get("type"),
            "city": gi.get("city"),
            "state": gi.get("state"),
        }
    counterpart_group_id = None
    if role == "seller" and doc.get("part_request"):
        counterpart_group_id = doc["part_request"].get("creatorGroup")
    elif role == "buyer":
        counterpart_group_id = doc.get("group_id")
    if counterpart_group_id:
        counterpart = groupRepository.find_by_id(
            str(counterpart_group_id), {"name": 1, "type": 1, "city": 1, "state": 1}
        )
        if counterpart:
            serialized["counterpart_group"] = {
                "_id": str(counterpart.get("_id", "")),
                "name": counterpart.get("name"),
                "type": counterpart.get("type"),
                "city": counterpart.get("city"),
                "state": counterpart.get("state"),
            }
    return serialized


def find_by_group(
    group_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    role: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    status_filter: Dict = {}
    if status:
        status_filter["status"] = status

    seller_filters = {"group_id": group_id, **status_filter}
    seller_docs = [
        {**doc, "_role": "seller"}
        for doc in offerRepository.find(seller_filters)
    ]

    buyer_request_ids = [
        str(doc["_id"])
        for doc in partRequestRepository.find(
            {"creatorGroup": group_id},
            {"_id": 1},
        )
    ]
    buyer_docs: List[dict] = []
    if buyer_request_ids:
        buyer_filters = {"request_id": {"$in": buyer_request_ids}, **status_filter}
        buyer_docs = [
            {**doc, "_role": "buyer"}
            for doc in offerRepository.find(buyer_filters)
        ]

    if role == "seller":
        merged = seller_docs
    elif role == "buyer":
        merged = buyer_docs
    else:
        merged = seller_docs + buyer_docs

    def sort_key(doc):
        created = doc.get("createdAt")
        if created is None:
            return datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        if isinstance(created, str):
            try:
                return datetime.fromisoformat(created.replace(" ", "T"))
            except ValueError:
                return datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        if getattr(created, "tzinfo", None) is None:
            return created.replace(tzinfo=ZoneInfo("UTC"))
        return created

    merged.sort(key=sort_key, reverse=True)

    total = len(merged)
    skip = (page - 1) * page_size
    page_docs = merged[skip : skip + page_size]

    offer_ids = [doc["_id"] for doc in page_docs if doc.get("_id")]
    enriched_by_id = {
        str(doc["_id"]): doc
        for doc in offerRepository.find_by_ids_enriched(offer_ids)
    }

    items = []
    for raw in page_docs:
        oid = raw["_id"]
        enriched = enriched_by_id.get(str(oid), raw)
        enriched = {**raw, **enriched}
        items.append(_serialize_offer_doc(enriched, raw["_role"]))

    total_pages = max(1, (total + page_size - 1) // page_size) if total else 0
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


def build_and_send_notification(
    user_id: str,
    group_id: str,
    part_name: str,
    store_name: str,
    user_token: str,
    part_request_id: str,
    offer_id: str,
    status: OfferStatus,
    parent_request_uid: str | None = None,
) -> None:
    try:
        if isinstance(user_id, dict):
            owner_id = user_id.get("_id") or user_id.get(
                "uid") or user_id.get("id")
        else:
            owner_id = user_id

        if not owner_id:
            print(f"⚠️ Warning: Invalid user_id format: {user_id}")
            return

        meta_data = buyer_offer_notification_meta(
            request_id=part_request_id,
            parent_request_uid=parent_request_uid,
            offer_id=offer_id,
        )
        buyer_url = buyer_offer_review_path(part_request_id, parent_request_uid)

        notification: Notification

        if status == OfferStatus.workshop_approval_pending:
            notification = create_offer_workshop_approval(
                owner=owner_id,
                owner_group=group_id,
                store_name=store_name,
                part_name=part_name,
                navigate_to_url=buyer_url,
                meta_data=meta_data,
            )

        elif status == OfferStatus.pending_approval:
            notification = create_offer_notification(
                owner=owner_id,
                owner_group=group_id,
                store_name=store_name,
                part_name=part_name,
                navigate_to_url=buyer_url,
                meta_data=meta_data,
            )
        else:
            return

        send_notification(notification, user_token)

    except Exception as error:
        print(f"❌ Critical error in notification system: {error}")
        print(
            f"📧 Failed notification - User: {user_id}, Part: {part_name}, Store: {store_name}")
