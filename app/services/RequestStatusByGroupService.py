from fastapi import HTTPException
from app.repositories import RequestStatusByGroupRepository
from app.schemas.RequestStatusByGroup import RequestStatusByGroup


def insert(payload: RequestStatusByGroup) -> RequestStatusByGroup:
    try:
        return RequestStatusByGroupRepository.insert(payload)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting request status by group: {e}')


def find_by_group_and_request_id(group_id: str, request_id: str) -> RequestStatusByGroup | None:
    try:
        return RequestStatusByGroupRepository.find_by_group_and_request_id(group_id, request_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while finding request status by group_id={group_id} and request_id={request_id}: {e}')


def update(id: str, payload: RequestStatusByGroup) -> RequestStatusByGroup | None:
    try:
        return RequestStatusByGroupRepository.update(id, payload)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while updating request status by group id={id}: {e}')

def delete(id: str) -> bool:
    try:
        return RequestStatusByGroupRepository.delete(id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while delete request status by id={id}: {e}')