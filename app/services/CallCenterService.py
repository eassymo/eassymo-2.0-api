from fastapi import HTTPException, status
from app.repositories import PartRequestRepository, CallCenterConnectionRepository, OfferRepository, GroupRepository, UserRepository
from pymongo.errors import PyMongoError
from typing import List, Dict, Any
from app.schemas.PartRequest import PartRequestStatus, PartRequest


def find(callcenter_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    try:
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

        filters_for_part_requests = build_callcenter_requests_filters(
            callcenter_id, filters)

        # Get part requests and convert directly to the final format
        part_requests_data = list(
            PartRequestRepository.find_for_call_center(filters))

        part_requests = []
        for part_request_data in part_requests_data:
            part_request = PartRequest(**part_request_data)

            # Find all offers for this part request from any of the linked groups or callcenter
            offers_for_part_request = list(OfferRepository.find(
                {"request_id": part_request.id, "group_id": {"$in": group_ids + [callcenter_id]}}))

            part_request.offers_amount = len(offers_for_part_request)

            # Find which groups from the callcenter are subscribed to this part request
            subscribed_groups = [seller for seller in part_request.subscribedSellers if seller in group_ids]
            
            # Create a duplicate part request for each subscribed group
            for group_id in subscribed_groups:
                group_info = GroupRepository.find_by_id(group_id)
                # Match offers to specific group
                group_offers = [offer for offer in offers_for_part_request if offer.get("group_id") == group_id]
                
                # Create group details as an object (not an array)
                subscribed_group_details = {
                    "group_id": group_id,
                    "owner": group_info.get("owner"),
                    "group_name": group_info.get("name") if group_info else "Unknown",
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


def build_callcenter_requests_filters(callcenter_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        groups_linked_to_callcenter = CallCenterConnectionRepository.find_many(
            {"callcenter_id": callcenter_id})

        group_ids = [group.group_id for group in groups_linked_to_callcenter]

        filters = {
            **filters,
            "subscribedSellers": {"$in": group_ids},
            "status": PartRequestStatus.CREATED.value
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
                users_from_callcenter = UserRepository.find({"groups": callcenter_connection.callcenter_id})
                
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
