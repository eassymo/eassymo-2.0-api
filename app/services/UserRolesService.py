from fastapi import HTTPException, status
from app.repositories import UserRolesRepository
from pymongo.errors import PyMongoError

from app.schemas.UserRoles import UserRoles

from typing import List, Dict, Any
from bson import ObjectId


def insert(payload: UserRoles) -> str:
    try:
        currentUserRoles = find({
            "user_uid": payload.user_uid,
            "role": payload.role,
            "group": payload.group
        })

        if len(currentUserRoles) > 0:
            raise HTTPException(
                detail="Role already exists for user, role type and group")

        return str(UserRolesRepository.insert(payload).inserted_id)
    except PyMongoError as e:
        raise HTTPException(
            detail=e, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except HTTPException as e:
        raise HTTPException(e)


def find(filters) -> List[Dict[str, Any]]:
    try:
        userRolesFound = UserRolesRepository.find(filters)

        if not userRolesFound:
            return []

        userRolesFormatted = []

        for userRole in userRolesFound:
            userRolesFormatted.append(userRole.toJson())

        return userRolesFormatted

    except PyMongoError as e:
        raise HTTPException(
            detail=f'Error while searching for user roles db error {str(e)}', status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        raise HTTPException(
            detail=f'Error while searching for user roles processing error {str(e)}', status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def activate_role(
        user_uid: str,
        role: str,
        new_group_id: str
):
    try:
        roles_found = UserRolesRepository.find(
            {"user_uid": user_uid, "role": role, "group": None, "active": False})

        if len(roles_found) > 0:
            user_role = roles_found[0]

            user_role.group = new_group_id
            user_role.active = True

            user_role_json = user_role.toJson()

            user_role_json.pop("_id")

            updated_role = UserRolesRepository.update(
                {"_id": ObjectId(user_role.id)}, user_role_json)

            if updated_role != None:
                return updated_role.toJson()

            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Error while activating the user role")
    except HTTPException as e:
        raise HTTPException(e)


def add_role_to_user(user_uid, role: str, group_id: str) -> str:
    try:
        user_role = UserRoles(
            active=True,
            group=group_id,
            role=role,
            user_uid=user_uid,
        )
    
        inserted_id = UserRolesRepository.insert(user_role).inserted_id
        
        if inserted_id != None:
            return str(inserted_id)
        
        raise PyMongoError("db error while inserting user role")
    except PyMongoError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Error while inserting user role {str(e)}')

def remove_role_from_user(user_uid: str, role: str, group_id: str) -> List[UserRoles]:
    try:
        deleted_role = UserRolesRepository.remove({
            "user_uid": user_uid,
            "role": role,
            "group": group_id
        })

        if deleted_role == None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The requested role for deletion is not found")

        formatted_roles = []
        found_roles = list(UserRolesRepository.find({"user_uid": user_uid, "group": group_id}))

       
        for role_data in found_roles:
            user_role = UserRoles(**role_data)

            formatted_roles.append(user_role.toJson())

        return formatted_roles
    except PyMongoError:
        raise HTTPException(
            status_code=500, detail="Error while removing role from user")