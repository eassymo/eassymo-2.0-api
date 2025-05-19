from app.config import database
from app.schemas.CallCenterManagementList import CallCenterManagementList
from pymongo.errors import PyMongoError
from typing import List
from bson import ObjectId
from app.schemas.Groups import GroupSchema


def insert(payload) -> CallCenterManagementList:
    try:
        inserted_id = database.db["CallCenterManagementList"].insert_one(
            payload).inserted_id

        call_center_data = database.db["CallCenterManagementList"].find_one({
                                                                            "_id": inserted_id})

        return CallCenterManagementList(**call_center_data)
    except PyMongoError as e:
        raise PyMongoError("Error while inserting call center management list")


def find(filters) -> List[CallCenterManagementList]:
    try:
        callcenters_data = list(
            database.db["CallCenterManagementList"].aggregate([
                {
                    "$match": filters
                },
                {
                    "$addFields": {
                        "groups": {
                            "$map": {
                                "input": "$groups",
                                "as": "group",
                                "in": {"$toObjectId": "$$group"}
                            }
                        }
                    }
                },
                {
                    "$lookup": {
                        "from": "groups",
                        "localField": "groups",
                        "foreignField": "_id",
                        "as": "groupObjects"
                    }
                },
                {
                    "$addFields": {
                        "groups": "$groupObjects"
                    }
                },
            ])
        )

        call_center_management_lists: List[CallCenterManagementList] = []

        for callcenter_management_list_data in callcenters_data:
            call_center_management_lists.append(
                CallCenterManagementList(**callcenter_management_list_data))

        return call_center_management_lists
    except PyMongoError as e:
        raise PyMongoError("Error while finding call center management list")


def find_by_id(list_id: str) -> CallCenterManagementList:
    try:
        # First find the list by ID
        callcenter_data = database.db["CallCenterManagementList"].find_one(
            {"_id": ObjectId(list_id)})

        if not callcenter_data:
            return None

        if "groups" in callcenter_data and callcenter_data["groups"]:
            group_ids = [ObjectId(
                group_id) for group_id in callcenter_data["groups"] if isinstance(group_id, str)]

            if group_ids:
                group_info = list(database.db["groups"].find(
                    {"_id": {"$in": group_ids}}))

                group_dict = {}
                for group in group_info:
                    group_obj = GroupSchema(**group).toJson()
                    group_id = str(group["_id"])
                    group_dict[group_id] = group_obj

                # Replace string IDs with group objects where available
                group_objects = []

                for group_id in callcenter_data["groups"]:
                    if isinstance(group_id, str) and group_id in group_dict:
                        group_objects.append(group_dict[group_id])
                    else:
                        group_objects.append(group_id)

                callcenter_data["groups"] = group_objects

        return CallCenterManagementList(**callcenter_data)
    except PyMongoError as e:
        raise PyMongoError("Error while fetching call center management list")
