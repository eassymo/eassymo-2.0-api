from app.repositories import OfferRepository as offerRepository
from app.services import BrandService as brandService
from app.services import GuaranteeService as guaranteeService
from app.schemas.Offer import Offer
from app.schemas.Brand import Brand
from app.schemas.Guarantee import Guarantee
from fastapi import HTTPException
from uuid import uuid4


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
        found_offers = offerRepository.find_by_request_id_and_group(part_request_id, group_id)
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
    filter_options = offerRepository.build_filter(propName)
    return filter_options