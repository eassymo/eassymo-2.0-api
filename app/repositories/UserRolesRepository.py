from app.config import database
from app.schemas.UserRoles import UserRoles

from pymongo.errors import PyMongoError
from pymongo import ReturnDocument

from typing import List


def insert(payload: UserRoles):
    try:
        user_json = payload.toJson()

        if '_id' in user_json:
            user_json.pop('_id')

        return database.db["UserRoles"].insert_one(user_json)
    except PyMongoError as e:
        raise PyMongoError(message=f'Error while inserting user role {str(e)}')


def find(filters) -> List[UserRoles]:
    try:
        user_roles_list = list(database.db["UserRoles"].find(filters))

        user_roles: List[UserRoles] = []

        if len(user_roles_list) > 0:
            for user_role in user_roles_list:
                user_roles.append(UserRoles(**user_role))

        return user_roles
    except PyMongoError as e:
        raise PyMongoError(e)


def update(filters, payload) -> UserRoles | None:
    try:
        updated_role = database.db["UserRoles"].find_one_and_update(
            filters, {"$set": payload}, return_document=ReturnDocument.AFTER)

        if updated_role != None:
            userRole = UserRoles(**updated_role)
            return userRole

        return None
    except PyMongoError as e:
        raise PyMongoError(e)
    
def remove(filters) -> UserRoles | None:
    try:
        deleted_role = database.db["UserRoles"].find_one_and_delete(filters)

        if deleted_role != None:
            userRole = UserRoles(**deleted_role)
            return userRole

        return None
    except PyMongoError as e:
        raise PyMongoError(e)
