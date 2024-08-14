from app.repositories import OfferRepository as offerRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.services import BrandService as brandService
from app.services import GuaranteeService as guaranteeService
from app.schemas.Offer import Offer
from app.schemas.Brand import Brand
from app.schemas.Guarantee import Guarantee
from fastapi import HTTPException
from uuid import uuid4
from typing import List


def insert(payload: Offer):
    try:
        if payload.offer_group_uid == None:
            offer_group_uid = str(uuid4())
            payload.offer_group_uid = offer_group_uid

        brand_payload = Brand(label=payload.brand, user_uid=payload.user_uid)
        brandService.insert(brand_payload)

        guarantee_payload = Guarantee(
            label=payload.guarantee, user_uid=payload.user_uid)
        guaranteeService.insert(guarantee_payload)

        inserted_id = offerRepository.insert(payload).inserted_id

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
        found_offers = offerRepository.find_by_request_id_and_group(
            part_request_id, group_id)
        found_offers = list(found_offers)

        if len(found_offers) == 0:
            return []

        for offer in found_offers:
            offer["_id"] = str(offer["_id"])
            offer["to_be_delivered_time"] = str(offer["to_be_delivered_time"])

        return found_offers

    except Exception as e:
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
