from app.repositories import UserRepository as userRepository
from app.repositories import RoleRepository as roleRepository
from app.schemas.Users import UserSchema
from app.schemas.Groups import GroupSchema
from app.schemas.UserRoles import UserRoles
from fastapi.encoders import jsonable_encoder
from pymongo.errors import PyMongoError
from fastapi import HTTPException, status
from typing import Dict, Any, List
from app.schemas.UserRoles import UserRoles
from app.repositories import UserRolesRepository
from app.repositories import GroupRepository


def create_user(user: UserSchema):
    try:
        user_exists = validate_if_users_exists(user.uid)

        linked_callcenters: List[Dict[str, Any]
                                 ] = _link_user_to_callcenters(user.uid)

        if user_exists != None:
            user_exists = {**user_exists,
                           "linked_callcenters": linked_callcenters}
            return user_exists

        user_payload = user.toJson()

        user_payload.pop('_id')

        user = {**user_payload, "groups": []}
        userRepository.insert_user(user)
        created_user = list(userRepository.find_by_uid(user["uid"]))
        return created_user[0] if len(created_user) > 0 else None
    except PyMongoError as e:
        raise HTTPException(
            status_code=500, detail="Error while creating user")


def find_user(uid: str):
    try:
        return userRepository.find_by_uid(uid)
    except PyMongoError as e:
        return 'Error While fetching user'


def find_users(filters: Dict[str, Any]):
    try:
        search_filters = {}
        if (filters["search_argument"] != None):
            search_filters = {
                "$text": {
                    "$search": filters["search_argument"],
                    "$caseSensitive": False
                }
            }

            users_found = list(userRepository.find(search_filters))

            if len(users_found) > 0:
                formatted_users = []
                for user_info in users_found:
                    user = UserSchema(**user_info)
                    formatted_users.append(user.toJson())
                return formatted_users

        return []
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f'Error while fetching users {str(e)}')


def update_user(uid: str, user: UserSchema):
    try:
        found_user = list(userRepository.find_by_uid(uid))

        if (user == None):
            return {"message": "No user was found with that uid"}

        if (len(found_user) == 0):
            return {"message": "No users found"}

        user_to_be_updated = found_user[0]

        user_to_be_updated["name"] = user.name if user.name is not None else user_to_be_updated.get(
            "name", None)
        user_to_be_updated["email"] = user.email if user.email is not None and user.email != "" else user_to_be_updated.get(
            "email", None)
        user_to_be_updated["phone"] = user.phone if user.phone is not None else user_to_be_updated.get(
            "phone", None)
        user_to_be_updated["phoneExtention"] = user.phoneExtention if user.phoneExtention is not None else user_to_be_updated.get(
            "phoneExtention", None)
        user_to_be_updated["location"] = user.location if user.location is not None else user_to_be_updated.get(
            "location", None)

        if user.roles is not None:
            user_to_be_updated["roles"] = [role.value for role in user.roles]
        else:
            user_to_be_updated["roles"] = user_to_be_updated.get("roles", None)

        userRepository.update_user(uid, user_to_be_updated)
        return {"message": "ok", "body": user_to_be_updated}
    except PyMongoError as error:
        return {"message": f'Error while updating user {error}'}


def validate_if_users_exists(uid: str):
    foundUser = {}
    try:
        user = list(userRepository.find_by_uid(uid))
        print(user)
        if (len(user) > 0):
            foundUser = user[0]
            foundUser = {
                **foundUser,
                "groups": __format_groups(foundUser["groups"])
            }
            print(foundUser)
            return foundUser
        else:
            return None
    except PyMongoError as e:
        raise HTTPException(
            status_code=500, detail="Error while finding user")


def _link_user_to_callcenters(user_uid: str) -> List[Dict[str, Any]]:
    try:
        callcenter_list = list(GroupRepository.find(
            {"users": user_uid, "is_callcenter": True}))

        callcenters_with_roles = []
        for callcenter_item in callcenter_list:
            callcenter = GroupSchema(**callcenter_item)

            roles_found = list(UserRolesRepository.find(
                {"group": callcenter.id, "user_uid": user_uid}))

            callcenters_with_roles.append(
                {
                    "callcenter_id": callcenter.id,
                    "callcenter_name": callcenter.name,
                    "roles": [role.role for role in roles_found] if len(roles_found) > 0 else []
                }
            )

        return callcenters_with_roles
    except PyMongoError as e:
        raise HTTPException(
            status_code=500, detail="Error while binding user to callcenters")


def __format_groups(groups):
    formatted_groups = []
    for group in groups:
        formatted_groups.append({
            **group,
            "_id": str(group["_id"])
        })
    return formatted_groups


def add_role_to_user(user_uid: str, role_id: str) -> UserSchema:
    try:
        user_data = userRepository.find_one({"uid": user_uid})
        role_data = roleRepository.find_by_id(role_id)

        if user_data != None and role_data != None:
            user: UserSchema = UserSchema(**user_data)

            current_user_roles: List[str] = [
                role_data["value"]
            ]

            for role in user.roles:
                current_user_roles.append(role.value)

            user_json = user.toJson()

            user_json.pop("_id")

            user_json["roles"] = list(set(current_user_roles))

            modified_user = UserSchema(
                **userRepository.update_user(user_uid, user_json))

            return modified_user
    except PyMongoError:
        raise HTTPException(
            status_code=500, detail="Error while finding user")
