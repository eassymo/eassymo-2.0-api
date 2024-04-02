from app.repositories import RolesRepository as rolesRepository
from app.schemas.Roles import RolesSchema
from pymongo.errors import PyMongoError

def find_roles():
    try:
        response = list()
        rolesFound = rolesRepository.find()
        for rol in rolesFound:
            response.append({
                **rol,
                "_id": str(rol["_id"])
            })
        return response
    except PyMongoError as err:
        return {"message": f'error while finding roles {err}'}