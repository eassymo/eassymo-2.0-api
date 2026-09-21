from app.repositories import RolesRepository as rolesRepository
from app.schemas.Roles import RolesSchema
from pymongo.errors import PyMongoError
from fastapi import HTTPException, status

def find_roles():
    try:
        response = list()
        rolesFound = rolesRepository.find({"display": True})
        for rol in rolesFound:
            response.append({
                **rol,
                "_id": str(rol["_id"])
            })
        return response
    except PyMongoError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"error while finding roles {err}",
        )