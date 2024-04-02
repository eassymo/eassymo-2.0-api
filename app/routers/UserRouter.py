from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status
from app.schemas.Users import UserSchema
from app.utils import TypeUtilities as typeUtilities
from app.services import UserService as userService


userRouter = APIRouter(prefix="/users")

@userRouter.post("/create", response_description="User creation endpoint", response_model=UserSchema, tags=["Users"])
def create(user: UserSchema = Body(...)):
    response = typeUtilities.parse_json(userService.create_user(user))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)

@userRouter.get("/{uid}", response_description="User information endpoint", response_model=UserSchema, tags=["Users"])
def find(uid: str):
    response = typeUtilities.parse_json(userService.find_user(uid))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)

@userRouter.put("/{uid}", response_description="Edit user", response_model=UserSchema, tags=["Users", "Edit"])
def update(uid: str, user:UserSchema = Body()):
    response = typeUtilities.parse_json(userService.update_user(uid, user))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)