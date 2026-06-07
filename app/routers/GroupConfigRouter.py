from fastapi import APIRouter, Body, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.schemas.GroupConfig import (
    ArmadorasConfigUpdate,
    ArmadoraCompatibilityRequest,
)
from app.services import GroupConfigService
from app.services import ArmadoraCompatibilityService
from app.utils.ResponseUtils import get_successful_response

groupConfigRouter = APIRouter(prefix="/group-config", tags=["GroupConfig"])


@groupConfigRouter.post("/armadora-compatibility")
def evaluate_armadora_compatibility(payload: ArmadoraCompatibilityRequest = Body(...)):
    try:
        result = ArmadoraCompatibilityService.evaluate_bulk(
            payload.group_ids,
            payload.vehicle_maker,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(result)),
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "GENERIC_ERROR", "error": str(e)},
        )


@groupConfigRouter.get("/{group_id}")
def get_group_config(group_id: str):
    try:
        config = GroupConfigService.get_by_group_id(group_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(config.toJson())),
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "GENERIC_ERROR", "error": str(e)},
        )


@groupConfigRouter.put("/{group_id}/armadoras")
def upsert_armadoras_config(
    group_id: str,
    payload: ArmadorasConfigUpdate = Body(...),
):
    try:
        config = GroupConfigService.upsert_armadoras(group_id, payload)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(config.toJson())),
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "GENERIC_ERROR", "error": str(e)},
        )
