import fastapi
from app.routers import UserRouter as userRouter
from app.routers import RolesRouter as rolesRouter
from app.routers import CensusRouter as censusRouter
from app.routers import NetworkRouter as networkRouter
from fastapi.middleware.cors import CORSMiddleware

app = fastapi.FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to your needs
    allow_credentials=True,
    allow_methods=["*"],  # Or specify just the methods your API uses
    allow_headers=["*"],
)

app.include_router(userRouter.userRouter)
app.include_router(rolesRouter.rolesRouter)
app.include_router(censusRouter.censusRouter)
app.include_router(networkRouter.networkRouter)