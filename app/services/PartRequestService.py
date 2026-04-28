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
from app.repositories import ListsRepository as listRepository
from app.schemas.Groups import GroupType, GroupSchema
from app.schemas.Offer import Offer
from fastapi import HTTPException, Request, status
from uuid import uuid4
from bson import ObjectId
from typing import List, Any, Dict, Optional
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo
from app.services import GroupService as groupService
from app.factories.NotificationsCreator import (
    create_part_request_notification,
)
from app.utils.notifications import send_notification
from app.services import ListsService as listService
from app.repositories import ListsRepository as listRepository

import pymongo


def _default_fulfillment_type_on_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc.get("fulfillment_type"):
        return {**doc, "fulfillment_type": FulfillmentType.delivery.value}
    return doc


def insert(part_request: PartRequest, user_token: str = None):
    try:
        try:
            validate_delivery_fulfillment(
                part_request.fulfillment_type,
                part_request.delivery_address,
                part_request.delivery_contact,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        inserted_ids = []

        users_from_groups: List[str] = []

        if part_request.parent_request_uid != None and len(part_request.parent_request_uid) > 0:
            parent_request_uid = part_request.parent_request_uid
        else:
            parent_request_uid = str(uuid4())
        part_req = part_request.dict()
        part_req["fulfillment_type"] = part_request.fulfillment_type.value
        vehicle_information = groupCarRepository.find_by_id(
            part_req["vehicleId"])

        creator_group_data = groupRepository.find_by_id(
            part_request.creatorGroup)

        if creator_group_data != None:
            part_request.group_info = GroupSchema(**creator_group_data)

        subscribed_sellers = part_request.subscribedSellers

        if part_request.commissioner_group != None:
            nearby_commissioner_groups = __find_commissioner_group_connections(
                creator_group_id=part_request.creatorGroup,
                commissioner_group_id=part_request.commissioner_group
            )

            users_from_groups = nearby_commissioner_groups["users_from_groups"]

            for commissioner_group in nearby_commissioner_groups["commissioner_groups_from_lists"]:
                if commissioner_group.id not in subscribed_sellers:
                    subscribed_sellers.append(commissioner_group.id)

        for car_part in part_request.partList:
            part_request_payload = {
                **part_req,
                "part": car_part,
                "vehicleInformation": vehicle_information,
                "parent_request_uid": parent_request_uid,
                "status": part_request.status.value,
                "specific_order_uid": part_request.specific_order_uid,
                "subscribedSellers": subscribed_sellers,
                "createdAt": datetime.now(ZoneInfo('UTC'))
            }
            del part_request_payload["partList"]
            part_request_id = partRequestRepository.insert(
                part_request_payload).inserted_id
            inserted_ids.append(part_request_id)

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

        return found_part_requests
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting part request {e}')


def __find_commissioner_group_connections(creator_group_id: str, commissioner_group_id: str) -> Dict[str, Any]:
    # TODO: Encontrar a los grupos del comisionado que esten cercanos a el grupo que esta creando la solicitud
    try:
        creator_group_data = groupRepository.find_by_id(creator_group_id)
        if creator_group_data != None:
            creator_group = GroupSchema(**creator_group_data)

            if creator_group.location is None:
                return []

            commissioner_group_lists = list(
                listRepository.find_all_groups_in_user_lists(None, commissioner_group_id))

            all_group_ids = []
            for list_data in commissioner_group_lists:
                if 'all_groups' in list_data:
                    all_group_ids.extend(list_data['all_groups'])

            unique_group_ids = list(set(all_group_ids))

            if not unique_group_ids:
                return []

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
            return []

    except HTTPException as e:
        raise HTTPException(e)


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
            navigate_to_url=f"/dashboard/part-request/{created_part_request_id}",
            meta_data={"requestId": created_part_request_id}
        )

        send_notification(notification, user_token)

    except Exception as error:
        print(f"❌ Critical error in notification system: {error}")
        print(
            f"📧 Failed notification - User: {user_id}, Part: {part_name}, Store: {store_name}")
        # Log the error but don't re-raise to avoid breaking part request creation


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
                    {"subscribedSellers": group_id}
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


def find_by_id(id):
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
        if group_id == creator_group:
            matching_offers = [
                offer for offer in matching_offers if offer.status != OfferStatus.pending_approval.value
            ]

    return matching_offers


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
    # Step 1: Match by parent_request_uid and optional status
    match_stage = {"parent_request_uid": parent_request_uid}
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

    part_requests_with_offers = []

    for part_request_data in sibling_part_requests:
        part_request_dict = PartRequest(**part_request_data).toJson()

        offer_filters = {
            "request_id": part_request_dict.get("_id"),
        }

        if status != None:
            offer_filters["status"] = status

        if filters_dict and len(filters_dict) > 0:
            custom_filters = __build_filters_for_sibling_requests(
                filters_dict, 
                newest_part_request.creatorGroup, 
                logged_in_user
            )
            offer_filters.update(custom_filters)
        
        """    # If a specific offer_owner_group is provided, it takes precedence
        if offer_owner_group != None and len(offer_owner_group) > 0:
            offer_filters["group_id"] = offer_owner_group """

        part_request_offers = list[Any](offerRepository.find(offer_filters))

        followers = []
        followers = listService.get_followers_list(
            logged_in_user, newest_part_request.creatorGroup)

        offers = []
        for offer_data in part_request_offers:
            offer_json = Offer(**offer_data).toJson()
            group_info = groupRepository.find_by_id(offer_json["group_id"])
            group = GroupSchema(**group_info)
            offer_json["group_info"] = group.toJson()

            for follower in followers:
                if follower.get('_id') == offer_json.get('group_id'):
                    offer_json['createdByFollower'] = True
                else:
                    offer_json['createdByFollower'] = False

            offer_json["creatorIsFavoriteAtSomeList"] = __check_if_group_is_favorite(
                group)
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
            # Show offers only from follower groups (groups that follow creator but creator doesn't follow back)
            all_group_ids.extend(filter_values)
            
        elif filter_type == "connected_custom":
            # Show offers only from connected groups (groups in creator's lists)
            all_group_ids.extend(filter_values)
            
        elif filter_type == "favorites":
            # Check if we should apply favorite filtering
            if filter_values and filter_values[0] == 'true':
                favorite_lists = list(listRepository.find({
                    "group_id": creator_group_id,
                    "user_uid": logged_in_user,
                    "is_favorite": True
                }))
                
                # Collect all group IDs from these favorite lists
                for favorite_list in favorite_lists:
                    groups_in_list = favorite_list.get("groups", [])
                    all_group_ids.extend(groups_in_list)
            # If filter_values[0] is False, don't apply any favorite filtering
    
    # Remove duplicates in case same group appears in multiple filter types
    unique_group_ids = list(set(all_group_ids))
    
    # If we have group IDs to filter by, return the MongoDB $in filter
    if len(unique_group_ids) > 0:
        return {
            "group_id": {"$in": unique_group_ids}
        }
    
    # No applicable filters, return empty dict (no additional filtering)
    return {}


def __check_if_group_is_favorite(group: GroupSchema) -> bool:
    favorite_lists = list[Any](listRepository.find(
        {"is_favorite": True, "groups": group.id}))

    return len(favorite_lists) > 0


def edit_part_request(part_request_data: List[PartRequestEdit]):
    try:
        edited_ids = []
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
                if part_request_edit.subscribedSellers is not None:
                    subs = list(set(subs + part_request_edit.subscribedSellers))

                part_request_json = {
                    "part": {
                        **current_part_request.part,
                        "comments": part_request_edit.comment,
                        "amount": part_request_edit.amount
                    },
                    "subscribedSellers": subs,
                    "fulfillment_type": merged.fulfillment_type.value,
                    "delivery_address": merged.delivery_address.model_dump()
                    if merged.delivery_address is not None else None,
                    "delivery_contact": merged.delivery_contact.model_dump()
                    if merged.delivery_contact is not None else None,
                    "updatedAt": datetime.now(ZoneInfo('UTC')),
                }

                edited_part_request = partRequestRepository.edit_part_request(
                    part_request_edit.id, part_request_json)
                edited_ids.append(str(edited_part_request["_id"]))

        return edited_ids
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while editing part request {e}')


def join_seller_to_part_request(parent_request_id: str | None, new_seller_group_id: str | None):
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

        edited_part_request_ids: List[str] = []
        for part_request in part_requests:

            if part_request.status != PartRequestStatus.CREATED:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail="The part request status does not allow this operation")

            if part_request.subscribedSellers and new_seller_group_id in part_request.subscribedSellers:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail="The current seller already belongs to the request")

            part_request.subscribedSellers.append(new_seller_group_id)

            edit_payload = part_request.toJson()

            edit_payload.pop("_id")

            edited_part_request = partRequestRepository.edit_part_request(
                part_request.id, edit_payload)
            edited_part_request_ids.append(str(edited_part_request["_id"]))

        return edited_part_request_ids
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


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


def find_grouped_by_parent_request_uid(creator_group_id: Optional[str], seller_group_id: Optional[str], status: Optional[str]):
    try:
        status_enum = PartRequestStatus(status) if status else None
        
        results = list(partRequestRepository.find_grouped_by_parent_request_uid(
            creator_group_id,
            seller_group_id,
            status_enum
        ))

        for group_result in results:
            base_request = group_result.get("part_requests")[0]

            vehicle_information = base_request.get("vehicleInformation")
            
            creator_group_data = groupRepository.find_by_id(base_request.get("creatorGroup"))

            group_result["creator_group"] = creator_group_data.get("name")
            group_result["car_data"] = f'{vehicle_information.get("maker")} {vehicle_information.get("model")} {vehicle_information.get("year")}'

            part_requests_jsons = []

            for part_request_data in group_result.get("part_requests"):
                part_request_data = PartRequest(**part_request_data).toJson()

                part_requests_jsons.append(part_request_data)
            
            group_result["part_requests"] = part_requests_jsons

        return results
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while finding part requests grouped by parent_request_uid: {e}')
