from fastapi import APIRouter, Body, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.services import PendingCartService as pendingCartService
from app.schemas.PendingCart import SavePendingCartRequest
from app.utils.ResponseUtils import get_successful_response, error_json_response
from app.dependencies.group_auth import assert_group_membership, require_authenticated_uid

pendingCartRouter = APIRouter(prefix="/pending-cart")


@pendingCartRouter.put(
    "/",
    response_description="Upsert pending cart",
    tags=["PendingCart"],
)
def save_pending_cart(
    request: Request,
    body: SavePendingCartRequest = Body(...),
    groupselected: str = Header(None),
):
    try:
        caller_uid = require_authenticated_uid(request)
        group_id = groupselected or body.group_id
        assert_group_membership(caller_uid, str(group_id))
        part_list = [p.dict() for p in body.part_list]
        response = pendingCartService.save(caller_uid, str(group_id), body.vehicle_id, part_list)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return error_json_response(e)


@pendingCartRouter.get(
    "/{user_uid}",
    response_description="Get pending cart for user",
    tags=["PendingCart"],
)
def get_pending_cart(request: Request, user_uid: str, groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        if str(user_uid) != str(caller_uid):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Cannot access another user's pending cart")
        assert_group_membership(caller_uid, str(groupselected))
        response = pendingCartService.get(caller_uid, groupselected)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return error_json_response(e)


@pendingCartRouter.delete(
    "/{user_uid}",
    response_description="Clear pending cart for user",
    tags=["PendingCart"],
)
def delete_pending_cart(request: Request, user_uid: str, groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        if str(user_uid) != str(caller_uid):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Cannot clear another user's pending cart")
        assert_group_membership(caller_uid, str(groupselected))
        response = pendingCartService.delete(caller_uid, groupselected)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return error_json_response(e)
