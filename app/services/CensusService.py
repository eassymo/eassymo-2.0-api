from datetime import datetime, timedelta
from app.repositories import CensusRepository as censusRepository
from pymongo.errors import PyMongoError
from fastapi import HTTPException, Request, status
from app.repositories import InvitationRepository as invitationRepository
from app.repositories import ListsRepository as listRepository
from bson import ObjectId
from app.schemas.Census import CensusSchema
from app.schemas.RequestInvites import RequestInviteStatus
from app.repositories import PartRequestInviteRepository as partRequestInviteRepository
from typing import List
from difflib import SequenceMatcher


def find(filters):
    try:
        user_uid = filters["userUid"]
        group_id = filters["group_id"]

        # Check if this is a geospatial search
        is_geospatial_search = (filters.get("lat") is not None and
                                filters.get("lng") is not None and
                                filters.get("range_km") is not None)

        built_filters = build_filters(filters)
        print(built_filters)

        if is_geospatial_search:
            # Use geospatial aggregation for location-based search
            range_meters = filters["range_km"] * 1000
            results = list(censusRepository.find_with_geospatial(
                built_filters,
                filters["lat"],
                filters["lng"],
                range_meters,
                built_filters["limit"],
                built_filters["page"]
            ))
            # For geospatial search, we can't easily get accurate counts, so approximate
            total_count = len(results)  # This is just the current page count
            group_count = sum(
                1 for r in results if r.get("group_reference_id"))
        else:
            # Use regular find for non-geospatial searches
            results = list(censusRepository.find(
                built_filters, built_filters["limit"], built_filters["page"]))
            counts = censusRepository.count(built_filters)
            total_count = counts["total_count"]
            group_count = counts["group_count"]

        # Apply status checking to results
        results = check_census_status(user_uid, results, group_id)

        return {
            "message": "ok",
            "body": results,
            "count": total_count,
            "group_count": group_count,
            "page": built_filters["page"],
            "limit": built_filters["limit"],
            "is_geospatial_search": is_geospatial_search
        }
    except PyMongoError as err:
        return {"message": f'Error getting items from census {err}'}


def build_filters(parameters):
    filters = {}

    if parameters["id"] is not None:
        filters["_id"] = ObjectId(parameters["id"])

    if parameters["exclude_group"] is not None and len(parameters["exclude_group"]) > 0:
        filters["group_reference_id"] = {
            "$ne": parameters["exclude_group"]
        }

    if parameters["limit"] is not None:
        filters["limit"] = parameters["limit"]
    else:
        filters["limit"] = 20

    if parameters["page"] is not None:
        filters["page"] = parameters["page"]
    else:
        filters["page"] = 1

    # Create a list of conditions that will be combined with $and
    conditions = []

    if parameters["search_argument"] is not None and len(parameters["search_argument"]) > 0:
        search_term = parameters["search_argument"]
        if not (search_term.startswith('"') and search_term.endswith('"')):
            search_term = f'"{search_term}"'

        conditions.append({"$text": {"$search": search_term}})

    if parameters["Entity_Type"] is not None and len(parameters["Entity_Type"]) > 0:
        if parameters["Entity_Type"] == "Refa":
            conditions.append({"Entity_Type": 1})
        elif parameters["Entity_Type"] == "Taller":
            conditions.append({"Entity_Type": 2})

    # Apply state and city filters directly to the filters dictionary instead of conditions
    # Create location OR conditions
    location_conditions = []

    if parameters["Entity_Location_State"] is not None and len(parameters["Entity_Location_State"]) > 0:
        location_conditions.append(
            {"Entity_Location_State": parameters["Entity_Location_State"]})

    if parameters["Entity_Address_City"] is not None and len(parameters["Entity_Address_City"]) > 0:
        location_conditions.append(
            {"Entity_Address_City": parameters["Entity_Address_City"]})

    # Add OR condition if any location filters exist
    if len(location_conditions) > 0:
        if len(location_conditions) == 1:
            # If only one condition, add it directly
            filters.update(location_conditions[0])
        else:
            # If multiple conditions, use $or
            filters["$or"] = location_conditions

    if "show_only_census" in parameters and parameters["show_only_census"] is not None:
        conditions.append({
            "$or": [
                {"group_reference_id": None},
                {"group_reference_id": {"$exists": False}}
            ]
        })

    # Handle geospatial search
    if (parameters.get("lat") is not None and
        parameters.get("lng") is not None and
            parameters.get("range_km") is not None):

        # Convert kilometers to meters (MongoDB uses meters)
        range_meters = parameters["range_km"] * 1000

        # Add geospatial query using $near
        filters["location"] = {
            "$near": {
                "$geometry": {
                    "type": "Point",
                    # [longitude, latitude]
                    "coordinates": [parameters["lng"], parameters["lat"]]
                },
                "$maxDistance": range_meters
            }
        }

    # If we have conditions, combine them with $and
    if conditions:
        if len(conditions) == 1:
            # If only one condition, no need for $and
            filters.update(conditions[0])
        else:
            filters["$and"] = conditions

    return filters


def get_states():
    try:
        states_found = censusRepository.find_states()
        return {"message": "ok", "body": states_found}
    except PyMongoError as err:
        return {"message": f'Error getting states from census {err}'}


def get_cities(state: str):
    try:
        cities_found = censusRepository.find_city(state)
        return {"message": "ok", "body": cities_found}
    except PyMongoError as err:
        return {"message": f'Error getting cities from census {err}'}


def check_census_status(user_uid: str, census_items, group_id: str):
    found_invites = list(invitationRepository.find(
        {"user": user_uid, "creator_group": group_id}))
    user_groups_in_lists = list(
        listRepository.find_all_groups_in_user_lists(user_uid, group_id))

    all_groups_in_lists = []
    if len(user_groups_in_lists) > 0:
        all_groups_in_lists = user_groups_in_lists[0]["all_groups"]
    for index, census_item in enumerate(census_items):
        census_items[index]["can_send_invite"] = True
        for invite in found_invites:
            if invite["censusId"] == str(census_item["_id"]):
                can_send_invite = validate_if_invite_canbe_resent(
                    invite["lastSent"])
                census_items[index]["can_send_invite"] = can_send_invite
                census_items[index]["census_status"] = "INVITED"
                census_items[index]["invite_id"] = str(invite["_id"])
        if "group_reference_id" in census_item and census_item["group_reference_id"] is not None:
            census_items[index]["census_status"] = "CAN_CONNECT"
            census_items[index]["can_send_invite"] = False
            if "BOSH CAR SERVICE ORIZABA" in census_item["Entity_Name"]:
                print(census_item)
            if census_item["group_reference_id"] in all_groups_in_lists:
                census_items[index]["census_status"] = "CONNECTED"

    return census_items


def validate_if_invite_canbe_resent(last_sent: datetime):
    current_date = datetime.now()
    difference = current_date - last_sent
    return difference >= timedelta(days=7)


def text_search(request: Request, argument: str | None, parent_request_id: str | None):
    try:

        user = request.state._state.get('user')
        groupSelected = request.state._state.get('groupSelected')

        search_filters = {}

        if argument != None:
            search_filters["$text"] = {
                "$search": argument,
            }

        search_filters["group_reference_id"] = {"$eq": None}

        results = list(censusRepository.find(search_filters, 30, 0))

        results_json = []
        for census_item in results:
            census = CensusSchema(**census_item)

            invitation_filters = {
                "inviter_user": user.get('uid'),
                "inviter_group": groupSelected,
                "census_id": str(census.id),
                "$or": [
                    {
                        "status": RequestInviteStatus.CREATED.value
                    },
                    {
                        "status": RequestInviteStatus.ACCEPTED.value
                    }
                ]
            }

            if parent_request_id != None:
                invitation_filters["parent_request_id"] = parent_request_id

            invites_data_found = list(
                partRequestInviteRepository.find(invitation_filters))

            census.can_be_invited = len(invites_data_found) == 0

            results_json.append(census.toJson())

        return results_json
    except (PyMongoError, Exception) as e:
        raise HTTPException(e)


def verify_for_similitudes(lat: float, lng: float, name: str, range_meters=500):
    try:
        filters = {
            "$or": [
                {"group_reference_id": {"$exists": False}},
                {"group_reference_id": {"$eq": None}}
            ]
        }

        if not isinstance(lat, float) or not isinstance(lng, float):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="lat and lng are required")

        if not name or not isinstance(name, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")

        near_results_data = list(
            censusRepository.find_with_geospatial(filters, lat, lng, range_meters))

        census_list: List[dict] = []
        search_name_lower = name.lower().strip()

        for census_data in near_results_data:
            entity_name = census_data.get("Entity_Name", "")
            if not entity_name:
                continue

            entity_name_lower = entity_name.lower().strip()

            # Calculate similarity using multiple methods
            similarity_score = calculate_name_similarity(
                search_name_lower, entity_name_lower)

            # Consider it a match if similarity is above threshold (0.6 = 60%)
            if similarity_score >= 0.7:
                census_schema = CensusSchema(**census_data)
                result = census_schema.toJson()
                result["similarity_score"] = similarity_score
                result["matched_name"] = entity_name
                census_list.append(result)

        # Sort by similarity score (highest first)
        census_list.sort(key=lambda x: x["similarity_score"], reverse=True)

        return census_list

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


def calculate_name_similarity(search_name: str, entity_name: str) -> float:
    """
    Calculate similarity between search name and entity name using multiple methods
    """
    # Method 1: Direct substring match (highest priority)
    if search_name in entity_name or entity_name in search_name:
        return 0.95

    # Method 2: Word-based matching
    search_words = set(search_name.split())
    entity_words = set(entity_name.split())

    if search_words and entity_words:
        word_intersection = len(search_words.intersection(entity_words))
        word_union = len(search_words.union(entity_words))
        word_similarity = word_intersection / word_union if word_union > 0 else 0

        # If most words match, give high score
        if word_similarity >= 0.7:
            return 0.9

    # Method 3: Sequence matcher for character-level similarity
    sequence_similarity = SequenceMatcher(
        None, search_name, entity_name).ratio()

    # Method 4: Check if search name words are substrings of entity name
    search_words_list = search_name.split()
    substring_matches = 0
    for word in search_words_list:
        if len(word) >= 3 and word in entity_name:  # Only check words with 3+ chars
            substring_matches += 1

    substring_ratio = substring_matches / \
        len(search_words_list) if search_words_list else 0

    # Combine scores with weights
    final_score = max(
        sequence_similarity,
        word_similarity * 0.8,
        substring_ratio * 0.7
    )

    return final_score
