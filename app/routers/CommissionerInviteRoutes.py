from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.services import CommissionerInviteService as commissionerInviteService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response


commissionerInviteRouter = APIRouter(prefix="/commissioner-invites", tags=["Commissioner invites"])


def _exc_detail(exc: HTTPException) -> str:
    d = exc.detail
    return d if isinstance(d, str) else str(d)


@commissionerInviteRouter.post("")
def create_commissioner_invite(request: Request, payload: Dict[str, Any] = Body(...)):
    try:
        census_id = payload.get("census_id")
        if not census_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "census_id requerido"
            )
        data = commissionerInviteService.create_invite(request, str(census_id))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(data)),
        )
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(_exc_detail(e)),
        )


@commissionerInviteRouter.get("")
def list_commissioner_invites(
    request: Request,
    commissioner_group_id: Optional[str] = Query(
        None,
        description="Invites originated by this commissioner group",
    ),
    invited_group_id: Optional[str] = Query(
        None,
        description="Invites targeting this invited group",
    ),
    invite_status: Optional[str] = Query(None, alias="status"),
):
    try:
        gs = request.state._state.get("groupSelected")
        cg = commissioner_group_id
        ig = invited_group_id
        if cg is None and ig is None:
            cg = gs

        data = commissionerInviteService.list_invites(cg, ig, invite_status)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(data)),
        )
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(_exc_detail(e)),
        )


@commissionerInviteRouter.post("/revoke-accepted")
def revoke_accepted_commissioner_relationship(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    try:
        cg = payload.get("commissioner_group_id")
        if not cg:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "commissioner_group_id requerido",
            )
        data = commissionerInviteService.revoke_accepted_relationship(
            request, str(cg))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(data)),
        )
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(_exc_detail(e)),
        )


@commissionerInviteRouter.get("/{invite_id}")
def get_commissioner_invite(request: Request, invite_id: str):
    try:
        gs = request.state._state.get("groupSelected")
        data = commissionerInviteService.find_by_id_public(invite_id, gs)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(data)),
        )
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(_exc_detail(e)),
        )


@commissionerInviteRouter.patch("/{invite_id}/respond")
def respond_commissioner_invite(
    request: Request,
    invite_id: str,
    payload: Dict[str, Any] = Body(...),
):
    try:
        st = payload.get("status")
        if not st:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, 'status es requerido ("ACCEPTED" o "REJECTED")',
            )
        data = commissionerInviteService.respond_invite(request, invite_id, str(st))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(data)),
        )
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(_exc_detail(e)),
        )
