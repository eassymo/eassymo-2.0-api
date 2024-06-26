from fastapi import APIRouter, Body, status, Query
from app.schemas.Lists import ListsSchema
from app.utils import TypeUtilities as typeUtilities
from app.services import ListsService as listService
from fastapi.responses import JSONResponse


listRouter = APIRouter(prefix="/lists")


@listRouter.post("", response_description="id of the created list", tags=["Lists"])
def create_list(payload: ListsSchema = Body(...)):
    response = typeUtilities.parse_json(listService.create_list(payload))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)
