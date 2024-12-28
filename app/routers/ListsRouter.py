from fastapi import APIRouter, Body, status, Query, Request
from app.schemas.Lists import ListsSchema
from app.utils import TypeUtilities as typeUtilities
from app.services import ListsService as listService
from fastapi.responses import JSONResponse
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


listRouter = APIRouter(prefix="/lists")


@listRouter.post("", response_description="id of the created list", tags=["Lists"])
def create_list(payload: ListsSchema = Body(...)):
    response = typeUtilities.parse_json(listService.create_list(payload))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@listRouter.get("/{userId}/{groupId}", response_description="created lists for user", tags=["Lists"])
def find_lists(userId: str, groupId: str):
    response = typeUtilities.parse_json(
        listService.get_lists_by_user_and_group(userId, groupId))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@listRouter.put("/{list_id}", response_description="updated result", tags=["Lists"])
def update(request: Request, list_id: str, payload: ListsSchema = Body(...)):
    try:
        user_info = request.state._state.get('user')
        response = listService.update(user_info, list_id, payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=get_unsuccessful_response(str(e)))
