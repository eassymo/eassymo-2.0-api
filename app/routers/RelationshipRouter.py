from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.dependencies.group_auth import (
    assert_group_membership,
    require_authenticated_uid,
)
from app.schemas.Relationship import (
    RelationshipDirection,
    SaveReminderPrefsRequest,
    SubmitPerceptionRequest,
)
from app.services import RelationshipService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

relationshipRouter = APIRouter(prefix="/relaciones", tags=["Relaciones"])


def _error_response(exception: Exception, *, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
    return JSONResponse(status_code=status_code, content=get_unsuccessful_response(exception))


def _group_selected(request: Request) -> Optional[str]:
    return getattr(request.state, "groupSelected", None)


def _require_group(request: Request) -> str:
    reviewer_group_id = _group_selected(request)
    if not reviewer_group_id:
        raise HTTPException(status_code=400, detail="GroupSelected header is required")
    caller_uid = require_authenticated_uid(request)
    assert_group_membership(caller_uid, reviewer_group_id)
    return reviewer_group_id


@relationshipRouter.get("")
def list_relationships(
    request: Request,
    direction: RelationshipDirection = Query(RelationshipDirection.COMPRANDO),
):
    try:
        reviewer_group_id = _require_group(request)
        result = RelationshipService.list_relationships(reviewer_group_id, direction)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@relationshipRouter.post("/percepcion")
def submit_perception(request: Request, payload: SubmitPerceptionRequest = Body(...)):
    try:
        reviewer_group_id = _require_group(request)
        user_uid = require_authenticated_uid(request)
        result = RelationshipService.submit_perception(
            user_uid=user_uid,
            reviewer_group_id=reviewer_group_id,
            payload=payload,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@relationshipRouter.get("/actividad/{counterpart_group_id}")
def get_activity(
    request: Request,
    counterpart_group_id: str,
    direction: RelationshipDirection = Query(RelationshipDirection.COMPRANDO),
):
    try:
        reviewer_group_id = _require_group(request)
        result = RelationshipService.get_activity(
            reviewer_group_id, counterpart_group_id, direction
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@relationshipRouter.get("/recordatorio")
def get_reminder(request: Request):
    try:
        uid = require_authenticated_uid(request)
        result = RelationshipService.get_reminder_prefs(uid)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@relationshipRouter.put("/recordatorio")
def save_reminder(request: Request, payload: SaveReminderPrefsRequest = Body(...)):
    try:
        uid = require_authenticated_uid(request)
        result = RelationshipService.save_reminder_prefs(uid, payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)
