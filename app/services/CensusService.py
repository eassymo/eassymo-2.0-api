from app.repositories import CensusRepository as censusRepository
from pymongo.errors import PyMongoError


def find(filters):
    try:
        filters = build_filters(filters)
        results = list(censusRepository.find(filters))
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
