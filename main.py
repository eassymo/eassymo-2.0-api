import fastapi
from app.routers import UserRouter as userRouter
from app.routers import RolesRouter as rolesRouter
from app.routers import CensusRouter as censusRouter
from app.routers import NetworkRouter as networkRouter
from app.routers import GroupRouter as groupRouter
from app.routers import ListsRouter as listRouter
from app.routers import GroupCarRouter as groupCarRouter
from app.routers import PartRequestRouter as partRequestRouter
from app.routers import OfferRouter as offerRouter
from app.routers import BrandRouter as brandRouter
from app.routers import GuaranteeRouter as guaranteeRouter
from app.routers import PhotoRouter as photoRouter
from app.routers import OrderRouter as orderRouter

from fastapi.middleware.cors import CORSMiddleware

app = fastapi.FastAPI()

origins = [
    "https://eassymo-2-0-client.vercel.app",
    "https://eassymo-2-0-client-nw5q0qylv-fernando-francos-projects-1618c379.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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
app.include_router(offerRouter.offerRouter)
app.include_router(brandRouter.brandRouter)
app.include_router(guaranteeRouter.guaranteeRouter)
app.include_router(photoRouter.photoRouter)
app.include_router(orderRouter.orderRouter)