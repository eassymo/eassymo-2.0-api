from fastapi.responses import JSONResponse
from fastapi import APIRouter, status
from app.services import RolesService as rolesService
from typing import List
from app.schemas.Roles import RolesSchema
from app.utils import TypeUtilities as typeUtilities

rolesRouter = APIRouter(prefix="/roles")

# Both paths are registered so /roles does not 307 to /roles/. Behind the TLS
# proxy that redirect was built as http:// and the browser blocked it.
@rolesRouter.get("", response_description="List of user roles", response_model=List[RolesSchema], tags=["Roles"])
@rolesRouter.get("/", response_description="List of user roles", response_model=List[RolesSchema], tags=["Roles"], include_in_schema=False)
def find():
    response = typeUtilities.parse_json(rolesService.find_roles())
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)