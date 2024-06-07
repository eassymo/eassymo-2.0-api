import fastapi
from app.routers import UserRouter as userRouter
from app.routers import RolesRouter as rolesRouter
from app.routers import CensusRouter as censusRouter
from app.routers import NetworkRouter as networkRouter
from app.routers import GroupRouter as groupRouter
from app.routers import ListsRouter as listRouter
from app.routers import GroupCarRouter as groupCarRouter
from app.routers import PartRequestRouter as partRequestRouter
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
app.include_router(groupRouter.groupRouter)
app.include_router(listRouter.listRouter)
app.include_router(groupCarRouter.groupCarRouter)
app.include_router(partRequestRouter.partRequestRouter)