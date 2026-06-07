from fastapi import HTTPException, status
from app.repositories import CallCenterManagementListRepository

from pymongo.errors import PyMongoError

def insert(payload):
    try:
        inserted = CallCenterManagementListRepository.insert(payload).toJson()

        return inserted
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error while inserting call center management list {e}")
    
def find(filters):
    try:

        lists_found = CallCenterManagementListRepository.find(filters)

        lists_dicts = [list.toJson() for list in lists_found]

        return lists_dicts
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error while fetching call center management lists {e}")
    

def find_by_id(id: str):
    try:

        list_found = CallCenterManagementListRepository.find_by_id(id)

        return list_found
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error while fetching call center management lists {e}")