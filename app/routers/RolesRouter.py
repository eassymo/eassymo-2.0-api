from fastapi.responses import JSONResponse
from fastapi import APIRouter, Query, Request, status
from app.repositories import RolesRepository as rolesRepository
from app.services import RolesService as rolesService
from app.services import authz
from typing import List
from app.schemas.Roles import RolesSchema
from app.utils import TypeUtilities as typeUtilities

rolesRouter = APIRouter(prefix="/roles")

# Both paths are registered so /roles does not 307 to /roles/. Behind the TLS
# proxy that redirect was built as http:// and the browser blocked it.
@rolesRouter.get("", response_description="List of user roles", response_model=List[RolesSchema], tags=["Roles"])
@rolesRouter.get("/", response_description="List of user roles", response_model=List[RolesSchema], tags=["Roles"], include_in_schema=False)
def find(
    request: Request,
    assignable: bool = Query(False, description="Only roles the caller may assign in the selected group"),
    all: bool = Query(False, description="Every active role (labels for team screens), not only onboarding ones"),
):
    if all and not assignable:
        authz.caller_uid(request)
        roles = [{**r, "_id": str(r["_id"])} for r in rolesRepository.find({"active": {"$ne": False}})]
        return JSONResponse(status_code=status.HTTP_200_OK, content=typeUtilities.parse_json(roles))
    if not assignable:
        response = typeUtilities.parse_json(rolesService.find_roles())
        return JSONResponse(status_code=status.HTTP_200_OK, content=response)

    uid = authz.caller_uid(request)
    group_id = authz.selected_group(request)
    candidates = rolesRepository.find({"active": {"$ne": False}})

    def allowed_for_caller(value: str) -> bool:
        # Used by My Team (assign) and the invite dialog (invite); the API re-checks each action.
        return (authz.can_assign_role(uid, group_id, value, request)[0]
                or authz.can_invite_with_role(uid, group_id, value, request)[0])

    allowed = [
        {**role, "_id": str(role["_id"])}
        for role in candidates
        if allowed_for_caller(str(role.get("value")))
    ]
    allowed.sort(key=lambda r: (r.get("pov") or "", r.get("description") or ""))
    return JSONResponse(status_code=status.HTTP_200_OK, content=typeUtilities.parse_json(allowed))
