from app.config import database
from bson import ObjectId
from app.schemas.CallCenterConnection import CallCenterConnection
from pymongo.errors import PyMongoError


def insert(payload: CallCenterConnection) -> str:
    try:

        data_json = payload.toJson()

        data_json.pop("_id")

        inserted_item = database.db["callcenterConnection"].insert_one(data_json)

        return str(inserted_item.inserted_id)
    except PyMongoError as e:
        raise Exception(e)



def find_one(filters) -> CallCenterConnection | None:
    try:
        callcenter_connection_data = database.db["callcenterConnection"].find_one(
            filters)

        if callcenter_connection_data != None:
            callcenter_connection = CallCenterConnection(
                **callcenter_connection_data)

            return callcenter_connection

        return None
    except PyMongoError as e:
        raise Exception(e)


def delete(filters) -> CallCenterConnection | None:
    try:
        deleted = database.db["callcenterConnection"].find_one_and_delete(
            filters)

        if deleted != None:
            callcenter_connection = CallCenterConnection(
                **deleted)

            return callcenter_connection
        return None
    except PyMongoError as e:
        raise Exception(e)


def find_many(filters) -> list[CallCenterConnection]:
    try:
        callcenter_connections_data = database.db["callcenterConnection"].find(filters)
        
        callcenter_connections = []
        for connection_data in callcenter_connections_data:
            callcenter_connections.append(CallCenterConnection(**connection_data))
            
        return callcenter_connections
    except PyMongoError as e:
        raise Exception(e)