from app.repositories import PartRequestRepository as partRequestRepository
from app.schemas.PartRequest import PartRequest
from app.repositories import GroupCarRepository as groupCarRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import OfferRepository as offerRepository
from app.schemas.Groups import GroupType
from fastapi import HTTPException
from uuid import uuid4
from bson import ObjectId
from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo


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


def find_grouped(
        group_id: str,
        group_role: str,
        creator_group: str,
        vehicle_model: str,
        created_at: str,
        search_argument: str,
):
    try:
        filters = __format_grouped_filters(
            group_id,
            group_role,
            creator_group,
            vehicle_model,
            created_at,
            search_argument,
        )
        role = int(group_role)
        part_requests = list(partRequestRepository.find_grouped(filters))
        print(part_requests)
        if len(part_requests) > 0:
            found_offers = __find_offers_for_requests(
                part_requests, group_id if role == GroupType.CAR_SHOP.value else None)
            __format_offers_with_found_requests(
                requests=part_requests, offers=found_offers)
            __format_grouped_part_requests(part_requests)

        return part_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error finding grouped requests {e}')


def __find_offers_for_requests(requests, group_id: str):
    request_ids = []
    for request in requests:
        request_ids.append(str(request["_id"]))

    offers_found = list(
        offerRepository.find_by_request_ids(request_ids, group_id))
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


def __format_grouped_filters(
    group_id: str,
    group_role: str,
    creatorGroup: str,
    vehicle_model: str,
    created_at: str,
    search_argument: str,
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
            filters["$and"].append({"subscribedSellers": group_id})
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

    if created_at != None:
        created_at_array = created_at.split(',')

        created_at_dates = list(map(lambda created: datetime.strptime(created, "%Y-%m-%d %H:%M:%S.%f"), created_at_array))
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
    for part_request in part_requests:
        part_request["_id"] = str(part_request["_id"])
        part_request["vehicleInformation"]["_id"] = str(
            part_request["vehicleInformation"]["_id"])
        part_request["createdAt"] = str(part_request["createdAt"])


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
