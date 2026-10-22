from app.repositories import UserRepository as userRepository
from app.repositories import RoleRepository as roleRepository
from app.schemas.Users import UserSchema
from app.schemas.Groups import GroupSchema
from app.schemas.UserRoles import UserRoles
from fastapi.encoders import jsonable_encoder
from pymongo.errors import PyMongoError
from fastapi import HTTPException, status
from typing import Dict, Any, List, Optional
from app.schemas.UserRoles import UserRoles
from app.repositories import UserRolesRepository
from app.repositories import GroupRepository


def create_user(user: UserSchema):
    try:
        linked_callcenters: List[Dict[str, Any]] = _link_user_to_callcenters(user.uid)
        existing = validate_if_users_exists(user.uid)

        if existing is not None:
            _sync_profile_from_schema(user.uid, user)
            refreshed = get_user_with_groups(user.uid)
            if refreshed is not None:
                refreshed["linked_callcenters"] = linked_callcenters
            return refreshed

        user_payload = user.toJson()
        user_payload.pop('_id', None)

        new_user = {**user_payload, "groups": []}
        userRepository.insert_user(new_user)
        created = get_user_with_groups(user.uid)
        if created is not None:
            created["linked_callcenters"] = linked_callcenters
        return created
    except PyMongoError as e:
        raise HTTPException(
            status_code=500, detail="Error while creating user")


def get_user_with_groups(uid: str) -> Optional[dict]:
    """Load user document with populated groups (for login / guest provision)."""
    rows = list(userRepository.find_by_uid(uid))
    if len(rows) == 0:
        return None
    found_user = rows[0]
    groups = found_user.get("groups") or []
    found_user["groups"] = __format_groups(groups) if groups else []
    if "_id" in found_user and not isinstance(found_user["_id"], str):
        found_user["_id"] = str(found_user["_id"])
    return found_user


def find_user(uid: str):
    try:
        return userRepository.find_by_uid(uid)
    except PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error while fetching user",
        )


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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error while updating user {error}",
        )


def validate_if_users_exists(uid: str):
    return get_user_with_groups(uid)


def _sync_profile_from_schema(uid: str, user: UserSchema) -> None:
    raw = userRepository.find_one({"uid": uid})
    if not raw:
        return
    updates: Dict[str, Any] = {}
    if user.name:
        updates["name"] = user.name
    if user.phone:
        updates["phone"] = user.phone
    if user.email is not None and str(user.email) != "":
        updates["email"] = str(user.email)
    if not updates:
        return
    userRepository.update_user(uid, {**raw, **updates})


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
        if isinstance(group, str):
            continue
        if not isinstance(group, dict):
            continue
        formatted_groups.append({
            **group,
            "_id": str(group.get("_id", "")),
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
