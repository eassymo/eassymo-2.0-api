from typing import Any


from fastapi import HTTPException
from app.repositories import PreloadedFiltersRepository
from app.schemas.PreloadedFilters import PreloadedFilters, PreloadedFiltersTypes


def insert(payload: PreloadedFilters) -> PreloadedFilters:
    try:
        existing_filters = list[Any](PreloadedFiltersRepository.find_by_user_group_type(
            payload.user_uid,
            payload.group_id,
            payload.type
        ))

        if len(existing_filters) > 0:
            existing_filter = PreloadedFilters(**existing_filters[0])
            return PreloadedFiltersRepository.update(existing_filter.id, payload)
        else:
            return PreloadedFiltersRepository.create(payload)

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting preloaded filter {e}')


def find_by_user_group_type(user_uid: str, group_id: str, type: str) -> PreloadedFilters:
    try:
        filter_type = PreloadedFiltersTypes(type)

        filters = list[Any](PreloadedFiltersRepository.find_by_user_group_type(
            user_uid,
            group_id,
            filter_type
        ))

        if len(filters) > 0:
            return PreloadedFilters(**filters[0])

        return None

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while finding preloaded filter {e}')


def delete(id: str) -> bool:
    try:
        deleted = PreloadedFiltersRepository.delete(id)

        return deleted
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while deleting filter with id {id}')
