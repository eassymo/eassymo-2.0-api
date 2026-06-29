from fastapi import HTTPException, status
from app.repositories import PartRequestRepository, CallCenterConnectionRepository, OfferRepository, GroupRepository, UserRepository, CallCenterManagementListRepository
from pymongo.errors import PyMongoError
from typing import List, Dict, Any
from app.schemas.PartRequest import PartRequestStatus, PartRequest
from app.schemas.Groups import GroupSchema
from bson import ObjectId


def find(callcenter_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    try:

        is_filtering_by_management_list = False
        # Get groups linked to the callcenter
        groups_linked_to_callcenter = CallCenterConnectionRepository.find_many(
            {"callcenter_id": callcenter_id})

        # Extract group IDs properly using list comprehension
        group_ids = [group.group_id for group in groups_linked_to_callcenter]

        # Use group_ids in the filter rather than the entire group objects
        filters = {
            **filters,
            "subscribedSellers": {"$in": group_ids},
        }

        if "search_term" in filters and filters["search_term"].strip():
            search_pattern = {
                "$regex": filters["search_term"], "$options": "i"}

            filters = {
                **filters,
                "$or": [
                    {
                        "part.tipoParteDescripcion": {
                            "$regex": filters["search_term"],
                            "$options": "i"
                        }
                    },
                    {
                        "vehicleInformation.model": {
                            "$regex": filters["search_term"],
                            "$options": "i"
                        }
                    },
                    {
                        "vehicleInformation.maker": {
                            "$regex": filters["search_term"],
                            "$options": "i"
                        }
                    },
                    {
                        "vehicleInformation.year": {
                            "$regex": filters["search_term"],
                            "$options": "i"
                        }
                    },
                    {
                        "vehicleInformation.engine": {
                            "$regex": filters["search_term"],
                            "$options": "i"
                        }
                    }
                ]
            }

            groups_matching = list(GroupRepository.find({
                "$or": [
                    {"name": search_pattern},
                    {"address": search_pattern}
                ]
            }))

            if groups_matching:
                matching_group_ids = [str(group["_id"])
                                      for group in groups_matching]
                filters["creatorGroup"] = {"$in": matching_group_ids}

            filters.pop("search_term")

        if "positions" in filters:
            filters = {
                **filters,
                "part.position": {
                    "$in": filters["positions"]
                }
            }

            filters.pop("positions")

        if "unitsOfMeasure" in filters:
            filters = {
                **filters,
                "part.unitOfMeasure": {
                    "$in": filters["unitsOfMeasure"]
                }
            }

            filters.pop("unitsOfMeasure")

        if "statuses" in filters:
            filters = {
                **filters,
                "status": {
                    "$in": filters["statuses"]
                }
            }

            filters.pop("statuses")

        if "managementListIds" in filters:

            subscribed_sellers = _get_group_ids_from_management_lists(
                filters["managementListIds"])

            filters = {**filters, "subscribedSellers": {
                "$in": subscribed_sellers,
            }}

            is_filtering_by_management_list = True

            filters.pop("managementListIds")

        filters_for_part_requests = build_callcenter_requests_filters(
            callcenter_id, filters)

        # Get part requests and convert directly to the final format
        part_requests_data = list(
            PartRequestRepository.find_for_call_center(filters))

        all_request_ids = [str(pr.get("_id")) for pr in part_requests_data]

        all_offers = list(OfferRepository.find({
            "request_id": {"$in": all_request_ids},
            "call_center_that_posted_offer._id": {"$in": [callcenter_id]}
        }, {"group_id": 1, "request_id": 1}))

        # Group offers by request_id for fast lookup
        offers_by_request = {}
        for offer in all_offers:
            request_id = offer["request_id"]
            if request_id not in offers_by_request:
                offers_by_request[request_id] = []
            offers_by_request[request_id].append(offer)

        part_requests = []
        for part_request_data in part_requests_data:
            part_request = PartRequest(**part_request_data)

            # Find all offers for this part request from any of the linked groups or callcenter
            offers_for_part_request = offers_by_request.get(
                part_request.id, [])

            part_request.offers_amount = len(offers_for_part_request)

            # Find which groups from the callcenter are subscribed to this part request
            subscribed_groups = [
                seller for seller in part_request.subscribedSellers if seller in group_ids]
            
            if is_filtering_by_management_list:
                subscribed_in_list = filters["subscribedSellers"].get("$in")
                subscribed_groups = [seller for seller in subscribed_groups if seller in subscribed_in_list]

                print(subscribed_groups)

            # Create a duplicate part request for each subscribed group

            all_groups_info = list(GroupRepository.find({
                "_id": {
                    "$in": [ObjectId(subscribed_group_id) for subscribed_group_id in subscribed_groups]
                }
            }))

            for group in all_groups_info:

                group_id = str(group.get("_id"))
                # Match offers to specific group
                group_offers = [offer for offer in offers_for_part_request if offer.get(
                    "group_id") == group_id]

                # Create group details as an object (not an array)
                subscribed_group_details = {
                    "group_id": group_id,
                    "owner": group.get("owner"),
                    "group_name": group.get("name") if group else "Unknown",
                    "offers_count": len(group_offers),
                }

                # Add a duplicate part request for this specific group
                part_requests.append({
                    **part_request.toJson(),
                    "subscribed_group": subscribed_group_details
                })

        # Return JSON representation of the part requests with offers_amount included
        return {
            "part_requests": part_requests,
            "filter_data": filters_for_part_requests
        }
    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while finding part requests for callcenter")


def _get_group_ids_from_management_lists(management_list_ids: List[str]):
    try:
        ids = [ObjectId(list_id) for list_id in management_list_ids]
        management_lists_data = list(
            CallCenterManagementListRepository.find({"_id": {"$in": ids}}))

        # Flatten the nested lists of groups
        all_groups = []
        for management_list in management_lists_data:
            all_groups.extend(management_list.groups)

        # Extract IDs handling both string IDs and GroupSchema objects
        group_ids = []
        for group in all_groups:
            if isinstance(group, GroupSchema):
                group_ids.append(group.id)
            elif isinstance(group, str):
                group_ids.append(group)

        return group_ids
    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while getting groups from management lists")


def build_callcenter_requests_filters(callcenter_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    try:

        filters = {
            **filters,
            "status": PartRequestStatus.CREATED.value
        }

        if "subscribedSellers" in filters and len(filters.get("subscribedSellers")) > 0:

            filters["subscribedSellers"] = filters.get("subscribedSellers")
        else:
            groups_linked_to_callcenter = CallCenterConnectionRepository.find_many(
                {"callcenter_id": callcenter_id})

            group_ids = [
                group.group_id for group in groups_linked_to_callcenter]

            filters["subscribedSellers"] = {
                "$in": group_ids
            }

        units = PartRequestRepository.distinct("part.unitOfMeasure", filters)
        statuses = PartRequestRepository.distinct("status", filters)
        positions = PartRequestRepository.distinct("part.position", filters)

        return {"units": units, "statuses": statuses, "positions": positions}

    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while building filters for requests filters")


def get_users_of_callcenters_from_group_ids(group_ids: List[str]) -> List[Dict[str, Any]]:
    try:

        callcenters_for_group = CallCenterConnectionRepository.find(
            {"group_id": {"$in": group_ids}})

        if len(callcenters_for_group) > 0:
            users_formatted = []
            for callcenter_connection in callcenters_for_group:
                users_from_callcenter = UserRepository.find(
                    {"groups": callcenter_connection.callcenter_id})

                for user in users_from_callcenter:
                    users_formatted.append({
                        "user_id": user.get("uid"),
                        "name": user.get("name"),
                        "callcenter_id": callcenter_connection.callcenter_id,
                        "group_id": callcenter_connection.group_id
                    })

            return users_formatted
        else:
            return []

    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while building filters for requests filters")


def get_related_groups(callcenter_id: str) -> List[Dict[str, Any]]:
    try:
        groups_linked_to_callcenter = CallCenterConnectionRepository.find_many(
            {"callcenter_id": callcenter_id})

        group_ids = [ObjectId(group.group_id)
                     for group in groups_linked_to_callcenter]

        groups_data = list(GroupRepository.find(
            {"_id": {"$in": group_ids}}, {}))

        groups: List[Dict[str, Any]] = []
        for group_data in groups_data:
            group = GroupSchema(**group_data)
            groups.append(group.toJson())

        return groups
    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while fetching related groups")
