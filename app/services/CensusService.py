from app.repositories import CensusRepository as censusRepository
from pymongo.errors import PyMongoError

from app.repositories import InvitationRepository as invitationRepository
from app.repositories import ListsRepository as listRepository


def find(filters):
    try:
        user_uid = filters["userUid"]
        filters = build_filters(filters)
        results = list(censusRepository.find(filters))
        results = check_census_status(user_uid, results)
        return {"message": "ok", "body": results}
    except PyMongoError as err:
        return {"message": f'Error getting items from census'}


def build_filters(parameters):
    filters = {}
    if parameters["Entity_Name"] is not None:
        filters["Entity_Name"] = {
            "$regex": parameters["Entity_Name"], "$options": "i"}
    if parameters["Entity_Address_City"] is not None:
        filters["Entity_Address_City"] = parameters["Entity_Address_City"]
    if parameters["Entity_Location_State"] is not None:
        filters["Entity_Location_State"] = parameters["Entity_Location_State"]
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
        for invite in found_invites:
            if invite["censusId"] == str(census_item["_id"]):
                census_items[index]["census_status"] = "INVITED"
                census_items[index]["invite_id"] = str(invite["_id"])
        if "group_reference_id" in census_item and census_item["group_reference_id"] is not None:
            census_items[index]["census_status"] = "CAN_CONNECT"
        for group_in_list in all_groups_in_lists:
            if "group_reference_id" in census_item:
                if group_in_list == census_item["group_reference_id"]:
                    census_items[index]["census_status"] = "CONNECTED"

    return census_items
