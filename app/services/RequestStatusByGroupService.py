from fastapi import HTTPException
from app.repositories import RequestStatusByGroupRepository
from app.schemas.Offer import OfferStatus
from app.schemas.RequestStatusByGroup import RequestStatusByGroup


def _resolve_quote_decision(saved) -> None:
    """The group said no stock / rejected: the "cotiza" reminder no longer waits on them."""
    try:
        from app.services import NotificationService
        if saved is not None and saved.status in (OfferStatus.no_inventory, OfferStatus.rejected):
            NotificationService.resolve_decisions(f"request:{saved.request_id}:quote:{saved.group_id}")
    except Exception:
        pass


def insert(payload: RequestStatusByGroup) -> RequestStatusByGroup:
    try:
        saved = RequestStatusByGroupRepository.insert(payload)
        _resolve_quote_decision(saved)
        return saved
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
        saved = RequestStatusByGroupRepository.update(id, payload)
        _resolve_quote_decision(saved)
        return saved
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while updating request status by group id={id}: {e}')

def delete(id: str) -> bool:
    try:
        return RequestStatusByGroupRepository.delete(id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while delete request status by id={id}: {e}')