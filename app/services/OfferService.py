from app.repositories import OfferRepository as offerRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.services import BrandService as brandService
from app.services import GuaranteeService as guaranteeService
from app.schemas.Offer import Offer
from app.schemas.Brand import Brand
from app.schemas.Guarantee import Guarantee
from app.schemas.PartRequest import PartRequest, PartRequestStatus
from app.schemas.Groups import GroupSchema
from fastapi import HTTPException, status
from uuid import uuid4
from app.schemas.Offer import OfferStatus, OfferType
from app.repositories import OrderRepository as orderRepository
from app.repositories import CallCenterConnectionRepository as callCenterConnectionRepository
from app.schemas.Order import Order, OrderStatus
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List


def insert(payload: Offer):
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

        offer_payload = payload.toJson()

        offer_payload.pop('_id')

        inserted_id = offerRepository.insert(offer_payload).inserted_id

        return str(inserted_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while creating offer Error: {e}')


def find(filters: Offer):
    try:
        found_offers = offerRepository.find(__format_filters(filters))
        return __format_offers_response(found_offers)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching offer Error: {e}')


def find_by_request_id_and_group(part_request_id: str, group_id: str):
    try:

        group_ids = []

        part_request_data = list(partRequestRepository.find_by_id(part_request_id))

        if len(part_request_data) > 0:
            part_request = PartRequest(**part_request_data[0])
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Part Request not found")

        if group_id != None:
            group_info = groupRepository.find_by_id(group_id)

            if group_info == None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Group info is not found")

            group = GroupSchema(**group_info)

            group_ids.append(group.id)

        if group_id == part_request.creatorGroup:
            group_ids = []

        found_offers_dicts = list(offerRepository.find_by_request_id_and_group(
            part_request_id, group_ids, group.is_callcenter))

        if len(found_offers_dicts) == 0:
            return []

        found_offers: List[Offer] = [
            Offer(**offer_data).toJson() for offer_data in found_offers_dicts]

        return found_offers

    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f'Error while getting specific offer {e}')


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

    groups_found = []

    have_offered_qty = 0

    seller_dict = list(map(lambda seller_id: {
                       "seller_id": seller_id, "has_offered": False}, subscribed_sellers))

    for seller in seller_dict:
        offers = list(offerRepository.find_by_request_id_and_group(
            request_id, [seller["seller_id"]]))

        if len(offers) > 0:
            seller["has_offered"] = True
            have_offered_qty += 1

    for seller in seller_dict:
        group_data = groupRepository.find_by_id(seller["seller_id"])
        if group_data == None:
            continue

        group_item = GroupSchema(**group_data)

        group_json = group_item.toJson()
        group_json["has_offered"] = seller["has_offered"]
        groups_found.append(group_json)

    return {"groups_found": groups_found, "have_offered": have_offered_qty, "have_not_offered": len(seller_dict) - have_offered_qty}


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


def change_offer_status(request_id: str, offer_id: str, status: str):
    try:
        part_request: PartRequest = _get_part_request_data(request_id)
        offer: Offer = _get_offer_data(offer_id)
        offer_status = OfferStatus[status.lower()]
        order_id: str = ""
        match offer_status:
            case offer_status.created:
                offer.update_status(OfferStatus.created)
            case offer_status.selected:
                part_request.update_status(PartRequestStatus.OFFER_SELECTED)
                offer.update_status(OfferStatus.selected)

                order = Order(offer=offer, part_request=part_request, status=OrderStatus.WAITING_FOR_CONFIRMATION,
                              creator_user=part_request.creatorUser, group=part_request.creatorGroup, created_at=datetime.now(ZoneInfo('UTC')))
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

        return offer_json

    except Exception as e:
        HTTPException(
            status_code=500, detail=f'Error while changing offer status {e}')


def get_ranked_offers(request_id: str):

    found_offers = list(offerRepository.find({"request_id": request_id, "status": {
                        "$in": [OfferStatus.created.value, OfferStatus.selected.value]}}))

    ids = [offer["_id"] for offer in found_offers]

    ranked_offers = {}

    counter = 1

    offers = list(offerRepository.get_ranked_offers(ids))

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
        HTTPException(
            status_code=500, detail=f'Error while fetching part request {e}')


def _get_offer_data(offer_id: str) -> Offer:
    try:
        offer_data = offerRepository.find_offer_by_id(offer_id)
        if (offer_data is not None):
            return Offer(**offer_data)
        return None
    except Exception as e:
        HTTPException(
            status_code=500, detail=f'Error while fetching part offer {e}')
