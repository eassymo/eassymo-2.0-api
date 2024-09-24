from datetime import datetime, timedelta
from app.repositories import CensusRepository as censusRepository
from pymongo.errors import PyMongoError

from app.repositories import InvitationRepository as invitationRepository
from app.repositories import ListsRepository as listRepository


def find(filters):
    try:
        user_uid = filters["userUid"]
        filters = build_filters(filters)
        results = list(censusRepository.find(
            filters, filters["limit"], filters["page"]))
        results = check_census_status(user_uid, results)
        counts = censusRepository.count(filters)
        total_count = counts["total_count"]
        group_count = counts["group_count"]
        return {"message": "ok", "body": results, "count": total_count, "group_count": group_count, "page": filters["page"], "limit": filters["limit"]}
    except PyMongoError as err:
        return {"message": f'Error getting items from census'}


def build_filters(parameters):
    filters = {}
    if parameters["limit"] is not None:
        filters["limit"] = parameters["limit"]
    else:
        filters["limit"] = 20

    if parameters["page"] is not None:
        filters["page"] = parameters["page"]
    else:
        filters["page"] = 1

    if parameters["Entity_Name"] is not None:
        filters["Entity_Name"] = {
            "$regex": parameters["Entity_Name"], "$options": "i"}
    if parameters["Entity_Address_City"] is not None:
        filters["Entity_Address_City"] = {
            "$regex": parameters["Entity_Address_City"], "$options": "i"}
    if parameters["Entity_Location_State"] is not None:
        filters["Entity_Location_State"] = {
            "$regex": parameters["Entity_Location_State"], "$options": "i"}
    if "Entity_Type" in parameters and parameters["Entity_Type"] is not None:
        if parameters["Entity_Type"] == "Refaccionaria":
            parameters["Entity_Type"] = 1
        if parameters["Entity_Type"] == "Taller":
            parameters["Entity_Type"] = 2
        filters["Entity_Type"] = parameters["Entity_Type"]
    if "show_only_census" in parameters and parameters["show_only_census"] is not None:
        filters["show_only_census"] = parameters["show_only_census"]
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


def check_census_status(user_uid: str, census_items):
    found_invites = list(invitationRepository.find_user_invites(user_uid))
    user_groups_in_lists = list(
        listRepository.find_all_groups_in_user_lists(user_uid))

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
        for group_in_list in all_groups_in_lists:
            if "group_reference_id" in census_item:
                if group_in_list == census_item["group_reference_id"]:
                    census_items[index]["census_status"] = "CONNECTED"

    return census_items


def validate_if_invite_canbe_resent(last_sent: datetime):
    current_date = datetime.now()
    difference = current_date - last_sent
    return difference >= timedelta(days=7)
