from fastapi import HTTPException, status
from app.repositories import PartRequestRepository, CallCenterConnectionRepository, OfferRepository, GroupRepository
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
            "status": PartRequestStatus.CREATED.value
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

        # Get part requests and convert directly to the final format
        part_requests_data = list(
            PartRequestRepository.find_for_call_center(filters))

        part_requests = []
        for part_request_data in part_requests_data:
            part_request = PartRequest(**part_request_data)

            offers_for_part_request = list(OfferRepository.find(
                {"request_id": part_request.id, "group_id": {"$in": group_ids + [callcenter_id]}}))

            part_request.offers_amount = len(offers_for_part_request)
            part_requests.append(part_request)

        # Return JSON representation of the part requests with offers_amount included
        return [part_request.toJson() for part_request in part_requests]
    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while finding part requests for callcenter")
