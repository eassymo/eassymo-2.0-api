from fastapi import HTTPException, status
from app.repositories import CallCenterConnectionRepository
from app.schemas.CallCenterConnection import CallCenterConnection
from typing import Dict, Any
from app.repositories import GroupRepository
from app.schemas.Groups import GroupSchema
from bson import ObjectId


def insert(payload: CallCenterConnection):
    try:
        if (_check_if_connection_exists(payload)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Connection already exists")

        created_id = CallCenterConnectionRepository.insert(payload)

        return created_id
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f'Error while inserting a callcenter connection {str(e)}')


def _check_if_connection_exists(payload: CallCenterConnection) -> bool:
    try:
        callcenter_connection_data = CallCenterConnectionRepository.find_one(
            {"callcenter_id": payload.callcenter_id, "group_id": payload.group_id})

        return callcenter_connection_data != None
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f'Error while checking if callcenterConnection exists {str(e)}')


def find_one(filters) -> Dict[str, Any]:
    try:
        callcenter_connection = CallCenterConnectionRepository.find_one(
            filters)

        if callcenter_connection != None:
            callcenter_info = GroupRepository.find_by_id(
                callcenter_connection.callcenter_id)

            if callcenter_info != None:
                callcenter = GroupSchema(**callcenter_info)
                callcenter_connection.callenter_info = callcenter

            return callcenter_connection.toJson()

        return None
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f'Error while searching for a callcenter {str(e)}')


def delete(id: str) -> Dict[str, Any]:
    try:
        callcenter_connection = CallCenterConnectionRepository.delete({"_id": ObjectId(id)})

        if callcenter_connection != None:
            return callcenter_connection.toJson()

        return None
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f'Error while searching for a callcenter {str(e)}') 