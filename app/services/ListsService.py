from app.repositories import ListsRepository as listsRepository
from app.schemas.Lists import ListsSchema
from pymongo.errors import PyMongoError
from app.exceptions.InternalServerError import InternalServerError


def create_list(data: ListsSchema):
    list_info = {
        **data.model_dump()
    }
    try:
        user_lists = list(listsRepository.find_by_user(data.user_uid))
        if user_lists is not None and len(user_lists) > 0:
            list_id = user_lists[0]["_id"]
            listsRepository.insert_group_to_list(list_id, data.groups[0])
            return {"body": str(list_id)}
        created_list = listsRepository.insert(list_info)
        return {"body": str(created_list.inserted_id)}
    except PyMongoError as error:
        raise InternalServerError(str(error))
    
def get_lists_by_user(user_uid: str):
    try:
        user_lists = list(listsRepository.find_by_user(user_uid))
        return {"body": user_lists}
    except PyMongoError as error:
        raise InternalServerError(str(error))