from app.repositories import PartRequestRepository as partRequestRepository
from app.schemas.PartRequest import PartRequest
from app.repositories import GroupCarRepository as groupCarRepository
from app.repositories import OfferRepository as offerRepository
from fastapi import HTTPException
from uuid import uuid4


def insert(part_request: PartRequest):
    try:
        inserted_ids = []
        parent_request_uid = str(uuid4())
        part_req = part_request.model_dump()
        vehicle_information = groupCarRepository.find_by_id(
            part_req["vehicleId"])

        for car_part in part_request.partList:
            part_request_payload = {
                **part_req,
                "part": car_part,
                "vehicleInformation": vehicle_information,
                "parent_request_uid": parent_request_uid
            }
            del part_request_payload["partList"]
            part_request_id = partRequestRepository.insert(
                part_request_payload).inserted_id
            inserted_ids.append(str(part_request_id))

        return inserted_ids
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def find(user_uid: str, group_id: str):
    try:
        found_requests = partRequestRepository.find_by_group_and_user(
            user_uid, group_id)

        found_requests_list = list(found_requests)
        return format_part_requests(found_requests_list)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def find_by_id(id):
    try:
        found_request = list(partRequestRepository.find_by_id(id))

        if found_request is not None and len(found_request) > 0:
            found_request = found_request[0]

        if found_request is not None:
            found_request = {
                **found_request,
                "_id": str(found_request["_id"]),
                "vehicleInformation": {
                    **found_request["vehicleInformation"],
                    "_id": str(found_request["_id"])
                },
                "group_info": {
                    **found_request["group_info"],
                    "_id": str(found_request["_id"])
                }
            }

        found_request["partList"] = __find_sister_part_list(
            found_request["parent_request_uid"])

        return found_request
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def __find_sister_part_list(parent_request_uid: str):
    try:
        sister_requests = list(
            partRequestRepository.find_sister_part_requests(parent_request_uid))

        formatted_sister_requests = []

        for sister_part in sister_requests:
            formatted_sister_requests.append({
                **sister_part,
                "_id": str(sister_part["_id"])
            })

        return formatted_sister_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def format_part_requests(part_requests):
    formatted_requests = []
    for part_request in part_requests:
        formatted_requests.append({
            **part_request,
            "vehicleInformation": {
                **part_request["vehicleInformation"],
                "_id": str(part_request["vehicleInformation"]["_id"])
            },
            "_id": str(part_request["_id"])
        })
    return formatted_requests


def find_grouped(group_id: str):
    try:
        filters = __format_grouped_filters(group_id)
        part_requests = list(partRequestRepository.find_grouped(filters))
        print(part_requests)
        if len(part_requests) > 0:
            found_offers = __find_offers_for_requests(part_requests)
            __format_offers_with_found_requests(
                requests=part_requests, offers=found_offers)
            __format_grouped_part_requests(part_requests)

        return part_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error finding grouped requests {e}')


def __find_offers_for_requests(requests):
    request_ids = []
    for request in requests:
        request_ids.append(str(request["_id"]))

    offers_found = list(offerRepository.find_by_request_ids(request_ids))
    return offers_found


def __format_offers_with_found_requests(requests, offers):
    for request in requests:
        offers_found = __filter_part_offer_by_request_id(
            offers, str(request["_id"]))
        if len(offers_found) > 0:
            request["offers"] = offers_found
        else:
            request["offers"] = []


def __format_grouped_part_requests(part_requests):
    for part_request in part_requests:
        part_request["_id"] = str(part_request["_id"])
        part_request["creatorGroup"]["_id"] = str(
            part_request["creatorGroup"]["_id"])
        part_request["vehicleInformation"]["_id"] = str(
            part_request["vehicleInformation"]["_id"])
        part_request["createdAt"] = str(part_request["createdAt"])
        part_request["updatedAt"] = str(part_request["updatedAt"])


def __filter_part_offer_by_request_id(offers, requestId):
    matching_offers = [
        offer for offer in offers
        if offer["request_id"] == requestId
    ]

    for offer in matching_offers:
        offer["_id"] = str(offer["_id"])
        offer["to_be_delivered_time"] = str(offer["to_be_delivered_time"])
    return matching_offers


def __format_grouped_filters(group_id: str):
    filters = {}
    if group_id is not None:
        filters["subscribedSellers"] = group_id
    return filters


def search(search_argument: str):
    try: 
        filters = __format_search_arguments(search_argument)
        reduced_part_requests = list(partRequestRepository.search_reduced(filters))
        __format_reduced_requests(reduced_part_requests)
        return reduced_part_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error finding reduced requests {e}')


def __format_search_arguments(search_argument: str):
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
            }
        ]
    }
    return applied_filters


def __format_reduced_requests(part_requests):
    for part_request in part_requests:
        part_request["_id"] = str(part_request["_id"])
        part_request["vehicleInformation"]["_id"] = str(part_request["vehicleInformation"]["_id"])
        part_request["createdAt"] = str(part_request["createdAt"])